"""Colour the lights from the desktop wallpaper, and follow it when it changes.

The ranking and the light assignment are pure; ImageMagick (and ffmpeg for
videos) is only used to read pixels. Brightness is never touched, so syncing
cannot make a room brighter than it was set.
"""
from __future__ import annotations

import colorsys
import math
import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import colour, settings

log = logging.getLogger("hue")

LINK = Path.home() / ".local" / "state" / "omarchy" / "current" / "background"
VIDEO_SUFFIXES = (".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".gif")
DEFAULTS: Dict[str, Any] = {"enabled": False, "targets": [], "turnOn": False, "transitionMs": 2500}
FAILED_RETRY = 600.0  # seconds before a wallpaper whose palette could not be read is tried again


def _milliseconds(value: Any, default: int) -> int:
    """`value` as whole milliseconds in 0..60000; `default` for anything not a finite number."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    return int(max(0.0, min(60000.0, number)))


def normalise(config: Dict[str, Any]) -> Dict[str, Any]:
    """Defaults filled in and types forced, so a hand-edited file cannot break the sync."""
    out = dict(DEFAULTS)
    out["enabled"] = bool(config.get("enabled", out["enabled"]))
    out["turnOn"] = bool(config.get("turnOn", out["turnOn"]))
    targets = config.get("targets", out["targets"])
    out["targets"] = [t for t in targets if isinstance(t, str)] if isinstance(targets, list) else []
    out["transitionMs"] = _milliseconds(config.get("transitionMs", out["transitionMs"]), out["transitionMs"])
    return out


# Palette ranking thresholds (HSV components and shares are 0..1; chroma is s * v).
NEAR_BLACK_V = 0.12      # darker than this says nothing about the mood: ignored
HUED_MIN_S = 0.15        # below this saturation the hue is noise: a near-white/near-grey
HUED_MIN_CHROMA = 0.05   # ... and so is a dark colour with little chroma (a tinted black)
HUE_RADIUS = 0.05        # rows within this hue distance (18 degrees) are one colour family
VIVID_MIN_CHROMA = 0.10  # a family's mean chroma must reach this to count as vivid
VIVID_MIN_SHARE = 0.003  # ... and it must cover this much of the picture (not a stray speck)
MUTED_MIN_SHARE = 0.05   # a duller family still beats the neutrals when it is this common
NEUTRAL_MIN_V = 0.3      # a dark grey is not a light colour: too dark to be filler
NEUTRAL_MAX_S = 0.15     # neutrals keep only a faint tint
NEUTRAL_MIN_DIST = 24.0  # neutrals closer than this (RGB distance) are the same white


def _hue_dist(a: float, b: float) -> float:
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def _hex(h: float, s: float, v: float = 1.0) -> str:
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(h % 1.0, s, v))


def _family_colour(members: List[Tuple[float, float, float, float]]) -> Tuple[float, float, float]:
    """(score, hue, saturation) of one hue family of (hue, s, v, share) rows.

    The score is share x chroma squared summed over the family: common counts, but
    colourful counts more, so a large dark or greyish field cannot outrank the
    colour the eye actually sees. The hue is the circular mean, so a family that
    straddles red (h = 0.98 and 0.02) stays red.
    """
    weights = [share * (s * v) ** 2 for _, s, v, share in members]
    score = sum(weights) or 1e-12
    x = sum(w * math.cos(2 * math.pi * h) for w, (h, _, _, _) in zip(weights, members))
    y = sum(w * math.sin(2 * math.pi * h) for w, (h, _, _, _) in zip(weights, members))
    hue = (math.atan2(y, x) / (2 * math.pi)) % 1.0
    sat = sum(w * s for w, (_, s, _, _) in zip(weights, members)) / score
    return sum(weights), hue, sat


def rank_palette(rows: List[Tuple[int, str]], n: int = 6) -> List[str]:
    """Pick up to n mutually distinct light colours from (count, '#rrggbb') histogram rows.

    Rows are grouped into hue families. Families come out in three tiers, and a
    later tier never precedes an earlier one:

    1. vivid: colourful enough (mean chroma) and not a stray speck;
    2. muted: duller families that still cover a good part of the picture;
    3. neutral: near-white and light-grey rows, only as filler (dark greys
       only when the picture has nothing else, so a dark wallpaper still gets a colour).

    Within a tier the most representative colour comes first (share x chroma^2),
    which matters most because one light shows only the first colour. Families
    are pushed to a vivid tone at full value, since lights render pastels as
    washed-out white; neutrals keep only a faint tint. Near-black is ignored.
    The output brightness (value) is always full: brightness is never set.
    """
    total = float(sum(c for c, _ in rows)) or 1.0
    hued: List[Tuple[float, float, float, float]] = []
    neutral: List[Tuple[float, float, float, float]] = []
    for count, hx in rows:
        r, g, b = (c / 255 for c in colour.parse_hex(hx))
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if v < NEAR_BLACK_V or count <= 0:
            continue
        row = (h, s, v, count / total)
        (hued if s >= HUED_MIN_S and s * v >= HUED_MIN_CHROMA else neutral).append(row)

    # Greedy hue families, seeded by the most colourful-and-common rows.
    hued.sort(key=lambda r: r[3] * (r[1] * r[2]) ** 2, reverse=True)
    families: List[Tuple[float, List[Tuple[float, float, float, float]]]] = []
    for row in hued:
        for seed, members in families:
            if _hue_dist(seed, row[0]) <= HUE_RADIUS:
                members.append(row)
                break
        else:
            families.append((row[0], [row]))

    vivid, muted = [], []
    for _, members in families:
        share = sum(m[3] for m in members)
        mean_chroma = sum(m[3] * m[1] * m[2] for m in members) / share
        if mean_chroma >= VIVID_MIN_CHROMA and share >= VIVID_MIN_SHARE:
            vivid.append(_family_colour(members))
        elif share >= MUTED_MIN_SHARE:
            muted.append(_family_colour(members))
        else:
            neutral.extend(members)  # too dull and too rare to be the room's colour

    out: List[str] = []
    picked_hues: List[float] = []
    for _, h, s in sorted(vivid, reverse=True) + sorted(muted, reverse=True):
        if len(out) >= n:
            return out
        if all(_hue_dist(h, ph) > 0.04 for ph in picked_hues):
            picked_hues.append(h)
            out.append(_hex(h, min(1.0, max(s, 0.55) * 1.1)))

    neutral.sort(key=lambda r: r[3], reverse=True)
    if out or any(v >= NEUTRAL_MIN_V for _, _, v, _ in neutral):
        neutral = [r for r in neutral if r[2] >= NEUTRAL_MIN_V]  # dark greys only for an all-dark picture
    neutral_rgb: List[Tuple[int, int, int]] = []
    for h, s, _, _ in neutral:
        if len(out) >= n:
            break
        hx = _hex(h, min(s, NEUTRAL_MAX_S))
        rgb = colour.parse_hex(hx)
        if all(math.dist(rgb, p) >= NEUTRAL_MIN_DIST for p in neutral_rgb):
            neutral_rgb.append(rgb)
            out.append(hx)
    return out


def _histogram(image: str, colours: int = 24) -> List[Tuple[int, str]]:
    """(pixel count, '#rrggbb') rows of the image quantised to `colours` colours (ImageMagick)."""
    out = subprocess.run(
        ["magick", image + "[0]", "-resize", "256x256", "-colors", str(colours), "-depth", "8",
         "-format", "%c", "histogram:info:-"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True, timeout=30).stdout
    rows = []
    for line in out.splitlines():
        if ":" in line and "#" in line:
            rows.append((int(line.split(":")[0]), "#" + line.split("#")[1][:6]))
    return rows


def extract_palette(path: str, n: int = 6) -> List[str]:
    """The wallpaper's palette; a single frame is used for videos and GIFs.

    The tools never see the backend's stdin or stdout: those carry the protocol.
    """
    if not path.lower().endswith(VIDEO_SUFFIXES):
        return rank_palette(_histogram(path), n)
    fd, temp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", "1", "-i", path, "-frames:v", "1", temp],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=30)
        return rank_palette(_histogram(temp), n)
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass


def choose_lights(snapshot: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Colour-capable, reachable lights in the target groups (every room when none are chosen)."""
    wanted = set(config["targets"])
    seen: set = set()
    chosen = []
    for group in snapshot.get("groups", []):
        if wanted:
            if group["id"] not in wanted:
                continue
        elif group["kind"] != "room":
            continue  # zones overlap rooms; with no choice made, rooms alone cover every light
        for lid in group["lightIds"]:
            light = snapshot["lights"].get(lid)
            if not light or lid in seen or not light["color"] or not light["reachable"]:
                continue
            if not (light["on"] or config["turnOn"]):
                continue
            seen.add(lid)
            chosen.append(light)
    return chosen


def build_commands(snapshot: Dict[str, Any], config: Dict[str, Any], palette: List[str]) -> List[Dict[str, Any]]:
    """One `set` per chosen light, cycling the palette; colour only, never brightness."""
    cmds = []
    for i, light in enumerate(choose_lights(snapshot, config)):
        if not palette:
            break
        cmd: Dict[str, Any] = {"cmd": "set", "kind": "light", "ids": [light["id"]],
                               "hex": palette[i % len(palette)], "duration": config["transitionMs"]}
        if config["turnOn"] and not light["on"]:
            cmd["on"] = True
        cmds.append(cmd)
    return cmds


class WallpaperSync:
    """Owns the sync settings and, while enabled, a thread that follows the wallpaper.

    `snapshot` returns the current state snapshot, or None while not connected.
    A wallpaper that changes while not connected is painted once the
    connection is back. A wallpaper whose palette cannot be read is not
    retried until it changes or FAILED_RETRY has passed (an explicit
    `sync_now` always tries). Applies never overlap.
    """

    def __init__(self, *, snapshot: Callable[[], Optional[Dict[str, Any]]],
                 submit: Callable[[List[Dict[str, Any]]], None], emit: Callable[[Dict[str, Any]], None],
                 link: Path = LINK, poll: float = 2.0, settle: float = 0.8,
                 extract: Callable[[str], List[str]] = extract_palette,
                 load: Callable[[], Dict[str, Any]] = settings.load,
                 save: Callable[[Dict[str, Any]], None] = settings.save,
                 clock: Callable[[], float] = time.monotonic):
        self._snapshot, self._submit, self._emit = snapshot, submit, emit
        self._link, self._poll, self._settle, self._extract = link, poll, settle, extract
        self._load, self._save, self._clock = load, save, clock
        self.config = normalise(load().get("wallpaper", {}))
        self.palette: List[str] = []
        self.applied_at: Optional[float] = None
        self.applied_count = 0  # lights painted by the apply at `applied_at`
        self._eligible_sent: Optional[int] = None
        self._last: Optional[Tuple[str, float]] = None         # the wallpaper already handled
        self._palette_sig: Optional[Tuple[str, float]] = None  # the wallpaper `palette` was read from
        self._failed: Optional[Tuple[Tuple[str, float], float]] = None  # (signature, when) of a failed read
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()        # config
        self._apply_lock = threading.Lock()  # one apply at a time (follower and sync_now)

    def start(self) -> None:
        """Start following the wallpaper on a daemon thread (fills the preview at once)."""
        self._thread = threading.Thread(target=self._run, name="wallpaper", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the follower thread to exit; returns without waiting for it."""
        self._stop.set()
        self._wake.set()

    def eligible(self) -> int:
        """How many lights an apply would paint right now (0 while not connected)."""
        snap = self._snapshot()
        return len(choose_lights(snap, self.config)) if snap is not None else 0

    def event(self) -> Dict[str, Any]:
        """The `wallpaper` event (see PROTOCOL.md)."""
        eligible = self.eligible()
        self._eligible_sent = eligible
        return {"event": "wallpaper", "config": self.config, "palette": self.palette,
                "appliedAt": self.applied_at, "appliedCount": self.applied_count, "eligible": eligible}

    def refresh_eligible(self) -> None:
        """Re-send the event when the bridge state changed how many lights would be painted.

        Called by the server on every connection or state change, so it also
        wakes the follower when a wallpaper is still waiting to be painted.
        """
        if self.eligible() != self._eligible_sent:
            self._emit(self.event())
        if self.config["enabled"] and self._palette_sig is not None and self._palette_sig != self._last:
            self._wake.set()

    def update(self, partial: Dict[str, Any]) -> None:
        """Merge a partial config (unknown keys ignored), persist it, emit and re-apply.

        Raises OSError when the settings cannot be saved; the config is then unchanged.
        """
        with self._lock:
            merged = dict(self.config)
            merged.update({k: v for k, v in partial.items() if k in DEFAULTS})
            config = normalise(merged)
            data = self._load()
            data["wallpaper"] = config
            self._save(data)
            self.config = config
            self._last = None  # re-apply under the new settings
        self._emit(self.event())
        self._wake.set()

    def sync_now(self) -> None:
        """Apply the current wallpaper's colours now, even while the sync is disabled."""
        self._apply(force=True)

    def _signature(self) -> Optional[Tuple[str, float]]:
        try:
            real = os.path.realpath(self._link)
            return real, os.stat(real).st_mtime
        except OSError:
            return None

    def _backing_off(self, sig: Tuple[str, float]) -> bool:
        """True while `sig` is a wallpaper whose palette recently failed to read."""
        return self._failed is not None and self._failed[0] == sig and self._clock() - self._failed[1] < FAILED_RETRY

    def _read_palette(self, sig: Tuple[str, float], name: str) -> Optional[List[str]]:
        """The palette of wallpaper `sig` (reused when already read), or None when it cannot be read."""
        if sig == self._palette_sig:
            return self.palette
        try:
            palette = self._extract(sig[0])
        except Exception as exc:  # noqa: BLE001 - a missing tool, a bad file or anything odd: the same skip
            if self._failed is None or self._failed[0] != sig:  # once per wallpaper, not once per retry
                log.warning("wallpaper palette failed for %s: %s", name, exc.__class__.__name__)
            self._failed = (sig, self._clock())
            return None
        self._failed = None
        self.palette, self._palette_sig = palette, sig
        return palette

    def _apply(self, force: bool = False, initial: bool = False) -> None:
        with self._apply_lock:
            sig = self._signature()
            if sig is None:
                log.info("wallpaper sync skipped: no current wallpaper")
                return
            name = os.path.basename(sig[0])
            palette = self._read_palette(sig, name)
            if palette is None:
                return
            outcome = self._paint(name, palette, force)
            # Not connected: leave it unhandled so it is painted once connected,
            # including the wallpaper that was already set when the backend started.
            if outcome != "not connected":
                self._last = sig
            self._emit(self.event())

    def _paint(self, name: str, palette: List[str], force: bool) -> str:
        """Submit the colours, or log why not. Returns 'applied' or the reason it skipped."""
        if not (self.config["enabled"] or force):
            log.info("wallpaper sync skipped for %s: disabled (palette preview only)", name)
            return "disabled"
        snap = self._snapshot()
        if snap is None:
            log.info("wallpaper sync skipped for %s: not connected", name)
            return "not connected"
        if not palette:
            log.info("wallpaper sync skipped for %s: no usable colours", name)
            return "no usable colours"
        cmds = build_commands(snap, self.config, palette)
        if not cmds:
            log.info("wallpaper sync skipped for %s: no eligible lights", name)
            return "no eligible lights"
        self._submit(cmds)
        self.applied_at = time.time()
        self.applied_count = len(cmds)
        log.info("wallpaper sync applied %s to %d light(s): %s", name, len(cmds),
                 " ".join(sorted(set(c["hex"] for c in cmds), key=palette.index)))
        return "applied"

    def _step(self) -> None:
        """One poll: apply (or just preview) a wallpaper that has not been handled yet."""
        sig = self._signature()
        if sig is None or sig == self._last or self._backing_off(sig):
            return
        if not self.config["enabled"]:
            self._apply()  # keep the preview current even while the sync is off
            return
        if sig == self._palette_sig and self._snapshot() is None:
            return  # already previewed; painted once the connection is back
        self._stop.wait(self._settle)  # let a cycling wallpaper settle
        if self._signature() == sig and not self._stop.is_set():
            self._apply()

    def _guarded(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 - the follower must outlive one bad wallpaper or snapshot
            log.exception("wallpaper sync failed")

    def _run(self) -> None:
        self._guarded(lambda: self._apply(initial=True))  # fill the palette preview at start
        while not self._stop.is_set():
            self._wake.wait(self._poll)
            self._wake.clear()
            if self._stop.is_set():
                return
            self._guarded(self._step)
