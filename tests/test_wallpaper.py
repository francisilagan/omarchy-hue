import colorsys
import math
import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

import support  # noqa: F401
from hue_backend import wallpaper


def snap():
    def L(i, color=True, on=True, reachable=True):
        return {"id": "L%d" % i, "color": color, "on": on, "reachable": reachable}
    lights = {l["id"]: l for l in (L(1), L(2, on=False), L(3, color=False), L(4, reachable=False), L(5))}
    return {"lights": lights, "groups": [
        {"id": "R1", "kind": "room", "lightIds": ["L1", "L2", "L3"]},
        {"id": "R2", "kind": "room", "lightIds": ["L4", "L5"]},
        {"id": "Z1", "kind": "zone", "lightIds": ["L1", "L5"]},
    ]}


class Palette(unittest.TestCase):
    def test_colourful_common_colours_win_and_near_black_is_ignored(self):
        rows = [(9000, "#050505"), (4000, "#9030a0"), (3000, "#d03060"), (50, "#808080")]
        pal = wallpaper.rank_palette(rows, 3)
        self.assertEqual(len(pal), 3)
        self.assertNotIn("#050505", pal)
        self.assertNotEqual(pal[0], "#808080")

    def test_similar_colours_are_not_repeated(self):
        rows = [(100, "#ff0000"), (90, "#fe0101"), (80, "#fd0202"), (70, "#0000ff")]
        pal = wallpaper.rank_palette(rows, 4)
        self.assertEqual(len(pal), 2)

    def test_pastels_are_made_vivid_and_all_are_full_value(self):
        pal = wallpaper.rank_palette([(10, "#c8a0b0")], 1)
        r, g, b = (int(pal[0][i:i + 2], 16) for i in (1, 3, 5))
        self.assertEqual(max(r, g, b), 255)
        self.assertGreater(max(r, g, b) - min(r, g, b), 90)

    def test_vivid_colours_come_before_near_whites_even_when_whites_dominate(self):
        # Shaped like the eyes-wide wallpaper that ranked three near-whites in five.
        rows = [(16000, "#0c0b0c"), (2500, "#b1948d"), (1500, "#4f352b"), (1400, "#926a5b"),
                (650, "#b1a3a1"), (620, "#e2dfde"), (350, "#b1c0c7"), (170, "#374b50"), (150, "#6f8a93")]
        pal = wallpaper.rank_palette(rows, 5)
        self.assertEqual(_tiers(pal)[:2], ["vivid", "vivid"])
        self.assertTrue(_is_warm(pal[0]), pal)          # the skin tone family, the biggest colour
        self.assertGreater(_hsv(pal[1])[0], 0.45)        # then the eyes' teal, before any white
        self.assertLess(_hsv(pal[1])[0], 0.6)

    def test_no_neutral_ever_precedes_a_vivid_colour(self):
        rnd = random.Random(7)
        for _ in range(300):
            rows = [(rnd.randint(1, 5000), "#%06x" % rnd.randint(0, 0xFFFFFF)) for _ in range(rnd.randint(1, 24))]
            tiers = _tiers(wallpaper.rank_palette(rows, 6))
            if "neutral" in tiers:
                self.assertNotIn("vivid", tiers[tiers.index("neutral"):], rows)

    def test_neutrals_are_still_filler_when_nothing_better_exists(self):
        pal = wallpaper.rank_palette([(9000, "#fffcf0"), (100, "#888b75"), (100, "#767864")], 3)
        self.assertEqual(pal[0], "#fffcf0")  # a cream wallpaper stays cream, not lime
        self.assertEqual(set(_tiers(pal)), {"neutral"})

    def test_a_common_dull_family_comes_after_vivid_ones_and_before_filler(self):
        # Tree-tops-like slate (dull: low chroma) covering half the picture, a small vivid orange, whites.
        rows = [(5000, "#3a444a"), (4000, "#313b42"), (300, "#e08020"), (3000, "#f0f0f0")]
        pal = wallpaper.rank_palette(rows, 3)
        self.assertEqual(len(pal), 3)
        self.assertAlmostEqual(_hsv(pal[0])[0], 0.08, delta=0.02)   # vivid orange first
        self.assertAlmostEqual(_hsv(pal[1])[0], 0.56, delta=0.03)   # then the muted slate, pushed to a colour
        self.assertEqual(_tiers(pal), ["vivid", "vivid", "neutral"])

    def test_a_broad_colour_family_beats_a_tiny_hyper_saturated_speck(self):
        rows = [(3000, "#5a7fa0"), (2500, "#4f7090"), (2000, "#6a8cb0"), (60, "#ff0000")]
        pal = wallpaper.rank_palette(rows, 3)
        self.assertAlmostEqual(_hsv(pal[0])[0], 0.58, delta=0.04)  # the steel blue
        self.assertEqual(pal[1], "#ff0000")  # the speck still makes the palette, second

    def test_colour_beats_a_larger_but_nearly_black_field(self):
        # Totoro: a dark navy background (87%) around a lilac disc.
        pal = wallpaper.rank_palette([(32000, "#181826"), (1600, "#d3a9f3"), (650, "#c49ef0")], 3)
        self.assertAlmostEqual(_hsv(pal[0])[0], 0.76, delta=0.03)

    def test_tinted_near_black_is_not_promoted_to_a_vivid_colour(self):
        pal = wallpaper.rank_palette([(5000, "#1e1c23"), (1000, "#c03020")], 5)
        self.assertEqual(len(pal), 1)  # the red; the dark violet-grey is not a colour and too dark to be filler

    def test_a_family_that_straddles_red_stays_red(self):
        pal = wallpaper.rank_palette([(1000, "#e0203a"), (1000, "#e03a20")], 3)
        self.assertEqual(len(pal), 1)
        h = _hsv(pal[0])[0]
        self.assertLess(min(h, 1 - h), 0.02)

    def test_near_identical_whites_appear_once(self):
        pal = wallpaper.rank_palette([(500, "#c03020"), (300, "#fafafa"), (290, "#f5f5f5"), (280, "#f0f0f2")], 6)
        self.assertEqual(len(pal), 2)

    def test_an_all_dark_grey_picture_still_gets_a_colour(self):
        self.assertEqual(wallpaper.rank_palette([(9000, "#0b0b0b"), (900, "#282828")], 3), ["#ffffff"])

    def test_output_is_always_full_value(self):
        rnd = random.Random(3)
        rows = [(rnd.randint(1, 900), "#%06x" % rnd.randint(0, 0xFFFFFF)) for _ in range(24)]
        for hx in wallpaper.rank_palette(rows, 6):
            self.assertEqual(max(int(hx[i:i + 2], 16) for i in (1, 3, 5)), 255, hx)

    def test_empty_input_gives_empty_palette(self):
        self.assertEqual(wallpaper.rank_palette([], 5), [])
        self.assertEqual(wallpaper.rank_palette([(5, "#000000")], 5), [])


def _hsv(hx):
    return colorsys.rgb_to_hsv(*(int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)))


def _tiers(palette):
    """'vivid' for a pushed colour (saturation at least 0.55), 'neutral' for a faint tint."""
    return ["vivid" if _hsv(p)[1] >= 0.5 else "neutral" for p in palette]


def _is_warm(hx):
    h = _hsv(hx)[0]
    return h < 0.12 or h > 0.95


class Targets(unittest.TestCase):
    def cfg(self, **kw):
        return wallpaper.normalise(kw)

    def test_default_colours_lights_that_are_on_in_every_room_once(self):
        ids = [l["id"] for l in wallpaper.choose_lights(snap(), self.cfg())]
        self.assertEqual(ids, ["L1", "L5"])  # L2 off, L3 white-only, L4 unreachable

    def test_turn_on_includes_lights_that_are_off(self):
        ids = [l["id"] for l in wallpaper.choose_lights(snap(), self.cfg(turnOn=True))]
        self.assertEqual(ids, ["L1", "L2", "L5"])

    def test_targets_limit_to_chosen_groups(self):
        ids = [l["id"] for l in wallpaper.choose_lights(snap(), self.cfg(targets=["R2"]))]
        self.assertEqual(ids, ["L5"])

    def test_commands_cycle_the_palette_and_never_set_brightness(self):
        cmds = wallpaper.build_commands(snap(), self.cfg(), ["#111111", "#222222"])
        self.assertEqual([c["hex"] for c in cmds], ["#111111", "#222222"])
        for c in cmds:
            self.assertNotIn("pct", c)
            self.assertNotIn("on", c)
            self.assertEqual(c["duration"], 2500)

    def test_turn_on_sets_on_only_for_lights_that_were_off(self):
        cmds = wallpaper.build_commands(snap(), self.cfg(turnOn=True), ["#111111"])
        self.assertEqual({c["ids"][0]: c.get("on") for c in cmds}, {"L1": None, "L2": True, "L5": None})

    def test_normalise_survives_hand_edited_junk(self):
        c = wallpaper.normalise({"enabled": "yes", "targets": "oops", "transitionMs": "slow", "extra": 1})
        self.assertEqual((c["targets"], c["transitionMs"]), ([], 2500))
        self.assertNotIn("extra", c)
        self.assertEqual(wallpaper.normalise({"transitionMs": 10 ** 9})["transitionMs"], 60000)

    def test_normalise_survives_infinite_and_huge_numbers(self):
        # settings.json with `1e999` parses to inf; int(inf) used to raise OverflowError at every start.
        for junk in (float("inf"), float("-inf"), float("nan"), 10 ** 400, "1e999", "nan", None, [], {}, True):
            ms = wallpaper.normalise({"transitionMs": junk})["transitionMs"]
            self.assertIsInstance(ms, int, junk)
            self.assertTrue(0 <= ms <= 60000, junk)
        self.assertEqual(wallpaper.normalise({"transitionMs": 1234.7})["transitionMs"], 1234)
        self.assertEqual(wallpaper.normalise({"transitionMs": -5})["transitionMs"], 0)


class ApplyReporting(unittest.TestCase):
    """One synchronous apply: what is logged and what the event says."""

    def make(self, snapshot=snap, palette=("#aa0000", "#0000bb"), **config):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        image = os.path.join(d, "3-sunset.webp")
        open(image, "w").close()
        link = os.path.join(d, "background")
        os.symlink(image, link)
        self.sent, self.events = [], []
        self.current = snapshot
        store = {"wallpaper": dict(config)}
        return wallpaper.WallpaperSync(
            snapshot=lambda: self.current() if self.current else None, submit=self.sent.append,
            emit=self.events.append, link=wallpaper.Path(link), extract=lambda path: list(palette),
            load=lambda: dict(store), save=lambda data: store.update(data))

    def test_an_apply_is_logged_and_counted(self):
        ws = self.make(enabled=True)
        with self.assertLogs("hue", "INFO") as logs:
            ws._apply()
        self.assertEqual(len(self.sent[0]), 2)
        text = "\n".join(logs.output)
        for part in ("3-sunset.webp", "2 light(s)", "#aa0000", "#0000bb"):
            self.assertIn(part, text)
        self.assertNotIn(os.path.dirname(ws._link), text)  # the basename only
        ev = self.events[-1]
        self.assertEqual((ev["appliedCount"], ev["eligible"]), (2, 2))
        self.assertIsNotNone(ev["appliedAt"])

    def test_disabled_is_a_logged_skip_with_a_preview(self):
        ws = self.make(enabled=False)
        with self.assertLogs("hue", "INFO") as logs:
            ws._apply()
        self.assertIn("disabled", "\n".join(logs.output))
        self.assertEqual(self.sent, [])
        ev = self.events[-1]
        self.assertEqual((ev["appliedCount"], ev["eligible"], ev["appliedAt"]), (0, 2, None))
        self.assertEqual(ev["palette"], ["#aa0000", "#0000bb"])

    def test_not_connected_is_a_logged_skip(self):
        ws = self.make(snapshot=None, enabled=True)
        with self.assertLogs("hue", "INFO") as logs:
            ws.sync_now()
        self.assertIn("not connected", "\n".join(logs.output))
        self.assertEqual(self.sent, [])
        self.assertEqual((self.events[-1]["appliedCount"], self.events[-1]["eligible"]), (0, 0))

    def test_no_eligible_lights_is_a_logged_skip(self):
        ws = self.make(enabled=True, targets=["R-none"])
        with self.assertLogs("hue", "INFO") as logs:
            ws._apply()
        self.assertIn("no eligible lights", "\n".join(logs.output))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.events[-1]["eligible"], 0)

    def test_a_skip_keeps_the_last_apply_count_with_its_time(self):
        ws = self.make(enabled=True)
        ws._apply()
        at = ws.applied_at
        self.current = None  # the connection drops
        ws.sync_now()
        ev = self.events[-1]
        self.assertEqual((ev["appliedCount"], ev["appliedAt"], ev["eligible"]), (2, at, 0))

    def test_eligible_is_resent_only_when_it_changes(self):
        ws = self.make(enabled=True)
        ws.event()
        ws.refresh_eligible()
        self.assertEqual(self.events, [])
        self.current = lambda: dict(snap(), lights={k: v for k, v in snap()["lights"].items() if k != "L5"})
        ws.refresh_eligible()
        self.assertEqual([e["eligible"] for e in self.events], [1])
        ws.refresh_eligible()
        self.assertEqual(len(self.events), 1)

    def test_existing_event_fields_are_unchanged(self):
        ev = self.make().event()
        self.assertEqual(set(ev), {"event", "config", "palette", "appliedAt", "appliedCount", "eligible"})
        self.assertEqual(ev["event"], "wallpaper")


SH = "#!/bin/sh\n"
MAGICK = SH + "echo '    5000: (255,0,0) #FF0000 srgb(255,0,0)'\necho '     700: (0,0,255) #0000FF blue'\necho 'not a row'\n"
FFMPEG_OK = SH + 'for a; do last="$a"; done\n: > "$last"\n'
FFMPEG_FAIL = SH + "exit 1\n"


class Extraction(unittest.TestCase):
    """The ImageMagick/ffmpeg path, with tiny fake tools on PATH (shell builtins only)."""

    def setUp(self):
        self.bin = tempfile.mkdtemp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.bin, True)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for patcher in (mock.patch.dict(os.environ, {"PATH": self.bin}), mock.patch.object(tempfile, "tempdir", self.tmp)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tool("magick", MAGICK)
        self.runs = []
        real = subprocess.run

        def spy(args, **kw):
            self.runs.append((list(args), kw))
            return real(args, **kw)
        patcher = mock.patch.object(wallpaper.subprocess, "run", side_effect=spy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tool(self, name, script):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(script)
        os.chmod(path, 0o755)

    def assert_detached_from_the_protocol(self, args, kw):
        self.assertIs(kw.get("stdin"), subprocess.DEVNULL, args)  # never reads the command pipe

    def test_histogram_rows_are_parsed_from_magick(self):
        self.assertEqual(wallpaper._histogram("/x/wall.png"), [(5000, "#FF0000"), (700, "#0000FF")])
        args, kw = self.runs[0]
        self.assertEqual((args[0], args[1]), ("magick", "/x/wall.png[0]"))
        self.assert_detached_from_the_protocol(args, kw)

    def test_an_image_palette_comes_from_magick(self):
        pal = wallpaper.extract_palette("/x/wall.png")
        self.assertEqual(pal[0], "#ff0000")
        self.assertEqual(len(self.runs), 1)

    def test_a_video_frame_comes_from_ffmpeg_detached_and_the_temp_file_is_removed(self):
        self.tool("ffmpeg", FFMPEG_OK)
        self.assertEqual(wallpaper.extract_palette("/x/clip.MP4")[0], "#ff0000")
        args, kw = self.runs[0]
        self.assertEqual(args[0], "ffmpeg")
        self.assertIn("-nostdin", args)
        self.assert_detached_from_the_protocol(args, kw)
        self.assertIs(kw.get("stdout"), subprocess.DEVNULL)  # can never write into the event stream
        self.assertEqual(os.listdir(self.tmp), [])

    def test_a_failing_ffmpeg_leaves_no_temp_file(self):
        self.tool("ffmpeg", FFMPEG_FAIL)
        with self.assertRaises(subprocess.CalledProcessError):
            wallpaper.extract_palette("/x/clip.webm")
        self.assertEqual(os.listdir(self.tmp), [])

    def test_a_missing_ffmpeg_leaves_no_temp_file(self):
        with self.assertRaises(OSError):
            wallpaper.extract_palette("/x/clip.mkv")
        self.assertEqual(os.listdir(self.tmp), [])

    def test_a_missing_magick_is_an_os_error(self):
        os.unlink(os.path.join(self.bin, "magick"))
        with self.assertRaises(OSError):
            wallpaper.extract_palette("/x/wall.png")


def wallpapers(test, *names):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d, True)
    paths = []
    for n in names:
        p = os.path.join(d, n)
        open(p, "w").close()
        paths.append(p)
    link = os.path.join(d, "bg")
    os.symlink(paths[0], link)
    return link, paths


def point(link, target):
    os.unlink(link)
    os.symlink(target, link)


def until(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


class Robustness(unittest.TestCase):
    def make(self, link, extract, snapshot=snap, enabled=True, **kw):
        self.sent, self.events = [], []
        store = {"wallpaper": {"enabled": enabled}}
        self.store = store
        ws = wallpaper.WallpaperSync(snapshot=snapshot, submit=self.sent.append, emit=self.events.append,
                                     link=wallpaper.Path(link), poll=0.02, settle=0.0, extract=extract,
                                     load=lambda: dict(store), save=lambda data: store.update(data), **kw)
        self.addCleanup(ws.stop)
        return ws

    def test_a_failed_extraction_is_not_retried_every_poll_and_is_logged_once(self):
        link, (a, b) = wallpapers(self, "a.png", "b.png")
        calls, now = [], [0.0]

        def extract(path):
            calls.append(path)
            if path == a:
                raise subprocess.CalledProcessError(1, "magick")
            return ["#0000bb"]
        ws = self.make(link, extract, clock=lambda: now[0])
        with self.assertLogs("hue", "WARNING") as logs:
            ws.start()
            time.sleep(0.4)  # about twenty polls
            self.assertEqual(calls, [a])
            now[0] += wallpaper.FAILED_RETRY + 1  # a long time later it is tried again
            self.assertTrue(until(lambda: len(calls) == 2))
            ws.sync_now()  # an explicit sync always tries
            self.assertEqual(len(calls), 3)
        self.assertEqual(len([l for l in logs.output if "palette failed" in l]), 1, logs.output)
        point(link, b)  # a new wallpaper is tried at once
        self.assertTrue(until(lambda: self.sent and self.sent[-1][0]["hex"] == "#0000bb"))

    def test_an_unexpected_extraction_error_does_not_kill_the_follower(self):
        link, (a, b) = wallpapers(self, "a.png", "b.png")

        def extract(path):
            if path == a:
                raise RuntimeError("odd")
            return ["#0000bb"]
        ws = self.make(link, extract)
        with self.assertLogs("hue", "WARNING"):
            ws.start()
            time.sleep(0.1)
        point(link, b)
        self.assertTrue(until(lambda: len(self.sent) == 1))

    def test_a_change_while_disconnected_is_applied_on_reconnect(self):
        link, (a, b) = wallpapers(self, "a.png", "b.png")
        current, calls = [None], []

        def extract(path):
            calls.append(path)
            return ["#aa0000" if path == a else "#0000bb"]
        ws = self.make(link, extract, snapshot=lambda: current[0])
        ws.start()
        self.assertTrue(until(lambda: ws.palette == ["#aa0000"]))
        point(link, b)
        self.assertTrue(until(lambda: ws.palette == ["#0000bb"]))  # the preview follows
        time.sleep(0.2)
        self.assertEqual(self.sent, [])  # nothing to paint while not connected
        current[0] = snap()
        ws.refresh_eligible()  # what the server calls when it (re)connects
        self.assertTrue(until(lambda: len(self.sent) == 1))
        self.assertEqual(self.sent[0][0]["hex"], "#0000bb")
        self.assertEqual(calls.count(b), 1)  # the palette was reused, not re-extracted
        time.sleep(0.2)
        self.assertEqual(len(self.sent), 1)

    def test_the_wallpaper_at_startup_is_painted_on_first_connect(self):
        link, _ = wallpapers(self, "a.png")
        current = [None]
        ws = self.make(link, lambda path: ["#aa0000"], snapshot=lambda: current[0])
        ws.start()
        self.assertTrue(until(lambda: ws.palette == ["#aa0000"]))
        current[0] = snap()
        ws.refresh_eligible()
        self.assertTrue(until(lambda: len(self.sent) == 1))

    def test_sync_now_and_the_follower_never_apply_at_once(self):
        link, _ = wallpapers(self, "a.png")
        active, peak = [0], [0]
        lock = threading.Lock()

        def submit(cmds):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.1)
            with lock:
                active[0] -= 1
        ws = self.make(link, lambda path: ["#aa0000"])
        ws._submit = submit
        threads = [threading.Thread(target=ws.sync_now) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(3)
        self.assertEqual(peak[0], 1)

    def test_a_settings_save_failure_raises_and_keeps_the_old_config(self):
        link, _ = wallpapers(self, "a.png")
        ws = self.make(link, lambda path: [], enabled=False)

        def fail(data):
            raise OSError("read-only")
        ws._save = fail
        with self.assertRaises(OSError):
            ws.update({"enabled": True})
        self.assertFalse(ws.config["enabled"])
        self.assertEqual(self.events, [])


class Follower(unittest.TestCase):
    def test_applies_on_change_while_enabled_and_not_otherwise(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.png"), os.path.join(d, "b.png")
            for p in (a, b):
                open(p, "w").close()
            link = os.path.join(d, "bg")
            os.symlink(a, link)
            sent, events, store = [], [], {}
            ws = wallpaper.WallpaperSync(
                snapshot=snap, submit=sent.append, emit=events.append, link=wallpaper.Path(link), poll=0.05,
                extract=lambda path: ["#aa0000" if path.endswith("a.png") else "#0000bb"],
                load=lambda: dict(store), save=lambda data: store.update(data))
            ws.start()
            try:
                self.assertTrue(self._until(lambda: ws.palette == ["#aa0000"]))
                self.assertEqual(sent, [])  # disabled: palette preview only
                ws.update({"enabled": True})
                self.assertTrue(self._until(lambda: len(sent) == 1))
                self.assertEqual(sent[0][0]["hex"], "#aa0000")
                os.unlink(link)
                os.symlink(b, link)
                self.assertTrue(self._until(lambda: len(sent) == 2, 4))
                self.assertEqual(sent[1][0]["hex"], "#0000bb")
                self.assertTrue(store["wallpaper"]["enabled"])  # persisted
            finally:
                ws.stop()

    @staticmethod
    def _until(pred, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.02)
        return False


if __name__ == "__main__":
    unittest.main()
