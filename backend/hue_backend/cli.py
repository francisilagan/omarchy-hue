"""One-shot commands for scripts (bar scripts and other tools): `status`, `toggle`, `room`, `scene`.

They reuse the paired credentials, pinned TLS client, rate limits and command
planner of the long-lived service, but open their own short connection: the
service speaks only over its stdin/stdout pipe to the shell, so a script cannot
route through it. Output formats are a compatibility contract with the old
`openhue`-based scripts (see tests/test_cli.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Dict, List, Optional, TextIO

from . import credentials, ops
from .bridge import BridgeClient, BridgeError
from .state import Cache, build_snapshot

TIMEOUT = 8.0
# Nerd Font glyphs: bulb on U+F06E8, bulb off U+F0E4F, offline U+F06E9.
ICON_ON, ICON_OFF, ICON_OFFLINE = "\U000f06e8", "\U000f0e4f", "\U000f06e9"



class CliError(Exception):
    """A usage or lookup problem; the message goes to stderr and the exit status is 1."""


def offline_status() -> str:
    """What the bar shows when the bridge cannot be read."""
    return json.dumps({"text": ICON_OFFLINE + " --", "tooltip": "Hue bridge unreachable", "class": "offline"})


def status_line(snapshot: Dict[str, Any]) -> str:
    """The bar's JSON: '<lights on>/<total>' plus a per-room tooltip."""
    # Rooms in the bridge's own order (what `openhue` listed); lights without a room come last.
    lights = snapshot.get("lights", {})
    rooms: Dict[str, List[int]] = {}
    seen = set()
    for group in snapshot.get("groups", []):
        if group.get("kind") != "room":
            continue
        for lid in group.get("lightIds", []):
            if lid in lights and lid not in seen:
                seen.add(lid)
                counts = rooms.setdefault(group.get("name", "?"), [0, 0])
                counts[1] += 1
                counts[0] += bool(lights[lid].get("on"))
    for lid, light in lights.items():
        if lid not in seen:
            counts = rooms.setdefault("?", [0, 0])
            counts[1] += 1
            counts[0] += bool(light.get("on"))
    n_on = sum(v[0] for v in rooms.values())
    total = sum(v[1] for v in rooms.values())
    tip = "\n".join("%s: %d/%d on" % (r, a, b) for r, (a, b) in rooms.items()) + "\n\nClick: toggle all lights"
    return json.dumps({"text": "%s %d/%d" % (ICON_ON if n_on else ICON_OFF, n_on, total),
                       "tooltip": tip, "class": "on" if n_on else "off"})


def _room_groups(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [g for g in snapshot.get("groups", []) if g.get("kind") == "room" and g.get("group")]


def toggle_command(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Any light on: everything off; otherwise everything on."""
    ids = [g["group"] for g in _room_groups(snapshot)]
    if not ids:
        raise CliError("the bridge has no rooms")
    any_on = any(l.get("on") for l in snapshot.get("lights", {}).values())
    return {"cmd": "set", "kind": "group", "ids": ids, "on": not any_on}


def room_command(snapshot: Dict[str, Any], room_ids: List[str], on: Optional[bool], pct: Optional[float]) -> Dict[str, Any]:
    """A group `set` for room ids (not grouped_light ids); raises CliError for an unknown room."""
    by_id = {g["id"]: g["group"] for g in _room_groups(snapshot)}
    missing = [r for r in room_ids if r not in by_id]
    if missing:
        raise CliError("no such room: %s" % missing[0])
    cmd: Dict[str, Any] = {"cmd": "set", "kind": "group", "ids": [by_id[r] for r in room_ids]}
    if on is not None:
        cmd["on"] = on
    if pct is not None:
        cmd["pct"] = pct
    return cmd


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backend", description="One-shot Hue commands for scripts.")
    sub = p.add_subparsers(dest="name", required=True)
    sub.add_parser("status", help="bar JSON: lights on / total, per-room tooltip")
    sub.add_parser("toggle", help="any light on: all rooms off, otherwise all on")
    room = sub.add_parser("room", help="switch and/or dim rooms")
    room.add_argument("ids", nargs="+", metavar="ROOM_ID")
    state = room.add_mutually_exclusive_group()
    state.add_argument("--on", action="store_true")
    state.add_argument("--off", action="store_true")
    room.add_argument("--brightness", type=float, metavar="PCT")
    scene = sub.add_parser("scene", help="recall a scene")
    scene.add_argument("id", metavar="SCENE_ID")
    return p


def run(argv: List[str], *, out: TextIO = sys.stdout, err: TextIO = sys.stderr,
        load_credentials: Callable[[], Optional[credentials.Credentials]] = credentials.load,
        client_factory: Callable[..., BridgeClient] = BridgeClient) -> int:
    """Run one script command; returns the process exit status."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    quiet = args.name == "status"  # the bar must always get JSON on stdout and a clean exit
    client = None
    try:
        creds = load_credentials()
        if creds is None:
            raise BridgeError("unpaired", "not paired with a bridge (open the Hue panel to pair)")
        client = client_factory(creds, timeout=TIMEOUT)
        cache = Cache()
        if args.name == "scene":
            cmd: Dict[str, Any] = {"cmd": "scene.recall", "id": args.id, "mode": "active"}
        else:
            cache.load(client.resources())
            snapshot = build_snapshot(cache)
            if args.name == "status":
                out.write(status_line(snapshot) + "\n")
                return 0
            if args.name == "toggle":
                cmd = toggle_command(snapshot)
            else:
                if args.on is False and args.off is False and args.brightness is None:
                    raise CliError("room needs --on, --off or --brightness")
                cmd = room_command(snapshot, args.ids, True if args.on else False if args.off else None, args.brightness)
        for req in ops.plan(cmd, cache):
            client.request(req.method, req.path, req.body, req.klass)
        return 0
    except Exception as exc:  # noqa: BLE001 - scripts get one line, never a traceback
        if quiet:
            out.write(offline_status() + "\n")
            return 0
        detail = exc.message if isinstance(exc, BridgeError) else str(exc) or exc.__class__.__name__
        err.write("hue: %s\n" % detail)
        return 1
    finally:
        if client is not None:
            client.close()
