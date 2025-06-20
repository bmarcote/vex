#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Vex files parser
The vex module is a parser for VEX files that is written completely in Python.
It parses a VEX file into a Vex object, storing all the inputs as an (ordered)
dictionary structure. This module does not validate the VEX file, in particular
it does not check if the block names and parameter names are actually defined by
the VEX standard (https://vlbi.org/vex).
All parameters are stored as strings, without further evaluation.

Usage
-----

import pyvexfile as vex

v = vex.Vex(vexfilename)


Now you can go through all the sections of the VEX file as

v['STATION']['Jb']...

Note that all comments from the VEX file are kept,
and will be shown as different entries named 'comment-##', where ## is the number
of the comment line within the respective section/definition.


Version: 1.1
Date: Jul 2018
Written by Benito Marcote (marcote@jive.eu)


version 1.1 changes
- Bug fixes (in Section.__repr__). Fixed by Jay Blanchard

"""
from collections import OrderedDict as _OrderedDict
from enum import Enum as _Enum
import copy as _copy
import os as _os
import sys as _sys
import re as _re


class EntryType(_Enum):
    """Accepted types for an entry line in a key file (ignoring section titles and def).
    The possible types are:
        - comment. A comment line
        - parameter. If the line has the form 'key = value'
        - variable. If the line has the form 'ref $key = value'
    """
    comment = 1
    parameter = 2
    variable = 3

    @classmethod
    def has_type(cls, str_type):
        """Checks if EntryType has an enumeration with the name 'str_type'
        """
        return str_type in cls.__members__.keys()



class Entry:
    """Defines an entry in a vex file, that can be either a comment (everything after a *),
    a parameter (key = value;), or a variable definition (ref $key = value;).
    Value can be either a string, or a list of strings (if in the vexfile there are values
    separated by a ':').
    In the case of a comment line, the key is ignored and all the information is stored in value
    """

    def __init__(self, type_entry, key, value):
        # self._type = None
        self.type = type_entry
        self.key = key
        self.value = value
        self.__name__ = 'Entry'


    @property
    def type(self):
        """Type of the entry. It can only be 'parameter', 'variable', or 'comment'
        """
        return self._type

    @type.setter
    def type(self, type_entry):
        if not isinstance(type_entry, EntryType):
            raise ValueError(f'{type_entry} is not an accepted EntryType')

        self._type = type_entry


    @property
    def key(self):
        return self._key


    @key.setter
    def key(self, a_key):
        if (self.type is EntryType.comment) and (a_key is not None):
            raise ValueError('key must be None for comment entries')

        self._key = a_key


    def entry_from_text(text):
        """Interprets a string line (such as a line in the vex file) and saves it as an 
        Entry object
        """
        if text.strip()[0] == '*':
            # It is a comment line. Nothing additionally to do
            return Entry(EntryType.comment, key=None, value=text.strip()[1:])

        assert text.count('=') >= 1
        key, *value = [i for i in text.split('=')]
        key = key.strip()
        if isinstance(value, list):
            # In the case of >1 everything after first will be placed as the value (str)
            value = '='.join(value)

        value = value.strip()
        if value[-1] == ';':
            value = value[:-1]

        if 'ref ' in key:
            # This is a variable definition
            assert key.count('$') == 1
            key = key.split('$')[1].strip()
            text_entry = EntryType.variable
        else:
            # Should not be spaces in the key
            # assert key.count(' ') == 0
            text_entry = EntryType.parameter

        # Removing the trailing ; that denotes the end of the line
        # DO NOT DO THAT!! in some places as in the $FREQ, cahn_def, there are comment 
        # after it that should remain and they would produce a bad bahavior later
        # value = value.replace(';', '')
        # Value can be a list of values (separated by a :)
        if ':' in value:
            value = value.split(':')

        return Entry(text_entry, key, value)

    def entry_literal(key, text):
        """Interprets a string line (such as a line in the vex file) and saves it as an 
        Entry object
        """
        text = text.strip()

        return Entry(EntryType.parameter, key, text)

    def __getitem__(self, key):
        if self.key == key:
            return self.value
        else:
            raise KeyError(f'{key} not found')


    def __setitem__(self, value):
        self.value = value

    def __setitem__(self, key, value):
        if self.key == key:
            self.value = value
        else:
            raise KeyError(f'{key} not found. New Entry required')


    def to_string(self, heading_spaces=None):
        return self.__str__(heading_spaces)


    def __str__(self, heading_spaces=None):
        if heading_spaces is None:
            s = ' '*5
        else:
            s = ' '*heading_spaces

        if self.type is EntryType.comment:
            return f'*{self.value}\n'
        elif self.type is EntryType.variable:
            if type(self.value) is list:
                return s + f"ref ${self.key} = {':'.join(self.value)};\n"
            else:
                return s + f"ref ${self.key} = {self.value};\n"
        elif self.type is EntryType.parameter:
            if type(self.value) is list:
                return s + f"{self.key} = {':'.join(self.value)};\n"
            else:
                return s + f"{self.key} = {self.value};\n"
        else:
            # Just as control. To make sure noone updated wrongly this code.
            raise ValueError('The EntryType is inconsistent with the __str__ representations of Entry')


    def __repr__(self):
        return f'<{self.__module__}.{self.__name__} at {hex(id(self))}>'


class Definition(_OrderedDict):
    """Represents a definition from a vex file (everything between a 'def name;' line and 'enddef;'
    A Definition consists of a name (the name written right after 'def', and an OrderedDict containing
    all the Entries within that definition. The keys from the OrderedDict are the same as the key in
    each Entry (see that help, basically following the ' key = params..;'  format). For each key one
    of more entries are possible (in case the same key is used multiple types within that definition,
    e.g. as typically happens in 'ref $IF = ...' entries.

    In the case of comment lines, the key will be 'comment#' where # will be a number describing that
    this is the #-line within this definition.

    An empty Definition (without any entry) can be created, although a name must always be provided.
    """
    def __init__(self, name, list_of_entries=None):
        self.name = name
        if list_of_entries is None:
            self._entries = _OrderedDict()
        else:
            self.entries = list_of_entries

        self._number_comments = 0


    @property
    def entries(self):
        return self._entries


    @entries.setter
    def entries(self, new_entries):
        self._entries = _OrderedDict()
        for an_entry in new_entries:
            self.add_entry(an_entry)


    def add_entry(self, new_entry):
        """Add a new entry to the list of entries already available in this Definition. It will be
        appended to the end (after all the previous entries). new_entry must be an Entry object.
        """
        assert isinstance(new_entry, Entry)
        if new_entry.type is EntryType.comment:
            self._number_comments += 1
            self._entries[f'comment-{self._number_comments}'] = new_entry
        else:
            # If it is an existing key, then add the Entry as a new element in a list
            #for such key. NOTE that this will force that all entries for the same key
            # will be consecutive in the final Definition, even if in the input they
            # are not
            if new_entry.key in self._entries:
                if type(self._entries[new_entry.key]) is list:
                    # There were already more than one entry
                    self._entries[new_entry.key].append(new_entry)
                else:
                    # There was only one entry, meaning that the value was the Entry object
                    self._entries[new_entry.key] = [self._entries[new_entry.key], new_entry]
            else:
                self._entries[new_entry.key] = new_entry


    def __getitem__(self, key):
        return self._entries[key]


    def __setitem__(self, key, value):
        self._entries[key] = value


    def __len__(self):
        return len(self._entries)


    def __delitem__(self, key):
        del self._entries[key]


    def has_key(self, key):
        return key in self._entries


    def keys(self):
        return self._entries.keys()


    def values(self):
        return self._entries.values()


    def items(self):
        return self._entries.items()


    def pop(self, *args):
        return self._entries.pop(*args)


    def __contains__(self, item):
        return item in self._entries


    def __iter__(self):
        return iter(self._entries)


    def to_string(self):
        return self.__str__()


    def __str__(self):
        # Preferred way. In CPython += strings is much faster but only there.
        s = [f'def {self.name};\n']
        for an_entry in self.entries.values():
            if type(an_entry) is list:
                for an_entry2 in an_entry:
                    s.append(an_entry2.to_string())
            else:
                s.append(an_entry.to_string())

        s.append('enddef;\n')
        return ''.join(s)



class Scan(Definition):

    def __init__(self, name, list_of_entries=None):
        super().__init__(name, list_of_entries)


    def to_string(self):
        return self.__str__()


    def __str__(self):
        # Preferred way. In CPython += strings is much faster but only there.
        s = [f'scan {self.name};\n']
        for an_entry in self.entries.values():
            if type(an_entry) is list:
                for an_entry2 in an_entry:
                    s.append(an_entry2.to_string())
            else:
                s.append(an_entry.to_string())

        s.append('endscan;\n')
        return ''.join(s)



class Section:
    """A Section in a vex file is defined by a starting line with $section_name; and
    can contain entries and/or definitions. It cover everything below such line until
    another section is declared.
    """
    def __init__(self, name, definitions=None):
        self.name = name
        if definitions is not None:
            self.definitions = definitions
        else:
            self._definitions = _OrderedDict()

        self._number_comments = 0
        self.__name__ = 'Section'


    @property
    def definitions(self):
        return self._definitions


    @definitions.setter
    def definitions(self, new_definitions):
        """A definition can be either a Definition or an Entry (typically because it is a comment line)
        """
        self._definitions = _OrderedDict()
        for new_definition in new_definitions:
            self.add_definition(new_definition)


    def add_definition(self, new_definition):
        """Add a new Definition (or an Entry) to the definitions in this Section.
        If new_definition.name matches an existing definition, the former one will be replaced.
        """
        if isinstance(new_definition, Definition):
            self._definitions[new_definition.name] = new_definition
        elif isinstance(new_definition, Entry):
            if new_definition.type is EntryType.comment:
                self._number_comments += 1
                self._definitions[f'comment-{self._number_comments}'] = new_definition
            else:
                self._definitions[new_definition.key] = new_definition
        else:
            raise ValueError('new_definition must be an instance of Definition or Entry')


    def __getitem__(self, key):
        return self._definitions[key]


    def __setitem__(self, key, value):
        self._definitions[key] = value


    def __len__(self):
        return len(self._definitions)


    def __delitem__(self, key):
        del self._definitions[key]


    def has_key(self, key):
        return key in self._definitions


    def keys(self):
        return self._definitions.keys()


    def values(self):
        return self._definitions.values()


    def items(self):
        return self._definitions.items()


    def pop(self, *args):
        return self._definitions.pop(*args)


    def __contains__(self, item):
        return item in self._definitions


    def __iter__(self):
        return iter(self._definitions)


    def to_string(self):
        return self.__str__()


    def __str__(self):
        s = [f'${self.name};\n']
        for a_definition in self.definitions.values():
            s.append(a_definition.to_string())

        # s.append('*\n')
        return ''.join(s)


    def __repr__(self):
        return f'<{self.__module__}.{self.__name__} {self._definitions.__repr__()} at {hex(id(self))})>'



class Vex:
    """Vex file parser.
    Vex opens and interprets a vexfile and stores it as an ordered dictionary
    containing the existing sections and options from the vex file. Vex not
    only interprets the information but also keeps all the comments existing
    in the original file.

    It can also write a new vexfile with the same information or after updating
    some of the information.

    A Vex file consists of a name (same as the filename without extension), a set
    of entries with the form 'key = value;' (or comments '* this is a comment line')
    and a set of sections with the form '$name;' that can contain a set of definitions
    or entries. The two later sets are optional at the beginning (i.e. an empty Vex file
    can be created with only a name).
    """
    def __init__(self, name, vexfile=None):
        self.name = name
        self._sections = _OrderedDict()
        self._number_comments = 0

        if vexfile is not None:
            self.from_file(vexfile)


    @property
    def sections(self):
        return self._sections


    @sections.setter
    def sections(self, new_sections):
        """A section can be either a Definition or an Entry (typically because it is a comment line)
        """
        self._sections = _OrderedDict()
        for new_section in new_sections:
            self.add_section(new_section)


    def add_section(self, a_section):
        """Add a new Section (or an Entry) to the sections in this Vex object.
        If new_section.name matches an existing section, the former one will be replaced.
        """
        if isinstance(a_section, Section) or isinstance(a_section, Definition):
            self._sections[a_section.name] = a_section
        elif isinstance(a_section, Entry):
            if a_section.type is EntryType.comment:
                self._number_comments += 1
                self._sections[f'comment-{self._number_comments}'] = a_section
            else:
                self._sections[a_section.key] = a_section
        else:
            raise ValueError('new_definition must be an instance of Section, Definition or Entry')


    def __getitem__(self, key):
        return self._sections[key]


    def __setitem__(self, key, value):
        self._sections[key] = value


    def __len__(self):
        return len(self._sections)


    def __delitem__(self, key):
        del self._sections[key]


    def has_key(self, key):
        return key in self._sections


    def keys(self):
        return self._sections.keys()


    def values(self):
        return self._sections.values()


    def items(self):
        return self._sections.items()


    def pop(self, *args):
        return self._sections.pop(*args)


    def __contains__(self, item):
        return item in self._sections


    def __iter__(self):
        return iter(self._sections)



    def to_string(self):
        return self.__str__()


    def __str__(self):
        s = []
        for a_section in self.sections.values():
            if isinstance(a_section, Entry):
                s.append(a_section.to_string(0))
            else:
                s.append(a_section.to_string())

        return ''.join(s)


    def to_file(self, filename, overwrite=True):
        """Save the current Vex object to a text file called filename.
        If overwrite is False and the file already exists, raises an Exception.
        """
        if (not overwrite) and (_os.path.exists(filename)):
            raise FileExistsError(f'{filename} exists and will not be overwrite')

        with open(filename, 'w') as newfile:
            newfile.write(self.to_string())


    def from_file(self, filename):
        """Read a vexfile and stores it in the current object. In case this Vex object
        had previous data, everything will be flushed and only the data from vexfile
        will be kept.
        """
        with open(filename, 'r') as vexfile:
            vexlines = vexfile.readlines()
            # In case of entries spread over multiple lines, this will be used to keep data:
            prev_line = None
            current_section = None
            current_definition = None
            literal = None
            for vexline in vexlines:
                currentline = vexline
                # print(currentline)
                if currentline.strip()[0] == '*':
                    if current_definition is not None:
                        current_definition.add_entry(Entry.entry_from_text(currentline))
                    elif current_section is not None:
                        current_section.add_definition(Entry.entry_from_text(currentline))
                    else:
                        self.add_section(Entry.entry_from_text(currentline))
                else:
                    # Checks if this is the full line, otherwise save it cumulatively
                    if ';' not in currentline:
                        if prev_line is None:
                            prev_line = _copy.copy(currentline)
                        else:
                            prev_line += _copy.copy(currentline)
                        continue

                    if prev_line is not None:
                        currentline = prev_line + currentline
                        prev_line = None

                    currentline = currentline.strip()
                    # Evaluates the different possible key words, starting with literals
                    if currentline.startswith("start_literal"):
                        rule = r"start_literal\((.*)\)"
                        literal = _re.findall(rule, currentline)[0].strip()
                    elif isinstance(literal, str) and "end_literal" in currentline:
                        i = currentline.find("end_literal")
                        if current_definition is not None:
                            current_definition.add_entry(
                                Entry.entry_literal(literal, currentline[:i]))
                            literal = None
                        else:
                            raise ValueError(
                                'A literal outside a definition')
                    elif currentline[0] == '$':
                        if current_section is not None:
                            # we just finished the prev. section and we are starting a new one
                            self.add_section(current_section)

                        current_section = Section(currentline[1:currentline.index(';')])
                    elif currentline[:4] == 'def ':
                        if current_definition is not None:
                            raise ValueError('A definition inside a definition is not supported')

                        current_definition = Definition(currentline[4:currentline.index(';')])
                    elif currentline[:6] == 'enddef':
                        if current_definition is None:
                            raise ValueError('enddef without a previous def')

                        current_section.add_definition(current_definition)
                        current_definition = None
                    elif currentline[:5] == 'scan ':
                        if current_definition is not None:
                            raise ValueError('A definition inside a definition is not supported')

                        current_definition = Scan(currentline[5:currentline.index(';')])
                    elif currentline[:7] == 'endscan':
                        if current_definition is None:
                            raise ValueError('endscan without a previous scan')

                        current_section.add_definition(current_definition)
                        current_definition = None
                    else:
                        # It is going to be an entry
                        if current_definition is not None:
                            current_definition.add_entry(Entry.entry_from_text(currentline))
                        elif current_section is not None:
                            current_section.add_definition(Entry.entry_from_text(currentline))
                        else:
                            self.add_section(Entry.entry_from_text(currentline))

            # End of the file, add the final section if exists
            if current_section is not None:
                self.add_section(current_section)
        return


# def Vex(file):
#     fp = open(file, 'r')
#     vex = fp.read()
#     fp.close()
#     return parse(vex.replace('\r\n', '\n'))


if __name__ == '__main__':
    print(Vex(_sys.argv[1]))
