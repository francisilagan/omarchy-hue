"""Talking to a Hue bridge: pinned TLS, one kept-alive connection, rate limits, the event stream."""
from __future__ import annotations

import hashlib
import http.client
import json
import logging
import socket
import ssl
import threading
import time
from typing import Callable, List, NamedTuple, Optional

from .credentials import Credentials

log = logging.getLogger("hue")

# Documented limits: about 10 commands a second to lights, about 1 a second to groups.
LIGHT_RATE, LIGHT_BURST = 8.0, 4
GROUP_RATE, GROUP_BURST = 1.0, 2


class BridgeError(Exception):
    """Failure with a machine-readable code (see PROTOCOL.md, result codes)."""

    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class Reply(NamedTuple):
    """A successful API reply: its `data` items and any bridge warnings."""

    data: List[dict]
    warnings: List[str]


class RateLimiter:
    """Token bucket. `acquire` blocks until a token is available."""

    def __init__(self, rate: float, burst: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.rate, self.burst = rate, float(burst)
        self._tokens = float(burst)
        self._clock, self._sleep = clock, sleep
        self._last = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Take one token, sleeping until the bucket has one."""
        while True:
            with self._lock:
                now = self._clock()
                self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate
            self._sleep(wait)


class PinnedConnection(http.client.HTTPSConnection):
    """HTTPS to a bridge whose certificate must match a pinned fingerprint.

    Bridges use a private CA, so normal chain validation cannot work. Instead
    the certificate's fingerprint is recorded at pairing and required on every
    connection. An empty pin is refused as `cert_changed` before anything is
    sent: only the explicit first-contact path (`FirstContactConnection`,
    used by link-button pairing) may talk to an unpinned bridge.
    """

    first_contact = False

    def __init__(self, host: str, fingerprint: str, timeout: float):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        super().__init__(host, 443, timeout=timeout, context=ctx)
        self.pin = fingerprint
        self.observed = ""

    def connect(self) -> None:
        """Connect, record the certificate fingerprint, and refuse a missing or different pin as cert_changed."""
        if not self.pin and not self.first_contact:
            raise BridgeError("cert_changed", "no certificate is pinned for this bridge; trust it to continue")
        super().connect()
        der = self.sock.getpeercert(binary_form=True)  # type: ignore[union-attr]
        self.observed = hashlib.sha256(der or b"").hexdigest()
        if self.pin and self.observed != self.pin:
            self.close()
            raise BridgeError("cert_changed", "the bridge's certificate is not the one that was trusted")


class FirstContactConnection(PinnedConnection):
    """Trust on first use: connects to an unpinned bridge and exposes what it saw as `observed`.

    Only for link-button pairing, which records `observed` as the pin. A pin,
    when given, is still enforced.
    """

    first_contact = True


def _classify(exc: Exception) -> BridgeError:
    """Map a transport failure to a BridgeError with a protocol result code."""
    if isinstance(exc, BridgeError):
        return exc
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return BridgeError("timeout", "the bridge did not answer in time")
    if isinstance(exc, ssl.SSLError):
        return BridgeError("unreachable", "TLS error talking to the bridge: %s" % exc.__class__.__name__)
    if isinstance(exc, (OSError, http.client.HTTPException)):
        return BridgeError("unreachable", "cannot reach the bridge (%s)" % exc.__class__.__name__)
    return BridgeError("internal", "%s: %s" % (exc.__class__.__name__, exc))


class BridgeClient:
    """Thread-safe request/response client with a kept-alive connection."""

    def __init__(self, creds: Credentials, timeout: float = 10.0,
                 sleep: Callable[[float], None] = time.sleep,
                 connection_factory: Optional[Callable[..., PinnedConnection]] = None):
        self.creds = creds
        self.timeout = timeout
        self._sleep = sleep
        self._factory = connection_factory or PinnedConnection
        self._conn: Optional[PinnedConnection] = None
        self._lock = threading.Lock()
        self._limits = {"light": RateLimiter(LIGHT_RATE, LIGHT_BURST), "group": RateLimiter(GROUP_RATE, GROUP_BURST)}

    @property
    def observed_fingerprint(self) -> str:
        """The fingerprint the current connection saw ('' when not connected)."""
        return self._conn.observed if self._conn else ""

    def close(self) -> None:
        """Close the kept-alive connection; the next request opens a new one."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def _connection(self) -> PinnedConnection:
        """The kept-alive connection, opened on first use. Call with the lock held."""
        if self._conn is None:
            self._conn = self._factory(self.creds.host, self.creds.fingerprint, self.timeout)
        return self._conn

    def request(self, method: str, path: str, body: Optional[dict] = None, klass: str = "") -> Reply:
        """One API call. `klass` ('light'/'group') selects the rate limit.

        Raises BridgeError. A reply that carries `data` plus `errors` is a
        success with warnings, not a failure.
        """
        if klass in self._limits:
            self._limits[klass].acquire()
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"hue-application-key": self.creds.key}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        attempts = 0
        while True:
            attempts += 1
            try:
                with self._lock:
                    conn = self._connection()
                    done = False
                    try:
                        conn.request(method, "/clip/v2/" + path.lstrip("/"), body=payload, headers=headers)
                        resp = conn.getresponse()
                        raw = resp.read()
                        status = resp.status
                        done = True
                    finally:
                        if not done:  # any failure, KeyboardInterrupt included: never reuse a half-used socket
                            conn.close()
                            self._conn = None
            except Exception as exc:  # noqa: BLE001 - classified below; KeyboardInterrupt/SystemExit propagate
                err = _classify(exc)
                # A kept-alive socket the bridge dropped: one retry on a fresh connection.
                # POST is not idempotent (could create twice), so it is never replayed.
                if err.code == "unreachable" and attempts == 1 and method != "POST":
                    continue
                raise err from None
            if status in (429, 503) and attempts <= 3:
                self._sleep(0.5 * attempts)
                continue
            return self._interpret(status, raw)

    @staticmethod
    def _interpret(status: int, raw: bytes) -> Reply:
        """Turn an HTTP status and body into a Reply, or raise the matching BridgeError."""
        if status in (401, 403):
            raise BridgeError("unauthorized", "the bridge rejected the application key", status)
        if status in (429, 503):
            raise BridgeError("rate_limited", "the bridge is busy, try again", status)
        try:
            payload = json.loads(raw.decode() or "{}")
        except ValueError:
            raise BridgeError("bridge_error", "the bridge sent a reply that is not JSON (HTTP %d)" % status, status) from None
        if not isinstance(payload, dict):
            raise BridgeError("bridge_error", "the bridge sent an unexpected reply (HTTP %d)" % status, status)
        data = payload.get("data") or []
        raw_errors = payload.get("errors") or []
        if not isinstance(data, list) or not isinstance(raw_errors, list):
            raise BridgeError("bridge_error", "the bridge sent an unexpected reply (HTTP %d)" % status, status)
        data = [d for d in data if isinstance(d, dict)]
        errors = [str(e.get("description", "unknown error")) for e in raw_errors if isinstance(e, dict)]
        if status >= 400 or (errors and not data):
            raise BridgeError("bridge_error", "; ".join(errors)[:300] or "HTTP %d" % status, status)
        return Reply(data, errors)

    def resources(self) -> List[dict]:
        """Every resource on the bridge (GET /clip/v2/resource)."""
        return self.request("GET", "resource").data


class EventStream:
    """The bridge's server-sent event feed on its own connection."""

    def __init__(self, creds: Credentials, timeout: float = 150.0,
                 connection_factory: Optional[Callable[..., PinnedConnection]] = None):
        self.creds = creds
        self.timeout = timeout
        self._factory = connection_factory or PinnedConnection
        self._conn: Optional[PinnedConnection] = None
        self._sock: Optional[socket.socket] = None

    def close(self) -> None:
        """Interrupt a running `run` from another thread.

        Only the socket is shut down: closing the buffered response from here
        would block on the lock the reading thread holds. The reader then sees
        end-of-stream and closes everything itself.
        """
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def run(self, stop: threading.Event, on_events: Callable[[List[dict]], None],
            on_open: Optional[Callable[[], None]] = None) -> None:
        """Block, calling on_events for each batch, until the stream drops or `stop` is set.

        Raises BridgeError when the connection fails or ends. A stream that
        opened and then stayed silent past `timeout` raises code `idle`: the
        bridge may be fine, only this connection went quiet.
        """
        opened = False
        try:
            conn = self._factory(self.creds.host, self.creds.fingerprint, self.timeout)
            self._conn = conn
            conn.request("GET", "/eventstream/clip/v2", headers={
                "hue-application-key": self.creds.key, "Accept": "text/event-stream"})
            self._sock = conn.sock  # http.client drops conn.sock for close-delimited replies; keep our own handle
            resp = conn.getresponse()
            if resp.status in (401, 403):
                raise BridgeError("unauthorized", "the bridge rejected the application key", resp.status)
            if resp.status != 200:
                raise BridgeError("unreachable", "event stream refused (HTTP %d)" % resp.status, resp.status)
            opened = True
            if on_open:
                on_open()
            while not stop.is_set():
                line = resp.readline()
                if not line:
                    raise BridgeError("unreachable", "the event stream ended")
                if line.startswith(b"data:"):
                    try:
                        batch = json.loads(line[5:].decode())
                    except ValueError:
                        log.debug("ignoring an unparsable event")
                        continue
                    if isinstance(batch, list):
                        on_events(batch)
        except Exception as exc:  # noqa: BLE001 - classified; KeyboardInterrupt/SystemExit propagate (finally closes)
            if stop.is_set():
                return
            if opened and isinstance(exc, (socket.timeout, TimeoutError)):
                raise BridgeError("idle", "the event stream was quiet for %d s" % self.timeout) from None
            raise _classify(exc) from None
        finally:
            if self._conn is not None:
                self._conn.close()

