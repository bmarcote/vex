from datetime import datetime, timezone
from pathlib import Path

import pytest

from pyvexfile import Vex
from pyvexfile.observation import IF, Channel, Station
from pyvexfile.units import parse_duration, parse_epoch, parse_frequency


DATA = Path(__file__).parent / "data"
SCHED_FILES = sorted(DATA.glob("n26*.vex"))


@pytest.fixture
def vex() -> Vex:
    return Vex.from_file(DATA / "n26c3.vex")


# Units

@pytest.mark.parametrize("text, mhz", [
    ("4632 MHz", 4632.0), ("32.00 MHz", 32.0), ("1.5 GHz", 1500.0), ("500 kHz", 0.5),
    ("8000000 Hz", 8.0), ("4632MHz", 4632.0),
])
def test_parse_frequency(text: str, mhz: float):
    assert parse_frequency(text) == pytest.approx(mhz)


@pytest.mark.parametrize("text", ["4632", "4632 Mhz", "MHz", "abc MHz", ""])
def test_parse_frequency_errors(text: str):
    with pytest.raises(ValueError):
        parse_frequency(text)


@pytest.mark.parametrize("text, seconds", [("360 sec", 360), ("0 sec", 0), ("2 min", 120), ("5", 5)])
def test_parse_duration(text: str, seconds: float):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text, expected", [
    ("2026y293d11h00m00s", datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)),
    ("1997y001d", datetime(1997, 1, 1, tzinfo=timezone.utc)),
    ("2024y366d23h59m59.5s", datetime(2024, 12, 31, 23, 59, 59, 500000, tzinfo=timezone.utc)),
])
def test_parse_epoch(text: str, expected: datetime):
    assert parse_epoch(text) == expected


@pytest.mark.parametrize("text", ["293d11h", "2026", "2026y293dxx", "2026yd"])
def test_parse_epoch_errors(text: str):
    with pytest.raises(ValueError):
        parse_epoch(text)


# Observation

def test_experiment_and_modes(vex: Vex):
    assert vex.experiment == "N26C3"
    assert vex.modes == ["evn6cm-4Gbps-32MHz"]
    assert Vex().experiment is None and Vex().modes == [] and Vex().stations == []


def test_stations(vex: Vex):
    stations = vex.stations
    assert len(stations) == 15
    assert stations[0] == Station("Jb", "JODRELL2", "JODRELL2", "JODRELL2", "DBBC+Mark5C")


def test_scans(vex: Vex):
    scan = vex.scans[0]
    assert scan.name == "No0001"
    assert scan.start == datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc)
    assert scan.duration == 360
    assert scan.mode == "evn6cm-4Gbps-32MHz"
    assert scan.sources == ["J1753+2848"]
    assert scan.stations[:3] == ["Jb", "Wb", "Ef"] and len(scan.stations) == 15


def test_setups(vex: Vex):
    mode = "evn6cm-4Gbps-32MHz"
    assert vex.setups("FREQ", mode) == {
        "4632MHz32x32MHz": ["Ef", "Hh", "Ir", "Jb", "Mc", "O8", "T6", "Tr", "Ur"],
        "4888MHz2x64MHz": ["Cm", "Da", "De", "Kn", "Pi"],
        "4888MHz8x32MHz": ["Wb"],
    }
    assert vex.setup("$FREQ", mode, "Wb").name == "4888MHz8x32MHz"
    assert vex.setup("FREQ", mode, "Xx") is None


def test_ref_without_stations_applies_to_all():
    vex = Vex.from_string(
        "$MODE;\ndef m;\n  ref $FREQ = f;\nenddef;\n"
        "$STATION;\ndef Aa;\nenddef;\ndef Bb;\nenddef;\n"
        "$FREQ;\ndef f;\n  chan_def = : 100 MHz : U : 8 MHz : &CH01 : &BBC01;\nenddef;\n"
    )
    assert vex.setups("FREQ", "m") == {"f": ["Aa", "Bb"]}
    assert vex.channels("m", "Bb") == [Channel("CH01", 100.0, "U", 8.0, "BBC01", None)]


def test_channels(vex: Vex):
    channels = vex.channels("evn6cm-4Gbps-32MHz", "Cm")
    assert channels == [
        Channel("CH01", 4888.0, "U", 64.0, "BBC01", "R"),
        Channel("CH02", 4888.0, "U", 64.0, "BBC09", "L"),
    ]
    assert (channels[0].low, channels[0].high) == (4888.0, 4952.0)
    lower = vex.channels("evn6cm-4Gbps-32MHz", "Ef")[0]
    assert lower.sideband == "L" and (lower.low, lower.high) == (4600.0, 4632.0)
    assert vex.channels("evn6cm-4Gbps-32MHz", "Xx") == []


@pytest.mark.parametrize("vexfile", SCHED_FILES, ids=lambda p: p.name)
def test_polarizations_match_sched_comments(vexfile: Path):
    """SCHED writes the polarization of each channel as a comment ('* RCP'), which must agree
    with the one obtained following chan_def -> BBC_assign -> if_def.
    """
    vex = Vex.from_file(vexfile)
    checked = 0
    for mode in vex.modes:
        for freq_name, stations in vex.setups("FREQ", mode).items():
            comments = [s.comment.strip()[0] for s in vex["FREQ"][freq_name].statements("chan_def")]
            for station in stations:
                assert [c.polarization for c in vex.channels(mode, station)] == comments
                checked += 1

    assert checked == len({code for scan in vex.scans for code in scan.stations})


def test_if_from_def(vex: Vex):
    ifs = IF.from_def(vex["IF"]["LO@4088MHzDPolNoTone"])
    assert ifs[0] == IF("IF_A1", "A1", "R", 4088.0, "U")
    assert [an_if.polarization for an_if in ifs] == ["R", "L", "R", "L"]
