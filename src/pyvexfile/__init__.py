"""pyvexfile: parser for VEX files that keeps the comments and layout of the original file.

Usage
-----

from pyvexfile import Vex

vex = Vex.from_file("experiment.vex")
vex["STATION"]["Jb"]["$SITE"]                     # value of 'ref $SITE = ...;'
vex["FREQ"]["4632MHz32x32MHz"].get_all("chan_def")
vex["EXPER"]["N26C3"]["exper_name"] = "N26C4"
problems = vex.verify()
vex.to_file("new.vex")

Unmodified parts of the file are written exactly as they were read, comments included.
"""
from importlib.metadata import PackageNotFoundError, version

from .lexer import VexSyntaxError
from .nodes import BlankLine, Block, Comment, Def, Literal, Node, Scan, Statement, Value, Vex
from .observation import IF, Channel, Station
from .parser import parse
from .verify import Issue, Severity


__all__: list[str] = [
    "Vex", "Block", "Def", "Scan", "Statement", "Comment", "BlankLine", "Literal", "Node",
    "Value", "Station", "Channel", "IF", "Issue", "Severity", "VexSyntaxError", "parse",
    "__version__",
]

try:
    __version__ = version("pyvexfile")
except PackageNotFoundError:  # running from the source tree without installing it
    __version__ = "unknown"
