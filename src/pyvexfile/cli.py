"""Command line interface to inspect VEX files.

    vex experiment.vex                 summary of the observation
    vex experiment.vex --stations      list of stations
    vex experiment.vex --if            IF setups of each mode
    vex experiment.vex --scans         list of scans
    vex experiment.vex --freq          frequencies observed by each station, with a plot
    vex experiment.vex --verify        check the file (exit status 1 if it has errors)
    vex experiment.vex --version       VEX version of the file
    vex experiment.vex --trim [-o NEW] remove the comments after the statements, writing the
                                       result to NEW (or overwriting the file if not given)

Several options can be combined.
"""
import argparse
import math
import re
import shutil
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path

from .lexer import TokenType, VexSyntaxError, tokenize
from .nodes import Vex
from .observation import IF, covered_ranges
from .verify import Severity


__all__: list[str] = ["main"]

# Whitespace followed by '*', unless only '*' and whitespace follow (a closing decoration)
_SECOND_COMMENT = re.compile(r"\s+\*(?!\**\s*$)")

# Characters used in the frequency plot, depending on how much of each cell is covered
_FULL, _PARTIAL, _EMPTY = "█", "▌", " "
_MIN_PLOT_WIDTH = 20


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]], indent: str = "") -> str:
    """Returns the rows as a text table with aligned columns."""
    cells = [[str(cell) for cell in row] for row in rows]
    widths = [max([len(header)] + [len(row[i]) for row in cells]) for i, header in enumerate(headers)]
    lines = [headers, ["-" * width for width in widths]] + cells
    return "\n".join(indent + "  ".join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip()
                     for line in lines)


def _format_frequency(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _section(title: str, body: str) -> str:
    return f"{title}\n{body}"


def show_summary(vex: Vex) -> str:
    scans = vex.scans
    starts = [scan.start for scan in scans if scan.start is not None]
    rows = [
        ("Experiment", vex.experiment or "-"),
        ("VEX version", vex.version or "-"),
        ("Stations", f"{len(vex.stations)}: {' '.join(s.code for s in vex.stations)}"),
        ("Modes", ", ".join(vex.modes) or "-"),
        ("Sources", len(vex["SOURCE"]) if "SOURCE" in vex else 0),
        ("Scans", len(scans)),
    ]
    if starts:
        end = max(scan.start + timedelta(seconds=scan.duration or 0)
                  for scan in scans if scan.start is not None)
        rows.append(("Start (UTC)", f"{min(starts):%Y-%m-%d %H:%M:%S}"))
        rows.append(("End (UTC)", f"{end:%Y-%m-%d %H:%M:%S}"))

    width = max(len(name) for name, _ in rows)
    return "\n".join(f"{name.ljust(width)}  {value}" for name, value in rows)


def show_version(vex: Vex) -> str:
    return f"VEX version: {vex.version or 'unknown (no VEX_rev statement)'}"


def show_stations(vex: Vex) -> str:
    rows = [(s.code, s.name, s.antenna or "-", s.das or "-") for s in vex.stations]
    return _section(f"Stations ({len(rows)})", _table(["Code", "Name", "Antenna", "DAS"], rows))


def show_scans(vex: Vex) -> str:
    rows = []
    for scan in vex.scans:
        start = f"{scan.start:%Y-%m-%d %H:%M:%S}" if scan.start else "-"
        duration = f"{scan.duration:.0f} s" if scan.duration is not None else "-"
        rows.append((scan.name, start, duration, " ".join(scan.sources), scan.mode or "-",
                     f"{len(scan.stations)}: {' '.join(scan.stations)}"))

    headers = ["Scan", "Start (UTC)", "Duration", "Source", "Mode", "Stations"]
    return _section(f"Scans ({len(rows)})", _table(headers, rows))


def show_ifs(vex: Vex) -> str:
    sections = []
    for mode in vex.modes:
        rows = []
        for name, stations in vex.setups("IF", mode).items():
            definition = vex["IF"].get(name) if "IF" in vex else None
            ifs = IF.from_def(definition) if definition is not None else []
            for i, an_if in enumerate(ifs or [None]):
                setup = (name, " ".join(stations)) if i == 0 else ("", "")
                if an_if is None:
                    rows.append(setup + ("(missing in $IF)", "", "", "", ""))
                else:
                    rows.append(setup + (an_if.name, an_if.physical_name, an_if.polarization,
                                         _format_frequency(an_if.lo), an_if.sideband))

        headers = ["$IF setup", "Stations", "IF", "Physical", "Pol", "LO (MHz)", "Sideband"]
        sections.append(_section(f"Mode {mode}", _table(headers, rows, indent="  ")))

    return "\n\n".join(sections) if sections else "No modes defined in $MODE"


def _tick_step(span: float, max_ticks: int) -> float:
    """Returns a round step (1, 2 or 5 times a power of 10) giving at most max_ticks ticks in span."""
    step = 10 ** math.floor(math.log10(span / max(max_ticks, 1))) if span > 0 else 1.0
    while span / step > max_ticks:
        for factor in (2, 2.5, 2):  # 1 -> 2 -> 5 -> 10
            step *= factor
            if span / step <= max_ticks:
                break

    return step


def _ruler(low: float, high: float, width: int) -> tuple[str, str]:
    """Returns the lines with the frequency labels and the ticks for a plot of the given width,
    with ticks at round frequencies.
    """
    span = high - low
    step = _tick_step(span, max(2, width // 12))
    ticks = ["─"] * width
    ticks[0], ticks[-1] = "├", "┤"
    labels = [" "] * width
    free_from = 0  # first column where a new label can start
    value = math.ceil(low / step) * step
    while value <= high + 1e-9:
        position = round((value - low) / span * (width - 1)) if span > 0 else 0
        if 0 < position < width - 1:
            ticks[position] = "┼"

        text = _format_frequency(value)
        start = min(max(position - len(text) // 2, 0), width - len(text))
        if start >= free_from:
            labels[start:start + len(text)] = text
            free_from = start + len(text) + 1

        value += step

    return "".join(labels).rstrip(), "".join(ticks)


def _plot_row(ranges: list[tuple[float, float]], low: float, high: float, width: int) -> str:
    cell = (high - low) / width
    row = []
    for i in range(width):
        cell_low, cell_high = low + i * cell, low + (i + 1) * cell
        covered = sum(max(0.0, min(high_, cell_high) - max(low_, cell_low)) for low_, high_ in ranges)
        row.append(_FULL if covered >= 0.99 * cell else _PARTIAL if covered > 0 else _EMPTY)

    return "".join(row)


def show_frequencies(vex: Vex, width: int | None = None) -> str:
    width = width or shutil.get_terminal_size((100, 24)).columns
    sections = []
    for mode in vex.modes:
        stations = [code for codes in vex.setups("FREQ", mode).values() for code in codes]
        stations = list(dict.fromkeys(stations))
        channels = {code: vex.channels(mode, code) for code in stations}
        rows = []
        for code in stations:
            setup = vex.setup("FREQ", mode, code)
            chans = channels[code]
            bandwidths = Counter(channel.bandwidth for channel in chans)
            polarizations = sorted({c.polarization for c in chans if c.polarization}) or ["?"]
            rows.append((
                code,
                setup.name if setup is not None else "(missing in $FREQ)",
                ", ".join(f"{n}x{_format_frequency(bw)}" for bw, n in sorted(bandwidths.items())),
                ", ".join(f"{_format_frequency(lo)}-{_format_frequency(hi)}"
                          for lo, hi in covered_ranges(chans)),
                " ".join(polarizations),
            ))

        headers = ["Station", "$FREQ setup", "Channels (MHz)", "Covered (MHz)", "Pol"]
        body = [_table(headers, rows, indent="  ")]
        all_channels = [channel for chans in channels.values() for channel in chans]
        if all_channels:
            low = min(channel.low for channel in all_channels)
            high = max(channel.high for channel in all_channels)
            label_width = max(len(code) for code in stations)
            plot_width = max(_MIN_PLOT_WIDTH, width - label_width - 6)
            labels, ticks = _ruler(low, high, plot_width)
            pad = "  " + " " * label_width + " "
            body.append("")
            body.append(f"{pad} Frequency coverage (MHz)")
            body.append(f"{pad} {labels}")
            body.append(f"{pad} {ticks}")
            for code in stations:
                row = _plot_row(covered_ranges(channels[code]), low, high, plot_width)
                body.append(f"  {code.ljust(label_width)} │{row}│")

            body.append(f"{pad} {ticks}")

        sections.append(_section(f"Mode {mode}", "\n".join(body)))

    return "\n\n".join(sections) if sections else "No modes defined in $MODE"


def show_verify(vex: Vex, path: Path, freq_overlap: bool = True) -> tuple[str, bool]:
    """Returns the problems found in the file, and whether any of them is an error."""
    issues = vex.verify(freq_overlap=freq_overlap)
    if not issues:
        return f"{path}: no problems found", False

    lines = [f"{path}:{'' if issue.line is None else f'{issue.line}:'} {issue.severity}: {issue.message}"
             for issue in issues]
    n_errors = sum(issue.severity is Severity.ERROR for issue in issues)
    n_warnings = len(issues) - n_errors
    lines.append(f"{n_errors} error{'s' if n_errors != 1 else ''}, "
                 f"{n_warnings} warning{'s' if n_warnings != 1 else ''}")
    return "\n".join(lines), n_errors > 0


def _trim_line_comment(comment: str) -> str:
    """Removes a second comment (whitespace followed by '*') from a comment that starts a line.
    A closing run of '*' (as in '* Title *') is kept.
    """
    start = len(comment) - len(comment.lstrip("*"))
    match = _SECOND_COMMENT.search(comment, start)
    return comment if match is None else comment[:match.start()]


def trim_comments(text: str) -> str:
    """Returns the text without the comments written after a statement in the same line.
    The comments at the beginning of a line (only preceded by whitespace) are kept, but
    any further comment inside them (e.g. '* Station   * note') is removed.
    """
    parts: list[str] = []
    in_statement = False  # whether the current line has something other than whitespace
    for token in tokenize(text):
        if token.type is TokenType.NEWLINE:
            in_statement = False
        elif token.type is TokenType.COMMENT:
            if in_statement:
                while parts and parts[-1].isspace():
                    parts.pop()
                continue

            parts.append(_trim_line_comment(token.value))
            continue
        elif token.type is not TokenType.WHITESPACE:
            in_statement = True

        parts.append(token.value)

    return "".join(parts)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vex",
        description="Inspect a VEX file. Without options, shows a summary of the observation.",
    )
    parser.add_argument("vexfile", type=Path, help="the VEX file")
    parser.add_argument("--version", action="store_true", help="show the VEX version of the file")
    parser.add_argument("--stations", action="store_true", help="list the stations")
    parser.add_argument("--if", dest="ifs", action="store_true", help="list the IF setups of each mode")
    parser.add_argument("--scans", action="store_true", help="list the scans")
    parser.add_argument("--freq", action="store_true",
                        help="show the frequencies observed by each station, with a plot")
    parser.add_argument("--verify", action="store_true", help="check that the VEX file is correct")
    parser.add_argument("--no-freq-overlap", dest="freq_overlap", action="store_false",
                        help="with --verify, do not check that each station shares frequencies "
                             "with the other stations in its scans")
    parser.add_argument("--trim", action="store_true",
                        help="remove the comments written after a statement (comments at the "
                             "beginning of a line are kept), and overwrite the VEX file "
                             "(or write the result to the file given with -o)")
    parser.add_argument("-o", "--output", type=Path, metavar="NEWFILE",
                        help="with --trim, write the result to NEWFILE instead of overwriting "
                             "the VEX file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.trim and any((args.version, args.verify, args.stations, args.ifs, args.freq, args.scans)):
        parser.error("--trim cannot be combined with other options")
    if args.output is not None and not args.trim:
        parser.error("-o/--output can only be used with --trim")

    try:
        vex = Vex(args.vexfile)
    except OSError as error:
        print(f"vex: cannot read {args.vexfile}: {error.strerror or error}", file=sys.stderr)
        return 1
    except VexSyntaxError as error:
        print(f"{args.vexfile}:{error.line}:{error.col}: syntax error: {error.message}", file=sys.stderr)
        return 1

    if args.trim:
        target = args.output or args.vexfile
        try:
            with open(target, "w", newline="") as trimmed:  # newline='' keeps the original line breaks
                trimmed.write(trim_comments(vex.to_string()))
        except OSError as error:
            print(f"vex: cannot write {target}: {error.strerror or error}", file=sys.stderr)
            return 1

        print(f"Trimmed VEX file written to {target}")
        return 0

    has_errors = False

    def verification() -> str:
        nonlocal has_errors
        text, has_errors = show_verify(vex, args.vexfile, args.freq_overlap)
        return text

    views: list[tuple[bool, Callable[[], str]]] = [
        (args.version, lambda: show_version(vex)),
        (args.verify, verification),
        (args.stations, lambda: show_stations(vex)),
        (args.ifs, lambda: show_ifs(vex)),
        (args.freq, lambda: show_frequencies(vex)),
        (args.scans, lambda: show_scans(vex)),
    ]
    outputs = [view() for selected, view in views if selected] or [show_summary(vex)]
    try:
        print("\n\n".join(outputs))
    except BrokenPipeError:  # e.g. when piped to 'head'
        sys.stderr.close()

    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
