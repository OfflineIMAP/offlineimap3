import base64
import unittest

from offlineimap.folder.Base import BaseFolder


class _UI:
    def debug(self, *args, **kw):
        pass

    def warn(self, *args, **kw):
        pass


class _Config:
    def getdefaultboolean(self, section, key, default):
        return default


class _Repository:
    name = 'test'
    newmail_hook = None

    def nametrans(self, name):
        return name

    def getconfig(self):
        return _Config()

    def should_sync_folder(self, name):
        return True


DEFECTIVE_MAIL = (
    b"From: a@b.c\nTo: d@e.f\nSubject: test\nMIME-Version: 1.0\n"
    b"Content-Type: multipart/mixed; boundary=\"AAAA\"\n\n"
    b"--AAAA\nContent-Type: message/rfc822\n\n"
    b"From: inner@x.y\nTo: outer@z.w\nSubject: inner\nMIME-Version: 1.0\n"
    b"Content-Type: multipart/mixed; boundary=\"BBBB\"\n\n"
    b"Body with non-ascii: caf\xc3\xa9\n--BBBB--\n--AAAA--\n"
)


class _TestFolder(BaseFolder):
    sep = '/'


class TestMessageDefects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from offlineimap.ui import setglobalui

        setglobalui(_UI())
        cls.folder = _TestFolder('test', _Repository())
        cls.parser = cls.folder.parser['8bit']
        cls.policy = cls.folder.policy['8bit']

    def test_nested_defects_are_repaired(self):
        """Defects on nested message/rfc822 parts must not break
        serialization; the body content must be preserved."""
        message = self.parser.parsebytes(DEFECTIVE_MAIL)
        repaired = self.folder._repair_message_defects(
            message, self.parser, DEFECTIVE_MAIL, self.policy, '1')
        repaired.as_bytes(policy=self.policy)
        inner = repaired.get_payload(0).get_payload(0)
        self.assertEqual(
            base64.b64decode(inner.get_payload()),
            b'Body with non-ascii: caf\xc3\xa9\n')

    def test_clean_message_unchanged(self):
        message = self.parser.parsebytes(
            b"From: a@b.c\nTo: d@e.f\nSubject: test\n"
            b"Content-Type: text/plain\n\nhello\n")
        result = self.folder._repair_message_defects(
            message, self.parser, DEFECTIVE_MAIL, self.policy, '1')
        self.assertIs(result, message)


if __name__ == '__main__':
    unittest.main()
