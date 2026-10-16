"""Parser for VEX files.

Builds the tree of nodes (see pyvexfile.nodes) from the tokens produced by the lexer.
It only checks the syntax of the file (blocks, definitions, statements and their ';'),
not whether the blocks and parameters are the ones defined by the VEX standard.

Usage
-----

from pyvexfile.parser import parse

vex = parse(text)
assert vex.to_string() == text
"""
from .lexer import TRIVIA, Token, TokenType, VexSyntaxError, tokenize
from .nodes import BlankLine, Block, Comment, Def, Literal, Node, Scan, Statement, Vex, _Source


__all__: list[str] = ["parse", "VexSyntaxError"]

T = TokenType

_DEFINITIONS: dict[str, type[Def]] = {Def.keyword: Def, Scan.keyword: Scan}
_END_KEYWORDS: dict[str, type[Def]] = {Def.end_keyword: Def, Scan.end_keyword: Scan}
_KEYWORDS = frozenset(_DEFINITIONS) | frozenset(_END_KEYWORDS)


def parse(text: str) -> Vex:
    """Parses the text of a VEX file into a Vex object.
    Raises VexSyntaxError if the text is not syntactically correct.
    """
    return _Parser(text).parse_vex()


def _describe(token: Token) -> str:
    return "a literal block" if token.type is T.LITERAL else f"'{token.value}'"


def _unexpected(token: Token, expected: str) -> VexSyntaxError:
    return VexSyntaxError(f"expected {expected}, found {_describe(token)}", token.line, token.col)


class _Parser:
    def __init__(self, text: str):
        self._tokens = list(tokenize(text))
        self._pos = 0

    # Low-level helpers

    def _peek(self) -> Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _peek_significant(self, start: int) -> Token | None:
        """Returns the first token that is not trivia from the position start, without consuming it."""
        for i in range(start, len(self._tokens)):
            if self._tokens[i].type not in TRIVIA:
                return self._tokens[i]

        return None

    def _next_significant(self, expected: str) -> Token:
        """Consumes the trivia and returns the next token. Raises VexSyntaxError at the end of file."""
        while (token := self._peek()) is not None and token.type in TRIVIA:
            self._pos += 1

        if token is None:
            last = self._tokens[-1]
            raise VexSyntaxError(f"expected {expected}, found the end of the file", last.line, last.col)

        self._pos += 1
        return token

    def _expect(self, token_type: TokenType, expected: str) -> Token:
        token = self._next_significant(expected)
        if token.type is not token_type:
            raise _unexpected(token, expected)

        return token

    def _line(self, index: int) -> int:
        return self._tokens[index].line

    def _text_since(self, start: int) -> str:
        return "".join(token.value for token in self._tokens[start:self._pos])

    def _take_whitespace(self) -> str:
        start = self._pos
        while (token := self._peek()) is not None and token.type is T.WHITESPACE:
            self._pos += 1

        return self._text_since(start)

    def _take_trailing(self) -> tuple[str, Token | None]:
        """Consumes the rest of the line after a statement: whitespace, a comment and the line break.
        If another statement follows in the same line, nothing is consumed.
        Returns the consumed text and the comment token (if any).
        """
        start = self._pos
        self._take_whitespace()
        comment = None
        if (token := self._peek()) is not None and token.type is T.COMMENT:
            comment = token
            self._pos += 1

        token = self._peek()
        if token is None:
            return self._text_since(start), comment

        if token.type is T.NEWLINE:
            self._pos += 1
            return self._text_since(start), comment

        # Another statement in the same line: its leading whitespace belongs to it
        self._pos = start
        return "", None

    def _keyword(self) -> str | None:
        """Returns the keyword (def, enddef, scan, endscan) at the current position, if any.
        A word followed by '=' is a parameter name, even if it is spelled like a keyword.
        """
        token = self._peek()
        if token is None or token.type is not T.WORD or token.value not in _KEYWORDS:
            return None

        following = self._peek_significant(self._pos + 1)
        if following is not None and following.type is T.EQUALS:
            return None

        return token.value

    # Grammar

    def parse_vex(self) -> Vex:
        vex = Vex()
        while self._peek() is not None:
            leading = self._take_whitespace()
            token = self._peek()
            if token is not None and token.type is T.DOLLAR:
                vex.children.append(self._parse_block(leading))
            elif (keyword := self._keyword()) is not None:
                if keyword in _DEFINITIONS:
                    raise VexSyntaxError(f"'{keyword}' outside of a $BLOCK", token.line, token.col)

                raise VexSyntaxError(f"'{keyword}' without a previous '{_END_KEYWORDS[keyword].keyword}'",
                                     token.line, token.col)
            else:
                vex.children.append(self._parse_item(leading))

        return vex

    def _parse_block(self, leading: str) -> Block:
        start = self._pos
        self._expect(T.DOLLAR, "'$'")
        name = self._expect(T.WORD, "a block name after '$'").value
        self._expect(T.SEMICOLON, f"';' after '${name}'")
        block = Block(name)
        core = self._text_since(start)
        block._set_source(_Source(leading, core, self._take_trailing()[0]), self._line(start))
        while self._peek() is not None:
            item_start = self._pos
            leading = self._take_whitespace()
            token = self._peek()
            if token is not None and token.type is T.DOLLAR:
                # The next block starts here (including its leading whitespace)
                self._pos = item_start
                break

            if (keyword := self._keyword()) is not None:
                if keyword not in _DEFINITIONS:
                    raise VexSyntaxError(
                        f"'{keyword}' without a previous '{_END_KEYWORDS[keyword].keyword}'",
                        token.line, token.col,
                    )

                block.children.append(self._parse_definition(leading, _DEFINITIONS[keyword]))
            else:
                block.children.append(self._parse_item(leading))

        return block

    def _parse_definition(self, leading: str, cls: type[Def]) -> Def:
        start = self._pos
        keyword = self._expect(T.WORD, f"'{cls.keyword}'")
        name_token = self._next_significant(f"a name after '{cls.keyword}'")
        if name_token.type not in (T.WORD, T.STRING):
            raise _unexpected(name_token, f"a name after '{cls.keyword}'")

        title = f"'{cls.keyword} {name_token.value}' (line {keyword.line})"
        self._expect(T.SEMICOLON, f"';' after '{cls.keyword} {name_token.value}'")
        definition = cls(name_token.value)
        core = self._text_since(start)
        definition._set_source(_Source(leading, core, self._take_trailing()[0]), keyword.line)
        while True:
            if self._peek() is None:
                raise VexSyntaxError(f"{title} without '{cls.end_keyword}'", keyword.line, keyword.col)

            leading = self._take_whitespace()
            token = self._peek()
            if token is not None and token.type is T.DOLLAR:
                raise VexSyntaxError(f"new block before the '{cls.end_keyword}' of {title}",
                                     token.line, token.col)

            found = self._keyword()
            if found == cls.end_keyword:
                end_start = self._pos
                self._pos += 1
                self._expect(T.SEMICOLON, f"';' after '{cls.end_keyword}'")
                core = self._text_since(end_start)
                definition._end_source = leading + core + self._take_trailing()[0]
                return definition

            if found is not None:
                raise VexSyntaxError(f"found '{found}' inside {title}; missing '{cls.end_keyword}'?",
                                     token.line, token.col)

            definition.children.append(self._parse_item(leading))

    def _parse_item(self, leading: str) -> Node:
        """Parses a node that can be found anywhere: blank line, comment, literal block or statement."""
        token = self._peek()
        if token is None or token.type is T.NEWLINE:
            self._pos += token is not None
            node: Node = BlankLine()
            node._set_source(_Source(leading, "", "" if token is None else token.value),
                             None if token is None else token.line)
            return node

        if token.type is T.COMMENT:
            self._pos += 1
            newline = self._peek()
            trailing = ""
            if newline is not None and newline.type is T.NEWLINE:
                self._pos += 1
                trailing = newline.value

            node = Comment(token.value[1:])
            node._set_source(_Source(leading, token.value, trailing), token.line)
            return node

        if token.type is T.LITERAL:
            return self._parse_literal(leading)

        return self._parse_statement(leading)

    def _parse_literal(self, leading: str) -> Literal:
        start = self._pos
        token = self._tokens[self._pos]
        self._pos += 1
        self._expect(T.SEMICOLON, "';' after 'end_literal(...)'")
        raw = token.value
        label_end = raw.index(")")
        after_label = raw[label_end + 1:]
        if not after_label.lstrip(" \t").startswith(";"):
            raise VexSyntaxError("expected ';' after 'start_literal(...)'", token.line, token.col)

        body_start = label_end + 1 + after_label.index(";") + 1
        literal = Literal(raw[raw.index("(") + 1:label_end].strip(),
                          raw[body_start:raw.rindex("end_literal")])
        core = self._text_since(start)
        literal._set_source(_Source(leading, core, self._take_trailing()[0]), token.line)
        return literal

    def _parse_statement(self, leading: str) -> Statement:
        start = self._pos
        first = self._next_significant("a statement")
        following = self._peek_significant(self._pos)
        ref = first.type is T.WORD and first.value == "ref" and following is not None \
            and following.type is T.DOLLAR
        if ref:
            self._next_significant("'$'")
            key = self._expect(T.WORD, "a block name after 'ref $'").value
        elif first.type is T.WORD:
            key = first.value
        else:
            raise _unexpected(first, "a statement")

        self._expect(T.EQUALS, f"'=' after '{key}'")
        fields = [""]
        separated = False  # whitespace, comments or line breaks since the previous token
        last_newline: Token | None = None
        while True:
            token = self._peek()
            if token is None:
                raise VexSyntaxError(f"statement '{key}' without ';' at the end", first.line, first.col)

            self._pos += 1
            if token.type is T.SEMICOLON:
                break

            if token.type in TRIVIA:
                separated = True
                if token.type is T.NEWLINE:
                    last_newline = token
            elif token.type is T.COLON:
                fields.append("")
                separated = False
            elif token.type in (T.WORD, T.STRING, T.AMPERSAND) and not (
                token.type is T.WORD and token.value in _KEYWORDS and last_newline is not None
            ):
                if fields[-1] and separated:
                    fields[-1] += " "

                fields[-1] += token.value
                separated = False
            else:
                hint = "" if last_newline is None else \
                    f" (missing ';' at the end of line {last_newline.line}?)"
                raise VexSyntaxError(f"unexpected {_describe(token)} in the value of '{key}'{hint}",
                                     token.line, token.col)

        statement = Statement(key, fields, ref=ref)
        core = self._text_since(start)
        trailing, comment = self._take_trailing()
        if comment is not None:
            statement.comment = comment.value[1:]

        statement._set_source(_Source(leading, core, trailing), first.line)
        return statement
