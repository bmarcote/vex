from pathlib import Path

import pytest

from pyvexfile.cli import _ruler, _tick_step, main, show_frequencies
from pyvexfile import Vex


DATA = Path(__file__).parent / "data"
N26C3 = str(DATA / "n26c3.vex")


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_summary(capsys):
    code, out, _ = run(capsys, N26C3)
    assert code == 0
    assert "Experiment   N26C3" in out
    assert "Scans        14" in out
    assert "Start (UTC)  2026-10-20 11:00:00" in out
    assert "End (UTC)    2026-10-20 14:00:00" in out


def test_version(capsys):
    assert run(capsys, N26C3, "--version")[1] == "VEX version: 1.5\n"


def test_stations(capsys):
    out = run(capsys, N26C3, "--stations")[1]
    assert out.startswith("Stations (15)\nCode  Name")
    assert "Jb    JODRELL2  JODRELL2  DBBC+Mark5C" in out


def test_scans(capsys):
    out = run(capsys, N26C3, "--scans")[1]
    assert "No0001  2026-10-20 11:00:00  360 s     J1753+2848  evn6cm-4Gbps-32MHz  15: Jb Wb" in out


def test_ifs(capsys):
    out = run(capsys, N26C3, "--if")[1]
    assert out.startswith("Mode evn6cm-4Gbps-32MHz\n")
    assert "LO@4088MHzDPolNoTone#02  Ir O8" in out
    assert "IF_C3  C3        L    4088      U" in out


def test_freq(capsys):
    out = run(capsys, N26C3, "--freq")[1]
    assert "  Cm       4888MHz2x64MHz   2x64            4888-4952      L R" in out
    assert "  Wb       4888MHz8x32MHz   8x32            4856-4984      L R" in out


def test_options_are_combined_in_order(capsys):
    out = run(capsys, N26C3, "--scans", "--version", "--stations")[1]
    assert out.index("VEX version") < out.index("Stations (15)") < out.index("Scans (14)")


def test_verify(capsys):
    code, out, _ = run(capsys, N26C3, "--verify")
    assert (code, out) == (0, f"{N26C3}: no problems found\n")


def test_verify_with_problems(capsys, tmp_path: Path):
    text = (DATA / "n26c3.vex").read_text().replace("ref $SITE = JODRELL2;", "ref $SITE = JODRELL3;")
    # Move only the frequencies of Wb (its own $FREQ setup) to 9.9 GHz
    before, header, after = text.partition("def 4888MHz8x32MHz;")
    wb, end, rest = after.partition("enddef;")
    text = before + header + wb.replace(" 4888 MHz", " 9888 MHz").replace(" 4952 MHz", " 9952 MHz") + end + rest
    bad = tmp_path / "bad.vex"
    bad.write_text("VEX_rev = 9.9;\n" + text.split("\n", 1)[1])
    code, out, _ = run(capsys, str(bad), "--verify")
    lines = out.splitlines()
    assert code == 1
    assert lines[0] == f"{bad}:1: warning: unknown VEX version '9.9'; the file is checked as VEX 1.5"
    site_line = text.split("ref $SITE = JODRELL3;")[0].count("\n") + 1
    assert lines[1].startswith(f"{bad}:{site_line}: error: 'ref $SITE' in 'def Jb' ($STATION): 'JODRELL3'")
    assert "station Wb does not share any frequency" in out
    assert lines[-1] == f"{len(lines) - 2} errors, 1 warning"

    code, out, _ = run(capsys, str(bad), "--verify", "--no-freq-overlap")
    assert code == 1 and "does not share" not in out
    assert out.splitlines()[-1] == "1 error, 1 warning"


def test_verify_only_warnings_exits_with_zero(capsys, tmp_path: Path):
    warned = tmp_path / "warned.vex"
    warned.write_text((DATA / "n26c3.vex").read_text().replace("VEX_rev = 1.5;", "VEX_rev = 9.9;"))
    code, out, _ = run(capsys, str(warned), "--verify")
    assert code == 0 and out.splitlines()[-1] == "0 errors, 1 warning"


def test_missing_file(capsys, tmp_path: Path):
    code, out, err = run(capsys, str(tmp_path / "nope.vex"))
    assert code == 1 and out == "" and "cannot read" in err


def test_syntax_error(capsys, tmp_path: Path):
    bad = tmp_path / "bad.vex"
    bad.write_text("VEX_rev = 1.5;\n$GLOBAL;\n  ref $EXPER = X\n$EXPER;\n")
    code, _, err = run(capsys, str(bad))
    assert code == 1
    assert err == f"{bad}:4:1: syntax error: unexpected '$' in the value of 'EXPER' " \
                  "(missing ';' at the end of line 3?)\n"


# Frequency plot

@pytest.mark.parametrize("width", [40, 80, 120, 200])
def test_frequency_plot_fits_and_aligns(width: int):
    lines = show_frequencies(Vex.from_file(N26C3), width=width).splitlines()
    plot = lines[lines.index("") + 1:]
    assert all(len(line) <= width for line in plot)
    rows = [line for line in plot if "│" in line]
    ticks = [line for line in plot if "├" in line]
    assert len(rows) == 15 and len(ticks) == 2
    # The plot area of every row starts and ends at the same columns as the ruler
    for row in rows:
        assert row.index("│") + 1 == ticks[0].index("├")
        assert row.rindex("│") == ticks[0].index("┤") + 1


def test_frequency_plot_coverage():
    lines = show_frequencies(Vex.from_file(N26C3), width=100).splitlines()
    rows = {line.split()[0]: line[line.index("│") + 1:line.rindex("│")] for line in lines if "│" in line}
    assert set(rows["Ef"]) == {"█"}  # covers the whole band
    cm = rows["Cm"].strip()
    assert cm and len(cm) < len(rows["Wb"].strip()) < len(rows["Ef"])


@pytest.mark.parametrize("span, max_ticks, step", [(512, 8, 100), (512, 4, 200), (64, 5, 20), (3.2, 4, 1)])
def test_tick_step(span: float, max_ticks: int, step: float):
    assert _tick_step(span, max_ticks) == pytest.approx(step)


def test_ruler_labels_at_round_values():
    labels, ticks = _ruler(4600, 5112, 52)
    assert labels.split() == ["4600", "4800", "5000"]
    assert len(ticks) == 52 and ticks[0] == "├" and ticks[-1] == "┤"
