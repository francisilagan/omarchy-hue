"""The shipped bridge fixture is public: it must stay sanitised, and the sanitiser must keep it coherent."""
import os
import sys
import unittest

import support

sys.path.insert(0, os.path.join(support.HERE, "..", "tools"))
import capture_fixture as cf  # noqa: E402


def _rids(o):
    if isinstance(o, dict):
        if "rid" in o and "rtype" in o:
            yield o["rid"]
        for v in o.values():
            yield from _rids(v)
    elif isinstance(o, list):
        for v in o:
            yield from _rids(v)


REAL_A = "3f2a9c1e-7b4d-4e8a-9c2b-1d5e6f7a8b9c"
REAL_B = "9e8d7c6b-5a49-4382-a716-f5e4d3c2b1a0"
REAL_C = "11111111-2222-4333-8444-555555555555"


def _raw():
    """A tiny un-sanitised payload with every kind of private detail the sanitiser knows about."""
    return [
        {"id": REAL_A, "id_v1": "/lights/1", "type": "device", "metadata": {"name": "Jane's lamp", "archetype": "hue_bulb"},
         "services": [{"rid": REAL_B, "rtype": "light"}, {"rid": REAL_C, "rtype": "zigbee_connectivity"}]},
        {"id": REAL_B, "type": "light", "owner": {"rid": REAL_A, "rtype": "device"}, "metadata": {"name": "Desk"}},
        {"id": REAL_C, "type": "zigbee_connectivity", "owner": {"rid": REAL_A, "rtype": "device"},
         "mac_address": "ab:cd:ef:12:34:56:78:9a", "extended_pan_id": "fedcba9876543210"},
        {"id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "type": "bridge", "bridge_id": "001788fffe123456",
         "owner": {"rid": REAL_A, "rtype": "device"}, "time_zone": {"time_zone": "Europe/Paris"}},
        {"id": "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee", "type": "entertainment_configuration", "name": "Cinema corner",
         "metadata": {"name": "Cinema corner"}, "note": "see %s" % REAL_B,
         "channels": [{"position": {"x": -0.27, "y": 1.0, "z": -1.0}}],
         "locations": {"positions": [{"x": 0.4, "y": 0.5, "z": 0.6}]}},
        {"id": "cccccccc-bbbb-4ccc-8ddd-eeeeeeeeeeee", "type": "smart_scene", "metadata": {"name": "Evening"},
         "week_timeslots": [{"timeslots": [
             {"start_time": {"kind": "time", "time": {"hour": 6, "minute": 15, "second": 30}}},
             {"start_time": {"kind": "sunset", "time": {"hour": 0, "minute": 0, "second": 0}}},
             {"start_time": {"kind": "time", "time": {"hour": 19, "minute": 45, "second": 0}}}]}]},
        {"id": "dddddddd-bbbb-4ccc-8ddd-eeeeeeeeeeee", "type": "behavior_instance", "metadata": {"name": "Sunset lights"},
         "configuration": {"when_extended": {"start_at": {"time_point": {"offset": {"minutes": -30}, "type": "sunset"}},
                                             "end_at": {"time_point": {"time": {"hour": 2, "minute": 0}, "type": "time"}}}}},
        {"id": "eeeeeeee-bbbb-4ccc-8ddd-eeeeeeeeeeee", "type": "scene", "metadata": {"name": "Read"},
         "status": {"last_recall": "2026-01-02T03:04:05.678Z"}},
        {"id": "ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee", "type": "geolocation", "is_configured": True},
    ]


class ShippedFixture(unittest.TestCase):
    def test_check_finds_nothing_private(self):
        self.assertEqual(cf.problems(support.fixture()), [])

    def test_sanitising_it_again_changes_nothing(self):
        self.assertEqual(cf.sanitise(support.fixture()), support.fixture())

    def test_every_resolving_reference_lands_on_its_rtype(self):
        types = {r["id"]: r["type"] for r in support.fixture()}

        def refs(o):
            if isinstance(o, dict):
                if "rid" in o and "rtype" in o:
                    yield o
                for v in o.values():
                    yield from refs(v)
            elif isinstance(o, list):
                for v in o:
                    yield from refs(v)

        resolved = [ref for ref in refs(support.fixture()) if ref["rid"] in types]
        self.assertGreater(len(resolved), 50)
        for ref in resolved:
            self.assertEqual(types[ref["rid"]], ref["rtype"], ref)

    def test_every_reference_is_fake(self):
        for rid in _rids(support.fixture()):
            self.assertTrue(rid.startswith(cf.FAKE_UUID_PREFIX), rid)


class Sanitiser(unittest.TestCase):
    def setUp(self):
        self.raw = _raw()
        self.out = cf.sanitise(self.raw)

    def test_check_flags_the_raw_payload_and_passes_the_sanitised_one(self):
        found = "\n".join(cf.problems(self.raw))
        for what in ("UUID outside", "MAC outside", "Europe/Paris", "2026-01-02", "Cinema corner",
                     "non-generic schedule time", "offset", "non-zero position", "bridge_id", "id_v1", "geolocation"):
            self.assertIn(what, found)
        self.assertEqual(cf.problems(self.out), [])

    def test_check_flags_addresses_and_emails(self):
        found = "\n".join(cf.problems([{"id": cf.fake_uuid(REAL_A), "type": "x",
                                         "a": "192.168.1.20", "b": "fe80::1:2ff:fe03:405", "c": "me@example.com"}]))
        for what in ("IPv4", "IPv6", "email"):
            self.assertIn(what, found)

    def test_the_same_id_maps_to_the_same_fake_everywhere(self):
        a = cf.fake_uuid(REAL_A)
        self.assertEqual(a, cf.fake_uuid(REAL_A.upper()))
        self.assertNotEqual(a, cf.fake_uuid(REAL_B))
        self.assertEqual(cf.fake_uuid(a), a)
        device, light, zigbee, bridge = self.out[:4]
        self.assertEqual(device["id"], a)
        self.assertEqual({light["owner"]["rid"], zigbee["owner"]["rid"], bridge["owner"]["rid"]}, {a})
        self.assertEqual([s["rid"] for s in device["services"]], [light["id"], zigbee["id"]])
        self.assertEqual(self.out[4]["note"], "see %s" % light["id"])

    def test_references_resolve_exactly_as_before(self):
        fixture_ids = {r["id"] for r in support.fixture()}
        before = [rid in {r["id"] for r in self.raw} for rid in _rids(self.raw)]
        ids = {r["id"] for r in self.out}
        self.assertEqual([rid in ids for rid in _rids(self.out)], before)
        # The shipped fixture: every rid resolves or dangles, and re-sanitising keeps each one that way.
        again = cf.sanitise(support.fixture())
        self.assertEqual([rid in fixture_ids for rid in _rids(support.fixture())],
                         [rid in {r["id"] for r in again} for rid in _rids(again)])

    def test_no_real_value_survives(self):
        text = repr(self.out)
        for real in (REAL_A, REAL_B, REAL_C, "Jane", "Cinema corner", "Paris", "2026", "ab:cd:ef", "fedcba", "001788fffe"):
            self.assertNotIn(real, text)

    def test_shape_is_kept(self):
        self.assertEqual([r["type"] for r in self.out], [r["type"] for r in self.raw if r["type"] not in cf.DROP])
        ent, smart, auto = self.out[4], self.out[5], self.out[6]
        self.assertEqual(ent["name"], ent["metadata"]["name"])
        self.assertEqual(ent["channels"][0]["position"], {"x": 0.0, "y": 0.0, "z": 0.0})
        self.assertEqual(ent["locations"]["positions"][0], {"x": 0.0, "y": 0.0, "z": 0.0})
        slots = smart["week_timeslots"][0]["timeslots"]
        self.assertEqual([s["start_time"]["kind"] for s in slots], ["time", "sunset", "time"])
        self.assertEqual([s["start_time"]["time"] for s in slots],
                         [{"hour": 8, "minute": 0, "second": 0}, {"hour": 0, "minute": 0, "second": 0},
                          {"hour": 12, "minute": 0, "second": 0}])
        when = auto["configuration"]["when_extended"]
        self.assertEqual(when["start_at"]["time_point"], {"offset": {"minutes": 0}, "type": "sunset"})
        self.assertEqual(self.out[7]["status"]["last_recall"], cf.PLACEHOLDER_TIME)
        self.assertEqual(self.out[3]["time_zone"]["time_zone"], "UTC")


if __name__ == "__main__":
    unittest.main()
