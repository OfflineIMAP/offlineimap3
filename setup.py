#!/usr/bin/env python

# $Id: setup.py,v 1.1 2002/06/21 18:10:49 jgoerzen Exp $

# IMAP synchronization
# Module: installer
# COPYRIGHT #
# Copyright (C) 2002 - 2018 John Goerzen & contributors
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
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA

import re
try:
    from setuptools import setup, Command
except:
    from distutils.core import setup, Command


with open('offlineimap/__init__.py') as f:
    version_grp = re.search(r"__version__ = ['\"](.+)['\"]", f.read())
    if version_grp:
        version = version_grp.group(1)
    else:
        version = "0.0.0"

    f.seek(0)
    description_grp = re.search(r"__description__ = ['\"](.+)['\"]", f.read())
    if description_grp:
        description = description_grp.group(1)
    else:
        description = "Disconnected Universal IMAP Mail Synchronization/Reader Support"

    f.seek(0)
    author_grp = re.search(r"__author__ = ['\"](.+)['\"]", f.read())
    if author_grp:
        author = author_grp.group(1)
    else:
        author = "John Goerzen"

    f.seek(0)
    author_email_grp = re.search(r"__author_email__ = ['\"](.+)['\"]", f.read())
    if author_email_grp:
        author_email = author_email_grp.group(1)
    else:
        author_email = ""

    f.seek(0)
    homepage_grp = re.search(r"__homepage__ = ['\"](.+)['\"]", f.read())
    if homepage_grp:
        homepage = homepage_grp.group(1)
    else:
        homepage = "http://www.offlineimap.org"

    f.seek(0)
    copyright_grp = re.search(r"__copyright__ = ['\"](.+)['\"]", f.read())
    if copyright_grp:
        copyright = copyright_grp.group(1)
    else:
        copyright = ""


setup(name="offlineimap",
      version=version,
      description=description,
      long_description=description,
      author=author,
      author_email=author_email,
      url=homepage,
      packages=['offlineimap', 'offlineimap.folder',
                'offlineimap.repository', 'offlineimap.ui',
                'offlineimap.utils'],
      scripts=['bin/offlineimap'],
      setup_requires=['setuptools>=18.5', 'wheel', 'imaplib2'],
      license=copyright + ", Licensed under the GPL version 2",
      install_requires=['distro',
                        'imaplib2>=3.5',
                        'rfc6555',
                        'urllib3~=1.25.9'],
      extras_require={'kerberos':'gssapi[kerberos]',
                      'keyring':'keyring[keyring]',
                      'cygwin':'portalocker[cygwin]',
                      'testinternet':'certifi~=2020.6.20'}
      )

