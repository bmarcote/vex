from pathlib import Path

import pytest

from pyvexfile.lexer import VexSyntaxError
from pyvexfile.nodes import BlankLine, Block, Comment, Def, Literal, Scan, Statement, Vex
from pyvexfile.parser import parse


DATA = Path(__file__).parent / "data"
VEX_FILES = sorted(DATA.glob("*.vex"))


def block(vex: Vex, name: str) -> Block:
    return next(node for node in vex.children if isinstance(node, Block) and node.name == name)


def child(container: Block | Def, name: str) -> Def:
    return next(node for node in container.children if isinstance(node, Def) and node.name == name)


def statements(container: Block | Def | Vex) -> list[Statement]:
    return [node for node in container.children if isinstance(node, Statement)]


@pytest.fixture
def edge() -> Vex:
    return parse((DATA / "edge_cases.vex").read_text())


@pytest.fixture
def n26c3_text() -> str:
    return (DATA / "n26c3.vex").read_text()


# Round trip

@pytest.mark.parametrize("vexfile", VEX_FILES, ids=lambda p: p.name)
def test_round_trip_is_identical(vexfile: Path):
    text = vexfile.read_text()
    assert parse(text).to_string() == text


@pytest.mark.parametrize("text", [
    "", "\n", "  \n\n", "* only a comment", "VEX_rev = 1.5;", "VEX_rev = 1.5;   ",
    "VEX_rev = 1.5;\r\n$GLOBAL;\r\n* c\r\n  ref $EXPER = X;\r\n",
])
def test_round_trip_small_inputs(text: str):
    assert parse(text).to_string() == text


# Structure

def test_structure_of_real_file(n26c3_text: str):
    vex = parse(n26c3_text)
    header = vex.children[0]
    assert isinstance(header, Statement) and (header.key, header.value) == ("VEX_rev", "1.5")
    assert isinstance(vex.children[1], Comment)
    assert vex.children[1].text == "    pySCHED version: 1.29.0"
    names = [node.name for node in vex.children if isinstance(node, Block)]
    assert names[:3] == ["GLOBAL", "EXPER", "MODE"]
    assert "SCHED" in names
    scans = [node for node in block(vex, "SCHED").children if isinstance(node, Scan)]
    assert scans[0].name == "No0001"
    stations = [s for s in statements(scans[0]) if s.key == "station"]
    assert stations[0].fields == ["Jb", "0 sec", "360 sec", "0.000 GB", "", "&n", "1"]


def test_ref_statement(n26c3_text: str):
    mode = child(block(parse(n26c3_text), "MODE"), "evn6cm-4Gbps-32MHz")
    ref_if = [s for s in statements(mode) if s.key == "IF"]
    assert len(ref_if) == 10
    assert ref_if[1].ref and ref_if[1].fields == ["LO@4088MHzDPolNoTone#02", "Ir", "O8"]


def test_several_statements_in_one_line(edge: Vex):
    source = child(block(edge, "SOURCE"), "J1753+2848")
    assert [(s.key, s.value) for s in statements(source)] == [
        ("source_name", "J1753+2848"),
        ("ra", "17h53m42.4736450s"),
        ("dec", "28d48'04.938910\""),
        ("ref_coord_frame", "J2000"),
    ]


def test_comment_after_statement(edge: Vex):
    chan_def = statements(child(block(edge, "FREQ"), "4632MHz"))[0]
    assert chan_def.fields == ["", "4632 MHz", "L", "32.00 MHz", "&CH01", "&BBC01", "&NoCal"]
    assert chan_def.comment == " RCP"


def test_statement_over_two_lines(edge: Vex):
    chan_def = statements(child(block(edge, "FREQ"), "4632MHz"))[1]
    assert chan_def.fields == ["", "4632 MHz", "L", "32.00 MHz", "&CH02", "&BBC09", "&NoCal"]


def test_repeated_keys_keep_their_order(edge: Vex):
    keys = [s.key for s in statements(child(block(edge, "FREQ"), "4632MHz"))]
    assert keys == ["chan_def", "chan_def", "sample_rate", "chan_def"]


def test_string_value(edge: Vex):
    exper = statements(child(block(edge, "EXPER"), "EDGE"))
    assert exper[1].value == '"A string with ; and * inside"'
    assert exper[1].comment is None


def test_blank_lines(edge: Vex):
    assert isinstance(edge.children[2], BlankLine)
    assert isinstance(block(edge, "GLOBAL").children[-1], BlankLine)


def test_literal(edge: Vex):
    literal = block(edge, "SCHEDULING_PARAMS").children[0]
    assert isinstance(literal, Literal)
    assert literal.label == "sched"
    assert literal.body.startswith("\n  Free text; with semicolons")
    assert "end_literal(other);" in literal.body


def test_empty_value():
    statement = statements(parse("a = ;"))[0]
    assert statement.value == "" and statement.fields == [""]


def test_keyword_used_as_parameter_name():
    scan = statements(parse("$X;\nscan = 3;\n").children[0])[0]
    assert (scan.key, scan.value) == ("scan", "3")


# Modifications

def changed_lines(original: str, modified: str) -> list[tuple[str, str]]:
    old, new = original.splitlines(), modified.splitlines()
    assert len(old) == len(new)
    return [(a, b) for a, b in zip(old, new) if a != b]


def test_modified_value_only_changes_its_line(n26c3_text: str):
    vex = parse(n26c3_text)
    exper = child(block(vex, "EXPER"), "N26C3")
    statements(exper)[0].value = "N99X1"
    assert changed_lines(n26c3_text, vex.to_string()) == [
        ("     exper_name = N26C3;", "     exper_name = N99X1;")
    ]


def test_value_modified_in_place_is_detected(edge: Vex):
    chan_def = statements(child(block(edge, "FREQ"), "4632MHz"))[0]
    chan_def.fields[1] = "4700 MHz"
    assert "     chan_def =  : 4700 MHz : L : 32.00 MHz : &CH01 : &BBC01 : &NoCal; * RCP\n" \
        in edge.to_string()


def test_modified_statement_in_shared_line(edge: Vex):
    source = child(block(edge, "SOURCE"), "J1753+2848")
    statements(source)[2].value = "28d48'05.0\""
    text = edge.to_string()
    assert "     ra = 17h53m42.4736450s; dec = 28d48'05.0\"; ref_coord_frame = J2000;\n" in text
    assert [s.value for s in statements(child(block(parse(text), "SOURCE"), "J1753+2848"))] == \
        ["J1753+2848", "17h53m42.4736450s", "28d48'05.0\"", "J2000"]


def test_change_and_remove_comment(edge: Vex):
    exper = statements(child(block(edge, "EXPER"), "EDGE"))
    exper[0].comment = " new comment"
    exper[2].comment = " added"
    text = edge.to_string()
    assert "     exper_name = EDGE;   * new comment\n" in text
    assert "     PI_name = Someone; * added\n" in text
    exper[0].comment = None
    assert "     exper_name = EDGE;\n" in edge.to_string()


def test_comment_added_to_statement_sharing_a_line(edge: Vex):
    statements(child(block(edge, "SOURCE"), "J1753+2848"))[1].comment = " RA"
    reparsed = statements(child(block(parse(edge.to_string()), "SOURCE"), "J1753+2848"))
    assert [(s.key, s.comment) for s in reparsed][1:3] == [("ra", " RA"), ("dec", None)]


def test_new_statement_and_renamed_def(edge: Vex):
    exper = child(block(edge, "EXPER"), "EDGE")
    exper.children.append(Statement("PI_email", "someone@example.com"))
    exper.name = "EDGE2"
    text = edge.to_string()
    assert "def EDGE2;\n" in text
    assert "     PI_name = Someone;\n     PI_email = someone@example.com;\nenddef;\n" in text


def test_modified_comment_line_and_literal(edge: Vex):
    edge.children[1].text = " replaced"
    literal = block(edge, "SCHEDULING_PARAMS").children[0]
    literal.body = "\nnew body\n"
    text = edge.to_string()
    assert text.splitlines()[1] == "* replaced"
    assert text.endswith("start_literal(sched);\nnew body\nend_literal(sched);\n")


def test_vex_built_from_scratch():
    vex = Vex([
        Statement("VEX_rev", "1.5"),
        Comment(" made by hand"),
        Block("GLOBAL", [Statement("EXPER", "X", ref=True)]),
        Block("FREQ", [
            Def("f1", [Statement("chan_def", ["", "4632 MHz", "L", "&CH01"], comment=" RCP")]),
        ]),
        Block("SCHED", [Scan("No0001", [Statement("source", "J1753+2848")])]),
    ])
    text = vex.to_string()
    assert text == (
        "VEX_rev = 1.5;\n"
        "* made by hand\n"
        "$GLOBAL;\n"
        "     ref $EXPER = X;\n"
        "$FREQ;\n"
        "def f1;\n"
        "     chan_def =  : 4632 MHz : L : &CH01; * RCP\n"
        "enddef;\n"
        "$SCHED;\n"
        "scan No0001;\n"
        "     source = J1753+2848;\n"
        "endscan;\n"
    )
    assert parse(text).to_string() == text


# Syntax errors

@pytest.mark.parametrize("text, message, line", [
    ("$A;\ndef x;\n  a = 1;\n", "'def x' (line 2) without 'enddef'", 2),
    ("$A;\ndef x;\ndef y;\nenddef;\n", "found 'def' inside 'def x' (line 2); missing 'enddef'?", 3),
    ("$A;\ndef x;\nendscan;\n", "found 'endscan' inside 'def x'", 3),
    ("$A;\nenddef;\n", "'enddef' without a previous 'def'", 2),
    ("def x;\nenddef;\n", "'def' outside of a $BLOCK", 1),
    ("$A;\ndef x;\n$B;\n", "new block before the 'enddef' of 'def x'", 3),
    ("$A;\n  a = 1\n", "statement 'a' without ';' at the end", 2),
    ("$A;\n  a = 1\n  b = 2;\n", "missing ';' at the end of line 2?", 3),
    ("$A;\ndef x;\n  a = 1\nenddef;\n", "missing ';' at the end of line 3?", 4),
    ("$A;\n  a 1;\n", "expected '=' after 'a', found '1'", 2),
    ("$A;\n  = 1;\n", "expected a statement, found '='", 2),
    ("$A\n", "expected ';' after '$A'", 1),
    ("$A;\nstart_literal(x)\nbody\nend_literal(x);\n", "expected ';' after 'start_literal(...)'", 2),
])
def test_syntax_errors(text: str, message: str, line: int):
    with pytest.raises(VexSyntaxError) as error:
        parse(text)

    assert message in str(error.value)
    assert error.value.line == line
