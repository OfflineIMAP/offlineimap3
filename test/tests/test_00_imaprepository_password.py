#!/usr/bin/env python

import os
import tempfile
import unittest

from offlineimap import OfflineImapError
from offlineimap.repository.IMAP import IMAPRepository


class DummyRepository(object):
    def __init__(self, values):
        self.values = values
        self.name = 'Remote'

    def getconf(self, name, default=None):
        return self.values.get(name, default)


class TestIMAPRepositoryGetPassword(unittest.TestCase):
    def test_remotepassfile_missing_raises_offlineimaperror(self):
        repo = DummyRepository({'remotepassfile': '/definitely/missing/password'})

        with self.assertRaises(OfflineImapError) as ctx:
            IMAPRepository.getpassword(repo)

        self.assertIn('Unable to read remotepassfile', str(ctx.exception))

    def test_remotepassfile_reads_first_line(self):
        with tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8') as fd:
            fd.write('mysecret\nsecondline\n')
            passfile = fd.name

        try:
            repo = DummyRepository({'remotepassfile': passfile})
            self.assertEqual('mysecret', IMAPRepository.getpassword(repo))
        finally:
            os.unlink(passfile)


if __name__ == '__main__':
    unittest.main()
