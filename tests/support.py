"""Shared helpers: load the recorded bridge payload and build small synthetic ones."""
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

import logging  # noqa: E402

from hue_backend.state import Cache  # noqa: E402

logging.getLogger("hue").addHandler(logging.NullHandler())  # keep test output quiet
logging.getLogger("hue").propagate = False


def fixture():
    """A real bridge's resources, scrubbed by tools/capture_fixture.py: every UUID is a fake one
    (references stay consistent), names, schedules, timestamps, positions, MACs and the time zone are
    generic. Only the structure, counts and capabilities are real; test_fixture.py keeps it that way."""
    with open(os.path.join(HERE, "fixtures", "bridge_resource.json")) as f:
        return json.load(f)


def cache_from(resources):
    c = Cache()
    c.load(resources)
    return c


def uid():
    return str(uuid.uuid4())


def device(name="Dev", services=(), archetype="hue_bulb", product="Hue bulb"):
    return {"id": uid(), "type": "device", "metadata": {"name": name, "archetype": archetype},
            "product_data": {"product_name": product, "product_archetype": archetype, "software_version": "1.0"},
            "services": [{"rid": r, "rtype": t} for r, t in services]}


def light(owner, name="Light", on=True, brightness=50.0, **extra):
    r = {"id": uid(), "type": "light", "owner": {"rid": owner, "rtype": "device"},
         "metadata": {"name": name, "archetype": "sultan_bulb"},
         "on": {"on": on}, "dimming": {"brightness": brightness}}
    r.update(extra)
    return r


def room(name, children, grouped=None):
    r = {"id": uid(), "type": "room", "metadata": {"name": name, "archetype": "living_room"},
         "children": [{"rid": c, "rtype": "device"} for c in children], "services": []}
    if grouped:
        r["services"] = [{"rid": grouped, "rtype": "grouped_light"}]
    return r


def grouped(on=False):
    return {"id": uid(), "type": "grouped_light", "on": {"on": on}}
