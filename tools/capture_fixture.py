#!/usr/bin/env python3
"""Record the paired bridge's resources as a sanitised test fixture, or check one.

    python3 tools/capture_fixture.py tests/fixtures/bridge_resource.json      # capture (needs pairing)
    python3 tools/capture_fixture.py --sanitise FILE                           # re-sanitise FILE in place
    python3 tools/capture_fixture.py --check FILE                              # exit 1 if FILE looks private

The fixture is committed to a public repository, so `sanitise` keeps only the
shape of the household and scrubs everything that identifies it:

* Resources of the types in DROP (geolocation, geofence clients, HomeKit,
  Matter, Zigbee discovery, motion area candidates) are removed entirely.
* `id_v1` is removed; `bridge_id` becomes "0123456789abcdef".
* Every UUID anywhere in the document (resource ids, every `rid` reference,
  `script_id`, and UUIDs embedded inside any other string or key) is replaced
  by a fake one, FAKE_UUID_PREFIX followed by the first 12 hex digits of the
  SHA-256 of the original. The same original always maps to the same fake, so
  references stay resolvable (and dangling references stay dangling); fakes are
  left as they are, so sanitising twice changes nothing.
* `metadata.name` and any top-level `name` of a resource become "<Type> <n>"
  (e.g. "Light 3"), except the bridge device ("Hue Bridge") and behavior
  scripts, whose names are Philips' fixed catalogue.
* `mac_address` becomes 00:17:88:01:00:00:00:<index>; `extended_pan_id` zeros.
* Every `time_zone` string becomes "UTC".
* Every ISO timestamp (e.g. a scene's `last_recall`) becomes PLACEHOLDER_TIME.
* Schedules: every clock time ({"hour", "minute"[, "second"]}) in a resource is
  replaced, in document order, by the round hours in GENERIC_HOURS with zero
  minutes and seconds; a time that belongs to a sunrise/sunset start keeps its
  keyword and becomes 00:00; every `offset` (minutes before/after sunset)
  becomes 0. Recurrence days and the number of timeslots are kept.
* Entertainment positions (any {"x", "y", "z"} point) become 0, 0, 0.

Structure, counts, capabilities, product data and software versions are kept:
that is what the tests need. `--check` fails on anything that should not be
there (see `problems`): a UUID outside the fake namespace, a MAC outside the
fake range, an IPv4/IPv6 address, a non-UTC time zone, an ISO date other than
the placeholder, an email-like string, a resource name that is not generic, a
non-generic schedule time or offset, or a non-zero entertainment position.
"""
import hashlib
import ipaddress
import json
import os
import re
import sys

DROP = {"geolocation", "geofence_client", "homekit", "matter", "zigbee_device_discovery", "motion_area_candidate"}

FAKE_UUID_PREFIX = "00000000-0000-4000-8000-"
FAKE_MAC_PREFIX = "00:17:88:01:00:00:00:"
FAKE_BRIDGE_ID = "0123456789abcdef"
PLACEHOLDER_TIME = "2000-01-01T00:00:00.000Z"
NEUTRAL_TIME_ZONE = "UTC"
GENERIC_HOURS = (8, 12, 18, 21, 23, 0)
KEPT_NAMES = {"Hue Bridge"}

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
DATE_RE = re.compile(r"(19|20)\d{2}-\d{2}-\d{2}")
MAC_RE = re.compile(r"\b[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5,7}\b")
IPV4_RE = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")
IPV6_CANDIDATE_RE = re.compile(r"[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
GENERIC_NAME_RE = re.compile(r"^[A-Z][a-z]*( [A-Z][a-z]*)* \d+$")


def fake_uuid(original):
    """The deterministic stand-in for one real UUID (fakes map to themselves)."""
    original = original.lower()
    if original.startswith(FAKE_UUID_PREFIX):
        return original
    return FAKE_UUID_PREFIX + hashlib.sha256(original.encode()).hexdigest()[:12]


def _remap_strings(o):
    if isinstance(o, dict):
        return {_remap_strings(k): _remap_strings(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_remap_strings(v) for v in o]
    if isinstance(o, str):
        o = UUID_RE.sub(lambda m: fake_uuid(m.group(0)), o)
        return TIMESTAMP_RE.sub(PLACEHOLDER_TIME, o)
    return o


def _is_clock(o):
    return isinstance(o, dict) and "hour" in o and "minute" in o


def _is_point(o):
    return isinstance(o, dict) and {"x", "y", "z"} <= set(o) and all(isinstance(o[k], (int, float)) for k in "xyz")


def _scrub_values(o, hours):
    """Time zones, clock times, offsets and positions, in place. `hours` is the per-resource sequence."""
    if isinstance(o, list):
        for v in o:
            _scrub_values(v, hours)
        return
    if not isinstance(o, dict):
        return
    if _is_point(o):
        for axis in "xyz":
            o[axis] = 0.0
        return
    if _is_clock(o):  # a bare clock time (one inside a list); keyed ones are handled below
        o.update({k: 0 for k in ("minute", "second") if k in o}, hour=next(hours))
        return
    solar = o.get("kind") in ("sunset", "sunrise") or o.get("type") in ("sunset", "sunrise")
    for k, v in o.items():
        if k == "time_zone" and isinstance(v, str):
            o[k] = NEUTRAL_TIME_ZONE
        elif k == "offset" and isinstance(v, dict):
            for unit in v:
                if isinstance(v[unit], (int, float)):
                    v[unit] = 0
        elif _is_clock(v):
            v["hour"] = 0 if solar else next(hours)
            v["minute"] = 0
            if "second" in v:
                v["second"] = 0
        else:
            _scrub_values(v, hours)


def _cycle(values):
    while True:
        yield from values


def sanitise(resources):
    counters = {}
    out = []
    for r in resources:
        if r["type"] in DROP:
            continue
        r = json.loads(json.dumps(r))
        meta = r.get("metadata")
        generic = None
        if r["type"] != "behavior_script":
            n = counters[r["type"]] = counters.get(r["type"], 0) + 1
            generic = "%s %d" % (r["type"].replace("_", " ").title(), n)
        if isinstance(meta, dict) and "name" in meta and generic:
            if (r.get("product_data") or {}).get("product_archetype") != "bridge_v2":
                meta["name"] = generic
        if "name" in r and generic:
            r["name"] = generic
        if "bridge_id" in r:
            r["bridge_id"] = FAKE_BRIDGE_ID
        r.pop("id_v1", None)
        # Real hardware identifiers of the Zigbee network and its devices.
        if "mac_address" in r:
            r["mac_address"] = FAKE_MAC_PREFIX + "%02x" % len(out)
        if "extended_pan_id" in r:
            r["extended_pan_id"] = "0000000000000000"
        _scrub_values(r, _cycle(GENERIC_HOURS))
        out.append(r)
    out = _remap_strings(out)
    ids = [r["id"] for r in out]
    if len(ids) != len(set(ids)):
        raise ValueError("fake UUID collision")
    return out


def _strings(o, path="$"):
    """Every (path, string) in the document, keys included."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield path, k
            yield from _strings(v, "%s.%s" % (path, k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _strings(v, "%s[%d]" % (path, i))
    elif isinstance(o, str):
        yield path, o


def _nodes(o, path="$"):
    yield path, o
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _nodes(v, "%s.%s" % (path, k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _nodes(v, "%s[%d]" % (path, i))


def problems(resources):
    """Everything in a fixture that looks private; empty when it is safe to publish."""
    found = []
    for path, s in _strings(resources):
        for m in UUID_RE.findall(s):
            if not m.lower().startswith(FAKE_UUID_PREFIX):
                found.append("%s: UUID outside the fake namespace: %s" % (path, m))
        macs = MAC_RE.findall(s)
        for m in macs:
            if not m.lower().startswith(FAKE_MAC_PREFIX):
                found.append("%s: MAC outside the fake range: %s" % (path, m))
        for m in IPV4_RE.findall(s):
            try:
                ipaddress.IPv4Address(m)
                found.append("%s: IPv4 address: %s" % (path, m))
            except ValueError:
                pass
        for m in IPV6_CANDIDATE_RE.findall(s):
            if any(m in mac for mac in macs) or not m.strip(":"):
                continue
            try:
                ipaddress.IPv6Address(m)
                found.append("%s: IPv6 address: %s" % (path, m))
            except ValueError:
                pass
        for m in DATE_RE.finditer(s):
            if not s[m.start():].startswith(PLACEHOLDER_TIME):
                found.append("%s: date other than the placeholder: %s" % (path, s))
        for m in EMAIL_RE.findall(s):
            found.append("%s: email-like string: %s" % (path, m))
        if re.fullmatch(r"[A-Z][A-Za-z]+/[A-Z][A-Za-z_]+(/[A-Za-z_]+)?", s):
            found.append("%s: time-zone-like string: %s" % (path, s))
    for path, o in _nodes(resources):
        if not isinstance(o, dict):
            continue
        if isinstance(o.get("time_zone"), str) and o["time_zone"] != NEUTRAL_TIME_ZONE:
            found.append("%s.time_zone: not %s: %s" % (path, NEUTRAL_TIME_ZONE, o["time_zone"]))
        if _is_clock(o) and (o["hour"] not in GENERIC_HOURS or o["minute"] or o.get("second")):
            found.append("%s: non-generic schedule time: %s" % (path, o))
        if isinstance(o.get("offset"), dict) and any(v for v in o["offset"].values()):
            found.append("%s.offset: non-zero: %s" % (path, o["offset"]))
        if _is_point(o) and any(o[k] for k in "xyz"):
            found.append("%s: non-zero position: %s" % (path, o))
        if "bridge_id" in o and o["bridge_id"] != FAKE_BRIDGE_ID:
            found.append("%s.bridge_id: not the fake one" % path)
        if "id_v1" in o:
            found.append("%s.id_v1: present" % path)
    for i, r in enumerate(resources):
        if r.get("type") == "behavior_script":
            continue
        for where, name in (("name", r.get("name")), ("metadata.name", (r.get("metadata") or {}).get("name"))):
            if isinstance(name, str) and name not in KEPT_NAMES and not GENERIC_NAME_RE.match(name):
                found.append("$[%d].%s: not a generic name: %s" % (i, where, name))
        if r.get("type") in DROP:
            found.append("$[%d]: resource type that should be dropped: %s" % (i, r["type"]))
    return found


def _load(path):
    with open(path) as f:
        return json.load(f)


def _save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")


def capture(path):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
    from hue_backend import credentials
    from hue_backend.bridge import BridgeClient

    creds = credentials.load() or credentials.import_openhue()
    if creds is None:
        sys.exit("not paired")
    creds.fingerprint = creds.fingerprint or credentials.fetch_fingerprint(creds.host)
    data = sanitise(BridgeClient(creds).resources())
    found = problems(data)
    if found:
        sys.exit("refusing to write, still private:\n" + "\n".join(found))
    _save(path, data)
    print("wrote %d resources" % len(data))


def main(argv):
    if len(argv) == 2 and argv[0] == "--check":
        found = problems(_load(argv[1]))
        for p in found:
            print(p)
        print("%s: %s" % (argv[1], "%d problem(s)" % len(found) if found else "clean"))
        return 1 if found else 0
    if len(argv) == 2 and argv[0] == "--sanitise":
        data = sanitise(_load(argv[1]))
        _save(argv[1], data)
        print("sanitised %d resources" % len(data))
        return 0
    if len(argv) == 1 and not argv[0].startswith("-"):
        capture(argv[0])
        return 0
    print("usage: capture_fixture.py [--check | --sanitise] FILE", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
