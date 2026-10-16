# pyVexfile

pyvexfile is a parser for VEX files written completely in Python, with no dependencies.
It reads a VEX file into a `Vex` object that can be inspected and modified, and written back to a file.

All comments and the original layout are kept: the parts of the file that have not been modified are
written exactly as they were read (spacing, alignment and comments included). Modified or new
statements are written in a standard format.

The parser checks the syntax of the file (blocks, definitions, statements, and their `;`) and reports
errors with their line and column. The content can then be checked with `verify()` (see below).
All values are stored as strings, without further evaluation.


## Usage

```python
from pyvexfile import Def, Statement, Vex

vex = Vex.from_file("n26c3.vex")
vex.version                                     # '1.5'
```

A `Vex` object behaves as a dictionary of blocks (`$NAME;`), and each block as a dictionary of its
definitions (`def NAME; ... enddef;`) or scans (`scan NAME; ... endscan;`):

```python
vex.keys()                                      # ['GLOBAL', 'EXPER', 'MODE', 'IF', ...]
for name, station in vex["STATION"].items():
    print(name, station["$SITE"])
```

Within a definition, statements are accessed by their key. References (`ref $KEY = value;`) use the
key with its `$`, as in the VEX file:

```python
vex["GLOBAL"]["$EXPER"]                         # 'N26C3'
vex["EXPER"]["N26C3"]["exper_name"]             # 'N26C3'
vex["SOURCE"]["J1753+2848"]["ra"]               # '17h53m42.4736450s'
```

Values made of several fields (separated by `:` in the file) are returned as a list of strings.
Empty fields are `''`, and link words keep their `&`:

```python
vex["SCHED"]["No0001"].get_all("station")[0]   # ['Jb', '0 sec', '360 sec', '0.000 GB', '', '&n', '1']
```

When a key appears several times in a definition (e.g. `chan_def` or `ref $IF`), use `get_all()`,
which returns all the values in order. Accessing it with `[]` raises a `ValueError`:

```python
freq = vex["FREQ"]["4632MHz32x32MHz"]
freq.get_all("chan_def")                        # [['', '4632 MHz', 'L', '32.00 MHz', '&CH01', ...], ...]
freq.statements("chan_def")[0].comment          # ' RCP'  (comment after the statement)
```

`statements()` gives the `Statement` objects, which also hold the comment written after them in the same line.


## Information about the observation

The blocks of a VEX file refer to each other (e.g. a `$MODE` definition selects which `$FREQ`, `$BBC`
and `$IF` definitions each station uses). The following properties and methods follow these
references and return parsed values (dates, frequencies in MHz, ...), while `[]` always returns
the raw text of the file:

```python
vex.experiment                                  # 'N26C3'
vex.stations                                    # [Station(code='Jb', name='JODRELL2', site=..., antenna=..., das=...), ...]
vex.modes                                       # ['evn6cm-4Gbps-32MHz']
vex.scans[0].start                              # datetime(2026, 10, 20, 11, 0, tzinfo=UTC)
vex.scans[0].duration                           # 360.0 (seconds)
vex.setup("FREQ", "evn6cm-4Gbps-32MHz", "Wb")   # the $FREQ Def used by Wb in that mode
vex.channels("evn6cm-4Gbps-32MHz", "Cm")        # [Channel(name='CH01', sky_frequency=4888.0, sideband='U',
                                                #          bandwidth=64.0, bbc='BBC01', polarization='R'), ...]
```


## Verifying a VEX file

`verify()` checks the content of the file and returns a list of `Issue`s (errors or warnings), sorted by line:

```python
for issue in vex.verify():
    print(issue)                                # line 518: error: 'ref $SITE' in 'def Jb' ($STATION): ...
```

It checks that:
- the file starts with `VEX_rev`, and its blocks are defined in that VEX version (1.5 or 2.0);
- blocks, definitions and scans are not duplicated, and scans are only defined in `$SCHED`;
- the main parameters have valid values: `chan_def`, `if_def`, `BBC_assign`, epochs, the stations of
  each scan, `site_position`, `ra`, `dec` and `ref_coord_frame`;
- every `ref $BLOCK = name` refers to an existing definition, and the stations in `$MODE` exist;
- in the setup of every station, channels use assigned BBCs, and BBCs use defined IFs;
- every scan uses an existing mode, sources and stations, every station in a scan has a `$FREQ`
  setup in the scan's mode, and no station observes in two scans at the same time.

With `freq_overlap=True` (the default), it also checks that **in every scan, each station shares part
of its frequency coverage with at least one other station of that scan**, using the mode of that scan.
Different parts of the observation can therefore use different setups: stations are only compared with
the stations they actually observe with. A warning is also given if the stations of a scan form
separate groups without any frequency in common between them. Use `vex.verify(freq_overlap=False)`
to skip these checks.

Parameter names are not checked against the VEX standard yet.


## Command line

Installing the package provides the `vex` command (also available as `python -m pyvexfile`):

```
vex experiment.vex                 summary of the observation
vex experiment.vex --stations      list of stations
vex experiment.vex --if            IF setups of each mode
vex experiment.vex --scans         list of scans
vex experiment.vex --freq          frequencies observed by each station, with a plot
vex experiment.vex --verify        check the file (exit status 1 if it has errors)
vex experiment.vex --verify --no-freq-overlap
vex experiment.vex --version       VEX version of the file
```

Options can be combined. Syntax errors are reported as `file:line:column: syntax error: ...`.


## Modifying and writing a VEX file

```python
exper = vex["EXPER"]["N26C3"]
exper["exper_name"] = "N26C4"                   # modifies the existing statement
exper["PI_email"] = "someone@example.com"       # adds it if it did not exist
freq.add("chan_def", ["", "4888 MHz", "U", "32.00 MHz", "&CH33", "&BBC17", "&NoCal"], comment=" RCP")
del exper["exper_description"]

vex["FREQ"]["new_setup"] = Def("new_setup", [Statement("sample_rate", "64.0 Ms/sec")])

vex.to_file("n26c4.vex")                        # or vex.to_string()
```

The full content of a file, including comments, blank lines and literal blocks, is available
as the `children` list of the `Vex`, `Block`, `Def` and `Scan` objects.
