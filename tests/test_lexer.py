from pathlib import Path

import pytest

from pyvexfile.lexer import TRIVIA, Token, TokenType, VexSyntaxError, tokenize


DATA = Path(__file__).parent / "data"
VEX_FILES = sorted(DATA.glob("*.vex"))

T = TokenType


def significant(text: str) -> list[tuple[TokenType, str]]:
    """Returns the (type, value) of all tokens that are not whitespace, newlines or comments."""
    return [(t.type, t.value) for t in tokenize(text) if t.type not in TRIVIA]


@pytest.mark.parametrize("vexfile", VEX_FILES, ids=lambda p: p.name)
def test_tokenize_is_lossless(vexfile: Path):
    text = vexfile.read_text()
    assert "".join(t.value for t in tokenize(text)) == text


@pytest.mark.parametrize("vexfile", VEX_FILES, ids=lambda p: p.name)
def test_offsets_match_values(vexfile: Path):
    text = vexfile.read_text()
    for token in tokenize(text):
        assert text[token.offset : token.offset + len(token.value)] == token.value


def test_empty_input():
    assert list(tokenize("")) == []


def test_simple_statement():
    assert significant("exper_name = N26C3;") == [
        (T.WORD, "exper_name"),
        (T.EQUALS, "="),
        (T.WORD, "N26C3"),
        (T.SEMICOLON, ";"),
    ]


def test_ref_statement_with_colon_fields():
    assert significant("ref $IF = LO@4088MHzDPolNoTone#02:Ir:O8;") == [
        (T.WORD, "ref"),
        (T.DOLLAR, "$"),
        (T.WORD, "IF"),
        (T.EQUALS, "="),
        (T.WORD, "LO@4088MHzDPolNoTone#02"),
        (T.COLON, ":"),
        (T.WORD, "Ir"),
        (T.COLON, ":"),
        (T.WORD, "O8"),
        (T.SEMICOLON, ";"),
    ]


def test_several_statements_in_one_line():
    tokens = significant("ra = 17h53m42.4736450s; dec =  28d48'04.938910\"; ref_coord_frame = J2000;")
    assert [v for _, v in tokens] == [
        "ra", "=", "17h53m42.4736450s", ";",
        "dec", "=", "28d48'04.938910\"", ";",
        "ref_coord_frame", "=", "J2000", ";",
    ]


def test_quote_inside_word_does_not_open_string():
    assert significant("dec = 28d48'04.9\";")[2] == (T.WORD, "28d48'04.9\"")


def test_link_words_and_empty_fields():
    tokens = significant("chan_def =  : 4632 MHz : L : &CH01;")
    assert [v for _, v in tokens] == [
        "chan_def", "=", ":", "4632", "MHz", ":", "L", ":", "&", "CH01", ";"
    ]


def test_comment_after_statement():
    tokens = list(tokenize("a = b; * RCP\nc = d;"))
    comments = [t for t in tokens if t.type is T.COMMENT]
    assert len(comments) == 1
    assert comments[0].value == "* RCP"
    assert (comments[0].line, comments[0].col) == (1, 8)


def test_comment_does_not_include_crlf():
    tokens = list(tokenize("* comment\r\na = b;"))
    assert tokens[0] == Token(T.COMMENT, "* comment", 1, 1, 0)
    assert tokens[1].type is T.NEWLINE and tokens[1].value == "\r\n"
    assert tokens[2].line == 2


def test_comment_at_end_of_file_without_newline():
    assert list(tokenize("* last"))[-1].value == "* last"


def test_string_keeps_special_characters():
    tokens = significant('exper_description = "A string with ; and * inside";')
    assert tokens[2] == (T.STRING, '"A string with ; and * inside"')
    assert tokens[3] == (T.SEMICOLON, ";")


def test_string_with_escaped_quote():
    assert significant(r'a = "say \"hi\"";')[2] == (T.STRING, r'"say \"hi\""')


def test_unterminated_string():
    with pytest.raises(VexSyntaxError) as error:
        list(tokenize('a = b;\n  c = "no end;\n'))

    assert (error.value.line, error.value.col) == (2, 7)


def test_line_and_column_tracking():
    tokens = [t for t in tokenize("$EXPER;\n\ndef N26C3;\n     exper_name = N26C3;\n")
              if t.type not in TRIVIA]
    positions = {t.value: (t.line, t.col) for t in tokens}
    assert positions["EXPER"] == (1, 2)
    assert positions["def"] == (3, 1)
    assert positions["exper_name"] == (4, 6)


def test_statement_over_two_lines():
    tokens = significant("chan_def = : 4632 MHz :\n      32.00 MHz;")
    assert [v for _, v in tokens] == ["chan_def", "=", ":", "4632", "MHz", ":", "32.00", "MHz", ";"]


def test_literal_block_is_one_token():
    text = (
        "$SCHEDULING_PARAMS;\n"
        "start_literal(sched);\n"
        "  Free text; with * and = and $\n"
        "  and an end_literal(other); that must not close the block.\n"
        "end_literal(sched);\n"
        "$NEXT;\n"
    )
    tokens = significant(text)
    assert tokens[3][0] is T.LITERAL
    assert tokens[3][1].startswith("start_literal(sched);")
    assert tokens[3][1].endswith("end_literal(sched)")
    assert "end_literal(other)" in tokens[3][1]
    assert tokens[4] == (T.SEMICOLON, ";")
    assert tokens[5:] == [(T.DOLLAR, "$"), (T.WORD, "NEXT"), (T.SEMICOLON, ";")]


def test_literal_block_without_label_and_spaces():
    tokens = significant("start_literal ( );\nraw\nend_literal();\n")
    assert tokens[0] == (T.LITERAL, "start_literal ( );\nraw\nend_literal()")


def test_literal_block_line_numbers_continue_after_it():
    tokens = [t for t in tokenize("start_literal();\na\nb\nend_literal();\nx = y;")
              if t.type is T.WORD]
    assert tokens[0].value == "x" and tokens[0].line == 5


def test_unterminated_literal_block():
    with pytest.raises(VexSyntaxError, match="without matching"):
        list(tokenize("a = b;\nstart_literal(x);\ntext\nend_literal(y);\n"))


def test_word_starting_like_literal_is_a_word():
    assert significant("start_literally = 1;")[0] == (T.WORD, "start_literally")
