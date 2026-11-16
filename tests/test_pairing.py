"""Pairing: the link-button flow, cloud discovery and first-contact fingerprints, against fakes and a local TLS server."""
import http.server
import inspect
import io
import json
import shutil
import tempfile
import threading
import unittest
from unittest import mock

import support  # noqa: F401
from hue_backend import bridge, credentials, pairing
from test_bridge import make_certificate, start_tls_server


class Reply:
    def __init__(self, payload):
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._raw


class FakeConn:
    """Answers each POST with the next scripted reply; `observed` is the certificate it 'saw'."""

    def __init__(self, replies, observed="c" * 64):
        self.replies, self.observed = list(replies), observed
        self.bodies, self.pins, self.closed = [], [], 0

    def __call__(self, host, fingerprint, timeout):
        self.pins.append(fingerprint)
        return self

    def request(self, method, path, body=None, headers=None):
        self.bodies.append((method, path, json.loads(body)))
        nxt = self.replies.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        self._reply = nxt

    def getresponse(self):
        return self._reply

    def close(self):
        self.closed += 1


def run_link(conn, **kw):
    progress = []
    creds = pairing.link_button("10.0.0.7", threading.Event(), progress.append, connection_factory=conn,
                                sleep=lambda s: None, **kw)
    return creds, progress


class LinkButton(unittest.TestCase):
    def test_device_type_is_generic_and_never_the_hostname(self):
        self.assertEqual(pairing.DEVICE_TYPE, "omarchy-hue#desktop")
        conn = FakeConn([Reply([{"success": {"username": "abc-123"}}])])
        with mock.patch("socket.gethostname", return_value="alices-laptop"):
            run_link(conn)
        method, path, body = conn.bodies[0]
        self.assertEqual((method, path), ("POST", "/api"))
        self.assertEqual(body, {"devicetype": "omarchy-hue#desktop"})  # no hostname, no unused client key

    def test_waits_for_the_button_then_pins_what_it_saw(self):
        not_pressed = Reply([{"error": {"type": 101, "description": "link button not pressed"}}])
        conn = FakeConn([not_pressed, not_pressed, Reply([{"success": {"username": "abc-123"}}])])
        creds, progress = run_link(conn)
        self.assertEqual((creds.host, creds.key, creds.fingerprint), ("10.0.0.7", "abc-123", "c" * 64))
        self.assertEqual(len(progress), 3)
        self.assertEqual(conn.closed, 3)
        self.assertEqual(conn.pins, ["", "", ""])

    def test_the_default_connection_is_the_explicit_first_contact_one(self):
        default = inspect.signature(pairing.link_button).parameters["connection_factory"].default
        self.assertIs(default, bridge.FirstContactConnection)

    def test_odd_replies_fail_as_bridge_errors_not_crashes(self):
        for payload in ([1], [None], {"x": 1}, [], [{"success": "x"}], [{"success": {"username": "has space"}}],
                        [{"error": "nope"}], [{"error": {"type": 7, "description": "invalid value"}}], b"<html>"):
            with self.assertRaises(bridge.BridgeError, msg=payload) as cm:
                run_link(FakeConn([Reply(payload)]))
            self.assertEqual(cm.exception.code, "bridge_error", payload)

    def test_a_reply_without_a_certificate_is_not_saved(self):
        with self.assertRaises(bridge.BridgeError):
            run_link(FakeConn([Reply([{"success": {"username": "abc"}}])], observed=""))

    def test_transport_failures_are_unreachable(self):
        with self.assertRaises(bridge.BridgeError) as cm:
            run_link(FakeConn([ConnectionRefusedError()]))
        self.assertEqual(cm.exception.code, "unreachable")

    def test_timeout_and_cancel(self):
        with self.assertRaises(bridge.BridgeError) as cm:
            run_link(FakeConn([]), timeout=0)
        self.assertEqual(cm.exception.code, "timeout")
        stop = threading.Event()
        stop.set()
        with self.assertRaises(bridge.BridgeError) as cm:
            pairing.link_button("10.0.0.7", stop, lambda s: None, connection_factory=FakeConn([]))
        self.assertEqual(cm.exception.code, "cancelled")


class Discovery(unittest.TestCase):
    def discover(self, payload):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(raw)) as opener:
            found = pairing.discover_cloud()
        self.assertEqual(opener.call_args[0][0].full_url, pairing.DISCOVERY_URL)
        return found

    def test_only_private_and_link_local_ipv4_addresses_are_kept(self):
        rows = [{"id": "a", "internalipaddress": "192.168.1.5"}, {"id": "b", "internalipaddress": "10.1.2.3"},
                {"id": "c", "internalipaddress": "172.20.0.9"}, {"id": "d", "internalipaddress": "169.254.3.4"}]
        junk = [{"id": "e", "internalipaddress": "8.8.8.8"}, {"id": "f", "internalipaddress": "evil.example"},
                {"id": "g", "internalipaddress": "127.0.0.1"}, {"id": "h", "internalipaddress": "fe80::1"},
                {"id": "i", "internalipaddress": "192.168.1.5\n"}, {"id": "j", "internalipaddress": "172.32.0.1"},
                {"id": "k", "internalipaddress": "0.0.0.0"}, {"id": "l"}, "x", 5]
        found = self.discover(rows + junk)
        self.assertEqual([b["host"] for b in found], ["192.168.1.5", "10.1.2.3", "172.20.0.9", "169.254.3.4"])
        self.assertEqual(found[0], {"id": "a", "host": "192.168.1.5"})

    def test_an_unexpected_payload_finds_nothing(self):
        self.assertEqual(self.discover({"internalipaddress": "10.0.0.1"}), [])

    def test_failures_are_unreachable(self):
        for exc in (OSError("down"),):
            with mock.patch("urllib.request.urlopen", side_effect=exc):
                with self.assertRaises(bridge.BridgeError) as cm:
                    pairing.discover_cloud()
            self.assertEqual(cm.exception.code, "unreachable")
        with self.assertRaises(bridge.BridgeError):
            self.discover(b"not json")


@unittest.skipUnless(shutil.which("openssl"), "openssl is needed to make a test certificate")
class AgainstATlsServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        key, crt, cls.fingerprint = make_certificate(cls.dir)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                body = json.dumps([{"success": {"username": "NEWKEY"}}]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        cls.server = start_tls_server(Handler, key, crt)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_fetch_fingerprint_reads_the_presented_certificate(self):
        self.assertEqual(credentials.fetch_fingerprint("127.0.0.1", port=self.port), self.fingerprint)

    def test_link_button_pairs_on_first_contact_and_pins_the_real_certificate(self):
        port = self.port

        class Local(bridge.FirstContactConnection):
            def __init__(self, host, fingerprint, timeout):
                super().__init__(host, fingerprint, timeout)
                self.port = port

        creds = pairing.link_button("127.0.0.1", threading.Event(), lambda s: None, connection_factory=Local)
        self.assertEqual((creds.key, creds.fingerprint), ("NEWKEY", self.fingerprint))


if __name__ == "__main__":
    unittest.main()
