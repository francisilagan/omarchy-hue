"""The bridge's resources, kept current from its event stream, and the UI snapshot built from them.

Everything here is pure and synchronous (the Cache has a lock for its own
data only), so it is tested against recorded bridge payloads.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import colour

log = logging.getLogger("hue")

Resource = Dict[str, Any]
PALETTE_KEYS = ("color", "dimming", "color_temperature", "effects", "effects_v2")


def deep_merge(base: Any, patch: Any) -> Any:
    """Merge a bridge 'update' patch into a resource. Dicts merge, everything else replaces."""
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            out[k] = deep_merge(base.get(k), v) if k in base else v
        return out
    return patch


class Cache:
    """All bridge resources by id, updated from event batches."""

    def __init__(self) -> None:
        self._items: Dict[str, Resource] = {}
        self._lock = threading.RLock()

    def load(self, resources: Iterable[Resource]) -> None:
        """Replace everything with a full resource listing (items without an id are dropped)."""
        with self._lock:
            self._items = {r["id"]: r for r in resources if isinstance(r, dict) and "id" in r}

    def apply_events(self, batch: Iterable[dict]) -> bool:
        """Apply a batch of bridge events. Returns True when anything changed."""
        changed = False
        with self._lock:
            for event in batch:
                if not isinstance(event, dict) or not isinstance(event.get("data"), list):
                    continue
                kind = event.get("type")
                for item in event["data"]:
                    rid = item.get("id") if isinstance(item, dict) else None
                    if not rid or not isinstance(rid, str):
                        continue
                    if kind == "add":
                        self._items[rid] = item
                        changed = True
                    elif kind == "update" and rid in self._items:
                        self._items[rid] = deep_merge(self._items[rid], item)
                        changed = True
                    elif kind == "delete" and rid in self._items:
                        del self._items[rid]
                        changed = True
        return changed

    def get(self, rid: str) -> Optional[Resource]:
        """One resource by id, or None."""
        with self._lock:
            return self._items.get(rid)

    def of_type(self, rtype: str) -> List[Resource]:
        """Every resource of one CLIP type (e.g. 'light')."""
        with self._lock:
            return [r for r in self._items.values() if r.get("type") == rtype]

    def snapshot_items(self) -> Dict[str, Resource]:
        """A shallow copy of all resources, safe to read without the lock."""
        with self._lock:
            return dict(self._items)


def first(d: Any, *path: str, default: Any = None) -> Any:
    """Follow `path` through nested dicts; `default` when a step is missing or the value is None."""
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return default if d is None else d


def service(dev: Resource, rtype: str) -> Optional[str]:
    """The id of the device's first service of `rtype`, or None."""
    for s in dev.get("services", []):
        if s.get("rtype") == rtype:
            return s.get("rid")
    return None


def lights_of_device(cache: Cache) -> Dict[str, List[str]]:
    """device id -> every light it owns (a device can own several)."""
    out: Dict[str, List[str]] = {}
    for light in cache.of_type("light"):
        out.setdefault(first(light, "owner", "rid", default=""), []).append(light["id"])
    return out


def group_light_ids(cache: Cache, group: Resource) -> List[str]:
    """Light ids in a room (via its devices) or a zone (directly)."""
    by_dev = lights_of_device(cache)
    ids: List[str] = []
    for child in group.get("children", []):
        if child.get("rtype") == "light":
            ids.append(child["rid"])
        elif child.get("rtype") == "device":
            ids.extend(by_dev.get(child["rid"], []))
    return ids


def _light_view(light: Resource, device: Resource, reachable: bool) -> Resource:
    """A light as the snapshot shows it (see PROTOCOL.md, `lights`)."""
    ct = light.get("color_temperature")
    mirek_valid = bool(ct and ct.get("mirek_valid") and ct.get("mirek"))
    col = light.get("color")
    if mirek_valid:
        hx: Optional[str] = colour.mirek_to_hex(ct["mirek"])  # type: ignore[index]
    elif col and col.get("xy"):
        hx = colour.xy_to_hex(col["xy"]["x"], col["xy"]["y"])
    else:
        hx = None
    eff = light.get("effects_v2") or {}
    timed = light.get("timed_effects") or {}
    return {
        "id": light["id"],
        "name": first(light, "metadata", "name", default="Light"),
        "archetype": first(light, "metadata", "archetype", default=""),
        "on": bool(first(light, "on", "on", default=False)),
        "brightness": round(first(light, "dimming", "brightness", default=100)),
        "dimmable": "dimming" in light,
        "reachable": reachable,
        "color": col is not None,
        "ct": ct is not None,
        "mirek": ct["mirek"] if mirek_valid else None,  # type: ignore[index]
        "mirekMin": first(ct, "mirek_schema", "mirek_minimum", default=153) if ct else 153,
        "mirekMax": first(ct, "mirek_schema", "mirek_maximum", default=500) if ct else 500,
        "hex": hx,
        "effects": [e for e in (first(eff, "action", "effect_values", default=[]) or []) if e != "no_effect"],
        "effect": first(eff, "status", "effect", default="no_effect"),
        "timedEffects": [e for e in (first(timed, "status_values", default=[]) or []) if e != "no_effect"],
        "timedEffect": first(timed, "status", "effect", default="no_effect") if timed else "no_effect",
        "gradient": "gradient" in light,
        "powerup": first(light, "powerup", "preset", default=None),
        "product": first(device, "product_data", "product_name", default=""),
        "device": device.get("id", ""),
    }


def _readings(device: Resource, cache_items: Dict[str, Resource]) -> Dict[str, Any]:
    """A device's sensor and button readings plus its switchable sensor controls."""
    readings: List[Dict[str, str]] = []
    controls: List[Dict[str, Any]] = []
    buttons: Dict[int, str] = {}
    for s in device.get("services", []):
        o = cache_items.get(s.get("rid", ""))
        if not o:
            continue
        t = o.get("type")
        if t in ("motion", "camera_motion"):
            moving = bool(first(o, "motion", "motion", default=False)
                          or first(o, "motion", "motion_report", "motion", default=False))
            readings.append({"label": "Motion", "value": "detected" if moving else "clear"})
            controls.append({"rtype": t, "id": o["id"], "label": "Motion sensing", "enabled": bool(o.get("enabled", True))})
        elif t == "temperature":
            v = first(o, "temperature", "temperature_report", "temperature", default=first(o, "temperature", "temperature"))
            if isinstance(v, (int, float)):
                readings.append({"label": "Temperature", "value": "%.1f °C" % v})
        elif t == "light_level":
            v = first(o, "light", "light_level_report", "light_level", default=first(o, "light", "light_level"))
            if isinstance(v, (int, float)):
                readings.append({"label": "Light", "value": "%d lux" % round(10 ** ((v - 1) / 10000.0))})
        elif t == "contact":
            readings.append({"label": "Contact", "value": str(first(o, "contact_report", "state", default="?"))})
        elif t == "button":
            event = first(o, "button", "button_report", "event", default=first(o, "button", "last_event"))
            if event:
                buttons[int(first(o, "metadata", "control_id", default=len(buttons) + 1))] = str(event)
    for number in sorted(buttons):
        readings.append({"label": "Button %d" % number, "value": buttons[number]})
    return {"readings": readings, "controls": controls}


_warned: set = set()


def _views(resources: Iterable[Resource], view: Callable[[Resource], Any]) -> List[Any]:
    """`view` of each resource, skipping (and logging once) any that a bad value makes fail.

    One malformed resource, e.g. a non-numeric brightness from an event, must
    not stop the whole snapshot from being built.
    """
    out = []
    for r in resources:
        try:
            out.append(view(r))
        except Exception as exc:  # noqa: BLE001 - any bad value in one resource
            key = (r.get("type"), r.get("id"), exc.__class__.__name__)
            if key not in _warned:
                _warned.add(key)
                log.warning("skipped a malformed %s resource (%s)", r.get("type"), exc.__class__.__name__)
    return out


def build_snapshot(cache: Cache) -> Resource:
    """The normalised, id-keyed view of the bridge described in PROTOCOL.md."""
    items = cache.snapshot_items()

    def of(t: str) -> List[Resource]:
        return [r for r in items.values() if r.get("type") == t]

    devices = {d["id"]: d for d in of("device")}
    zigbee = {z["id"]: z for z in of("zigbee_connectivity")}
    power = {p["id"]: p for p in of("device_power")}
    updates = {first(u, "owner", "rid", default=""): u for u in of("device_software_update")}

    def reachable(dev: Resource) -> bool:
        z = zigbee.get(service(dev, "zigbee_connectivity") or "")
        return True if z is None else z.get("status") == "connected"

    def light_view(l: Resource) -> Resource:
        dev = devices.get(first(l, "owner", "rid", default=""), {})
        return _light_view(l, dev, reachable(dev))

    lights: Dict[str, Resource] = {v["id"]: v for v in _views(of("light"), light_view)}

    def scene_view(s: Resource) -> Resource:
        state = first(s, "status", "active", default="inactive")
        palette = s.get("palette") or {}
        return {
            "id": s["id"], "name": first(s, "metadata", "name", default="Scene"),
            "group": first(s, "group", "rid", default=""),
            "active": state != "inactive", "mode": state, "speed": s.get("speed", 0.5),
            "autoDynamic": bool(s.get("auto_dynamic")),
            "dynamic": any(bool(palette.get(k)) for k in PALETTE_KEYS),
            "lights": len(s.get("actions", [])),
        }

    scenes: Dict[str, Resource] = {}
    scenes_of: Dict[str, List[str]] = {}
    for view in _views(of("scene"), scene_view):
        scenes[view["id"]] = view
        scenes_of.setdefault(view["group"], []).append(view["id"])
    smart: Dict[str, Resource] = {}
    smart_of: Dict[str, List[str]] = {}
    for s in of("smart_scene"):
        gid = first(s, "group", "rid", default="")
        smart[s["id"]] = {"id": s["id"], "name": first(s, "metadata", "name", default="Routine"),
                          "group": gid, "active": s.get("state") == "active"}
        smart_of.setdefault(gid, []).append(s["id"])

    def group_view(g: Resource, kind: str) -> Resource:
        gl = items.get(service(g, "grouped_light") or "", {})
        return {
            "id": g["id"], "kind": kind, "name": first(g, "metadata", "name", default="Group"),
            "archetype": first(g, "metadata", "archetype", default=""),
            "group": gl.get("id", ""), "on": bool(first(gl, "on", "on", default=False)),
            "lightIds": [i for i in group_light_ids(cache, g) if i in lights],
            "sceneIds": scenes_of.get(g["id"], []), "smartSceneIds": smart_of.get(g["id"], []),
        }

    groups = _views(of("room"), lambda r: group_view(r, "room")) + _views(of("zone"), lambda z: group_view(z, "zone"))

    home = (of("bridge_home") or [{}])[0]
    bridge_res = (of("bridge") or [{}])[0]
    bridge_dev = next((d for d in devices.values() if first(d, "product_data", "product_archetype") == "bridge_v2"), {})

    owned = {l["device"] for l in lights.values()}

    def accessory(d: Resource) -> Resource:
        item: Resource = {
            "id": d["id"], "name": first(d, "metadata", "name", default="Device"),
            "product": first(d, "product_data", "product_name", default=""),
            "software": first(d, "product_data", "software_version", default=""),
            "bridge": first(d, "product_data", "product_archetype", default="") == "bridge_v2",
            "reachable": reachable(d),
        }
        level = first(power.get(service(d, "device_power") or "", {}), "power_state", "battery_level")
        if isinstance(level, (int, float)):
            item["battery"] = level
        update = updates.get(d["id"])
        if update:
            item["update"] = update.get("state", "no_update")
        item.update(_readings(d, items))
        return item

    accessories = _views([d for dev_id, d in devices.items() if dev_id not in owned], accessory)
    accessories.sort(key=lambda a: (not a["bridge"], str(a["name"]).lower()))

    scripts = {s["id"]: s for s in of("behavior_script")}
    automations = []
    for b in of("behavior_instance"):
        script = scripts.get(b.get("script_id", ""), {})
        automations.append({
            "id": b["id"], "enabled": bool(b.get("enabled")), "status": b.get("status", ""),
            "name": first(b, "metadata", "name") or first(script, "metadata", "name") or "Automation",
            "script": first(script, "metadata", "name", default=""),
        })

    entertainment = [{
        "id": e["id"], "name": first(e, "metadata", "name", default="Entertainment"),
        "status": e.get("status", "inactive"), "type": e.get("configuration_type", ""),
        "lights": len(e.get("light_services", [])),
    } for e in of("entertainment_configuration")]

    return {
        "bridge": {"id": bridge_res.get("bridge_id", ""), "name": first(bridge_dev, "metadata", "name", default="Hue Bridge")},
        "homeGroup": service(home, "grouped_light") or "",
        "groups": groups, "lights": lights, "scenes": scenes, "smartScenes": smart,
        "automations": automations, "devices": accessories, "entertainment": entertainment,
    }
