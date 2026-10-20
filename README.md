# pyvexfile

[![PyPI](https://img.shields.io/pypi/v/pyvexfile)](https://pypi.org/project/pyvexfile/)
[![Python](https://img.shields.io/pypi/pyversions/pyvexfile)](https://pypi.org/project/pyvexfile/)
[![License](https://img.shields.io/pypi/l/pyvexfile)](https://github.com/bmarcote/vex/blob/master/LICENSE)

**pyvexfile** reads, inspects, modifies, verifies and writes [VEX](https://vlbi.org/vex/) files: the files
that describe VLBI observations (stations, frequency setups, sources and the schedule of scans).

Unlike other VEX parsers, pyvexfile keeps everything that is in the file. Comments, blank lines,
alignment and literal blocks survive a read–write cycle untouched. Only the statements you modify are
reformatted, so a file can be edited by a program and still read and diff like it was edited by hand.

```python
from pyvexfile import Vex

vex = Vex("n26c3.vex")
vex["EXPER"]["N26C3"]["exper_name"] = "N26C4"
vex.to_file("n26c4.vex")         # identical to n26c3.vex except for that line
```

- **Lossless.** Unmodified parts of a file are written back byte for byte, comments and line breaks included.
- **Robust parsing.** A real tokenizer and parser, not line splitting: several statements in one line,
  statements over several lines, comments after a statement, quoted strings containing `;` or `*`, and
  `start_literal`/`end_literal` blocks are all handled. Syntax errors give their line and column.
- **Simple access.** Blocks, definitions and statements behave like dictionaries, using the same names
  as in the file (`vex["STATION"]["Jb"]["$SITE"]`).
- **Knows how a VEX file fits together.** It follows the references between blocks to answer questions
  such as "which frequency channels does station Wb observe in this mode?".
- **Verification.** It checks references, values, scans and frequency overlap between stations.
- **Command line tool.** `vex` summarizes a file, lists stations, scans and IFs, plots the frequency
  coverage of each station, and verifies the file.
- Pure Python (3.11+), no dependencies.


## Contents

- [Installation](#installation)
- [Command line](#command-line)
- [Python API](#python-api)
  - [Reading and writing](#reading-and-writing)
  - [How a VEX file is represented](#how-a-vex-file-is-represented)
  - [Accessing blocks, definitions and statements](#accessing-blocks-definitions-and-statements)
  - [Modifying a file](#modifying-a-file)
  - [Creating a file from scratch](#creating-a-file-from-scratch)
  - [Information about the observation](#information-about-the-observation)
  - [Verification](#verification)
  - [Errors](#errors)
  - [Lower-level modules](#lower-level-modules)
- [Development](#development)
- [Known limitations](#known-limitations)
- [License](#license)


## Installation

pyvexfile is available on [PyPI](https://pypi.org/project/pyvexfile/):

```bash
pip install pyvexfile
```

This installs the `pyvexfile` Python package and the `vex` command. To install the latest development
version from the [GitHub repository](https://github.com/bmarcote/vex) instead:

```bash
pip install git+https://github.com/bmarcote/vex
```


## Command line

```
vex FILE [--version] [--stations] [--if] [--scans] [--freq] [--verify [--no-freq-overlap]]
vex FILE --trim [NEWFILE]
```

Without options, `vex` prints a summary of the observation:

```
$ vex n26c3.vex
Experiment   N26C3
VEX version  1.5
Stations     15: Jb Wb Ef Mc O8 T6 Ur Tr Hh Ir Cm Kn Pi Da De
Modes        evn6cm-4Gbps-32MHz
Sources      1
Scans        14
Start (UTC)  2026-10-20 11:00:00
End (UTC)    2026-10-20 14:00:00
```

The options can be combined, and each one adds a section to the output:

| Option | Shows |
|---|---|
| `--version` | The VEX version of the file (`VEX_rev`). |
| `--stations` | The stations, with their site name, antenna and DAS. |
| `--scans` | The scans: start time, duration, source, mode and stations. |
| `--if` | For each mode, the `$IF` setups, the stations using them and their IFs. |
| `--freq` | For each mode, the frequency setup of every station and a plot of the frequencies they cover. |
| `--verify` | The problems found in the file (see [Verification](#verification)). The exit status is 1 if there are errors. Add `--no-freq-overlap` to skip the frequency overlap checks. |

`--trim` removes the in-line comments (those written after a statement in the same line), keeping the
comments at the beginning of a line. The result is written to `NEWFILE` if given
(`vex n26c3.vex --trim n26c3_trimmed.vex`), otherwise the VEX file is overwritten. It cannot be combined
with other options.

```
$ vex n26c3.vex --stations --scans
Stations (15)
Code  Name      Antenna   DAS
----  --------  --------  ------------
Jb    JODRELL2  JODRELL2  DBBC+Mark5C
Wb    WSTRBORK  WSTRBORK  DBBC+Mark5C
...

Scans (14)
Scan    Start (UTC)          Duration  Source      Mode                Stations
------  -------------------  --------  ----------  ------------------  ------------------------------------------------
No0001  2026-10-20 11:00:00  360 s     J1753+2848  evn6cm-4Gbps-32MHz  15: Jb Wb Ef Mc O8 T6 Ur Tr Hh Ir Cm Kn Pi Da De
No0002  2026-10-20 11:08:00  240 s     J1753+2848  evn6cm-4Gbps-32MHz  15: Jb Wb Ef Mc O8 T6 Ur Tr Hh Ir Cm Kn Pi Da De
...
```

```
$ vex n26c3.vex --if
Mode evn6cm-4Gbps-32MHz
  $IF setup                Stations        IF     Physical  Pol  LO (MHz)  Sideband
  -----------------------  --------------  -----  --------  ---  --------  --------
  LO@4088MHzDPolNoTone     Ef              IF_A1  A1        R    4088      U
                                           IF_C3  C3        L    4088      U
                                           IF_B1  B1        R    4088      U
                                           IF_D3  D3        L    4088      U
  LO@4088MHzDPolNoTone#02  Ir O8           IF_A1  A1        R    4088      U
...
```

`--freq` shows, for each mode, which part of the band every station observes. The plot uses the width
of the terminal; `▌` marks cells that are only partly covered:

```
$ vex n26c3.vex --freq
Mode evn6cm-4Gbps-32MHz
  Station  $FREQ setup      Channels (MHz)  Covered (MHz)  Pol
  -------  ---------------  --------------  -------------  ---
  Ef       4632MHz32x32MHz  32x32           4600-5112      L R
  ...
  Cm       4888MHz2x64MHz   2x64            4888-4952      L R
  ...
  Wb       4888MHz8x32MHz   8x32            4856-4984      L R

      Frequency coverage (MHz)
      4600         4700            4800           4900            5000           5100
      ├──────────────┼───────────────┼──────────────┼───────────────┼──────────────┼─┤
  Ef │████████████████████████████████████████████████████████████████████████████████│
  ...
  Cm │                                             ██████████                         │
  ...
  Wb │                                        ████████████████████                    │
      ├──────────────┼───────────────┼──────────────┼───────────────┼──────────────┼─┤
```

`--verify` reports problems as `file:line: severity: message`, so editors can jump to them:

```
$ vex n26c4.vex --verify
n26c4.vex:518: error: 'ref $SITE' in 'def Jb' ($STATION): 'JODRELL3' is not defined in $SITE
n26c4.vex:915: error: scan No0001: source 'J1754+2848' is not defined in $SOURCE
n26c4.vex:915: warning: the stations in mode 'evn6cm-4Gbps-32MHz' form 2 groups without any frequency in common between them (scans No0001, No0002, No0003 and 11 more): Jb Wb Ef Mc O8 T6 Ur Tr Hh Ir (4600-5112 MHz); Cm Kn Pi Da De (9888-9952 MHz)
2 errors, 1 warning
```

Syntax errors are reported as `file:line:column: syntax error: ...` with exit status 1. The tool can also
be run as `python -m pyvexfile`.


## Python API

The examples below use [`n26c3.vex`](https://github.com/bmarcote/vex/blob/master/tests/data/n26c3.vex),
an EVN observation included in the repository.

### Reading and writing

```python
>>> from pyvexfile import Vex
>>> vex = Vex("n26c3.vex")
>>> vex.version
'1.5'
>>> text = vex.to_string()
>>> text == open("n26c3.vex").read()
True

```

`Vex(path)` reads a file (the same as `Vex.from_file(path)`), `Vex.from_string(text)` parses text that is already in memory, and `vex.to_file(path)` writes the file.
`to_file(path, overwrite=False)` raises `FileExistsError` instead of replacing an existing file. Line
breaks are kept as they are, so files with Windows (`\r\n`) line breaks are also written back unchanged.

### How a VEX file is represented

A VEX file is a list of blocks (`$NAME;`), most of which contain definitions (`def NAME; ... enddef;`),
or scans (`scan NAME; ... endscan;`) in the case of `$SCHED`. Definitions contain statements
(`key = value;`) and references to definitions in other blocks (`ref $BLOCK = name;`):

```
VEX_rev = 1.5;
$STATION;                          <- Block "STATION"
def Jb;                            <- Def "Jb"
     ref $SITE = JODRELL2;         <- Statement "$SITE" (a reference)
     ...
enddef;
$SITE;
def JODRELL2;
     site_name = JODRELL2;         <- Statement "site_name"
     ...
```

pyvexfile reads the file into a tree with the same shape. Every node keeps its position in the file, so
comments and blank lines stay where they were:

```
Vex
 ├── Statement, Comment, BlankLine          (before the first block, e.g. VEX_rev = 1.5;)
 └── Block                                  $NAME;
      ├── Statement, Comment, BlankLine, Literal
      └── Def / Scan                        def NAME; ... enddef;  /  scan NAME; ... endscan;
           └── Statement, Comment, BlankLine, Literal
```

The full list of nodes of a `Vex`, `Block`, `Def` or `Scan` is in its `children` attribute, and every node
read from a file has the `line` where it starts.

### Accessing blocks, definitions and statements

A `Vex` behaves as a dictionary of its blocks (without the `$`), and a `Block` as a dictionary of its
definitions:

```python
>>> vex.keys()
['GLOBAL', 'EXPER', 'MODE', 'IF', 'BBC', 'PHASE_CAL_DETECT', 'FREQ', 'TRACKS', 'ROLL', 'STATION', 'ANTENNA', 'DAS', 'SITE', 'PROCEDURES', 'SOURCE', 'SCHED']
>>> "STATION" in vex
True
>>> vex["STATION"].keys()
['Jb', 'Wb', 'Ef', 'Mc', 'O8', 'T6', 'Ur', 'Tr', 'Hh', 'Ir', 'Cm', 'Kn', 'Pi', 'Da', 'De']
>>> vex["STATION"]["Jb"]
Def('Jb', <3 children>)

```

A `Def` (or `Scan`) behaves as a dictionary of the values of its statements:

```python
>>> source = vex["SOURCE"]["J1753+2848"]
>>> source["ra"]
'17h53m42.4736450s'
>>> source.keys()
['source_name', 'ra', 'dec', 'ref_coord_frame']
>>> source.get("epoch", "not defined")
'not defined'

```

`get()`, `in`, iteration, `keys()`, `items()` and `len()` work as with dictionaries. A missing name raises
`KeyError`.

#### References: keys starting with `$`

References are accessed with the `$` in front of the block name, as written in the file. This keeps them
apart from parameters that could have the same name:

```python
>>> vex["STATION"]["Jb"]["$SITE"]           # ref $SITE = JODRELL2;
'JODRELL2'
>>> vex["GLOBAL"]["$EXPER"]                 # references directly in a block, as in $GLOBAL
'N26C3'

```

#### Values and fields

Values are always returned as the text written in the file. A value made of several fields (separated by
`:` in the file) is returned as a list. Spaces around each field are removed, empty fields are `''`, link
words keep their `&` and quoted strings keep their quotes:

```python
>>> vex["MODE"]["evn6cm-4Gbps-32MHz"].get_all("$IF")[1]     # ref $IF = LO@4088MHzDPolNoTone#02:Ir:O8;
['LO@4088MHzDPolNoTone#02', 'Ir', 'O8']
>>> vex["SCHED"]["No0001"].get_all("station")[0]           # station = Jb : 0 sec : 360 sec : ... ;
['Jb', '0 sec', '360 sec', '0.000 GB', '', '&n', '1']
>>> vex["EXPER"]["N26C3"]["exper_description"]
'"Network Monitoring Experiment"'

```

The [observation helpers](#information-about-the-observation) convert values into numbers and dates.

#### Repeated keys

Some keys appear several times in a definition, such as `chan_def` in `$FREQ` or `ref $IF` in `$MODE`.
`get_all()` returns all their values, in order. Accessing them with `[]` raises a `ValueError` instead of
returning only one of them:

```python
>>> freq = vex["FREQ"]["4632MHz32x32MHz"]
>>> len(freq.get_all("chan_def"))
32
>>> freq.get_all("chan_def")[0]
['', '4632 MHz', 'L', '32.00 MHz', '&CH01', '&BBC01', '&NoCal']
>>> freq["chan_def"]
Traceback (most recent call last):
...
ValueError: 'chan_def' appears 32 times in 'def 4632MHz32x32MHz'; use get_all('chan_def')

```

`items()` gives the `(key, value)` of every statement, including repeated keys.

#### Statements and comments

`statements(key)` returns the `Statement` objects themselves, which also hold the comment written after
them in the same line (without the `*`):

```python
>>> chan_def = freq.statements("chan_def")[0]
>>> chan_def
Statement('chan_def', ['', '4632 MHz', 'L', '32.00 MHz', '&CH01', '&BBC01', '&NoCal'], comment=' RCP')
>>> chan_def.fields[1], chan_def.comment, chan_def.line
('4632 MHz', ' RCP', 350)

```

Comment lines, blank lines and literal blocks are `Comment`, `BlankLine` and `Literal` nodes in the
`children` of the block or definition that contains them:

```python
>>> vex.children[1]
Comment('    pySCHED version: 1.29.0')
>>> vex["FREQ"]["4632MHz32x32MHz"].children[0]
Comment(' evn6cm-4Gbps-32MHz: Ef, Hh, Ir, Jb, Mc, O8, T6, Tr, Ur')

```

### Modifying a file

Assigning a value modifies the statement if it exists, or adds it otherwise. `add()` always adds a new
statement, after the last one with the same key. `del` removes all the statements with that key:

```python
>>> vex = Vex("n26c3.vex")
>>> exper = vex["EXPER"]["N26C3"]
>>> exper["exper_name"] = "N26C4"                       # modifies the existing statement
>>> exper["contact_name"] = "B. Marcote"                # new statement, added after the last one
>>> del exper["target_correlator"]
>>> freq = vex["FREQ"]["4888MHz2x64MHz"]
>>> new_channel = freq.add("chan_def", ["", "5016 MHz", "U", "64.00 MHz", "&CH03", "&BBC02", "&NoCal"], comment=" RCP")
>>> freq.statements("chan_def")[0].comment = " right circular polarization"

```

Statement objects can also be changed directly (`statement.value`, `statement.fields`,
`statement.comment`), even in place (`statement.fields[1] = "5000 MHz"`). Definitions and blocks are
replaced or added by assigning a `Def`, `Scan` or `Block`, and removed with `del`:

```python
>>> from pyvexfile import Def, Statement
>>> vex["SOURCE"]["J1800+3848"] = Def("J1800+3848", [
...     Statement("source_name", "J1800+3848"),
...     Statement("ra", "18h00m24.7653613s"),
...     Statement("dec", "38d48'30.697460\""),
...     Statement("ref_coord_frame", "J2000"),
... ])
>>> vex["SOURCE"].keys()
['J1753+2848', 'J1800+3848']

```

When the file is written, only the modified parts change. Modified statements keep their indentation and
their comment, and new statements are written in a standard format:

```python
>>> vex.to_file("n26c4.vex")
>>> import difflib
>>> diff = difflib.unified_diff(open("n26c3.vex").readlines(), open("n26c4.vex").readlines(), n=0)
>>> print("".join(line for line in diff if line[0] in "+-" and line[:3] not in ("+++", "---")), end="")
-     exper_name = N26C3;
+     exper_name = N26C4;
-     target_correlator = JIVE;
+     contact_name = B. Marcote;
-     chan_def =  : 4888 MHz : U :   64.00 MHz : &CH01 : &BBC01 : &NoCal; * RCP
+     chan_def =  : 4888 MHz : U :   64.00 MHz : &CH01 : &BBC01 : &NoCal; * right circular polarization
+     chan_def =  : 5016 MHz : U : 64.00 MHz : &CH03 : &BBC02 : &NoCal; * RCP
+def J1800+3848;
+     source_name = J1800+3848;
+     ra = 18h00m24.7653613s;
+     dec = 38d48'30.697460";
+     ref_coord_frame = J2000;
+enddef;

```

### Creating a file from scratch

All the nodes can be created directly. Keys starting with `$` create references:

```python
>>> from pyvexfile import Block, Comment, Scan
>>> new = Vex([
...     Statement("VEX_rev", "1.5"),
...     Comment(" Written with pyvexfile"),
...     Block("GLOBAL", [Statement("$EXPER", "TEST1")]),
...     Block("EXPER", [Def("TEST1", [Statement("exper_name", "TEST1")])]),
...     Block("SCHED", [Scan("No0001", [
...         Statement("start", "2026y293d11h00m00s"),
...         Statement("station", ["Jb", "0 sec", "360 sec"]),
...     ])]),
... ])
>>> print(new.to_string(), end="")
VEX_rev = 1.5;
* Written with pyvexfile
$GLOBAL;
     ref $EXPER = TEST1;
$EXPER;
def TEST1;
     exper_name = TEST1;
enddef;
$SCHED;
scan No0001;
     start = 2026y293d11h00m00s;
     station = Jb : 0 sec : 360 sec;
endscan;

```

### Information about the observation

The blocks of a VEX file refer to each other. A scan uses a mode, and each `$MODE` definition selects,
for every station, the definitions of `$FREQ`, `$BBC`, `$IF` and other blocks that apply to it. The
following properties and methods follow these references and return parsed values (numbers, dates,
frequencies in MHz), while `[]` always returns the raw text.

```python
>>> vex = Vex("n26c3.vex")
>>> vex.experiment
'N26C3'
>>> vex.modes
['evn6cm-4Gbps-32MHz']
>>> jb = vex.stations[0]
>>> jb.code, jb.name, jb.antenna, jb.das
('Jb', 'JODRELL2', 'JODRELL2', 'DBBC+Mark5C')

```

Scans give their start time (UTC), duration (the longest one among their stations, in seconds), mode,
sources and stations:

```python
>>> scan = vex.scans[0]
>>> scan.name, scan.start, scan.duration
('No0001', datetime.datetime(2026, 10, 20, 11, 0, tzinfo=datetime.timezone.utc), 360.0)
>>> scan.mode, scan.sources, scan.stations[:4]
('evn6cm-4Gbps-32MHz', ['J1753+2848'], ['Jb', 'Wb', 'Ef', 'Mc'])

```

`setups(block, mode)` tells which definitions of a block each station uses in a mode, and
`setup(block, mode, station)` returns the definition used by one station:

```python
>>> mode = "evn6cm-4Gbps-32MHz"
>>> vex.setups("FREQ", mode)
{'4632MHz32x32MHz': ['Ef', 'Hh', 'Ir', 'Jb', 'Mc', 'O8', 'T6', 'Tr', 'Ur'], '4888MHz2x64MHz': ['Cm', 'Da', 'De', 'Kn', 'Pi'], '4888MHz8x32MHz': ['Wb']}
>>> vex.setup("FREQ", mode, "Wb")
Def('4888MHz8x32MHz', <10 children>)

```

`channels(mode, station)` returns the frequency channels of a station. The polarization of each channel
is found by following `chan_def` → `BBC_assign` (in the station's `$BBC` setup) → `if_def` (in its `$IF`
setup):

```python
>>> for channel in vex.channels(mode, "Cm"):
...     print(channel.name, channel.sky_frequency, channel.sideband, channel.bandwidth,
...           channel.polarization, (channel.low, channel.high))
CH01 4888.0 U 64.0 R (4888.0, 4952.0)
CH02 4888.0 U 64.0 L (4888.0, 4952.0)

```

Other helpers:

```python
>>> from pyvexfile import IF
>>> from pyvexfile.observation import covered_ranges
>>> IF.from_def(vex["IF"]["LO@4088MHzDPolNoTone"])[0]
IF(name='IF_A1', physical_name='A1', polarization='R', lo=4088.0, sideband='U')
>>> covered_ranges(vex.channels(mode, "Wb"))               # merged frequency ranges, in MHz
[(4856.0, 4984.0)]
>>> from pyvexfile.units import parse_epoch, parse_frequency, parse_duration
>>> parse_frequency("1.5 GHz"), parse_duration("2 min"), parse_epoch("2026y293d11h")
(1500.0, 120.0, datetime.datetime(2026, 10, 20, 11, 0, tzinfo=datetime.timezone.utc))

```

### Verification

The parser only accepts files with a correct syntax. `verify()` checks their content and returns a list of
`Issue`s, sorted by line. Each one has a `severity` (`Severity.ERROR` when the file is wrong,
`Severity.WARNING` when it is unusual and may not be what was intended), a `message` and a `line`:

```python
>>> vex.verify()
[]
>>> vex["STATION"]["Jb"]["$SITE"] = "JODRELL3"
>>> vex["SCHED"]["No0001"]["source"] = "J1754+2848"
>>> for issue in vex.verify():
...     print(issue)
line 518: error: 'ref $SITE' in 'def Jb' ($STATION): 'JODRELL3' is not defined in $SITE
line 915: error: scan No0001: source 'J1754+2848' is not defined in $SOURCE

```

These are the checks:

| Area | Checks |
|---|---|
| Header | The file starts with `VEX_rev`, and the version is known (1.5 or 2.0). |
| Structure | Blocks are defined in that VEX version. There are no duplicated blocks, definitions or scans. Scans are only in `$SCHED`. Statements outside definitions are only references. |
| Values | `chan_def`, `if_def` and `BBC_assign` have enough fields, and valid frequencies, sidebands and polarizations. Epochs (`start`, `exper_nominal_start/stop`), scan `station` lines, `site_position`, `ra`, `dec` and `ref_coord_frame` have valid values. |
| References | Every `ref $BLOCK = name` points to an existing definition. The stations listed in `$MODE` references are defined in `$STATION`. |
| Setup links | In the setup of every station in every mode, the BBCs used by `chan_def` are assigned in `$BBC`, and the IFs used by `BBC_assign` are defined in `$IF`. |
| Scans | Every scan has a start time, and an existing mode, sources and stations. Every station in a scan has a `$FREQ` setup in the scan's mode. Scans are in time order, and no station is in two scans at the same time. |
| Frequency overlap | See below (can be disabled with `freq_overlap=False`). |

#### Frequency overlap

With `freq_overlap=True` (the default), `verify()` also checks that **in every scan, each station shares
part of its frequency coverage with at least one other station of that scan**. A station without any
frequency in common with the others would not produce any useful data. It does not need to overlap with
all of the other stations.

An observation can use different setups for different parts of the schedule: each scan names its mode,
and the mode decides the frequencies of each station. The check is therefore made for each scan, with the
mode of that scan and only the stations observing in it. Problems are reported once for each mode and
station, listing the affected scans:

```
error: station Cc does not share any frequency with the other stations in mode 'm1' (scans s3, s4); it covers 5000-5032 MHz
```

A warning is also given when the stations of a scan form separate groups, each one with more than one
station, without any frequency in common between the groups. Every station then overlaps with another
one, but the array is split in two:

```
warning: the stations in mode 'evn6cm-4Gbps-32MHz' form 2 groups without any frequency in common between them
(scans No0001, No0002, No0003 and 11 more): Jb Wb Ef Mc O8 T6 Ur Tr Hh Ir (4600-5112 MHz); Cm Kn Pi Da De (9888-9952 MHz)
```

If the file has no scans, the check is made for each mode with all the stations that have a `$FREQ` setup
in it.

### Errors

- `VexSyntaxError` (a subclass of `ValueError`) is raised when a file has a syntax error. It has the `line`
  and `col` where the problem was found, and its message often suggests the likely cause:

  ```python
  >>> from pyvexfile import VexSyntaxError
  >>> try:
  ...     Vex.from_string("$GLOBAL;\n     ref $EXPER = N26C3\n$EXPER;\n")
  ... except VexSyntaxError as error:
  ...     print(error.line, error.col, error.message)
  3 1 unexpected '$' in the value of 'EXPER' (missing ';' at the end of line 2?)

  ```

- `KeyError` is raised for blocks, definitions or keys that do not exist.
- `ValueError` is raised when accessing with `[]` a key that appears several times (use `get_all()`).

### Lower-level modules

- `pyvexfile.lexer.tokenize(text)` splits a VEX file into tokens, including comments and whitespace.
  Joining the values of all tokens gives back the original text.
- `pyvexfile.parse(text)` builds the tree from the text (the same as `Vex.from_string`).
- `pyvexfile.units` converts frequencies (`parse_frequency`, in MHz), durations (`parse_duration`, in
  seconds) and epochs (`parse_epoch`, as UTC `datetime`).


## Development

The source code is at [github.com/bmarcote/vex](https://github.com/bmarcote/vex). To work on it:

```bash
git clone https://github.com/bmarcote/vex.git
cd vex
pip install -e . pytest
```

The package is in `src/pyvexfile/`:

| Module | Contents |
|---|---|
| `lexer.py` | Lossless tokenizer. |
| `parser.py` | Recursive-descent parser that builds the tree. |
| `nodes.py` | Tree nodes (`Vex`, `Block`, `Def`, `Scan`, `Statement`, ...) and their dictionary-like access. |
| `observation.py` | Helpers that follow the references between blocks (`stations`, `channels`, ...). |
| `units.py` | Conversion of frequencies, durations and epochs. |
| `verify.py` | Verification of the content of a file. |
| `cli.py` | The `vex` command. |

Run the tests with:

```bash
pytest
```

The examples in this README are also tests: run them from a directory containing a copy of
`tests/data/n26c3.vex` with

```bash
python -m doctest -o ELLIPSIS README.md
```


## Known limitations

- Parameter names are not checked against the VEX standard: a misspelled parameter is not reported.
- Comments placed inside a statement that spans several lines are kept only while that statement is not
  modified.
- Comment lines right before a `$BLOCK;` line belong to the previous block, so they move with it if
  blocks are reordered.


Bug reports and suggestions are welcome in the [issue tracker](https://github.com/bmarcote/vex/issues).


## License

GPL-3.0-or-later. Written by Benito Marcote (JIVE).
