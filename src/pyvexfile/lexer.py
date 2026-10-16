"""Lexical analysis of VEX files.

The tokenizer is lossless: joining the values of all the tokens produced by
tokenize() gives back the input text exactly, including comments, whitespace
and line breaks. This allows the parser to keep the comments and the original
layout of a VEX file, so it can be written again without changes.

Usage
-----

from pyvexfile.lexer import tokenize

for token in tokenize(text):
    print(token.type, repr(token.value), token.line, token.col)
"""
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum, auto


__all__: list[str] = ["TokenType", "Token", "VexSyntaxError", "tokenize", "TRIVIA"]


class TokenType(Enum):
    """Types of the tokens that can be found in a VEX file:
    - WORD. Any sequence of characters not containing whitespace, ';', ':', '=', '$', '&' or '*'.
    - STRING. A quoted string, including the quotes ("...").
    - SEMICOLON, COLON, EQUALS, DOLLAR, AMPERSAND. The single-character punctuation.
    - COMMENT. Everything from a '*' until the end of the line (the line break not included).
    - WHITESPACE. A sequence of spaces and/or tabs.
    - NEWLINE. A line break ('\\n' or '\\r\\n').
    - LITERAL. A full literal block, from 'start_literal(...)' until 'end_literal(...)',
      both included. The final ';' after 'end_literal(...)' is a separated SEMICOLON token.
    """

    WORD = auto()
    STRING = auto()
    SEMICOLON = auto()
    COLON = auto()
    EQUALS = auto()
    DOLLAR = auto()
    AMPERSAND = auto()
    COMMENT = auto()
    WHITESPACE = auto()
    NEWLINE = auto()
    LITERAL = auto()


# Tokens that do not carry syntactic meaning, but must be kept to reproduce the file
TRIVIA: frozenset[TokenType] = frozenset(
    {TokenType.COMMENT, TokenType.WHITESPACE, TokenType.NEWLINE}
)

_PUNCTUATION: dict[str, TokenType] = {
    ";": TokenType.SEMICOLON,
    ":": TokenType.COLON,
    "=": TokenType.EQUALS,
    "$": TokenType.DOLLAR,
    "&": TokenType.AMPERSAND,
}
_WHITESPACE = " \t\f\v"
# Note that '"' is not a delimiter: it only opens a string at the start of a token,
# so values like  28d48'04.938910"  are read as a single word.
_WORD_DELIMITERS = frozenset(_WHITESPACE + "\r\n;:=$&*")
_LITERAL_START = "start_literal"
_LITERAL_END = "end_literal"


class VexSyntaxError(ValueError):
    """Error in the syntax of a VEX file, at the given line and column (both starting at 1)."""

    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"line {line}, column {col}: {message}")
        self.message = message
        self.line = line
        self.col = col


@dataclass(frozen=True, slots=True)
class Token:
    """A token from a VEX file. 'offset' is the position of its first character in the
    input text, and 'line' and 'col' its line and column numbers (starting at 1).
    """

    type: TokenType
    value: str
    line: int
    col: int
    offset: int


def tokenize(text: str) -> Iterator[Token]:
    """Splits the text of a VEX file into Tokens. Raises VexSyntaxError if a string or
    a literal block is not terminated.
    """
    pos, line, col = 0, 1, 1
    while pos < len(text):
        token_type, end = _scan_token(text, pos, line, col)
        value = text[pos:end]
        yield Token(token_type, value, line, col, pos)
        if (n_lines := value.count("\n")) > 0:
            line += n_lines
            col = len(value) - value.rfind("\n")
        else:
            col += len(value)

        pos = end


def _scan_token(text: str, pos: int, line: int, col: int) -> tuple[TokenType, int]:
    """Identifies the token starting at text[pos]. Returns its type and the position
    right after its last character.
    """
    char = text[pos]
    if char == "\n":
        return TokenType.NEWLINE, pos + 1

    if char == "\r":
        if text.startswith("\r\n", pos):
            return TokenType.NEWLINE, pos + 2

        return TokenType.WHITESPACE, pos + 1

    if char in _WHITESPACE:
        end = pos + 1
        while end < len(text) and text[end] in _WHITESPACE:
            end += 1

        return TokenType.WHITESPACE, end

    if char == "*":
        end = text.find("\n", pos)
        if end == -1:
            end = len(text)
        elif text[end - 1] == "\r":
            end -= 1

        return TokenType.COMMENT, end

    if char == '"':
        return TokenType.STRING, _scan_string(text, pos, line, col)

    if char in _PUNCTUATION:
        return _PUNCTUATION[char], pos + 1

    if (literal_end := _scan_literal(text, pos, line, col)) is not None:
        return TokenType.LITERAL, literal_end

    end = pos + 1
    while end < len(text) and text[end] not in _WORD_DELIMITERS:
        end += 1

    return TokenType.WORD, end


def _scan_string(text: str, pos: int, line: int, col: int) -> int:
    """Returns the position right after the closing quote of the string opened at text[pos].
    A backslash escapes the following character. Strings cannot span multiple lines.
    """
    end = pos + 1
    while end < len(text):
        char = text[end]
        if char == "\\":
            end += 2
        elif char == '"':
            return end + 1
        elif char in "\r\n":
            break
        else:
            end += 1

    raise VexSyntaxError("unterminated string", line, col)


def _scan_literal(text: str, pos: int, line: int, col: int) -> int | None:
    """If a literal block starts at text[pos], returns the position right after the
    'end_literal(label)' that closes it. Otherwise returns None.

    A literal block has the form:
        start_literal(label);
        ...any text, kept verbatim...
        end_literal(label);
    where the label is optional, but must be the same in both lines.
    """
    label_start = _open_parenthesis(text, pos, _LITERAL_START)
    if label_start is None:
        return None

    label_end = text.find(")", label_start)
    if label_end == -1:
        raise VexSyntaxError(f"'{_LITERAL_START}(' without closing ')'", line, col)

    label = text[label_start:label_end].strip()
    search_from = label_end + 1
    while (end_pos := text.find(_LITERAL_END, search_from)) != -1:
        end_label_start = _open_parenthesis(text, end_pos, _LITERAL_END)
        if end_label_start is not None:
            end_label_end = text.find(")", end_label_start)
            if end_label_end == -1:
                break

            if text[end_label_start:end_label_end].strip() == label:
                return end_label_end + 1

        search_from = end_pos + len(_LITERAL_END)

    raise VexSyntaxError(
        f"literal block '{_LITERAL_START}({label})' without matching '{_LITERAL_END}({label})'",
        line,
        col,
    )


def _open_parenthesis(text: str, pos: int, keyword: str) -> int | None:
    """If text[pos:] starts with keyword followed by '(' (optionally with whitespace in between),
    returns the position right after the '('. Otherwise returns None.
    """
    if not text.startswith(keyword, pos):
        return None

    after = pos + len(keyword)
    while after < len(text) and text[after] in _WHITESPACE:
        after += 1

    if after < len(text) and text[after] == "(":
        return after + 1

    return None
