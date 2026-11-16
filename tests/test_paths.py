"""The log file stays owner-only across rotations."""
import logging
import os
import stat
import tempfile
import unittest

import support  # noqa: F401
from hue_backend import paths


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class PrivateLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        old = os.umask(0o022)  # the usual umask: plain open() would make 0644 files
        self.addCleanup(os.umask, old)
        self.path = os.path.join(self.dir.name, "hue.log")

    def handler(self):
        h = paths.PrivateRotatingFileHandler(self.path, maxBytes=200, backupCount=2, encoding="utf-8")
        self.addCleanup(h.close)
        return h

    def test_the_log_and_every_backup_are_0600_after_rollovers(self):
        h = self.handler()
        for i in range(40):
            h.emit(logging.LogRecord("hue", logging.INFO, __file__, 1, "line %d %s", (i, "x" * 40), None))
        names = sorted(os.listdir(self.dir.name))
        self.assertEqual(names, ["hue.log", "hue.log.1", "hue.log.2"])  # it did roll over
        for name in names:
            self.assertEqual(mode(os.path.join(self.dir.name, name)), 0o600, name)

    def test_an_existing_loose_log_is_tightened(self):
        for name in ("hue.log", "hue.log.1"):
            with open(os.path.join(self.dir.name, name), "w") as f:
                f.write("old\n")
            os.chmod(os.path.join(self.dir.name, name), 0o644)
        h = self.handler()
        self.assertEqual(mode(self.path), 0o600)
        h.doRollover()
        for name in os.listdir(self.dir.name):
            self.assertEqual(mode(os.path.join(self.dir.name, name)), 0o600, name)


if __name__ == "__main__":
    unittest.main()
