"""Higher-level information about the observation described by a VEX file.

The blocks of a VEX file refer to each other: a scan uses a mode, and each $MODE definition
selects, for every station, which definitions of $FREQ, $BBC, $IF, ... apply to it, through
'ref $FREQ = def_name:station1:station2;' statements. The functions here follow these
references and return the result as numbers and dataclasses, while the dictionary access
of Vex, Block and Def always returns the raw text of the file.

They are available as methods and properties of Vex (e.g. vex.stations, vex.channels(...)).
"""
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .units import parse_frequency

if TYPE_CHECKING:
    from .nodes import Def, Scan, Vex


__all__: list[str] = ["Station", "Channel", "IF", "covered_ranges", "overlap"]


def _name(link: str) -> str:
    """Returns the name in a link word ('&BBC01' -> 'BBC01')."""
    return link.strip().removeprefix("&")


@dataclass(frozen=True, slots=True)
class Station:
    """A station from the $STATION block. 'code' is the name of its definition (e.g. 'Jb'),
    'name' its site_name in $SITE, and site, antenna and das the names of the definitions
    referred to from $STATION (None if missing).
    """

    code: str
    name: str
    site: str | None
    antenna: str | None
    das: str | None


@dataclass(frozen=True, slots=True)
class Channel:
    """A frequency channel (chan_def statement in $FREQ). Frequencies are in MHz.
    'sky_frequency' is the edge of the channel at the local oscillator side, so the channel
    covers [sky_frequency, sky_frequency + bandwidth] for the upper sideband ('U') and
    [sky_frequency - bandwidth, sky_frequency] for the lower one ('L').
    'polarization' is obtained from the $BBC and $IF definitions (None if they are missing).
    """

    name: str
    sky_frequency: float
    sideband: str
    bandwidth: float
    bbc: str | None
    polarization: str | None

    @property
    def low(self) -> float:
        return self.sky_frequency - self.bandwidth if self.sideband == "L" else self.sky_frequency

    @property
    def high(self) -> float:
        return self.sky_frequency if self.sideband == "L" else self.sky_frequency + self.bandwidth


@dataclass(frozen=True, slots=True)
class IF:
    """An IF (if_def statement in $IF): its link name (e.g. 'IF_A1'), the physical name of the
    IF (e.g. 'A1'), polarization, total LO frequency (MHz) and net sideband.
    """

    name: str
    physical_name: str
    polarization: str
    lo: float
    sideband: str

    @classmethod
    def from_def(cls, definition: "Def") -> list["IF"]:
        """Returns all the IFs defined in a $IF definition."""
        return [cls(_name(fields[0]), fields[1], fields[2], parse_frequency(fields[3]), fields[4])
                for fields in (s.fields for s in definition.statements("if_def"))]


def covered_ranges(channels: Iterable[Channel]) -> list[tuple[float, float]]:
    """Returns the sorted (low, high) frequency ranges in MHz covered by the channels,
    merging the ones that overlap or are adjacent.
    """
    merged: list[tuple[float, float]] = []
    for low, high in sorted((channel.low, channel.high) for channel in channels):
        if merged and low <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], high))
        else:
            merged.append((low, high))

    return merged


def overlap(ranges1: Iterable[tuple[float, float]], ranges2: Iterable[tuple[float, float]]) -> float:
    """Returns the total bandwidth in MHz shared by two lists of frequency ranges.
    Ranges that only touch at their edges do not overlap.
    """
    ranges2 = list(ranges2)
    return sum(max(0.0, min(high1, high2) - max(low1, low2))
               for low1, high1 in ranges1 for low2, high2 in ranges2)


class ObservationMixin:
    """Methods of Vex that resolve the references between blocks."""

    @property
    def experiment(self: "Vex") -> str | None:
        """Name of the experiment: exper_name in $EXPER (following 'ref $EXPER' in $GLOBAL)."""
        if "GLOBAL" not in self or "$EXPER" not in self["GLOBAL"]:
            return None

        name = self["GLOBAL"]["$EXPER"]
        if "EXPER" in self and name in self["EXPER"]:
            return self["EXPER"][name].get("exper_name", name)

        return name

    @property
    def stations(self: "Vex") -> list[Station]:
        """All the stations defined in $STATION, in order."""
        if "STATION" not in self:
            return []

        sites = self.get("SITE")
        stations = []
        for definition in self["STATION"].defs:
            site = definition.get("$SITE")
            name = definition.name
            if sites is not None and site in sites:
                name = sites[site].get("site_name", name)

            stations.append(Station(definition.name, name, site, definition.get("$ANTENNA"),
                                    definition.get("$DAS")))

        return stations

    @property
    def modes(self: "Vex") -> list[str]:
        """Names of the modes defined in $MODE."""
        return self["MODE"].keys() if "MODE" in self else []

    @property
    def scans(self: "Vex") -> list["Scan"]:
        """All the scans in $SCHED, in order."""
        from .nodes import Scan

        if "SCHED" not in self:
            return []

        return [definition for definition in self["SCHED"].defs if isinstance(definition, Scan)]

    def setups(self: "Vex", block: str, mode: str) -> dict[str, list[str]]:
        """Returns which definitions of the given block (e.g. 'FREQ') are used by each station
        in the mode, as {definition name: [station codes]}. A reference without stations
        applies to all the stations.
        """
        result: dict[str, list[str]] = {}
        all_stations = [station.code for station in self.stations]
        for statement in self["MODE"][mode].statements(f"${block.removeprefix('$')}"):
            name, *codes = statement.fields
            stations = result.setdefault(name, [])
            for code in codes or all_stations:
                if code and code not in stations:
                    stations.append(code)

        return result

    def setup(self: "Vex", block: str, mode: str, station: str) -> "Def | None":
        """Returns the definition of the block (e.g. 'FREQ') that the station uses in the mode,
        or None if there is none.
        """
        block = block.removeprefix("$")
        for name, codes in self.setups(block, mode).items():
            if station in codes:
                return self[block].get(name) if block in self else None

        return None

    def channels(self: "Vex", mode: str, station: str) -> list[Channel]:
        """Returns the frequency channels of a station in a mode, in the order of the file."""
        freq = self.setup("FREQ", mode, station)
        if freq is None:
            return []

        bbc_to_if: dict[str, str] = {}
        if (bbc := self.setup("BBC", mode, station)) is not None:
            for fields in (s.fields for s in bbc.statements("BBC_assign")):
                bbc_to_if[_name(fields[0])] = _name(fields[2])

        polarizations: dict[str, str] = {}
        if (ifs := self.setup("IF", mode, station)) is not None:
            polarizations = {an_if.name: an_if.polarization for an_if in IF.from_def(ifs)}

        channels = []
        for fields in (s.fields for s in freq.statements("chan_def")):
            bbc = _name(fields[5]) if len(fields) > 5 and fields[5] else None
            channels.append(Channel(
                name=_name(fields[4]) if len(fields) > 4 else "",
                sky_frequency=parse_frequency(fields[1]),
                sideband=fields[2],
                bandwidth=parse_frequency(fields[3]),
                bbc=bbc,
                polarization=polarizations.get(bbc_to_if.get(bbc, "")),
            ))

        return channels
