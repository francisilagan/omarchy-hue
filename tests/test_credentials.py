import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401
from hue_backend import credentials


class OpenhueImport(unittest.TestCase):
    def test_reads_flat_config(self):
        c = credentials.parse_openhue("bridge: 192.168.1.9\nkey: abc123\n")
        self.assertEqual((c.host, c.key), ("192.168.1.9", "abc123"))

    def test_ignores_indented_and_commented_keys(self):
        text = "other:\n  key: nested\nbridge: 10.0.0.2  # home\nkey: 'real'\n"
        c = credentials.parse_openhue(text)
        self.assertEqual((c.host, c.key), ("10.0.0.2", "real"))

    def test_missing_or_bad_values_give_none(self):
        self.assertIsNone(credentials.parse_openhue("bridge: 10.0.0.2\n"))
        self.assertIsNone(credentials.parse_openhue("key: abc\n"))
        self.assertIsNone(credentials.parse_openhue("bridge: not a host!\nkey: k\n"))
        self.assertIsNone(credentials.parse_openhue("key: |\nbridge: 1.2.3.4\n"))

    def test_host_validation(self):
        for ok in ("192.168.1.2", "hue.local", "fe80::1"):
            self.assertTrue(credentials.valid_host(ok), ok)
        for bad in ("", "a b", "x/y", "http://1.2.3.4", "1.2.3.4:443/path", "1.2.3.4\n", "fe80::1\n", None, 5):
            self.assertFalse(credentials.valid_host(bad), bad)


class Store(unittest.TestCase):
    def test_saved_credentials_are_private_and_round_trip(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home}):
            creds = credentials.Credentials("1.2.3.4", "SECRET", "bid", "f" * 64)
            credentials.save(creds)
            p = credentials.path()
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(p.parent.stat().st_mode), 0o700)
            self.assertEqual(credentials.load(), creds)
            credentials.forget()
            self.assertIsNone(credentials.load())

    def test_a_file_without_a_pin_still_loads_so_the_user_can_trust(self):
        # The connection layer refuses the empty pin (cert_changed); `pair.trust` needs host and key.
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home}):
            credentials.save(credentials.Credentials("1.2.3.4", "SECRET"))
            self.assertEqual(credentials.load().fingerprint, "")

    def test_corrupt_file_is_treated_as_unpaired(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home}):
            p = credentials.path()
            p.parent.mkdir(parents=True)
            p.write_text("{not json")
            self.assertIsNone(credentials.load())


if __name__ == "__main__":
    unittest.main()
