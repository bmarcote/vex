from pathlib import Path

import pytest

from pyvexfile import Issue, Severity, Vex


DATA = Path(__file__).parent / "data"
N26C3 = (DATA / "n26c3.vex").read_text()

E, W = Severity.ERROR, Severity.WARNING


def mutated(*replacements: tuple[str, str]) -> Vex:
    """Returns n26c3.vex with the given (old, new) text replacements (each old text must be unique)."""
    text = N26C3
    for old, new in replacements:
        assert text.count(old) == 1, old
        text = text.replace(old, new)

    return Vex.from_string(text)


def line_of(text: str) -> int:
    """Line number (starting at 1) of the unique occurrence of text in n26c3.vex."""
    assert N26C3.count(text) == 1, text
    return N26C3[:N26C3.index(text)].count("\n") + 1


def summary(issues: list[Issue]) -> list[tuple[Severity, str]]:
    return [(issue.severity, issue.message) for issue in issues]


@pytest.mark.parametrize("vexfile", sorted(DATA.glob("*.vex")), ids=lambda p: p.name)
def test_valid_files_have_no_issues(vexfile: Path):
    assert Vex.from_file(vexfile).verify() == []


def test_issue_str():
    assert str(Issue(E, "something", 12)) == "line 12: error: something"
    assert str(Issue(W, "something")) == "warning: something"


# Header and structure

def test_missing_vex_rev():
    issues = mutated(("VEX_rev = 1.5;\n", "")).verify()
    assert summary(issues) == [(E, "the file must start with 'VEX_rev = ...;'")]


def test_unknown_version():
    assert summary(mutated(("VEX_rev = 1.5;", "VEX_rev = 3.1;")).verify()) == [
        (W, "unknown VEX version '3.1'; the file is checked as VEX 1.5")
    ]


def test_unknown_and_duplicated_blocks():
    vex = mutated(("$SCHED;\n", "$FOO;\n$SOURCE;\n$SCHED;\n"))
    assert summary(vex.verify()) == [
        (W, "block $FOO is not defined in VEX 1.5"),
        (E, f"block $SOURCE is defined more than once (also at line {line_of('$SOURCE;')})"),
    ]


def test_vex2_blocks_are_known():
    assert mutated(("VEX_rev = 1.5;", "VEX_rev = 2.0;"),
                   ("$SCHED;\n", "$DATASTREAMS;\n$SCHED;\n")).verify() == []


def test_duplicated_definition_and_misplaced_scan():
    vex = mutated(("def JODRELL2;\n     site_type", "def DARNHALL;\n     site_type"),
                  ("$SOURCE;\n", "$SOURCE;\nscan X;\nendscan;\n"))
    messages = summary(vex.verify())
    assert (E, "'scan X' outside of $SOURCE") not in messages
    assert (E, "'scan X' outside of $SCHED") in messages
    assert any(message.startswith("'def DARNHALL' is defined more than once in $SITE")
               for _, message in messages)


# Values

@pytest.mark.parametrize("old, new, message", [
    ("&CH01 : &BBC01 : &NoCal; * RCP\n     chan_def =  : 4888 MHz : U :   64.00 MHz",
     "&CH01 : &BBC01 : &NoCal; * RCP\n     chan_def =  : 4888 MHz : X :   64.00 MHz",
     "chan_def in 'def 4888MHz2x64MHz' ($FREQ): net sideband must be one of U, L ('X')"),
    ("chan_def =  : 4888 MHz : U :   64.00 MHz : &CH01",
     "chan_def =  : 4888 MHz : U :   64.00 Mhz : &CH01",
     "chan_def in 'def 4888MHz2x64MHz' ($FREQ): bandwidth: unknown unit in '64.00 Mhz' "
     "(expected one of: Hz, kHz, MHz, GHz)"),
    ("if_def = &IF_A1 : A1 : R :   4088.00 MHz : U;\n     if_def = &IF_C3",
     "if_def = &IF_A1 : A1 : Q :   4088.00 MHz : U;\n     if_def = &IF_C3",
     "if_def in 'def LO@4088MHzDPolNoTone' ($IF): polarization must be one of R, L, X, Y, H, V ('Q')"),
    ("dec =  28d48'04.938910\"", "dec = 98d48'04.938910\"",
     "dec in 'def J1753+2848' ($SOURCE): '98d48'04.938910\"' is not a valid declination "
     "(e.g. 28d48'04.93\")"),
    ("start = 2026y293d11h00m00s;", "start = 2026y29xd11h00m00s;",
     "start in 'scan No0001' ($SCHED): '2026y29xd11h00m00s' is not a valid VEX epoch "
     "(expected e.g. 2026y293d11h00m00s)"),
])
def test_wrong_values(old: str, new: str, message: str):
    assert (E, message) in summary(mutated((old, new)).verify())


def test_issue_has_the_line_of_the_statement():
    issues = mutated(("dec =  28d48'04.938910\"", "dec = 98d48'04.938910\"")).verify()
    assert issues[0].line == line_of("dec =  28d48'04.938910\"")


# References

def test_undefined_reference():
    issues = mutated(("ref $SITE = JODRELL2;", "ref $SITE = JODRELL3;")).verify()
    assert summary(issues) == [
        (E, "'ref $SITE' in 'def Jb' ($STATION): 'JODRELL3' is not defined in $SITE")
    ]
    assert issues[0].line == line_of("ref $SITE = JODRELL2;")


def test_reference_to_missing_block():
    assert (E, "'ref $NOPE' in 'def Jb' ($STATION): block $NOPE is not defined") in \
        summary(mutated(("ref $SITE = JODRELL2;", "ref $SITE = JODRELL2;\n     ref $NOPE = x;")).verify())


def test_unknown_station_in_mode():
    issues = mutated(("ref $IF = LO@4088MHzDPolNoTone:Ef;", "ref $IF = LO@4088MHzDPolNoTone:Ef:Zz;"))
    assert summary(issues.verify()) == [
        (E, "'ref $IF' in 'def evn6cm-4Gbps-32MHz' ($MODE): unknown station Zz (not defined in $STATION)")
    ]


def test_channel_with_unassigned_bbc():
    issues = mutated(("U :   64.00 MHz : &CH01 : &BBC01", "U :   64.00 MHz : &CH01 : &BBC99")).verify()
    assert summary(issues) == [
        (E, "chan_def in 'def 4888MHz2x64MHz' ($FREQ) uses &BBC99, which is not assigned in "
            "'def 2BBCs' ($BBC) (setup of Cm in mode 'evn6cm-4Gbps-32MHz')"),
    ]


def test_bbc_with_undefined_if():
    vex = mutated(("Cm, Da, De, Kn, Pi\n     BBC_assign = &BBC01 : 1 : &IF_A1;",
                   "Cm, Da, De, Kn, Pi\n     BBC_assign = &BBC01 : 1 : &IF_Z9;"))
    messages = summary(vex.verify())
    assert len(messages) == 1
    assert messages[0][1].startswith("BBC_assign in 'def 2BBCs' ($BBC) uses &IF_Z9, which is not defined in")


# Scans

def test_scan_references():
    vex = mutated(("scan No0001;\n     start = 2026y293d11h00m00s;\n     mode = evn6cm-4Gbps-32MHz;\n"
                   "     source = J1753+2848;\n     station = Jb",
                   "scan No0001;\n     start = 2026y293d11h00m00s;\n     mode = nomode;\n"
                   "     source = NOSRC;\n     station = Zz"))
    assert summary(vex.verify()) == [
        (E, "scan No0001: mode 'nomode' is not defined in $MODE"),
        (E, "scan No0001: source 'NOSRC' is not defined in $SOURCE"),
        (E, "scan No0001: station Zz is not defined in $STATION"),
    ]


def test_station_without_freq_setup_is_reported_once():
    vex = mutated(("ref $FREQ = 4888MHz8x32MHz:Wb;\n", ""))
    assert summary(vex.verify()) == [
        (E, "station Wb has no $FREQ setup in mode 'evn6cm-4Gbps-32MHz' "
            "(scans No0001, No0002, No0003 and 11 more)"),
    ]


def test_scans_out_of_order_and_overlapping():
    vex = mutated(("start = 2026y293d11h08m00s;", "start = 2026y293d10h59m00s;"))
    issues = vex.verify()
    # The overlap is reported at the scan that is later in time (No0001), which is earlier in the file
    assert summary(issues) == [
        *[(W, f"station {code} observes in overlapping scans No0002 and No0001")
          for code in vex.scans[1].stations],
        (W, "scan No0002 starts before the previous scan"),
    ]
    assert issues[0].line == line_of("scan No0001;")


# Frequency overlap

def shifted_setup(name: str, shifts: dict[str, str]) -> str:
    """Returns n26c3.vex replacing the frequencies of the $FREQ definition 'name'."""
    before, header, after = N26C3.partition(f"def {name};")
    setup, end, rest = after.partition("enddef;")
    for old, new in shifts.items():
        setup = setup.replace(f" {old} MHz", f" {new} MHz")

    return before + header + setup + end + rest


def test_station_without_overlap_in_real_file():
    # Wb is the only station using 4888MHz8x32MHz
    vex = Vex.from_string(shifted_setup("4888MHz8x32MHz", {"4888": "9888", "4952": "9952"}))
    issues = vex.verify()
    assert summary(issues) == [
        (E, "station Wb does not share any frequency with the other stations in mode "
            "'evn6cm-4Gbps-32MHz' (scans No0001, No0002, No0003 and 11 more); "
            "it covers 9856-9984 MHz"),
    ]
    assert issues[0].line == line_of("scan No0001;")
    assert vex.verify(freq_overlap=False) == []


def synthetic(scans: list[tuple[str, list[str]]]) -> Vex:
    """A VEX file with stations Aa, Bb, Cc and two modes:
        m1: Aa and Bb observe at 1600-1632 MHz, Cc at 5000-5032 MHz
        m2: Aa, Bb and Cc observe at 5000-5032 MHz
    scans is a list of (mode, stations).
    """
    stations = "".join(f"def {code};\nenddef;\n" for code in ("Aa", "Bb", "Cc"))
    sched = "".join(
        f"scan s{i};\n  start = 2026y293d{10 + i:02d}h00m00s;\n  mode = {mode};\n  source = SRC;\n"
        + "".join(f"  station = {code} : 0 sec : 600 sec : 0 ft : 1A : &cw : 1;\n" for code in codes)
        + "endscan;\n"
        for i, (mode, codes) in enumerate(scans, start=1)
    )
    return Vex.from_string(
        "VEX_rev = 1.5;\n"
        "$MODE;\n"
        "def m1;\n  ref $FREQ = low:Aa:Bb;\n  ref $FREQ = high:Cc;\n"
        "  ref $BBC = bbcs:Aa:Bb:Cc;\n  ref $IF = ifs:Aa:Bb:Cc;\nenddef;\n"
        "def m2;\n  ref $FREQ = high:Aa:Bb:Cc;\n  ref $BBC = bbcs:Aa:Bb:Cc;\n  ref $IF = ifs:Aa:Bb:Cc;\nenddef;\n"
        "$FREQ;\n"
        "def low;\n  chan_def = : 1600 MHz : U : 32 MHz : &CH01 : &BBC01 : &NoCal;\nenddef;\n"
        "def high;\n  chan_def = : 5000 MHz : U : 32 MHz : &CH01 : &BBC01 : &NoCal;\nenddef;\n"
        "$BBC;\ndef bbcs;\n  BBC_assign = &BBC01 : 1 : &IF_A;\nenddef;\n"
        "$IF;\ndef ifs;\n  if_def = &IF_A : A : R : 1000 MHz : U;\nenddef;\n"
        f"$STATION;\n{stations}"
        "$SOURCE;\ndef SRC;\n  ra = 01h00m00s;\n  dec = 10d00'00\";\n  ref_coord_frame = J2000;\nenddef;\n"
        f"$SCHED;\n{sched}"
    )


def test_overlap_is_checked_with_the_stations_and_mode_of_each_scan():
    # Cc only observes with the others in m2, where they share frequencies
    assert synthetic([("m1", ["Aa", "Bb"]), ("m2", ["Aa", "Bb", "Cc"])]).verify() == []


def test_station_without_overlap_in_one_part_of_the_observation():
    vex = synthetic([("m1", ["Aa", "Bb"]), ("m2", ["Aa", "Bb", "Cc"]),
                     ("m1", ["Aa", "Bb", "Cc"]), ("m1", ["Aa", "Bb", "Cc"])])
    issues = vex.verify()
    assert summary(issues) == [
        (E, "station Cc does not share any frequency with the other stations in mode 'm1' "
            "(scans s3, s4); it covers 5000-5032 MHz"),
    ]
    assert issues[0].line == vex.scans[2].line
    assert vex.verify(freq_overlap=False) == []


def test_overlap_with_one_station_is_enough():
    # In m1, Cc and Aa share nothing, but each of them overlaps with Bb in this setup
    vex = synthetic([("m1", ["Aa", "Bb", "Cc"])])
    vex["FREQ"]["low"].statements("chan_def")[0].fields[1] = "4990 MHz"  # Aa, Bb: 4990-5022 MHz
    vex["MODE"]["m1"].statements("$FREQ")[0].fields[1:] = ["Bb"]
    vex["MODE"]["m1"].add("$FREQ", ["far", "Aa"])
    vex["FREQ"]["far"] = vex["FREQ"]["low"].__class__("far")
    vex["FREQ"]["far"].add("chan_def", ["", "4980 MHz", "U", "16 MHz", "&CH01", "&BBC01", "&NoCal"])
    ranges = {code: [(c.low, c.high) for c in vex.channels("m1", code)] for code in ("Aa", "Bb", "Cc")}
    assert ranges == {"Aa": [(4980, 4996)], "Bb": [(4990, 5022)], "Cc": [(5000, 5032)]}
    assert vex.verify() == []


def test_two_stations_without_overlap_are_both_reported():
    messages = [message for _, message in summary(synthetic([("m1", ["Aa", "Cc"])]).verify())]
    assert [message.split(" does not")[0] for message in messages] == ["station Aa", "station Cc"]


def test_overlap_without_scans_uses_all_stations_of_each_mode():
    vex = synthetic([])
    assert summary(vex.verify()) == [
        (E, "station Cc does not share any frequency with the other stations in mode 'm1' "
            "(all its stations); it covers 5000-5032 MHz"),
    ]


def test_separate_groups_of_stations_give_a_warning():
    # The five stations using 4888MHz2x64MHz overlap with each other, but not with the rest
    vex = Vex.from_string(shifted_setup("4888MHz2x64MHz", {"4888": "9888"}))
    issues = vex.verify()
    assert summary(issues) == [
        (W, "the stations in mode 'evn6cm-4Gbps-32MHz' form 2 groups without any frequency in common "
            "between them (scans No0001, No0002, No0003 and 11 more): "
            "Jb Wb Ef Mc O8 T6 Ur Tr Hh Ir (4600-5112 MHz); Cm Kn Pi Da De (9888-9952 MHz)"),
    ]
    assert vex.verify(freq_overlap=False) == []
