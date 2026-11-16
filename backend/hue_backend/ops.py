"""Turn a UI command into bridge requests.

`plan` is pure: it reads the cache and returns the requests to send, which
makes every command testable without a bridge. Validation lives here, so
nothing from the UI reaches a URL path unchecked.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from . import colour
from .state import Cache, first, group_light_ids

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")  # fullmatch only
EFFECT_RE = re.compile(r"[a-z_]{1,40}")  # bridge effect names: candle, no_effect, sunrise, ... (fullmatch only)
RENAMEABLE = {"light": "light", "room": "room", "zone": "zone", "scene": "scene",
              "smart_scene": "smart_scene", "device": "device"}
ENABLEABLE = {"motion", "camera_motion", "light_level", "temperature", "contact"}
POWERUP_PRESETS = {"safety", "powerfail", "last_on_state"}
SCENE_MODES = {"active", "dynamic_palette", "static"}


class InvalidCommand(ValueError):
    """The command is malformed; the UI gets code `invalid`."""


class Request(NamedTuple):
    method: str
    path: str
    body: Optional[Dict[str, Any]]
    klass: str  # rate-limit class: 'light', 'group' or ''


def _id(value: Any) -> str:
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise InvalidCommand("not a resource id: %r" % (value,))
    return value


def _effect(value: Any) -> str:
    if not isinstance(value, str) or not EFFECT_RE.fullmatch(value):
        raise InvalidCommand("not an effect name")
    return value


def _ids(value: Any) -> List[str]:
    if not isinstance(value, list) or not value:
        raise InvalidCommand("expected a non-empty list of ids")
    return [_id(v) for v in value]


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 32:
        raise InvalidCommand("a name must be 1-32 characters")
    return value.strip()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _set(cmd: Dict[str, Any], cache: Cache) -> List[Request]:
    kind = cmd.get("kind", "light")
    if kind not in ("light", "group"):
        raise InvalidCommand("kind must be light or group")
    out: List[Request] = []
    for rid in _ids(cmd.get("ids")):
        body: Dict[str, Any] = {}
        light = cache.get(rid) if kind == "light" else None
        if cmd.get("identify") and kind == "light":
            body = {"identify": {"action": "identify"}}
        else:
            if cmd.get("on") is not None:
                body["on"] = {"on": bool(cmd["on"])}
            if cmd.get("pct") is not None:
                body["dimming"] = {"brightness": _clamp(float(cmd["pct"]), 1.0, 100.0)}
            if cmd.get("hex"):
                gamut = colour.gamut_from_api((light or {}).get("color"))
                x, y = colour.hex_to_xy(str(cmd["hex"]), gamut)
                body["color"] = {"xy": {"x": x, "y": y}}
            elif cmd.get("mirek"):
                schema = first(light, "color_temperature", "mirek_schema", default={}) if light else {}
                lo = schema.get("mirek_minimum", 153)
                hi = schema.get("mirek_maximum", 500)
                body["color_temperature"] = {"mirek": int(_clamp(int(cmd["mirek"]), lo, hi))}
            if cmd.get("effect") and kind == "light":
                body["effects_v2"] = {"action": {"effect": _effect(cmd["effect"])}}
            if isinstance(cmd.get("timed"), dict) and kind == "light":
                t = cmd["timed"]
                body["timed_effects"] = {"effect": _effect(t.get("effect")), "duration": int(t.get("duration", 600000))}
            if cmd.get("duration") is not None:
                body["dynamics"] = {"duration": int(cmd["duration"])}
        if not body:
            raise InvalidCommand("nothing to set")
        rtype = "light" if kind == "light" else "grouped_light"
        out.append(Request("PUT", "resource/%s/%s" % (rtype, rid), body, "light" if kind == "light" else "group"))
    return out


def _snapshot_actions(cache: Cache, group_id: str) -> List[Dict[str, Any]]:
    group = cache.get(group_id)
    if not group or group.get("type") not in ("room", "zone"):
        raise InvalidCommand("room or zone not found")
    actions = []
    for lid in group_light_ids(cache, group):
        raw = cache.get(lid) or {}
        act: Dict[str, Any] = {"on": {"on": bool(first(raw, "on", "on", default=False))}}
        if "dimming" in raw:
            act["dimming"] = {"brightness": max(1.0, float(first(raw, "dimming", "brightness", default=100.0)))}
        ct = raw.get("color_temperature")
        if ct and ct.get("mirek_valid") and ct.get("mirek"):
            act["color_temperature"] = {"mirek": ct["mirek"]}
        elif first(raw, "color", "xy"):
            act["color"] = {"xy": raw["color"]["xy"]}
        actions.append({"target": {"rid": lid, "rtype": "light"}, "action": act})
    if not actions:
        raise InvalidCommand("that room or zone has no lights")
    return actions


def _scene_recall(cmd: Dict[str, Any], cache: Cache) -> List[Request]:
    mode = cmd.get("mode", "active")
    if mode not in SCENE_MODES:
        raise InvalidCommand("unknown scene mode")
    recall: Dict[str, Any] = {"action": mode}
    if cmd.get("duration") is not None:
        recall["duration"] = int(cmd["duration"])
    if cmd.get("pct") is not None:
        recall["dimming"] = {"brightness": _clamp(float(cmd["pct"]), 1.0, 100.0)}
    return [Request("PUT", "resource/scene/%s" % _id(cmd.get("id")), {"recall": recall}, "")]


def _scene_create(cmd: Dict[str, Any], cache: Cache) -> List[Request]:
    gid = _id(cmd.get("group"))
    group = cache.get(gid) or {}
    return [Request("POST", "resource/scene", {
        "metadata": {"name": _name(cmd.get("name"))},
        "group": {"rid": gid, "rtype": group.get("type", "room")},
        "actions": _snapshot_actions(cache, gid),
        "auto_dynamic": False,
    }, "")]


def _scene_update(cmd: Dict[str, Any], cache: Cache) -> List[Request]:
    sid = _id(cmd.get("id"))
    body: Dict[str, Any] = {}
    if cmd.get("name"):
        body["metadata"] = {"name": _name(cmd["name"])}
    if cmd.get("speed") is not None:
        body["speed"] = _clamp(float(cmd["speed"]), 0.0, 1.0)
    if cmd.get("autoDynamic") is not None:
        body["auto_dynamic"] = bool(cmd["autoDynamic"])
    if cmd.get("snapshot"):
        scene = cache.get(sid) or {}
        body["actions"] = _snapshot_actions(cache, first(scene, "group", "rid", default=""))
    if not body:
        raise InvalidCommand("nothing to update")
    return [Request("PUT", "resource/scene/%s" % sid, body, "")]


def _rename(cmd: Dict[str, Any], cache: Cache) -> List[Request]:
    rtype = RENAMEABLE.get(str(cmd.get("rtype")))
    if not rtype:
        raise InvalidCommand("cannot rename that kind of resource")
    rid = _id(cmd.get("id"))
    if rtype == "light":  # the Hue app names the device; the light follows it
        owner = first(cache.get(rid), "owner", "rid", default="")
        if owner:
            rtype, rid = "device", _id(owner)
    return [Request("PUT", "resource/%s/%s" % (rtype, rid), {"metadata": {"name": _name(cmd.get("name"))}}, "")]


def _children(ids: List[str]) -> List[Dict[str, str]]:
    return [{"rid": i, "rtype": "light"} for i in ids]


PLANNERS: Dict[str, Callable[[Dict[str, Any], Cache], List[Request]]] = {
    "set": _set,
    "scene.recall": _scene_recall,
    "scene.create": _scene_create,
    "scene.update": _scene_update,
    "scene.delete": lambda c, k: [Request("DELETE", "resource/scene/%s" % _id(c.get("id")), None, "")],
    "smartScene": lambda c, k: [Request("PUT", "resource/smart_scene/%s" % _id(c.get("id")),
                                        {"recall": {"action": "deactivate" if c.get("action") == "deactivate" else "activate"}}, "")],
    "automation": lambda c, k: [Request("PUT", "resource/behavior_instance/%s" % _id(c.get("id")),
                                        {"enabled": bool(c.get("enabled"))}, "")],
    "rename": _rename,
    "powerup": lambda c, k: [Request("PUT", "resource/light/%s" % _id(c.get("id")), {"powerup": {"preset": p}}, "")
                             for p in [str(c.get("preset"))] if p in POWERUP_PRESETS] or _bad("unknown power-up preset"),
    "zone.create": lambda c, k: [Request("POST", "resource/zone", {
        "metadata": {"name": _name(c.get("name")), "archetype": "other"}, "children": _children(_ids(c.get("lights")))}, "")],
    "zone.members": lambda c, k: [Request("PUT", "resource/zone/%s" % _id(c.get("id")),
                                          {"children": _children(_ids(c.get("lights")))}, "")],
    "zone.delete": lambda c, k: [Request("DELETE", "resource/zone/%s" % _id(c.get("id")), None, "")],
    "enable": lambda c, k: [Request("PUT", "resource/%s/%s" % (c.get("rtype"), _id(c.get("id"))), {"enabled": bool(c.get("enabled"))}, "")]
    if c.get("rtype") in ENABLEABLE else _bad("that resource cannot be enabled or disabled"),
    "entertainment.stop": lambda c, k: [Request("PUT", "resource/entertainment_configuration/%s" % _id(c.get("id")), {"action": "stop"}, "")],
}


def _bad(message: str) -> List[Request]:
    raise InvalidCommand(message)


def plan(cmd: Dict[str, Any], cache: Cache) -> List[Request]:
    """The bridge requests for a UI command; raises InvalidCommand when it is malformed."""
    planner = PLANNERS.get(str(cmd.get("cmd")))
    if planner is None:
        raise InvalidCommand("unknown command: %s" % cmd.get("cmd"))
    try:
        return planner(cmd, cache)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, InvalidCommand):
            raise
        raise InvalidCommand("malformed command (%s)" % exc.__class__.__name__) from None
