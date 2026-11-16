import hashlib
import http.server
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest

import support  # noqa: F401
from hue_backend import bridge
from hue_backend.credentials import Credentials


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class RateLimiting(unittest.TestCase):
    def test_burst_then_paced(self):
        c = Clock()
        lim = bridge.RateLimiter(rate=2.0, burst=2, clock=c.now, sleep=c.sleep)
        for _ in range(2):
            lim.acquire()
        self.assertEqual(c.slept, [])
        lim.acquire()
        self.assertAlmostEqual(sum(c.slept), 0.5, places=3)  # one token at 2/s

    def test_tokens_refill_over_time(self):
        c = Clock()
        lim = bridge.RateLimiter(rate=1.0, burst=1, clock=c.now, sleep=c.sleep)
        lim.acquire()
        c.t += 5
        lim.acquire()
        self.assertEqual(c.slept, [])


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._raw


class FakeConn:
    """Scripted connection: each request pops the next step (a response or an exception)."""

    def __init__(self, steps):
        self.steps = steps
        self.requests = []
        self.observed = ""
        self.closed = 0

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))
        self._next = self.steps.pop(0)
        if isinstance(self._next, BaseException):
            raise self._next

    def getresponse(self):
        return self._next

    def close(self):
        self.closed += 1


def client_with(steps):
    conn = FakeConn(steps)
    c = bridge.BridgeClient(Credentials("1.2.3.4", "KEY"), sleep=lambda s: None, connection_factory=lambda *a: conn)
    return c, conn


class Client(unittest.TestCase):
    def test_success_returns_data_and_sends_the_key_header(self):
        c, conn = client_with([FakeResponse(200, {"data": [{"id": "x"}], "errors": []})])
        self.assertEqual(c.request("GET", "resource").data, [{"id": "x"}])
        self.assertEqual(conn.requests[0][3]["hue-application-key"], "KEY")
        self.assertEqual(conn.requests[0][1], "/clip/v2/resource")

    def test_partial_success_is_ok_with_warnings(self):
        # HTTP 207: applied, but the bridge warns (e.g. a bulb switched off at the wall).
        c, _ = client_with([FakeResponse(207, {"data": [{"rid": "a"}], "errors": [{"description": "device has communication issues"}]})])
        reply = c.request("PUT", "resource/light/x", {"on": {"on": True}})
        self.assertEqual(reply.warnings, ["device has communication issues"])

    def test_errors_without_data_fail_with_the_bridges_text(self):
        c, _ = client_with([FakeResponse(400, {"data": [], "errors": [{"description": "invalid value"}]})])
        with self.assertRaises(bridge.BridgeError) as cm:
            c.request("PUT", "resource/light/x", {})
        self.assertEqual((cm.exception.code, cm.exception.message), ("bridge_error", "invalid value"))

    def test_revoked_key_is_unauthorized(self):
        for status in (401, 403):
            c, _ = client_with([FakeResponse(status, {})])
            with self.assertRaises(bridge.BridgeError) as cm:
                c.request("GET", "resource")
            self.assertEqual(cm.exception.code, "unauthorized")

    def test_busy_bridge_is_retried_then_succeeds(self):
        c, conn = client_with([FakeResponse(429, {}), FakeResponse(503, {}), FakeResponse(200, {"data": [{"id": "x"}]})])
        self.assertEqual(c.request("GET", "resource").data, [{"id": "x"}])
        self.assertEqual(len(conn.requests), 3)

    def test_busy_bridge_gives_up_as_rate_limited(self):
        c, _ = client_with([FakeResponse(429, {}) for _ in range(6)])
        with self.assertRaises(bridge.BridgeError) as cm:
            c.request("GET", "resource")
        self.assertEqual(cm.exception.code, "rate_limited")

    def test_dropped_keepalive_connection_is_retried_once_for_idempotent_calls(self):
        c, conn = client_with([ConnectionResetError(), FakeResponse(200, {"data": []})])
        c.request("PUT", "resource/light/x", {"on": {"on": True}})
        self.assertEqual(len(conn.requests), 2)

    def test_post_is_never_replayed(self):
        c, conn = client_with([ConnectionResetError(), FakeResponse(200, {"data": []})])
        with self.assertRaises(bridge.BridgeError) as cm:
            c.request("POST", "resource/scene", {})
        self.assertEqual(cm.exception.code, "unreachable")
        self.assertEqual(len(conn.requests), 1)

    def test_timeout_has_its_own_code(self):
        c, _ = client_with([TimeoutError(), TimeoutError()])
        with self.assertRaises(bridge.BridgeError) as cm:
            c.request("GET", "resource")
        self.assertEqual(cm.exception.code, "timeout")

    def test_non_json_reply_is_a_bridge_error_not_a_crash(self):
        c, _ = client_with([FakeResponse(200, b"<html>")])
        with self.assertRaises(bridge.BridgeError) as cm:
            c.request("GET", "resource")
        self.assertEqual(cm.exception.code, "bridge_error")

    def test_a_reply_that_is_not_an_object_is_a_bridge_error(self):
        # A JSON array (or a `data` that is not a list) used to escape as AttributeError.
        for payload in ([1], "text", {"data": {"id": "x"}}, {"data": [], "errors": "boom"}, {"data": [1, {"id": "a"}]}):
            c, _ = client_with([FakeResponse(200, payload)])
            try:
                reply = c.request("GET", "resource")
            except bridge.BridgeError as exc:
                self.assertEqual(exc.code, "bridge_error", payload)
            else:
                self.assertTrue(all(isinstance(d, dict) for d in reply.data), payload)

    def test_keyboard_interrupt_propagates_and_drops_the_connection(self):
        for exc in (KeyboardInterrupt(), SystemExit(1)):
            c, conn = client_with([exc, FakeResponse(200, {"data": []})])
            with self.assertRaises(type(exc)):
                c.request("PUT", "resource/light/x", {})
            self.assertEqual(conn.closed, 1)
            self.assertIsNone(c._conn)
            self.assertEqual(len(conn.requests), 1)  # not retried, not classified

    def test_unexpected_errors_still_become_internal_bridge_errors(self):
        c, conn = client_with([RuntimeError("boom")])
        with self.assertRaises(bridge.BridgeError) as cm:
            c.request("GET", "resource")
        self.assertEqual(cm.exception.code, "internal")
        self.assertEqual(conn.closed, 1)


class StreamFailures(unittest.TestCase):
    def stream_with(self, exc):
        conn = FakeConn([exc])
        conn.sock = None
        return bridge.EventStream(Credentials("1.2.3.4", "KEY"), connection_factory=lambda *a: conn), conn

    def test_keyboard_interrupt_propagates_and_closes_the_stream(self):
        stream, conn = self.stream_with(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            stream.run(threading.Event(), lambda batch: None)
        self.assertEqual(conn.closed, 1)

    def test_a_dropped_stream_is_classified(self):
        stream, conn = self.stream_with(ConnectionResetError())
        with self.assertRaises(bridge.BridgeError) as cm:
            stream.run(threading.Event(), lambda batch: None)
        self.assertEqual(cm.exception.code, "unreachable")
        self.assertEqual(conn.closed, 1)

    def test_a_quiet_open_stream_is_idle_not_a_timeout(self):
        class Resp:
            status = 200

            def readline(self):
                raise socket.timeout("timed out")

        conn = FakeConn([Resp()])
        conn.sock = None
        stream = bridge.EventStream(Credentials("1.2.3.4", "KEY", fingerprint="f" * 64), connection_factory=lambda *a: conn)
        with self.assertRaises(bridge.BridgeError) as cm:
            stream.run(threading.Event(), lambda batch: None)
        self.assertEqual(cm.exception.code, "idle")

    def test_a_timeout_before_the_stream_opens_is_still_a_timeout(self):
        stream, _ = self.stream_with(socket.timeout("timed out"))
        with self.assertRaises(bridge.BridgeError) as cm:
            stream.run(threading.Event(), lambda batch: None)
        self.assertEqual(cm.exception.code, "timeout")

    def test_a_failure_after_stop_is_quiet(self):
        stream, _ = self.stream_with(ConnectionResetError())
        stop = threading.Event()
        stop.set()
        stream.run(stop, lambda batch: None)  # no exception


def make_certificate(directory):
    """A throwaway self-signed certificate: (key path, cert path, sha256 fingerprint)."""
    key, crt = os.path.join(directory, "k.pem"), os.path.join(directory, "c.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
                    "-subj", "/CN=bridge", "-days", "1"], check=True, capture_output=True)
    with open(crt) as f:
        return key, crt, hashlib.sha256(ssl.PEM_cert_to_DER_cert(f.read())).hexdigest()


def start_tls_server(handler, key, crt):
    """A threaded HTTPS server on 127.0.0.1 (random port) using `handler`; returns the server."""
    class Quiet(http.server.ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):  # a client that aborts the handshake is expected here
            pass

    srv = Quiet(("127.0.0.1", 0), handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@unittest.skipUnless(shutil.which("openssl"), "openssl is needed to make a test certificate")
class Pinning(unittest.TestCase):
    """The real TLS path against a local server with a self-signed certificate."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        key, crt, cls.fingerprint = make_certificate(cls.dir)
        cls.seen = []
        seen = cls.seen

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("hue-application-key")))
                if self.path.startswith("/eventstream"):  # an open stream with nothing to say
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.flush()
                    threading.Event().wait(10)
                    return
                body = json.dumps({"data": [{"id": "a", "type": "light"}], "errors": []}).encode()
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

    def factory(self):
        port = self.port
        return lambda host, fp, timeout: _port_conn(host, fp, timeout, port)

    def test_matching_fingerprint_connects(self):
        c = bridge.BridgeClient(Credentials("127.0.0.1", "K", fingerprint=self.fingerprint), connection_factory=self.factory())
        self.addCleanup(c.close)
        self.assertEqual(c.request("GET", "resource").data[0]["id"], "a")
        self.assertEqual(c.observed_fingerprint, self.fingerprint)

    def test_different_certificate_is_refused_as_cert_changed(self):
        c = bridge.BridgeClient(Credentials("127.0.0.1", "K", fingerprint="0" * 64), connection_factory=self.factory())
        with self.assertRaises(bridge.BridgeError) as cm:
            c.request("GET", "resource")
        self.assertEqual(cm.exception.code, "cert_changed")

    def test_closing_a_blocked_event_stream_from_another_thread_returns_promptly(self):
        stream = bridge.EventStream(Credentials("127.0.0.1", "K", fingerprint=self.fingerprint), connection_factory=self.factory())
        stop, done = threading.Event(), threading.Event()
        outcome = []

        def run():
            try:
                stream.run(stop, lambda batch: None)
            except bridge.BridgeError as exc:
                outcome.append(exc.code)
            done.set()

        threading.Thread(target=run, daemon=True).start()
        threading.Event().wait(0.4)  # the stream is now blocked reading
        stop.set()
        stream.close()
        self.assertTrue(done.wait(2), "run() did not return after close()")

    def test_first_contact_records_what_was_seen(self):
        conn = _port_conn("127.0.0.1", "", 5, self.port, bridge.FirstContactConnection)
        conn.request("GET", "/clip/v2/resource")
        conn.getresponse().read()
        self.assertEqual(conn.observed, self.fingerprint)
        conn.close()

    def test_an_empty_pin_is_refused_before_the_key_is_sent(self):
        # A bridge.json without a fingerprint must not fail open to whatever answers.
        del self.seen[:]
        c = bridge.BridgeClient(Credentials("127.0.0.1", "SECRETKEY", fingerprint=""), connection_factory=self.factory())
        self.addCleanup(c.close)
        with self.assertRaises(bridge.BridgeError) as cm:
            c.request("GET", "resource")
        self.assertEqual(cm.exception.code, "cert_changed")
        stream = bridge.EventStream(Credentials("127.0.0.1", "SECRETKEY", fingerprint=""), connection_factory=self.factory())
        with self.assertRaises(bridge.BridgeError) as cm:
            stream.run(threading.Event(), lambda batch: None)
        self.assertEqual(cm.exception.code, "cert_changed")
        threading.Event().wait(0.1)
        self.assertEqual(self.seen, [])  # nothing, the key least of all, reached the server

    def test_plain_connections_refuse_an_empty_pin_even_without_a_client(self):
        conn = _port_conn("127.0.0.1", "", 5, self.port)
        with self.assertRaises(bridge.BridgeError) as cm:
            conn.connect()
        self.assertEqual(cm.exception.code, "cert_changed")
        conn.close()


def _port_conn(host, fp, timeout, port, cls=bridge.PinnedConnection):
    conn = cls(host, fp, timeout)
    conn.port = port
    return conn


if __name__ == "__main__":
    unittest.main()
