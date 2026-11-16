"""`python3 backend snapshot`: read-only, one clean line on any expected failure."""
import importlib.util
import io
import os
import unittest
from unittest import mock

import support
from hue_backend import bridge
from hue_backend.credentials import Credentials

_spec = importlib.util.spec_from_file_location(
    "hue_main", os.path.join(support.HERE, "..", "backend", "__main__.py"))
main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(main)


class Client:
    def __init__(self, outcome):
        self.outcome, self.closed = outcome, False

    def resources(self):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def close(self):
        self.closed = True


class Snapshot(unittest.TestCase):
    def run_with(self, outcome, creds=Credentials("1.2.3.4", "KEY")):
        self.client = Client(outcome)
        out, err = io.StringIO(), io.StringIO()
        code = main.snapshot(load_credentials=lambda: creds, client_factory=lambda c: self.client, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_prints_the_snapshot_without_secrets(self):
        code, out, err = self.run_with(support.fixture())
        self.assertEqual((code, err), (0, ""))
        self.assertIn('"lights"', out)
        self.assertNotIn("KEY", out)
        self.assertTrue(self.client.closed)

    def test_not_paired(self):
        code, out, err = self.run_with([], creds=None)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("not paired", err)

    def test_expected_failures_are_one_line_and_close_the_client(self):
        cases = [(bridge.BridgeError("unreachable", "cannot reach the bridge (OSError)"), 1),
                 (KeyboardInterrupt(), 130),
                 (ValueError("odd payload"), 1)]
        for exc, want in cases:
            code, out, err = self.run_with(exc)
            self.assertEqual((code, out), (want, ""), exc)
            self.assertEqual(err.count("\n"), 1, err)
            self.assertTrue(err.startswith("hue: "), err)
            self.assertNotIn("Traceback", err)
            self.assertTrue(self.client.closed)

    def test_a_closed_pipe_is_quiet(self):
        class Gone(io.StringIO):
            def write(self, s):
                raise BrokenPipeError()

        self.client, err = Client(support.fixture()), io.StringIO()
        code = main.snapshot(load_credentials=lambda: Credentials("1.2.3.4", "KEY"),
                             client_factory=lambda c: self.client, out=Gone(), err=err)
        self.assertEqual((code, err.getvalue()), (0, ""))
        self.assertTrue(self.client.closed)


if __name__ == "__main__":
    unittest.main()


class Usage(unittest.TestCase):
    def test_an_unknown_command_prints_usage_without_touching_the_log(self):
        err = io.StringIO()
        with mock.patch.object(main.paths, "setup_logging") as setup, mock.patch.object(main.sys, "stderr", err):
            self.assertEqual(main.main(["bogus"]), 2)
        setup.assert_not_called()  # no log directory is created for a typo
        self.assertIn("usage:", err.getvalue())
