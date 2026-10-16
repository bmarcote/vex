"""Verification of the content of a VEX file.

The parser already guarantees that the syntax of a file is correct. verify() checks its content:
    - the file starts with 'VEX_rev' and uses blocks known for that VEX version;
    - blocks, definitions and scans are not duplicated, and scans are only in $SCHED;
    - the values of the main parameters have the right format (frequencies, sidebands,
      polarizations, epochs, durations, coordinates);
    - every 'ref $BLOCK = name' points to an existing definition, and the stations in
      $MODE references exist;
    - within the setup of each station, channels refer to existing BBCs, and BBCs to existing IFs;
    - every scan uses an existing mode, sources and stations, every station in a scan has a $FREQ
      setup in its mode, and no station observes in two scans at the same time;
    - optionally (freq_overlap), in every scan each station shares part of its frequency
      coverage with at least one of the other stations in that scan, according to the
      mode used in that scan (so different parts of the observation can use different setups).
      A warning is also given if the stations of a scan form separate groups (of more than one
      station each) without any frequency in common between the groups.

Problems are returned as a list of Issues, each one an error (the file is wrong) or
a warning (the file is unusual and may not be what was intended).
"""
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise

from .nodes import BlankLine, Block, Comment, Def, Node, Scan, Statement, Vex
from .observation import covered_ranges, overlap
from .units import parse_duration, parse_epoch, parse_frequency


__all__: list[str] = ["Severity", "Issue", "verify"]


_VEX15_BLOCKS = frozenset({
    "GLOBAL", "EXPER", "SCHEDULING_PARAMS", "PROCEDURES", "EOP", "FREQ", "CLOCK", "SCHED", "MODE",
    "STATION", "ANTENNA", "BBC", "CORR", "DAS", "HEAD_POS", "PASS_ORDER", "PHASE_CAL_DETECT",
    "ROLL", "IF", "SEFD", "SITE", "SOURCE", "TAPELOG_OBS", "TRACKS",
})
KNOWN_BLOCKS: dict[str, frozenset[str]] = {
    "1.5": _VEX15_BLOCKS,
    "2.0": _VEX15_BLOCKS | {"BITSTREAMS", "DATASTREAMS", "THREADS", "EXTENSIONS"},
}
_DEFAULT_VERSION = "1.5"
_SIDEBANDS = ("U", "L")
_POLARIZATIONS = ("R", "L", "X", "Y", "H", "V")
_COORDINATE_FRAMES = ("J2000", "B1950")


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Issue:
    """A problem found in a VEX file, at the given line (None if it does not refer to one)."""

    severity: Severity
    message: str
    line: int | None = None

    def __str__(self) -> str:
        location = "" if self.line is None else f"line {self.line}: "
        return f"{location}{self.severity}: {self.message}"


def verify(vex: Vex, *, freq_overlap: bool = True) -> list[Issue]:
    """Checks the content of a VEX file and returns the problems found, sorted by line.
    If freq_overlap is True, it also checks that in every scan each station shares part
    of its frequency coverage with at least one other station.
    """
    return _Verifier(vex).run(freq_overlap)


# Checks of the values of statements. Each function receives the fields of the statement
# and returns the list of problems found.

def _frequency_problem(field: str, what: str) -> str | None:
    try:
        if parse_frequency(field) <= 0:
            return f"{what} must be positive ('{field}')"
    except ValueError as error:
        return f"{what}: {error}"

    return None


def _choice_problem(field: str, what: str, allowed: tuple[str, ...]) -> str | None:
    return None if field in allowed else f"{what} must be one of {', '.join(allowed)} ('{field}')"


def _min_fields(fields: list[str], n: int) -> list[str]:
    return [f"expected at least {n} fields, found {len(fields)}"] if len(fields) < n else []


def _check_chan_def(fields: list[str]) -> list[str]:
    if problems := _min_fields(fields, 6):
        return problems

    return [p for p in (_frequency_problem(fields[1], "sky frequency"),
                        _choice_problem(fields[2], "net sideband", _SIDEBANDS),
                        _frequency_problem(fields[3], "bandwidth")) if p]


def _check_if_def(fields: list[str]) -> list[str]:
    if problems := _min_fields(fields, 5):
        return problems

    return [p for p in (_choice_problem(fields[2], "polarization", _POLARIZATIONS),
                        _frequency_problem(fields[3], "LO frequency"),
                        _choice_problem(fields[4], "net sideband", _SIDEBANDS)) if p]


def _check_bbc_assign(fields: list[str]) -> list[str]:
    if problems := _min_fields(fields, 3):
        return problems

    if not fields[1].isdigit() or int(fields[1]) < 1:
        return [f"the physical BBC number must be a positive integer ('{fields[1]}')"]

    return []


def _check_epoch(fields: list[str]) -> list[str]:
    try:
        parse_epoch(fields[0])
    except ValueError as error:
        return [str(error)]

    return []


def _check_scan_station(fields: list[str]) -> list[str]:
    if problems := _min_fields(fields, 3):
        return problems

    try:
        good, stop = parse_duration(fields[1]), parse_duration(fields[2])
    except ValueError as error:
        return [str(error)]

    return [] if stop >= good else [f"data stop ({fields[2]}) is before data good ({fields[1]})"]


def _check_site_position(fields: list[str]) -> list[str]:
    if len(fields) != 3:
        return [f"expected 3 coordinates (x : y : z), found {len(fields)}"]

    for field in fields:
        try:
            float(field.removesuffix("m").strip())
        except ValueError:
            return [f"'{field}' is not a distance in meters"]

    return []


def _sexagesimal(text: str, separators: str) -> tuple[float, float, float] | None:
    """Splits values like '17h53m42.47s' or '-28d48'04.9"' into their three numbers."""
    values = []
    rest = text.strip()
    for separator in separators:
        number, found, rest = rest.partition(separator)
        if not found:
            return None
        try:
            values.append(float(number))
        except ValueError:
            return None

    return (values[0], values[1], values[2]) if not rest else None


def _check_ra(fields: list[str]) -> list[str]:
    parts = _sexagesimal(fields[0], "hms")
    if parts is None or not (0 <= parts[0] < 24 and 0 <= parts[1] < 60 and 0 <= parts[2] < 60):
        return [f"'{fields[0]}' is not a valid right ascension (e.g. 17h53m42.47s)"]

    return []


def _check_dec(fields: list[str]) -> list[str]:
    parts = _sexagesimal(fields[0], "d'\"")
    if parts is None or not (abs(parts[0]) <= 90 and 0 <= parts[1] < 60 and 0 <= parts[2] < 60):
        return [f"'{fields[0]}' is not a valid declination (e.g. 28d48'04.93\")"]

    return []


def _check_coordinate_frame(fields: list[str]) -> list[str]:
    problem = _choice_problem(fields[0], "the coordinate frame", _COORDINATE_FRAMES)
    return [problem] if problem else []


_VALUE_CHECKS: dict[tuple[str, str], Callable[[list[str]], list[str]]] = {
    ("FREQ", "chan_def"): _check_chan_def,
    ("IF", "if_def"): _check_if_def,
    ("BBC", "BBC_assign"): _check_bbc_assign,
    ("EXPER", "exper_nominal_start"): _check_epoch,
    ("EXPER", "exper_nominal_stop"): _check_epoch,
    ("SCHED", "start"): _check_epoch,
    ("SCHED", "station"): _check_scan_station,
    ("SITE", "site_position"): _check_site_position,
    ("SOURCE", "ra"): _check_ra,
    ("SOURCE", "dec"): _check_dec,
    ("SOURCE", "ref_coord_frame"): _check_coordinate_frame,
}


def _link(field: str) -> str:
    return field.strip().removeprefix("&")


def _where(block: Block, definition: Def | None) -> str:
    if definition is None:
        return f"${block.name}"

    return f"'{definition.keyword} {definition.name}' (${block.name})"


def _scan_list(nodes: list[Node]) -> str:
    names = [node.name for node in nodes if isinstance(node, Scan)]
    if len(names) <= 3:
        return f"scan{'s' if len(names) > 1 else ''} {', '.join(names)}"

    return f"scans {', '.join(names[:3])} and {len(names) - 3} more"


def _connected_groups(stations: list[str], shares: dict[str, set[str]]) -> list[tuple[str, ...]]:
    """Splits the stations into groups connected through shared frequencies (in their order)."""
    groups: list[tuple[str, ...]] = []
    assigned: set[str] = set()
    for station in stations:
        if station in assigned:
            continue

        group, pending = {station}, [station]
        while pending:
            for other in shares[pending.pop()] - group:
                group.add(other)
                pending.append(other)

        assigned |= group
        groups.append(tuple(code for code in stations if code in group))

    return groups


def _format_ranges(ranges: list[tuple[float, float]]) -> str:
    return ", ".join(f"{low:g}-{high:g} MHz" for low, high in ranges)


class _Verifier:
    def __init__(self, vex: Vex):
        self.vex = vex
        self.issues: list[Issue] = []
        versions = vex.statements("VEX_rev")
        self.version = versions[0].fields[0] if versions else None
        self.stations = {definition.name for block in vex.blocks if block.name == "STATION"
                         for definition in block.defs}

    def error(self, message: str, node: Node | None = None) -> None:
        self.issues.append(Issue(Severity.ERROR, message, None if node is None else node.line))

    def warning(self, message: str, node: Node | None = None) -> None:
        self.issues.append(Issue(Severity.WARNING, message, None if node is None else node.line))

    def run(self, freq_overlap: bool) -> list[Issue]:
        checks: list[tuple[str, Callable[[], None]]] = [
            ("header", self._check_header),
            ("structure", self._check_structure),
            ("values", self._check_values),
            ("references", self._check_references),
            ("setup links", self._check_links),
            ("scans", self._check_scans),
        ]
        if freq_overlap:
            checks.append(("frequency overlap", self._check_frequency_overlap))

        for name, check in checks:
            try:
                check()
            except (ValueError, KeyError, IndexError) as error:
                # Usually a consequence of problems already reported (e.g. duplicated definitions)
                self.error(f"the {name} check could not be completed: {error}")

        return sorted(self.issues, key=lambda issue: (issue.line is None, issue.line or 0))

    # Helpers

    def _block(self, name: str) -> Block | None:
        return next((block for block in self.vex.blocks if block.name == name), None)

    def _def(self, block: Block, name: str) -> Def | None:
        return next((definition for definition in block.defs if definition.name == name), None)

    def _statements(self) -> Iterator[tuple[Block, Def | None, Statement]]:
        for block in self.vex.blocks:
            for statement in block.statements():
                yield block, None, statement

            for definition in block.defs:
                for statement in definition.statements():
                    yield block, definition, statement

    def _mode_stations(self, mode: str) -> list[str]:
        """Stations with a $FREQ setup in the mode."""
        return list(dict.fromkeys(code for codes in self.vex.setups("FREQ", mode).values()
                                  for code in codes))

    # Checks

    def _check_header(self) -> None:
        first = next((node for node in self.vex.children
                      if not isinstance(node, (Comment, BlankLine))), None)
        if not (isinstance(first, Statement) and first.full_key == "VEX_rev"):
            self.error("the file must start with 'VEX_rev = ...;'", first)

        versions = self.vex.statements("VEX_rev")
        if len(versions) > 1:
            self.error(f"VEX_rev is defined {len(versions)} times", versions[1])

        if self.version is not None and self.version not in KNOWN_BLOCKS:
            self.warning(f"unknown VEX version '{self.version}'; "
                         f"the file is checked as VEX {_DEFAULT_VERSION}", versions[0])

        for statement in self.vex.statements():
            if statement.full_key != "VEX_rev":
                self.warning(f"statement '{statement.full_key}' outside of any block", statement)

    def _check_structure(self) -> None:
        version = self.version if self.version in KNOWN_BLOCKS else _DEFAULT_VERSION
        blocks: dict[str, Block] = {}
        for block in self.vex.blocks:
            if block.name in blocks:
                self.error(f"block ${block.name} is defined more than once "
                           f"(also at line {blocks[block.name].line})", block)
            else:
                blocks[block.name] = block

            if block.name not in KNOWN_BLOCKS[version]:
                self.warning(f"block ${block.name} is not defined in VEX {version}", block)

            definitions: dict[str, Def] = {}
            for definition in block.defs:
                title = f"'{definition.keyword} {definition.name}'"
                if block.name == "SCHED" and not isinstance(definition, Scan):
                    self.error(f"{title} in $SCHED: scans must be defined with 'scan ... endscan'",
                               definition)
                elif block.name != "SCHED" and isinstance(definition, Scan):
                    self.error(f"{title} outside of $SCHED", definition)

                if definition.name in definitions:
                    self.error(f"{title} is defined more than once in ${block.name} "
                               f"(also at line {definitions[definition.name].line})", definition)
                else:
                    definitions[definition.name] = definition

            for statement in block.statements():
                if not statement.ref:
                    self.warning(f"statement '{statement.key}' in ${block.name} outside of any "
                                 "definition", statement)

    def _check_values(self) -> None:
        for block, definition, statement in self._statements():
            check = None if statement.ref else _VALUE_CHECKS.get((block.name, statement.key))
            if check is not None:
                for problem in check(statement.fields):
                    self.error(f"{statement.key} in {_where(block, definition)}: {problem}", statement)

    def _check_references(self) -> None:
        for block, definition, statement in self._statements():
            if not statement.ref:
                continue

            where = f"'ref ${statement.key}' in {_where(block, definition)}"
            target = self._block(statement.key)
            name = statement.fields[0]
            if target is None:
                self.error(f"{where}: block ${statement.key} is not defined", statement)
            elif not name:
                self.error(f"{where}: missing definition name", statement)
            elif self._def(target, name) is None:
                self.error(f"{where}: '{name}' is not defined in ${statement.key}", statement)

            if block.name == "MODE":
                unknown = [code for code in statement.fields[1:] if code and code not in self.stations]
                if unknown:
                    self.error(f"{where}: unknown station{'s' if len(unknown) > 1 else ''} "
                               f"{', '.join(unknown)} (not defined in $STATION)", statement)

    def _check_links(self) -> None:
        if self._block("MODE") is None:
            return

        for mode in self.vex.modes:
            mode_def = self.vex["MODE"][mode]
            checked: set[tuple[int, int, int]] = set()
            for station in self._mode_stations(mode):
                freq = self.vex.setup("FREQ", mode, station)
                bbc = self.vex.setup("BBC", mode, station)
                ifs = self.vex.setup("IF", mode, station)
                if freq is None or (key := (id(freq), id(bbc), id(ifs))) in checked:
                    continue

                checked.add(key)
                used_by = f"(setup of {station} in mode '{mode}')"
                if bbc is None:
                    self.warning(f"station {station} has no $BBC setup in mode '{mode}'", mode_def)
                    continue

                assigned = {_link(s.fields[0]) for s in bbc.statements("BBC_assign")}
                for statement in freq.statements("chan_def"):
                    if len(statement.fields) > 5 and statement.fields[5] \
                            and _link(statement.fields[5]) not in assigned:
                        self.error(f"chan_def in 'def {freq.name}' ($FREQ) uses {statement.fields[5]}, "
                                   f"which is not assigned in 'def {bbc.name}' ($BBC) {used_by}",
                                   statement)

                if ifs is None:
                    self.warning(f"station {station} has no $IF setup in mode '{mode}'", mode_def)
                    continue

                defined = {_link(s.fields[0]) for s in ifs.statements("if_def")}
                for statement in bbc.statements("BBC_assign"):
                    if len(statement.fields) > 2 and _link(statement.fields[2]) not in defined:
                        self.error(f"BBC_assign in 'def {bbc.name}' ($BBC) uses {statement.fields[2]}, "
                                   f"which is not defined in 'def {ifs.name}' ($IF) {used_by}",
                                   statement)

    def _check_scans(self) -> None:
        modes = set(self.vex.modes)
        source_block = self._block("SOURCE")
        sources = {d.name for d in source_block.defs} if source_block is not None else set()
        missing_freq: dict[tuple[str, str], list[Node]] = defaultdict(list)
        observing: dict[str, list[tuple[datetime, datetime, Scan]]] = defaultdict(list)
        previous_start: datetime | None = None
        for scan in self.vex.scans:
            title = f"scan {scan.name}"
            mode = scan.mode
            if mode is None:
                self.error(f"{title} has no mode", scan)
            elif mode not in modes:
                self.error(f"{title}: mode '{mode}' is not defined in $MODE", scan)
                mode = None

            if not scan.sources:
                self.error(f"{title} has no source", scan)

            for source in scan.sources:
                if source not in sources:
                    self.error(f"{title}: source '{source}' is not defined in $SOURCE", scan)

            if not scan.stations:
                self.error(f"{title} has no stations", scan)

            seen: set[str] = set()
            for code in scan.stations:
                if code in seen:
                    self.warning(f"{title}: station {code} appears more than once", scan)
                elif code not in self.stations:
                    self.error(f"{title}: station {code} is not defined in $STATION", scan)
                elif mode is not None and self.vex.setup("FREQ", mode, code) is None:
                    missing_freq[(mode, code)].append(scan)

                seen.add(code)

            if "start" not in scan:
                self.error(f"{title} has no start time", scan)
                continue

            try:
                start = parse_epoch(scan["start"])
            except ValueError:
                continue  # already reported by the values check

            if previous_start is not None and start < previous_start:
                self.warning(f"{title} starts before the previous scan", scan)

            previous_start = start
            for statement in scan.statements("station"):
                try:
                    good = start + timedelta(seconds=parse_duration(statement.fields[1]))
                    stop = start + timedelta(seconds=parse_duration(statement.fields[2]))
                except (ValueError, IndexError):
                    continue

                observing[statement.fields[0]].append((good, stop, scan))

        for (mode, code), scans in missing_freq.items():
            self.error(f"station {code} has no $FREQ setup in mode '{mode}' ({_scan_list(scans)})",
                       scans[0])

        for code, intervals in observing.items():
            intervals.sort(key=lambda interval: interval[0])
            for (_, stop1, scan1), (start2, _, scan2) in pairwise(intervals):
                if start2 < stop1:
                    self.warning(f"station {code} observes in overlapping scans {scan1.name} and "
                                 f"{scan2.name}", scan2)

    def _check_frequency_overlap(self) -> None:
        if self._block("MODE") is None:
            return

        cache: dict[tuple[str, str], list[tuple[float, float]]] = {}

        def ranges(mode: str, station: str) -> list[tuple[float, float]]:
            if (mode, station) not in cache:
                try:
                    cache[(mode, station)] = covered_ranges(self.vex.channels(mode, station))
                except (ValueError, IndexError):
                    cache[(mode, station)] = []  # wrong channels, already reported

            return cache[(mode, station)]

        # Groups of stations that observe together, with the mode they use
        modes = set(self.vex.modes)
        groups: list[tuple[str, list[str], Node]] = [
            (scan.mode, scan.stations, scan) for scan in self.vex.scans if scan.mode in modes
        ]
        if not self.vex.scans:
            groups = [(mode, self._mode_stations(mode), self.vex["MODE"][mode]) for mode in self.vex.modes]

        failures: dict[tuple[str, str], list[Node]] = defaultdict(list)
        splits: dict[tuple[str, tuple[tuple[str, ...], ...]], list[Node]] = defaultdict(list)
        for mode, stations, node in groups:
            with_channels = [code for code in dict.fromkeys(stations) if ranges(mode, code)]
            shares = {code: {other for other in with_channels if other != code
                             and overlap(ranges(mode, code), ranges(mode, other)) > 0}
                      for code in with_channels}
            for code in with_channels:
                if len(with_channels) > 1 and not shares[code]:
                    failures[(mode, code)].append(node)

            # Stations connected through shared frequencies; isolated stations are already errors
            components = [group for group in _connected_groups(with_channels, shares) if len(group) > 1]
            if len(components) > 1:
                splits[(mode, tuple(components))].append(node)

        for (mode, code), nodes in failures.items():
            where = _scan_list(nodes) if isinstance(nodes[0], Scan) else "all its stations"
            self.error(f"station {code} does not share any frequency with the other stations in "
                       f"mode '{mode}' ({where}); it covers {_format_ranges(ranges(mode, code))}",
                       nodes[0])

        for (mode, components), nodes in splits.items():
            where = _scan_list(nodes) if isinstance(nodes[0], Scan) else "all its stations"
            described = "; ".join(
                f"{' '.join(group)} ({_format_ranges(covered_ranges(c for code in group for c in self.vex.channels(mode, code)))})"
                for group in components
            )
            self.warning(f"the stations in mode '{mode}' form {len(components)} groups without any "
                         f"frequency in common between them ({where}): {described}", nodes[0])
