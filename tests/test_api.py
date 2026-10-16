from pathlib import Path

import pytest

from pyvexfile import Block, Def, Scan, Statement, Vex, VexSyntaxError


DATA = Path(__file__).parent / "data"
VEX_FILES = sorted(DATA.glob("*.vex"))


@pytest.fixture
def vex() -> Vex:
    return Vex.from_file(DATA / "n26c3.vex")


@pytest.fixture
def edge() -> Vex:
    return Vex.from_file(DATA / "edge_cases.vex")


# Reading and writing

@pytest.mark.parametrize("vexfile", VEX_FILES, ids=lambda p: p.name)
def test_file_round_trip(vexfile: Path, tmp_path: Path):
    Vex.from_file(vexfile).to_file(tmp_path / "out.vex")
    assert (tmp_path / "out.vex").read_bytes() == vexfile.read_bytes()


def test_crlf_file_round_trip(tmp_path: Path):
    crlf = (DATA / "n26c3.vex").read_bytes().replace(b"\n", b"\r\n")
    (tmp_path / "in.vex").write_bytes(crlf)
    Vex.from_file(tmp_path / "in.vex").to_file(tmp_path / "out.vex")
    assert (tmp_path / "out.vex").read_bytes() == crlf


def test_to_file_does_not_overwrite(vex: Vex, tmp_path: Path):
    (tmp_path / "out.vex").write_text("existing")
    with pytest.raises(FileExistsError):
        vex.to_file(tmp_path / "out.vex", overwrite=False)

    assert (tmp_path / "out.vex").read_text() == "existing"


def test_from_string_syntax_error():
    with pytest.raises(VexSyntaxError):
        Vex.from_string("$A;\ndef x;\n")


# Vex

def test_version(vex: Vex):
    assert vex.version == "1.5"
    vex.version = "2.0"
    assert vex.to_string().startswith("VEX_rev = 2.0;\n*    pySCHED")
    assert Vex().version is None


def test_vex_is_a_mapping_of_blocks(vex: Vex):
    assert vex.keys()[:3] == ["GLOBAL", "EXPER", "MODE"]
    assert list(vex) == vex.keys()
    assert len(vex) == len(vex.blocks)
    assert "STATION" in vex and "NOPE" not in vex
    assert isinstance(vex["STATION"], Block)
    assert vex.get("NOPE") is None
    with pytest.raises(KeyError):
        vex["NOPE"]


def test_replace_add_and_delete_blocks(vex: Vex):
    vex["EXPER"] = Block("ignored", [Def("X", [Statement("exper_name", "X")])])
    assert vex.keys()[:3] == ["GLOBAL", "EXPER", "MODE"]
    assert vex["EXPER"]["X"]["exper_name"] == "X"
    vex["NEW"] = Block("NEW")
    assert vex.keys()[-1] == "NEW" and vex.to_string().endswith("$NEW;\n")
    del vex["NEW"]
    assert "NEW" not in vex


# Blocks

def test_block_is_a_mapping_of_defs(vex: Vex):
    station = vex["STATION"]
    assert "Jb" in station
    assert isinstance(station["Jb"], Def)
    assert [name for name, _ in station.items()] == station.keys() == list(station)
    assert len(station) == len(station.defs) == 15


def test_block_refs(vex: Vex):
    assert vex["GLOBAL"]["$EXPER"] == "N26C3"
    assert "$EXPER" in vex["GLOBAL"]
    assert len(vex["GLOBAL"]) == 0  # no definitions in $GLOBAL


def test_scans(vex: Vex):
    scan = vex["SCHED"]["No0001"]
    assert isinstance(scan, Scan)
    assert scan["source"] == "J1753+2848"
    assert scan.get_all("station")[0] == ["Jb", "0 sec", "360 sec", "0.000 GB", "", "&n", "1"]


def test_add_and_replace_def(edge: Vex):
    freq = edge["FREQ"]
    freq["new"] = Def("x", [Statement("sample_rate", "32.0 Ms/sec")])
    assert freq.keys() == ["4632MHz", "new"]
    assert edge.to_string().endswith("def new;\n     sample_rate = 32.0 Ms/sec;\nenddef;\n"
                                     "$SCHEDULING_PARAMS;\nstart_literal(sched);\n"
                                     "  Free text; with semicolons * asterisks = equals\n"
                                     "  and an end_literal(other); that must not close the block.\n"
                                     "end_literal(sched);\n")
    freq["4632MHz"] = Def("x")
    assert freq["4632MHz"].keys() == []
    del freq["new"]
    assert freq.keys() == ["4632MHz"]


def test_block_setitem_type_errors(edge: Vex):
    with pytest.raises(TypeError):
        edge["FREQ"]["x"] = "a value"
    with pytest.raises(TypeError):
        edge["GLOBAL"]["$EXPER"] = Def("x")


def test_new_block_ref_goes_before_defs(edge: Vex):
    edge["EXPER"]["$NEW"] = "value"
    assert edge["EXPER"].children[0].full_key == "$NEW"


# Definitions

def test_def_values(edge: Vex):
    source = edge["SOURCE"]["J1753+2848"]
    assert source["ra"] == "17h53m42.4736450s"
    assert source["dec"] == "28d48'04.938910\""
    assert source["ref_coord_frame"] == "J2000"
    assert source.keys() == ["source_name", "ra", "dec", "ref_coord_frame"]


def test_def_refs(vex: Vex):
    mode = vex["MODE"]["evn6cm-4Gbps-32MHz"]
    assert mode.get_all("$IF")[1] == ["LO@4088MHzDPolNoTone#02", "Ir", "O8"]
    assert mode["$PHASE_CAL_DETECT"][0] == "NoDetect"
    assert "$IF" in mode and "IF" not in mode


def test_repeated_key_needs_get_all(vex: Vex):
    freq = vex["FREQ"]["4632MHz32x32MHz"]
    with pytest.raises(ValueError, match=r"'chan_def' appears 32 times .* use get_all\('chan_def'\)"):
        freq["chan_def"]

    chan_defs = freq.get_all("chan_def")
    assert len(chan_defs) == 32
    assert chan_defs[0][-1] == "&NoCal"
    assert freq.statements("chan_def")[0].comment == " RCP"
    with pytest.raises(ValueError):
        freq["chan_def"] = "x"


def test_missing_key(edge: Vex):
    source = edge["SOURCE"]["J1753+2848"]
    with pytest.raises(KeyError):
        source["nope"]

    assert source.get("nope") is None
    assert source.get("nope", "default") == "default"


def test_items_include_repeated_keys(edge: Vex):
    freq = edge["FREQ"]["4632MHz"]
    assert [key for key, _ in freq.items()] == ["chan_def", "chan_def", "sample_rate", "chan_def"]
    assert freq.keys() == ["chan_def", "sample_rate"]
    assert len(freq) == 2


def test_set_existing_value_keeps_layout(vex: Vex):
    original = vex.to_string()
    vex["EXPER"]["N26C3"]["exper_name"] = "N99X1"
    changed = [(a, b) for a, b in zip(original.splitlines(), vex.to_string().splitlines()) if a != b]
    assert changed == [("     exper_name = N26C3;", "     exper_name = N99X1;")]


def test_set_new_value_and_add(edge: Vex):
    freq = edge["FREQ"]["4632MHz"]
    freq["new_param"] = ["a", "b"]
    added = freq.add("chan_def", ["", "4700 MHz", "U"], comment=" new")
    assert added in freq.statements("chan_def")
    keys = [key for key, _ in freq.items()]
    assert keys == ["chan_def", "chan_def", "sample_rate", "chan_def", "chan_def", "new_param"]
    text = edge.to_string()
    assert ("&CH03 : &BBC01 : &NoCal;\n     chan_def =  : 4700 MHz : U; * new\n"
            "     new_param = a : b;\nenddef;\n") in text
    assert Vex.from_string(text)["FREQ"]["4632MHz"]["new_param"] == ["a", "b"]


def test_add_ref_to_def(vex: Vex):
    mode = vex["MODE"]["evn6cm-4Gbps-32MHz"]
    mode.add("$IF", ["LO@new", "Xx"])
    assert mode.get_all("$IF")[-1] == ["LO@new", "Xx"]
    assert "     ref $IF = LO@5624MHzDPolNoTone#02:Jb;\n     ref $IF = LO@new:Xx;\n" in vex.to_string()


def test_delete_statements(edge: Vex):
    freq = edge["FREQ"]["4632MHz"]
    del freq["chan_def"]
    assert freq.keys() == ["sample_rate"]
    with pytest.raises(KeyError):
        del freq["chan_def"]


def test_statement_with_dollar_key_is_a_ref():
    statement = Statement("$IF", ["a", "b"])
    assert statement.ref and statement.key == "IF" and statement.full_key == "$IF"
    assert statement.to_string() == "     ref $IF = a:b;\n"
