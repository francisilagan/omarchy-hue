"""The protocol end to end, with fake bridge, stream and credential store."""
import io
import json
import queue
import threading
import time
import unittest
from unittest import mock

import support
from hue_backend import bridge, server
from hue_backend.credentials import Credentials


class FakeClient:
    def __init__(self, resources, fail=None):
        self.resources_data = resources
        self.calls = []
        self.fail = fail or {}
        self.closed = False
        self.loads = 0

    def resources(self):
        self.loads += 1
        err = self.fail.get("resources")
        if callable(err) and not isinstance(err, BaseException):
            err = err()
        if err:
            raise err
        return self.resources_data

    def request(self, method, path, body=None, klass=""):
        self.calls.append((method, path, body, klass))
        err = self.fail.get(path)
        if err:
            raise err
        return bridge.Reply([], self.fail.get("warn", []))

    def close(self):
        self.closed = True


class FakeStream:
    """Blocks until closed, delivering any batches pushed into `batches`."""

    def __init__(self):
        self.batches = queue.Queue()
        self.closed = threading.Event()

    def run(self, stop, on_events, on_open=None):
        while not stop.is_set() and not self.closed.is_set():
            try:
                on_events(self.batches.get(timeout=0.05))
            except queue.Empty:
                pass

    def close(self):
        self.closed.set()


class IdleStream(FakeStream):
    """Opens, stays quiet, then reports the idle read timeout."""

    def run(self, stop, on_events, on_open=None):
        time.sleep(0.05)
        raise bridge.BridgeError("idle", "the event stream was quiet for 150 s")


class DroppingStream(FakeStream):
    def __init__(self):
        super().__init__()
        self.opens = 0

    def run(self, stop, on_events, on_open=None):
        self.opens += 1
        raise bridge.BridgeError("unreachable", "the event stream ended")


class Out:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def write(self, text):
        with self.lock:
            self.events.extend(json.loads(l) for l in text.splitlines() if l)

    def flush(self):
        pass


class Harness:
    def __init__(self, creds=Credentials("1.2.3.4", "K", fingerprint="f" * 64), client=None, **kw):
        self.out = Out()
        self.stdin = queue.Queue()
        self.client = client or FakeClient(support.fixture())
        self.stream = FakeStream()
        self.saved = []
        self.creds = creds
        self.wallpaper_cmds = []

        class StubWallpaper:
            def __init__(s, **k):
                s.k = k

            def start(s): pass
            def stop(s): pass
            def event(s): return {"event": "wallpaper", "config": {"enabled": False}, "palette": [], "appliedAt": None}
            def update(s, partial): s.k["emit"]({"event": "wallpaper", "config": partial, "palette": [], "appliedAt": None})
            def sync_now(s): pass
            def refresh_eligible(s): s.refreshed = getattr(s, "refreshed", 0) + 1

        defaults = dict(
            load_credentials=lambda: self.creds,
            save_credentials=lambda c: (self.saved.append(c), setattr(self, "creds", c)),
            forget_credentials=lambda: setattr(self, "creds", None),
            import_openhue=lambda: Credentials("9.9.9.9", "OPENHUEKEY"),
            fingerprint_of=lambda host: "a" * 64,
            client_factory=lambda c: self.client,
            stream_factory=lambda c: self.stream,
            wallpaper_factory=StubWallpaper,
            backoff_cap=0.05,
        )
        defaults.update(kw)
        self.server = server.Server(self.out, **defaults)
        self.thread = threading.Thread(target=lambda: self.server.run(iter(self.stdin.get, None)), daemon=True)
        self.thread.start()
        self.next_id = 0

    def send(self, cmd, **fields):
        self.next_id += 1
        self.stdin.put(json.dumps(dict(fields, cmd=cmd, id=self.next_id)))
        return self.next_id

    def wait(self, pred, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            with self.out.lock:
                for e in self.out.events:
                    if pred(e):
                        return e
            time.sleep(0.01)
        raise AssertionError("timed out; events: %s" % [(e["event"], e.get("state") or e.get("id")) for e in self.out.events])

    def result(self, cid):
        return self.wait(lambda e: e["event"] == "result" and e["id"] == cid)

    def close(self):
        self.stdin.put(None)
        self.thread.join(3)

    def conns(self):
        with self.out.lock:
            return [e["state"] for e in self.out.events if e["event"] == "conn"]


def fixture_light(n=0):
    return [l["id"] for l in support.fixture() if l["type"] == "light"][n]


class Protocol(unittest.TestCase):
    def harness(self, **kw):
        h = Harness(**kw)
        self.addCleanup(h.close)
        return h

    def test_ready_then_connected_then_state(self):
        h = self.harness()
        self.assertEqual(h.wait(lambda e: e["event"] == "ready")["protocol"], 1)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected")
        st = h.wait(lambda e: e["event"] == "state")
        self.assertEqual(len(st["data"]["lights"]), 5)
        self.assertEqual(st["data"]["bridge"]["host"], "1.2.3.4")

    def test_set_sends_a_rate_classed_put_and_reports_ok(self):
        h = self.harness()
        st = h.wait(lambda e: e["event"] == "state")["data"]
        lid = next(iter(st["lights"]))
        cid = h.send("set", kind="light", ids=[lid], on=True, pct=30)
        self.assertTrue(h.result(cid)["ok"])
        method, path, body, klass = h.client.calls[-1]
        self.assertEqual((method, path, klass), ("PUT", "resource/light/" + lid, "light"))

    def test_one_failing_command_does_not_stop_the_next(self):
        lid = next(l["id"] for l in support.fixture() if l["type"] == "light")
        bad = bridge.BridgeError("bridge_error", "Not Found")
        h = self.harness(client=FakeClient(support.fixture(), fail={"resource/light/" + lid: bad}))
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected")
        c1 = h.send("set", kind="light", ids=[lid], on=True)
        other = next(l["id"] for l in support.fixture() if l["type"] == "light" and l["id"] != lid)
        c2 = h.send("set", kind="light", ids=[other], on=True)
        r1, r2 = h.result(c1), h.result(c2)
        self.assertEqual((r1["ok"], r1["code"], r1["message"]), (False, "bridge_error", "Not Found"))
        self.assertTrue(r2["ok"])

    def test_partial_success_stays_ok_with_warnings(self):
        h = self.harness(client=FakeClient(support.fixture(), fail={"warn": ["device has communication issues"]}))
        lid = next(l["id"] for l in support.fixture() if l["type"] == "light")
        r = h.result(h.send("set", kind="light", ids=[lid], on=True))
        self.assertTrue(r["ok"])
        self.assertEqual(r["warnings"], ["device has communication issues"])

    def test_invalid_commands_get_a_result_and_never_reach_the_bridge(self):
        h = self.harness()
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected")
        before = len(h.client.calls)
        for cmd, fields in (("set", {"kind": "light", "ids": ["../x"], "on": True}), ("nonsense", {})):
            r = h.result(h.send(cmd, **fields))
            self.assertEqual((r["ok"], r["code"]), (False, "invalid"))
        self.assertEqual(len(h.client.calls), before)

    def test_garbage_on_stdin_is_ignored(self):
        h = self.harness()
        h.stdin.put("not json")
        h.stdin.put("[1,2]")
        r = h.result(h.send("refresh"))
        self.assertTrue(r["ok"])

    def test_events_update_the_state_and_are_coalesced(self):
        h = self.harness()
        st = h.wait(lambda e: e["event"] == "state")
        lid = next(iter(st["data"]["lights"]))
        was_on = st["data"]["lights"][lid]["on"]
        for i in range(5):
            h.stream.batches.put([{"type": "update", "data": [{"id": lid, "type": "light", "on": {"on": not was_on}}]}])
        new = h.wait(lambda e: e["event"] == "state" and e["rev"] > st["rev"])
        self.assertEqual(new["data"]["lights"][lid]["on"], not was_on)
        time.sleep(0.4)
        revs = [e["rev"] for e in h.out.events if e["event"] == "state"]
        self.assertLessEqual(len(revs), 3)  # five events did not become five states
        self.assertEqual(revs, sorted(set(revs)))  # revisions only ever increase

    def test_unchanged_snapshot_is_not_resent(self):
        h = self.harness()
        st = h.wait(lambda e: e["event"] == "state")
        lid = next(iter(st["data"]["lights"]))
        same = st["data"]["lights"][lid]["on"]
        h.stream.batches.put([{"type": "update", "data": [{"id": lid, "type": "light", "on": {"on": same}}]}])
        time.sleep(0.5)
        self.assertEqual(len([e for e in h.out.events if e["event"] == "state"]), 1)

    def test_unpaired_reports_it_and_commands_fail_with_that_code(self):
        h = self.harness(creds=None)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unpaired")
        r = h.result(h.send("set", kind="light", ids=[support.uid()], on=True))
        self.assertEqual((r["ok"], r["code"]), (False, "unpaired"))

    def test_import_openhue_pins_the_certificate_and_connects(self):
        h = self.harness(creds=None)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unpaired")
        r = h.result(h.send("pair.importOpenhue"))
        self.assertTrue(r["ok"])
        self.assertEqual(h.saved[0].fingerprint, "a" * 64)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected")

    def test_revoked_key_is_reported_as_unauthorized_with_no_retry_storm(self):
        h = self.harness(client=FakeClient([], fail={"resources": bridge.BridgeError("unauthorized", "no")}))
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unauthorized")
        time.sleep(0.3)
        self.assertEqual(len([e for e in h.out.events if e["event"] == "conn" and e["state"] == "unauthorized"]), 1)

    def test_unreachable_bridge_retries_and_recovers(self):
        client = FakeClient(support.fixture(), fail={"resources": bridge.BridgeError("unreachable", "down")})
        h = self.harness(client=client)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unreachable")
        client.fail.pop("resources")
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected", 5)

    def test_cert_changed_waits_for_the_user_then_trust_repins(self):
        client = FakeClient(support.fixture(), fail={"resources": bridge.BridgeError("cert_changed", "different")})
        h = self.harness(client=client)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "cert_changed")
        client.fail.pop("resources")
        self.assertTrue(h.result(h.send("pair.trust"))["ok"])
        self.assertEqual(h.saved[-1].fingerprint, "a" * 64)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected")

    def test_link_button_pairing_reports_progress_and_saves(self):
        def flow(host, cancel, progress):
            progress(30)
            return Credentials(host, "NEWKEY", fingerprint="b" * 64)
        h = self.harness(creds=None, pair_flow=flow)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unpaired")
        self.assertTrue(h.result(h.send("pair.start", host="5.6.7.8"))["ok"])
        h.wait(lambda e: e["event"] == "pair" and e["state"] == "waiting_button")
        h.wait(lambda e: e["event"] == "pair" and e["state"] == "paired")
        self.assertEqual(h.saved[-1].key, "NEWKEY")
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected")

    def test_pairing_failure_is_reported(self):
        def flow(host, cancel, progress):
            raise bridge.BridgeError("timeout", "the link button was not pressed in time")
        h = self.harness(creds=None, pair_flow=flow)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unpaired")
        h.send("pair.start", host="5.6.7.8")
        e = h.wait(lambda e: e["event"] == "pair" and e["state"] == "failed")
        self.assertIn("link button", e["message"])

    def test_pair_start_rejects_a_bad_host(self):
        h = self.harness(creds=None)
        r = h.result(h.send("pair.start", host="http://evil/x"))
        self.assertEqual((r["ok"], r["code"]), (False, "invalid"))

    def test_discover_returns_bridges(self):
        h = self.harness(discover=lambda: [{"id": "abc", "host": "10.0.0.5"}])
        h.wait(lambda e: e["event"] == "ready")
        h.send("pair.discover")
        self.assertEqual(h.wait(lambda e: e["event"] == "discovered")["bridges"][0]["host"], "10.0.0.5")

    def test_forget_removes_the_bridge(self):
        h = self.harness()
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected")
        self.assertTrue(h.result(h.send("pair.forget"))["ok"])
        self.assertIsNone(h.creds)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unpaired")

    def test_wallpaper_config_is_forwarded_and_answered(self):
        h = self.harness()
        r = h.result(h.send("wallpaper.config", enabled=True))
        self.assertTrue(r["ok"])
        self.assertEqual(h.wait(lambda e: e["event"] == "wallpaper" and e["config"].get("enabled") is True)["palette"], [])

    def test_wallpaper_sees_a_snapshot_only_while_connected_and_hears_about_changes(self):
        h = self.harness()
        h.wait(lambda e: e["event"] == "state")
        self.assertIsNotNone(h.server._live_snapshot())
        self.assertGreater(getattr(h.server.wallpaper, "refreshed", 0), 0)
        h.server._set_conn("unreachable", "gone")  # a dropped stream keeps the last snapshot around
        self.assertIsNone(h.server._live_snapshot())

    def test_real_wallpaper_sync_counts_and_paints_through_the_worker(self):
        import functools
        import os
        import tempfile
        from hue_backend import wallpaper
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        image, link = os.path.join(d, "1-test.png"), os.path.join(d, "background")
        open(image, "w").close()
        os.symlink(image, link)
        store = {"wallpaper": {"enabled": False, "turnOn": False}}
        factory = functools.partial(wallpaper.WallpaperSync, link=wallpaper.Path(link), poll=0.05,
                                    extract=lambda path: ["#ff0000", "#00ff00"],
                                    load=lambda: dict(store), save=store.update)
        h = self.harness(wallpaper_factory=factory)
        first = h.wait(lambda e: e["event"] == "wallpaper")
        self.assertEqual((first["eligible"], first["appliedCount"]), (0, 0))  # not connected yet
        h.wait(lambda e: e["event"] == "state")
        live = h.wait(lambda e: e["event"] == "wallpaper" and e["eligible"] > 0)
        h.result(h.send("wallpaper.sync"))
        done = h.wait(lambda e: e["event"] == "wallpaper" and e["appliedCount"] > 0)
        self.assertEqual(done["appliedCount"], live["eligible"])
        h.wait(lambda e: len([c for c in h.client.calls if c[0] == "PUT"]) >= live["eligible"])
        puts = [c for c in h.client.calls if c[0] == "PUT"]
        self.assertTrue(all(c[1].startswith("resource/light/") for c in puts), puts)
        for _, _, body, _ in puts:
            self.assertIn("color", body)
            self.assertNotIn("dimming", body)  # brightness is never touched

    def test_wallpaper_has_no_snapshot_while_unpaired(self):
        h = self.harness(creds=None)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unpaired")
        self.assertIsNone(h.server._live_snapshot())

    # ---- audit regressions ---------------------------------------------------

    def test_an_unpinned_bridge_needs_trust_and_is_never_contacted(self):
        made = []
        client = FakeClient(support.fixture())
        h = self.harness(creds=Credentials("1.2.3.4", "K"),  # bridge.json without a fingerprint
                         client_factory=lambda c: (made.append(c.fingerprint), client)[1])
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "cert_changed")
        self.assertEqual(made, [])
        r = h.result(h.send("set", kind="light", ids=[fixture_light()], on=True))
        self.assertEqual((r["ok"], r["code"]), (False, "cert_changed"))
        self.assertTrue(h.result(h.send("pair.trust"))["ok"])
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected")
        self.assertEqual(made, ["a" * 64])

    def test_a_pairing_without_a_certificate_is_not_saved(self):
        h = self.harness(creds=None, pair_flow=lambda host, cancel, progress: Credentials(host, "NEWKEY"))
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unpaired")
        h.send("pair.start", host="10.0.0.9")
        h.wait(lambda e: e["event"] == "pair" and e["state"] == "failed")
        self.assertEqual(h.saved, [])

    def test_refresh_resyncs_in_place_without_dropping_the_connection(self):
        h = self.harness()
        h.wait(lambda e: e["event"] == "state")
        lid = fixture_light()
        renamed = [dict(r, metadata=dict(r["metadata"], name="Renamed")) if r["id"] == lid else r
                   for r in support.fixture()]
        h.client.resources_data = renamed
        c_refresh = h.send("refresh")
        c_set = h.send("set", kind="light", ids=[lid], on=True)  # right behind it: must not hit a torn-down client
        self.assertTrue(h.result(c_refresh)["ok"])
        self.assertTrue(h.result(c_set)["ok"], h.result(c_set))
        h.wait(lambda e: e["event"] == "state" and e["data"]["lights"][lid]["name"] == "Renamed")
        self.assertFalse(h.client.closed)
        self.assertFalse(h.stream.closed.is_set())
        self.assertEqual(h.conns(), ["connecting", "connected"])

    def test_a_refresh_that_cannot_reach_the_bridge_reconnects(self):
        h = self.harness()
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected")
        h.client.fail["resources"] = bridge.BridgeError("unreachable", "down")
        r = h.result(h.send("refresh"))
        self.assertEqual((r["ok"], r["code"]), (False, "unreachable"))
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unreachable")
        h.client.fail.pop("resources")
        end = time.time() + 5
        while h.conns()[-1] != "connected" and time.time() < end:
            time.sleep(0.02)
        self.assertEqual(h.conns()[-1], "connected")

    def test_commands_wait_for_a_connection_in_progress(self):
        class Slow(FakeClient):
            def resources(self):
                time.sleep(0.4)
                return super().resources()
        h = self.harness(client=Slow(support.fixture()))
        r = h.result(h.send("set", kind="light", ids=[fixture_light()], on=True))
        self.assertTrue(r["ok"], r)

    def test_a_quiet_stream_reopens_silently_and_keeps_the_client(self):
        opened = []
        idle = IdleStream()

        def streams(creds):
            opened.append(1)
            return idle if len(opened) == 1 else self.live
        self.live = FakeStream()
        h = self.harness(stream_factory=streams)
        h.wait(lambda e: len(opened) >= 2)
        time.sleep(0.1)
        self.assertEqual(h.conns(), ["connecting", "connected"])  # never "unreachable"
        self.assertFalse(h.client.closed)
        self.assertEqual(h.client.loads, 2)  # resynced over the same client in case anything was missed
        self.assertTrue(h.result(h.send("set", kind="light", ids=[fixture_light()], on=True))["ok"])

    def test_a_stream_that_keeps_dropping_backs_off_although_rest_works(self):
        stream = DroppingStream()
        h = self.harness(stream_factory=lambda c: stream, backoff_start=0.01, backoff_cap=10)
        time.sleep(1.0)
        # Doubling from 10 ms gives about 7 tries a second; resetting after each REST load gave about 100.
        self.assertLessEqual(stream.opens, 10)
        self.assertGreaterEqual(stream.opens, 3)

    def test_the_emitter_survives_a_snapshot_that_fails(self):
        h = self.harness()
        st = h.wait(lambda e: e["event"] == "state")
        a, b = fixture_light(0), fixture_light(1)
        real, calls = server.build_snapshot, []

        def flaky(cache):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return real(cache)
        with mock.patch.object(server, "build_snapshot", flaky):
            h.stream.batches.put([{"type": "update", "data": [{"id": a, "type": "light", "on": {"on": not st["data"]["lights"][a]["on"]}}]}])
            time.sleep(0.4)
            h.stream.batches.put([{"type": "update", "data": [{"id": b, "type": "light", "on": {"on": not st["data"]["lights"][b]["on"]}}]}])
            h.wait(lambda e: e["event"] == "state" and e["rev"] > st["rev"])

    def test_a_non_numeric_brightness_event_does_not_stop_state_events(self):
        h = self.harness()
        st = h.wait(lambda e: e["event"] == "state")
        a, b = fixture_light(0), fixture_light(1)
        h.stream.batches.put([{"type": "update", "data": [{"id": a, "type": "light", "dimming": {"brightness": "abc"}}]}])
        time.sleep(0.3)
        h.stream.batches.put([{"type": "update", "data": [{"id": b, "type": "light", "on": {"on": not st["data"]["lights"][b]["on"]}}]}])
        h.wait(lambda e: e["event"] == "state" and b in e["data"]["lights"]
               and e["data"]["lights"][b]["on"] != st["data"]["lights"][b]["on"])

    def test_the_connector_survives_an_unexpected_error(self):
        errors = [AttributeError("'list' object has no attribute 'get'")]
        client = FakeClient(support.fixture(), fail={"resources": lambda: errors.pop() if errors else None})
        h = self.harness(client=client)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unreachable")  # not stuck on "connecting"
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "connected", 5)

    def test_a_settings_save_failure_is_answered_and_the_server_keeps_running(self):
        class Wallpaper:
            def __init__(s, **k): pass
            def start(s): pass
            def stop(s): pass
            def event(s): return {"event": "wallpaper", "config": {}, "palette": [], "appliedAt": None}
            def refresh_eligible(s): pass
            def update(s, partial): raise OSError(30, "Read-only file system")
        h = self.harness(wallpaper_factory=Wallpaper)
        r = h.result(h.send("wallpaper.config", enabled=True))
        self.assertEqual((r["ok"], r["code"]), (False, "internal"))
        self.assertIn("settings", r["message"])
        self.assertTrue(h.result(h.send("refresh"))["ok"])
        self.assertTrue(h.thread.is_alive())

    def test_a_crashing_pairing_still_ends_with_a_failed_pair_event(self):
        def flow(host, cancel, progress):
            return [1][0]["success"]  # what an odd reply used to do inside pairing.py: TypeError
        h = self.harness(creds=None, pair_flow=flow)
        h.wait(lambda e: e["event"] == "conn" and e["state"] == "unpaired")
        h.send("pair.start", host="10.0.0.9")
        e = h.wait(lambda e: e["event"] == "pair" and e["state"] == "failed")
        self.assertTrue(e["message"])
        end = time.time() + 3
        while h.conns()[-1] != "unpaired" and time.time() < end:  # back from "pairing"
            time.sleep(0.02)
        self.assertEqual(h.conns()[-1], "unpaired")

    def test_crashing_pair_helpers_still_answer(self):
        def boom(*a):
            raise RuntimeError("odd")
        h = self.harness(discover=boom, import_openhue=boom, fingerprint_of=boom)
        for cmd in ("pair.discover", "pair.importOpenhue", "pair.trust"):
            r = h.result(h.send(cmd))
            self.assertEqual((r["ok"], r["code"]), (False, "internal"), cmd)

    def test_state_events_do_not_reread_bridge_json(self):
        loads = []
        creds = Credentials("1.2.3.4", "K", fingerprint="f" * 64)
        h = self.harness(load_credentials=lambda: (loads.append(1), creds)[1])
        st = h.wait(lambda e: e["event"] == "state")
        before = len(loads)
        lid = fixture_light()
        for i in range(3):
            h.stream.batches.put([{"type": "update", "data": [{"id": lid, "type": "light", "on": {"on": i % 2 == 0}}]}])
            time.sleep(0.25)
        h.wait(lambda e: e["event"] == "state" and e["rev"] >= st["rev"] + 2)
        self.assertEqual(len(loads), before)

    def test_closing_stdin_shuts_the_server_down(self):
        h = Harness()
        h.wait(lambda e: e["event"] == "ready")
        h.stdin.put(None)
        h.thread.join(3)
        self.assertFalse(h.thread.is_alive())
        self.assertTrue(h.stream.closed.is_set())


if __name__ == "__main__":
    unittest.main()
