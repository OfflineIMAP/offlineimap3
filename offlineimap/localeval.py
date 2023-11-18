"""Eval python code with global namespace of a python source file."""

# Copyright (C) 2002-2016 John Goerzen & contributors
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA

import importlib.util


class LocalEval:
    """Here is a powerfull but very dangerous option, of course."""

    def __init__(self, path=None):
        self.namespace = {}

        if path is not None:
            # FIXME: limit opening files owned by current user with rights set
            # to fixed mode 644.
            spec = importlib.util.spec_from_file_location('<none>', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for attr in dir(module):
                self.namespace[attr] = getattr(module, attr)

    def eval(self, text, namespace=None):
        names = {}
        names.update(self.namespace)
        if namespace is not None:
            names.update(namespace)
        return eval(text, names)
