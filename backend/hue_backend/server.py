"""The long-lived backend process: NDJSON commands in, events out. See PROTOCOL.md.

Threads (all daemon):
  main       reads commands from stdin and dispatches them
  connector  connects, loads every resource, then follows the event stream;
             a stream that drops while the bridge still answers is reopened
             (with a resync) over the same client; a real failure reconnects
             with backoff
  worker     runs commands one at a time through the rate-limited client
  emitter    coalesces cache changes into `state` events (debounced, with a max wait)
  wallpaper  follows the desktop wallpaper while that sync is enabled
  pairing    short-lived, one per pair.* request that touches the network
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional, TextIO

from . import credentials, ops, pairing
from .bridge import BridgeClient, BridgeError, EventStream
from .state import Cache, build_snapshot
from .wallpaper import WallpaperSync

PROTOCOL = 1
VERSION = "1.0.0"
DEBOUNCE = 0.12   # seconds of quiet before a state event
MAX_WAIT = 0.5    # a steady stream of events still produces a state this often
RECONNECT_WAIT = 5.0   # a command waits this long for a connection that is being (re)established
STREAM_HEALTHY = 60.0  # a stream that stayed up this long (or delivered events) resets the backoff
NEEDS_USER = ("unauthorized", "cert_changed")  # nothing to retry until the user re-pairs or trusts
TRANSIENT = ("", "connecting", "connected")      # states in which a missing client is about to come back

log = logging.getLogger("hue")


class Job(NamedTuple):
    """A queued unit of work: a client command, or a backend callable (`run`)."""

    id: Optional[int]
    cmd: Optional[Dict[str, Any]]
    run: Optional[Callable[[], None]]


class Server:
    """Wires the connector, worker and emitter threads to one NDJSON stream."""
    def __init__(self, out: TextIO, *,
                 load_credentials: Callable[[], Optional[credentials.Credentials]] = credentials.load,
                 save_credentials: Callable[[credentials.Credentials], None] = credentials.save,
                 forget_credentials: Callable[[], None] = credentials.forget,
                 import_openhue: Callable[[], Optional[credentials.Credentials]] = credentials.import_openhue,
                 fingerprint_of: Callable[[str], str] = credentials.fetch_fingerprint,
                 client_factory: Callable[[credentials.Credentials], BridgeClient] = BridgeClient,
                 stream_factory: Callable[[credentials.Credentials], EventStream] = EventStream,
                 discover: Callable[[], List[Dict[str, str]]] = pairing.discover_cloud,
                 pair_flow: Callable[..., credentials.Credentials] = pairing.link_button,
                 wallpaper_factory: Callable[..., WallpaperSync] = WallpaperSync,
                 backoff_start: float = 1.0, backoff_cap: float = 30.0,
                 reconnect_wait: float = RECONNECT_WAIT, stream_healthy: float = STREAM_HEALTHY):
        self._out = out
        self._out_lock = threading.Lock()
        self._load_creds, self._save_creds, self._forget_creds = load_credentials, save_credentials, forget_credentials
        self._import_openhue, self._fingerprint_of = import_openhue, fingerprint_of
        self._client_factory, self._stream_factory = client_factory, stream_factory
        self._discover, self._pair_flow = discover, pair_flow
        self._backoff_start, self._backoff_cap = backoff_start, backoff_cap
        self._reconnect_wait, self._stream_healthy = reconnect_wait, stream_healthy

        self.cache = Cache()
        self.client: Optional[BridgeClient] = None
        self._client_ready = threading.Event()  # set while `client` is usable
        self._creds: Optional[credentials.Credentials] = None  # bridge.json as last read (not re-read per state)
        self._stream_batches = 0
        self._crashes: Dict[str, str] = {}
        self._stream: Optional[EventStream] = None
        self._session_stop = threading.Event()
        self._wake = threading.Event()
        self.stop = threading.Event()
        self._jobs: "queue.Queue[Job]" = queue.Queue()
        self._dirty = threading.Event()
        self._conn: tuple = ("", "")
        self._rev = 0
        self._last_state_json = ""
        self._snap: Optional[Dict[str, Any]] = None
        self._pair_cancel: Optional[threading.Event] = None
        self.wallpaper = wallpaper_factory(snapshot=self._live_snapshot, submit=self._submit_internal, emit=self.emit)

    def _set_client(self, client: Optional[BridgeClient]) -> None:
        self.client = client
        if client is None:
            self._client_ready.clear()
        else:
            self._client_ready.set()

    def _crashed(self, where: str, exc: BaseException) -> None:
        """Log an unexpected exception with its traceback, once per distinct failure and place."""
        text = "%s: %s" % (exc.__class__.__name__, exc)
        if self._crashes.get(where) != text:
            self._crashes[where] = text
            log.error("%s failed unexpectedly", where, exc_info=exc)

    def _live_snapshot(self) -> Optional[Dict[str, Any]]:
        """The last snapshot, but only while connected: a stale one must not be painted."""
        return self._snap if self._conn[0] == "connected" and self.client is not None else None

    # ---- output -------------------------------------------------------------

    def emit(self, event: Dict[str, Any]) -> None:
        """Write one event line to stdout; a closed reader stops the server."""
        line = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        with self._out_lock:
            try:
                self._out.write(line + "\n")
                self._out.flush()
            except (BrokenPipeError, ValueError, OSError):
                self.stop.set()  # the reader is gone: shut down

    def _set_conn(self, state: str, detail: str = "") -> None:
        """Record and announce a connection state change (repeats are ignored)."""
        if (state, detail) == self._conn:
            return
        self._conn = (state, detail)
        log.info("connection: %s", state)
        self.emit({"event": "conn", "state": state, "detail": detail})
        self.wallpaper.refresh_eligible()

    def _result(self, cid: Optional[int], ok: bool, code: str = "", message: str = "", warnings: Optional[List[str]] = None) -> None:
        """Answer command `cid` (commands without an id get no result)."""
        if cid is not None:
            self.emit({"event": "result", "id": cid, "ok": ok, "code": code, "message": message, "warnings": warnings or []})

    # ---- lifecycle ----------------------------------------------------------

    def run(self, lines: Any) -> None:
        """Start the threads and dispatch command lines until input ends, then shut down."""
        self.emit({"event": "ready", "protocol": PROTOCOL, "version": VERSION})
        for target, name in ((self._connector, "connector"), (self._worker, "worker"), (self._emitter, "emitter")):
            threading.Thread(target=target, name=name, daemon=True).start()
        self.wallpaper.start()
        self.emit(self.wallpaper.event())
        try:
            for line in lines:
                if self.stop.is_set():
                    break
                line = line.strip()
                if line:
                    self._dispatch(line)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Stop every thread and cancel any pairing; safe to call more than once."""
        self.stop.set()
        self.wallpaper.stop()
        self._interrupt()
        if self._pair_cancel:
            self._pair_cancel.set()

    def _interrupt(self) -> None:
        """Make the connector re-read credentials and resync."""
        self._session_stop.set()
        stream = self._stream
        if stream:
            stream.close()
        self._wake.set()

    # ---- dispatch -----------------------------------------------------------

    def _dispatch(self, line: str) -> None:
        """Parse one command line and answer it now or queue it for the worker."""
        try:
            cmd = json.loads(line)
            if not isinstance(cmd, dict):
                raise ValueError("not an object")
        except ValueError:
            log.warning("ignored a command that is not valid JSON")
            return
        cid = cmd.get("id") if isinstance(cmd.get("id"), int) and not isinstance(cmd.get("id"), bool) else None
        name = str(cmd.get("cmd", ""))
        try:
            self._handle(cid, name, cmd)
        except Exception as exc:  # noqa: BLE001 - one bad command must not end the server
            self._crashed("command " + name[:40], exc)
            self._result(cid, False, "internal", exc.__class__.__name__)

    def _handle(self, cid: Optional[int], name: str, cmd: Dict[str, Any]) -> None:
        """Answer one parsed command now, or queue it for the worker."""
        if name == "refresh":
            self._jobs.put(Job(cid, None, self._refresh))
        elif name.startswith("pair."):
            self._pair(cid, name, cmd)
        elif name == "wallpaper.config":
            try:
                self.wallpaper.update({k: v for k, v in cmd.items() if k not in ("id", "cmd")})
            except OSError as exc:
                log.warning("wallpaper settings could not be saved: %s", exc.__class__.__name__)
                self._result(cid, False, "internal", "could not save the settings (%s)" % exc.__class__.__name__)
                return
            self._result(cid, True)
        elif name == "wallpaper.sync":
            self._jobs.put(Job(cid, None, self.wallpaper.sync_now))
        else:
            self._jobs.put(Job(cid, cmd, None))

    # ---- worker -------------------------------------------------------------

    def _submit_internal(self, cmds: List[Dict[str, Any]]) -> None:
        """Queue commands from the backend itself (wallpaper sync); they get no result."""
        self._jobs.put(Job(None, None, lambda: [self._execute(c) for c in cmds]))

    def _not_connected(self) -> BridgeError:
        """The error a command gets while there is no bridge connection."""
        state = self._conn[0]
        code = state if state in ("unpaired", "unauthorized", "cert_changed") else "unreachable"
        return BridgeError(code, "not connected to a bridge (%s)" % (state or "starting"))

    def _await_client(self) -> Optional[BridgeClient]:
        """The client, waiting briefly while a connection is being (re)established."""
        deadline = time.monotonic() + self._reconnect_wait
        while self.client is None and self._conn[0] in TRANSIENT and not self.stop.is_set():
            left = deadline - time.monotonic()
            if left <= 0:
                break
            self._client_ready.wait(min(left, 0.1))
        return self.client

    def _refresh(self) -> None:
        """`refresh`: re-read everything over the existing connection; with none, retry connecting now."""
        client = self.client
        if client is None:
            self._wake.set()
            return
        try:
            self._resync(client)
        except BridgeError as exc:
            if exc.code not in NEEDS_USER:  # (those already make the worker resync)
                self._interrupt()  # the bridge stopped answering: take the real reconnect path now
            raise

    def _resync(self, client: BridgeClient) -> None:
        """Reload every resource over `client` and schedule a state event; the stream is left alone."""
        self.cache.load(client.resources())
        self._dirty.set()

    def _execute(self, cmd: Dict[str, Any]) -> List[str]:
        """Run one command's API requests; returns the bridge's warnings."""
        client = self._await_client()
        if client is None:
            raise self._not_connected()
        warnings: List[str] = []
        for req in ops.plan(cmd, self.cache):
            warnings.extend(client.request(req.method, req.path, req.body, req.klass).warnings)
        return warnings

    def _worker(self) -> None:
        """Run queued jobs one at a time; a failure answers only its own command."""
        while not self.stop.is_set():
            try:
                job = self._jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if job.run is not None:
                    job.run()
                    self._result(job.id, True)
                else:
                    self._result(job.id, True, warnings=self._execute(job.cmd or {}))
            except ops.InvalidCommand as exc:
                self._result(job.id, False, "invalid", str(exc))
            except BridgeError as exc:
                log.warning("command %s failed: %s", (job.cmd or {}).get("cmd", "internal"), exc.code)
                self._result(job.id, False, exc.code, exc.message)
                if exc.code in NEEDS_USER:
                    self._interrupt()
            except Exception as exc:  # noqa: BLE001 - one bad command must not stop the worker
                self._crashed("command %s" % (job.cmd or {}).get("cmd", "internal"), exc)
                self._result(job.id, False, "internal", exc.__class__.__name__)

    # ---- connector ----------------------------------------------------------

    def _wait(self, seconds: float) -> None:
        self._wake.wait(seconds)
        self._wake.clear()

    def _grow(self, backoff: float) -> float:
        return min(backoff * 2, self._backoff_cap)

    def _connector(self) -> None:
        """Run sessions until shutdown; an unexpected error is logged and retried with backoff."""
        backoff = self._backoff_start
        while not self.stop.is_set():
            try:
                backoff = self._session(backoff)
            except Exception as exc:  # noqa: BLE001 - the connector must never die
                self._crashed("connector", exc)
                self._set_client(None)
                self._set_conn("unreachable", "internal error (%s); retrying" % exc.__class__.__name__)
                self._wait(backoff)
                backoff = self._grow(backoff)

    def _session(self, backoff: float) -> float:
        """Connect, load everything, follow the event stream. Returns the backoff for the next try."""
        if self._conn[0] == "pairing":
            self._wait(1.0)
            return backoff
        creds = self._load_creds()
        self._creds = creds
        if creds is None:
            self._set_client(None)
            self._set_conn("unpaired")
            self._wait(3600)
            return backoff
        if not creds.fingerprint:  # never fail open: no pin means no traffic until the user trusts
            self._set_client(None)
            self._set_conn("cert_changed", "no certificate is pinned for this bridge")
            self._wait(3600)
            return backoff
        session_stop = self._session_stop = threading.Event()
        self._set_conn("connecting")
        client = self._client_factory(creds)
        try:
            try:
                self.cache.load(client.resources())
            except BridgeError as exc:
                return self._failed(client, exc, backoff)
            self._set_client(client)
            self._snap = None
            self._dirty.set()
            self._set_conn("connected")
            while not self.stop.is_set() and not session_stop.is_set():
                opened, batches = time.monotonic(), self._stream_batches
                stream = self._stream_factory(creds)
                self._stream = stream
                try:
                    stream.run(session_stop, self._on_events)
                    if self.stop.is_set() or session_stop.is_set():
                        break
                    raise BridgeError("unreachable", "the event stream ended")  # never spin on a stream that returns
                except BridgeError as exc:
                    if self.stop.is_set() or session_stop.is_set():
                        break
                    if exc.code in NEEDS_USER:
                        return self._failed(client, exc, backoff)
                    if self._stream_batches != batches or time.monotonic() - opened >= self._stream_healthy:
                        backoff = self._backoff_start  # it was working: start the backoff afresh
                    try:
                        self._resync(client)  # does the bridge still answer? (and catch up on missed events)
                    except BridgeError as rest_exc:
                        return self._failed(client, rest_exc, backoff)
                    if exc.code == "idle":
                        log.info("event stream was quiet; reopened it")
                        continue  # a quiet stream ran for its whole timeout: no storm possible
                    log.info("event stream ended (%s); the bridge answers, reopening", exc.code)
                    self._wait(backoff)
                    backoff = self._grow(backoff)
            return backoff
        finally:
            self._stream = None
            if self.client is client:
                self._set_client(None)
            client.close()

    def _failed(self, client: BridgeClient, exc: BridgeError, backoff: float) -> float:
        """A session failed: report it, wait, and return the next backoff."""
        self._set_client(None)
        client.close()
        if exc.code in NEEDS_USER:
            self._set_conn(exc.code, exc.message)
            self._wait(3600)
            return backoff
        self._set_conn("unreachable", exc.message)
        self._wait(backoff)
        return self._grow(backoff)

    def _on_events(self, batch: List[dict]) -> None:
        """Apply an event-stream batch and mark the snapshot dirty if anything changed."""
        self._stream_batches += 1
        if self.cache.apply_events(batch):
            self._dirty.set()

    # ---- state emission -----------------------------------------------------

    def _emitter(self) -> None:
        """Coalesce cache changes into `state` events (debounced, with a max wait)."""
        while not self.stop.is_set():
            if not self._dirty.wait(0.5):
                continue
            began = time.monotonic()
            while not self.stop.is_set():
                self._dirty.clear()
                if self._dirty.wait(DEBOUNCE) and time.monotonic() - began < MAX_WAIT:
                    continue
                break
            try:
                self._emit_state()
            except Exception as exc:  # noqa: BLE001 - the next change must still produce a state
                self._crashed("state event", exc)

    def _emit_state(self) -> None:
        """Build the snapshot and emit it unless it is identical to the last one."""
        creds = self._creds
        if self.client is None or creds is None:
            return
        snap = build_snapshot(self.cache)
        snap["bridge"]["host"] = creds.host
        text = json.dumps(snap, sort_keys=True)
        self._snap = snap
        self.wallpaper.refresh_eligible()
        if text == self._last_state_json:
            return
        self._last_state_json = text
        self._rev += 1
        self.emit({"event": "state", "rev": self._rev, "data": snap})

    # ---- pairing ------------------------------------------------------------

    def _spawn(self, fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, name="pairing", daemon=True).start()

    def _answering(self, cid: Optional[int], where: str, fn: Callable[[Optional[int]], None]) -> Callable[[], None]:
        """`fn` for a pairing thread, answering `cid` with `internal` if it crashes."""
        def run() -> None:
            try:
                fn(cid)
            except BridgeError as exc:
                self._result(cid, False, exc.code, exc.message)
            except Exception as exc:  # noqa: BLE001 - every command gets its result
                self._crashed(where, exc)
                self._result(cid, False, "internal", exc.__class__.__name__)
        return run

    def _pair(self, cid: Optional[int], name: str, cmd: Dict[str, Any]) -> None:
        if name == "pair.cancel":
            if self._pair_cancel:
                self._pair_cancel.set()
            self._result(cid, True)
        elif name == "pair.forget":
            self._forget_creds()
            self._creds = None
            self.cache.load([])
            self._last_state_json = ""
            self._snap = None
            self._interrupt()
            self._result(cid, True)
        elif name == "pair.discover":
            self._spawn(self._answering(cid, "discovery", self._do_discover))
        elif name == "pair.importOpenhue":
            self._spawn(self._answering(cid, "openhue import", self._do_import))
        elif name == "pair.trust":
            self._spawn(self._answering(cid, "trust", self._do_trust))
        elif name == "pair.start":
            host = str(cmd.get("host", ""))
            if not credentials.valid_host(host):
                self._result(cid, False, "invalid", "that is not a host name or address")
            else:
                self._start_pairing(cid, host)
        else:
            self._result(cid, False, "invalid", "unknown command: %s" % name)

    def _do_discover(self, cid: Optional[int]) -> None:
        try:
            self.emit({"event": "discovered", "bridges": self._discover()})
            self._result(cid, True)
        except BridgeError as exc:
            self._result(cid, False, exc.code, exc.message)

    def _do_import(self, cid: Optional[int]) -> None:
        """Adopt openhue's bridge and key, pinning the certificate seen now."""
        creds = self._import_openhue()
        if creds is None:
            self._result(cid, False, "unpaired", "no bridge was found in the openhue configuration")
            return
        try:
            creds.fingerprint = self._fingerprint_of(creds.host)
        except OSError as exc:
            self._result(cid, False, "unreachable", "cannot reach %s (%s)" % (creds.host, exc.__class__.__name__))
            return
        self._store(creds)
        self._result(cid, True)

    def _store(self, creds: credentials.Credentials) -> None:
        """Save new credentials (always with a pin) and make the connector pick them up."""
        if not creds.fingerprint:
            raise BridgeError("bridge_error", "no certificate was recorded for the bridge")
        self._save_creds(creds)
        self._creds = creds
        self._last_state_json = ""  # a new bridge's first snapshot must always be sent
        self._interrupt()

    def _do_trust(self, cid: Optional[int]) -> None:
        """Re-pin the paired bridge's current certificate after a cert_changed."""
        creds = self._load_creds()
        if creds is None:
            self._result(cid, False, "unpaired", "no bridge is paired")
            return
        try:
            creds.fingerprint = self._fingerprint_of(creds.host)
        except OSError as exc:
            self._result(cid, False, "unreachable", "cannot reach %s (%s)" % (creds.host, exc.__class__.__name__))
            return
        self._store(creds)
        self._result(cid, True)

    def _start_pairing(self, cid: Optional[int], host: str) -> None:
        """Run the link-button flow on a pairing thread, cancelling any earlier one."""
        if self._pair_cancel:
            self._pair_cancel.set()
        cancel = threading.Event()
        self._pair_cancel = cancel
        self._set_conn("pairing")
        self._result(cid, True)

        def run() -> None:
            try:
                creds = self._pair_flow(host, cancel, lambda left: self.emit(
                    {"event": "pair", "state": "waiting_button", "secondsLeft": left}))
                if not isinstance(creds, credentials.Credentials):
                    raise BridgeError("bridge_error", "pairing returned no credentials")
                self._store(creds)
                self.emit({"event": "pair", "state": "paired"})
            except BridgeError as exc:
                state = "cancelled" if exc.code == "cancelled" else "failed"
                self.emit({"event": "pair", "state": state, "message": exc.message})
            except Exception as exc:  # noqa: BLE001 - the UI must always hear how pairing ended
                self._crashed("pairing", exc)
                self.emit({"event": "pair", "state": "failed",
                           "message": "pairing failed unexpectedly (%s)" % exc.__class__.__name__})
            finally:
                self._conn = ("", "")  # leave 'pairing'; the connector sets the real state
                self._interrupt()

        self._spawn(run)
