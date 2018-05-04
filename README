# Vex

The vex module is a parser for VEX files that is written completely in Python. It parses a VEX file into a Vex object,
storing all the inputs as an (ordered) dictionary structure. This module does not validate the VEX file, in particular it does not check if the block names and parameter names are actually defined by the VEX standard (https://vlbi.org/vex). All parameters are stored as strings, without further evaluation.


## Usage

```python
import vex

v = vex.Vex(vexfilename)

```

Now you can go through all the sections of the VEX file as

>>> v['STATION']['Jb']...

Note that all comments from the VEX file are kept, and will be shown as different entries named 'comment-##', where ## is the number of the comment line within the respective section/definition.


