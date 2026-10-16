"""Nodes of the tree that represents a VEX file.

A VEX file is represented as a Vex object, containing a list of nodes:
    Vex
     ├── Statement, Comment, BlankLine        (before the first block, e.g. 'VEX_rev = 1.5;')
     └── Block                                ($NAME;)
          ├── Statement, Comment, BlankLine, Literal
          └── Def / Scan                      (def NAME; ... enddef;  /  scan NAME; ... endscan;)
               └── Statement, Comment, BlankLine, Literal

All nodes keep the order in which they appear in the file, and nodes created by the
parser remember their original text. When a VEX file is written again, every node
that has not been modified is written exactly as it was in the original file (keeping
spacing, alignment and comments). Modified or new nodes are written in a standard format.

Statements are accessed by their key, written as in the VEX file: 'key' for a
'key = value;' statement, and '$KEY' for a 'ref $KEY = value;' statement.
"""
import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, TypeVar

from .observation import ObservationMixin
from .units import parse_duration, parse_epoch

if TYPE_CHECKING:
    from .verify import Issue


__all__: list[str] = [
    "Value", "Node", "Statement", "Comment", "BlankLine", "Literal", "Def", "Scan", "Block", "Vex"
]

# The value of a statement: a single field, or a list of fields (separated by ':' in the file)
Value = str | list[str]

# Indentation used for new statements inside blocks and definitions
DEFAULT_INDENT = " " * 5

_N = TypeVar("_N")


@dataclass(slots=True)
class _Source:
    """Original text of a node, split into the whitespace before it in its line (leading),
    its own text (core), and the text after it until the end of the line (trailing),
    which can contain whitespace, a comment and the line break.
    """

    leading: str
    core: str
    trailing: str

    def __str__(self) -> str:
        return self.leading + self.core + self.trailing


def _single(found: list[_N], key: str, where: str, hint: str = "") -> _N:
    """Returns the only element of found. Raises KeyError if it is empty,
    or ValueError if it contains more than one element.
    """
    if not found:
        raise KeyError(key)

    if len(found) > 1:
        raise ValueError(f"'{key}' appears {len(found)} times in {where}{hint}")

    return found[0]


class Node:
    """Base class for all the elements of a VEX file."""

    _source: _Source | None = None
    _parsed: object = None
    # Line where the node starts in the file it was read from (None for new nodes)
    line: int | None = None

    def _state(self) -> object:
        """Values that define the content of the node, to detect if it has been modified."""
        return None

    def _set_source(self, source: _Source, line: int | None = None) -> None:
        """Stores the original text of the node, and its line, as read by the parser."""
        self._source = source
        self._parsed = self._state()
        self.line = line

    def _is_modified(self) -> bool:
        return self._state() != self._parsed

    def _format(self) -> str:
        """Returns the node written in the standard format (without indentation or line break)."""
        raise NotImplementedError

    def _render_line(self, indent: str) -> str:
        """Returns the original text if the node has not been modified, or the
        standard format (keeping the original indentation and trailing text) otherwise.
        """
        if self._source is None:
            return indent + self._format() + "\n"

        core = self._format() if self._is_modified() else self._source.core
        return self._source.leading + core + self._source.trailing

    def to_string(self, indent: str | None = None) -> str:
        """Returns the text of the node as it would be written in a VEX file.
        'indent' is only used for new statements, which are indented by default.
        """
        return self._render_line("")

    def __str__(self) -> str:
        return self.to_string()


class Statement(Node):
    """A 'key = value;' statement, or a 'ref $KEY = value;' reference when ref is True
    (a key starting with '$' also creates a reference).

    The value is stored in 'fields', the list of the parts of the value separated by ':'.
    Each field is kept as text: quoted strings keep their quotes, link words keep their '&',
    and empty fields are ''. 'value' gives the single field as a string when there is only
    one, or the list of fields otherwise.

    'comment' is the text of a comment found in the same line after the statement
    (without the leading '*'), or None.
    """

    def __init__(self, key: str, value: Value = "", *, ref: bool = False,
                 comment: str | None = None):
        if key.startswith("$"):
            key, ref = key[1:], True

        self.key = key
        self.ref = ref
        self.value = value
        self.comment = comment
        self._parsed_comment: str | None = None

    @property
    def full_key(self) -> str:
        """The key as used to access the statement: '$KEY' for references, 'key' otherwise."""
        return f"${self.key}" if self.ref else self.key

    @property
    def value(self) -> Value:
        return self.fields[0] if len(self.fields) == 1 else self.fields

    @value.setter
    def value(self, value: Value) -> None:
        self.fields = [value] if isinstance(value, str) else list(value)

    def _state(self) -> object:
        return (self.key, self.ref, tuple(self.fields))

    def _set_source(self, source: _Source, line: int | None = None) -> None:
        super()._set_source(source, line)
        self._parsed_comment = self.comment

    def _format(self) -> str:
        if self.ref:
            return f"ref ${self.key} = {':'.join(self.fields)};"

        return f"{self.key} = {' : '.join(self.fields)};"

    def to_string(self, indent: str | None = None) -> str:
        indent = DEFAULT_INDENT if indent is None else indent
        if self._source is None:
            comment = "" if self.comment is None else f" *{self.comment}"
            return indent + self._format() + comment + "\n"

        line = self._render_line(indent)
        if self.comment == self._parsed_comment:
            return line

        # Only the comment changed in the trailing text: rebuild it
        original = self._source.trailing
        line = line[: len(line) - len(original)]
        newline = "\r\n" if original.endswith("\r\n") else "\n" if original.endswith("\n") else ""
        if self.comment is None:
            return line + newline

        spacing = original[: original.index("*")] if "*" in original else " "
        # A comment runs until the end of the line, so it must always be followed by a line break
        return line + f"{spacing}*{self.comment}" + (newline or "\n")

    def __repr__(self) -> str:
        comment = "" if self.comment is None else f", comment={self.comment!r}"
        return f"Statement({self.full_key!r}, {self.value!r}{comment})"


class Comment(Node):
    """A line containing only a comment. 'text' is everything after the '*'."""

    def __init__(self, text: str = ""):
        self.text = text

    def _state(self) -> object:
        return self.text

    def _format(self) -> str:
        return f"*{self.text}"

    def __repr__(self) -> str:
        return f"Comment({self.text!r})"


class BlankLine(Node):
    """An empty line (or containing only whitespace)."""

    def _format(self) -> str:
        return ""

    def __repr__(self) -> str:
        return "BlankLine()"


class Literal(Node):
    """A literal block, which contains text that is not parsed:
        start_literal(label);
        ...body...
        end_literal(label);
    'body' is the exact text between 'start_literal(label);' and 'end_literal(label);',
    including the line breaks at its start and end.
    """

    def __init__(self, label: str = "", body: str = "\n"):
        self.label = label
        self.body = body

    def _state(self) -> object:
        return (self.label, self.body)

    def _format(self) -> str:
        return f"start_literal({self.label});{self.body}end_literal({self.label});"

    def __repr__(self) -> str:
        return f"Literal({self.label!r}, {self.body!r})"


class _HasStatements:
    """Access to the statements among the children of a node, by their key
    ('key' for parameters, '$KEY' for references).
    """

    children: list[Node]

    def _where(self) -> str:
        raise NotImplementedError

    def statements(self, key: str | None = None) -> list[Statement]:
        """Returns the Statement objects with the given key (all of them if key is None),
        in the order they appear. Use them to access or modify their comments.
        """
        return [child for child in self.children if isinstance(child, Statement)
                and (key is None or child.full_key == key)]

    def get_all(self, key: str) -> list[Value]:
        """Returns the values of all the statements with the given key, in order."""
        return [statement.value for statement in self.statements(key)]

    def add(self, key: str, value: Value = "", *, comment: str | None = None) -> Statement:
        """Adds a new statement, even if others with the same key already exist.
        It is placed after the last statement with the same key, or after the last statement
        if there is none. Returns the new Statement.
        """
        statement = Statement(key, value, comment=comment)
        self.children.insert(self._insert_position(statement.full_key), statement)
        return statement

    def _insert_position(self, key: str) -> int:
        same_key = [i for i, child in enumerate(self.children)
                    if isinstance(child, Statement) and child.full_key == key]
        if same_key:
            return same_key[-1] + 1

        statements = [i for i, child in enumerate(self.children) if isinstance(child, Statement)]
        if statements:
            return statements[-1] + 1

        return self._default_position()

    def _default_position(self) -> int:
        return len(self.children)

    def _get_value(self, key: str) -> Value:
        statement = _single(self.statements(key), key, self._where(), f"; use get_all('{key}')")
        return statement.value

    def _set_value(self, key: str, value: Value) -> None:
        found = self.statements(key)
        if not found:
            self.add(key, value)
            return

        _single(found, key, self._where(), "; modify them through statements()").value = value

    def _del_value(self, key: str) -> None:
        found = {id(statement) for statement in self.statements(key)}
        if not found:
            raise KeyError(key)

        self.children = [child for child in self.children if id(child) not in found]


class Def(_HasStatements, Node):
    """A definition inside a block: from 'def NAME;' until 'enddef;'.

    It behaves as a dictionary of statement values:
        definition['key']             value of the 'key = value;' statement
        definition['$KEY']            value of the 'ref $KEY = value;' statement
        definition.get_all('key')     values of all the statements with that key
    Accessing with [] a key that appears several times raises ValueError (use get_all()).
    Assigning with [] modifies the existing statement, or adds a new one.
    """

    keyword = "def"
    end_keyword = "enddef"
    _end_source: str | None = None

    def __init__(self, name: str, children: list[Node] | None = None):
        self.name = name
        self.children: list[Node] = [] if children is None else list(children)

    def _where(self) -> str:
        return f"'{self.keyword} {self.name}'"

    def _state(self) -> object:
        return self.name

    def _format(self) -> str:
        return f"{self.keyword} {self.name};"

    def to_string(self, indent: str | None = None) -> str:
        end = f"{self.end_keyword};\n" if self._end_source is None else self._end_source
        body = "".join(child.to_string(DEFAULT_INDENT) for child in self.children)
        return self._render_line("") + body + end

    def __getitem__(self, key: str) -> Value:
        return self._get_value(key)

    def __setitem__(self, key: str, value: Value) -> None:
        self._set_value(key, value)

    def __delitem__(self, key: str) -> None:
        """Removes all the statements with the given key."""
        self._del_value(key)

    def get(self, key: str, default: Value | None = None) -> Value | None:
        return self._get_value(key) if key in self else default

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and bool(self.statements(key))

    def keys(self) -> list[str]:
        """The different keys of the statements, in order of first appearance."""
        return list(dict.fromkeys(statement.full_key for statement in self.statements()))

    def items(self) -> list[tuple[str, Value]]:
        """(key, value) of every statement, in order. Repeated keys appear several times."""
        return [(statement.full_key, statement.value) for statement in self.statements()]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.keys())

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, <{len(self.children)} children>)"


class Scan(Def):
    """A scan inside the $SCHED block: from 'scan NAME;' until 'endscan;'."""

    keyword = "scan"
    end_keyword = "endscan"

    @property
    def start(self) -> datetime | None:
        """Start time of the scan (UTC), or None if it has no 'start' statement."""
        return parse_epoch(self["start"]) if "start" in self else None

    @property
    def duration(self) -> float | None:
        """Duration of the scan in seconds: the latest data stop time among its stations."""
        stops = [parse_duration(s.fields[2]) for s in self.statements("station") if len(s.fields) > 2]
        return max(stops) if stops else None

    @property
    def mode(self) -> str | None:
        return self.get("mode")

    @property
    def sources(self) -> list[str]:
        return [s.fields[0] for s in self.statements("source")]

    @property
    def stations(self) -> list[str]:
        """Codes of the stations that observe in the scan."""
        return [s.fields[0] for s in self.statements("station")]


class Block(_HasStatements, Node):
    """A block of the VEX file: everything from a '$NAME;' line until the next block.

    It behaves as a dictionary of its definitions (or scans), by name:
        block['name']                 the Def (or Scan) called 'name'
        block['$KEY']                 value of a 'ref $KEY = value;' statement in the block
                                      (as found in $GLOBAL)
    Iterating over a block gives the names of its definitions.
    """

    def __init__(self, name: str, children: list[Node] | None = None):
        self.name = name
        self.children: list[Node] = [] if children is None else list(children)

    def _where(self) -> str:
        return f"'${self.name}'"

    def _state(self) -> object:
        return self.name

    def _format(self) -> str:
        return f"${self.name};"

    def _default_position(self) -> int:
        # New statements go before the first definition
        for i, child in enumerate(self.children):
            if isinstance(child, Def):
                return i

        return len(self.children)

    def to_string(self, indent: str | None = None) -> str:
        return self._render_line("") + "".join(child.to_string(DEFAULT_INDENT)
                                               for child in self.children)

    @property
    def defs(self) -> list[Def]:
        """All the definitions (or scans) in the block, in order."""
        return [child for child in self.children if isinstance(child, Def)]

    def _defs_named(self, name: str) -> list[Def]:
        return [definition for definition in self.defs if definition.name == name]

    def __getitem__(self, key: str) -> Def | Value:
        if key.startswith("$"):
            return self._get_value(key)

        return _single(self._defs_named(key), key, self._where())

    def __setitem__(self, key: str, value: Def | Value) -> None:
        """block['name'] = Def(...) replaces the definition with that name, or adds it at the end.
        block['$KEY'] = value modifies or adds a reference statement.
        """
        if key.startswith("$"):
            if isinstance(value, Def):
                raise TypeError(f"a reference ('{key}') takes a value, not a {type(value).__name__}")

            self._set_value(key, value)
            return

        if not isinstance(value, Def):
            raise TypeError(f"block['{key}'] must be a Def or Scan, not {type(value).__name__}")

        value.name = key
        existing = self._defs_named(key)
        if existing:
            self.children[self.children.index(_single(existing, key, self._where()))] = value
        else:
            self.children.append(value)

    def __delitem__(self, key: str) -> None:
        if key.startswith("$"):
            self._del_value(key)
            return

        found = {id(definition) for definition in self._defs_named(key)}
        if not found:
            raise KeyError(key)

        self.children = [child for child in self.children if id(child) not in found]

    def get(self, key: str, default: object = None) -> Def | Value | None:
        return self[key] if key in self else default

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False

        return bool(self.statements(key) if key.startswith("$") else self._defs_named(key))

    def keys(self) -> list[str]:
        """The names of the definitions in the block, in order."""
        return [definition.name for definition in self.defs]

    def values(self) -> list[Def]:
        return self.defs

    def items(self) -> list[tuple[str, Def]]:
        return [(definition.name, definition) for definition in self.defs]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.defs)

    def __repr__(self) -> str:
        return f"Block({self.name!r}, <{len(self.children)} children>)"


class Vex(ObservationMixin, _HasStatements, Node):
    """A full VEX file: the nodes before the first block (typically the 'VEX_rev = ...;'
    statement and comments) and the blocks, in the order they appear in the file.

    It behaves as a dictionary of its blocks, by name (without the '$'):
        vex = Vex.from_file('experiment.vex')
        vex['STATION']['Jb']['$SITE']
        vex.to_file('new.vex')
    """

    def __init__(self, children: list[Node] | None = None):
        self.children: list[Node] = [] if children is None else list(children)

    @classmethod
    def from_string(cls, text: str) -> "Vex":
        """Parses the text of a VEX file. Raises VexSyntaxError if it is not correct."""
        from .parser import parse

        return parse(text)

    @classmethod
    def from_file(cls, path: str | os.PathLike) -> "Vex":
        """Reads and parses a VEX file. Raises VexSyntaxError if it is not correct."""
        # newline='' keeps the original line breaks, so the file can be written back unchanged
        with open(path, newline="") as vexfile:
            return cls.from_string(vexfile.read())

    def to_file(self, path: str | os.PathLike, overwrite: bool = True) -> None:
        """Writes the VEX file. Raises FileExistsError if it exists and overwrite is False."""
        with open(path, "w" if overwrite else "x", newline="") as vexfile:
            vexfile.write(self.to_string())

    def verify(self, *, freq_overlap: bool = True) -> list["Issue"]:
        """Checks the content of the VEX file and returns the problems found (see pyvexfile.verify).
        If freq_overlap is True, it also checks that in every scan each station shares part of
        its frequency coverage with at least one of the other stations in that scan.
        """
        from .verify import verify

        return verify(self, freq_overlap=freq_overlap)

    def _where(self) -> str:
        return "the VEX file header"

    def _default_position(self) -> int:
        # New statements go before the first block
        for i, child in enumerate(self.children):
            if isinstance(child, Block):
                return i

        return len(self.children)

    def to_string(self, indent: str | None = None) -> str:
        return "".join(child.to_string("") for child in self.children)

    @property
    def version(self) -> str | None:
        """The VEX version, as given by the 'VEX_rev = ...;' statement (None if missing)."""
        found = self.statements("VEX_rev")
        return None if not found else self._get_value("VEX_rev")

    @version.setter
    def version(self, version: str) -> None:
        self._set_value("VEX_rev", version)

    @property
    def blocks(self) -> list[Block]:
        """All the blocks in the file, in order."""
        return [child for child in self.children if isinstance(child, Block)]

    def _blocks_named(self, name: str) -> list[Block]:
        return [block for block in self.blocks if block.name == name]

    def __getitem__(self, name: str) -> Block:
        return _single(self._blocks_named(name), name, "the VEX file")

    def __setitem__(self, name: str, block: Block) -> None:
        """vex['NAME'] = Block(...) replaces the block with that name, or adds it at the end."""
        if not isinstance(block, Block):
            raise TypeError(f"vex['{name}'] must be a Block, not {type(block).__name__}")

        block.name = name
        existing = self._blocks_named(name)
        if existing:
            self.children[self.children.index(_single(existing, name, "the VEX file"))] = block
        else:
            self.children.append(block)

    def __delitem__(self, name: str) -> None:
        found = {id(block) for block in self._blocks_named(name)}
        if not found:
            raise KeyError(name)

        self.children = [child for child in self.children if id(child) not in found]

    def get(self, name: str, default: Block | None = None) -> Block | None:
        return self[name] if name in self else default

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and bool(self._blocks_named(name))

    def keys(self) -> list[str]:
        """The names of the blocks, in order."""
        return [block.name for block in self.blocks]

    def values(self) -> list[Block]:
        return self.blocks

    def items(self) -> list[tuple[str, Block]]:
        return [(block.name, block) for block in self.blocks]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.blocks)

    def __repr__(self) -> str:
        return f"Vex(<{len(self.blocks)} blocks>)"
