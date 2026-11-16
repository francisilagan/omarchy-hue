import unittest

import support
from hue_backend import state


class RecordedBridge(unittest.TestCase):
    """The sanitised dump of a real bridge: 5 lights, 2 rooms, 7 scenes, 1 smart scene, 2 automations."""

    @classmethod
    def setUpClass(cls):
        cls.snap = state.build_snapshot(support.cache_from(support.fixture()))

    def test_counts(self):
        s = self.snap
        self.assertEqual((len(s["lights"]), len(s["scenes"]), len(s["smartScenes"])), (5, 7, 1))
        self.assertEqual([g["kind"] for g in s["groups"]], ["room", "room"])
        self.assertEqual(len(s["automations"]), 2)

    def test_every_room_light_exists_and_belongs_to_one_room(self):
        seen = []
        for g in self.snap["groups"]:
            for lid in g["lightIds"]:
                self.assertIn(lid, self.snap["lights"])
                seen.append(lid)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(seen), 5)

    def test_groups_reference_their_scenes(self):
        for g in self.snap["groups"]:
            for sid in g["sceneIds"]:
                self.assertEqual(self.snap["scenes"][sid]["group"], g["id"])

    def test_colour_light_has_colour_and_effects(self):
        strips = [l for l in self.snap["lights"].values() if l["color"] and l["ct"]]
        self.assertTrue(strips)
        self.assertIn("candle", strips[0]["effects"])
        self.assertRegex(strips[0]["hex"], r"^#[0-9a-f]{6}$")

    def test_white_only_light_has_no_colour(self):
        white = [l for l in self.snap["lights"].values() if not l["color"]]
        self.assertTrue(white)
        self.assertIsNone(white[0]["hex"])

    def test_bridge_is_listed_as_a_device_first(self):
        self.assertTrue(self.snap["devices"][0]["bridge"])
        self.assertTrue(self.snap["homeGroup"])

    def test_snapshot_is_json_serialisable_and_stable(self):
        import json
        a = json.dumps(self.snap, sort_keys=True)
        b = json.dumps(state.build_snapshot(support.cache_from(support.fixture())), sort_keys=True)
        self.assertEqual(a, b)


class Synthetic(unittest.TestCase):
    def test_a_device_with_two_lights_keeps_both(self):
        d = support.device("Twin")
        l1, l2 = support.light(d["id"], "Front"), support.light(d["id"], "Back")
        r = support.room("Hall", [d["id"]])
        snap = state.build_snapshot(support.cache_from([d, l1, l2, r]))
        self.assertEqual(sorted(snap["groups"][0]["lightIds"]), sorted([l1["id"], l2["id"]]))
        self.assertEqual(len(snap["lights"]), 2)

    def test_battery_is_omitted_when_the_device_reports_none(self):
        pw = {"id": support.uid(), "type": "device_power", "power_state": {}}
        d = support.device("Dimmer", [(pw["id"], "device_power")], archetype="unknown_archetype")
        snap = state.build_snapshot(support.cache_from([d, pw]))
        self.assertNotIn("battery", snap["devices"][0])

    def test_battery_level_is_reported(self):
        pw = {"id": support.uid(), "type": "device_power", "power_state": {"battery_level": 63, "battery_state": "normal"}}
        d = support.device("Dimmer", [(pw["id"], "device_power")])
        self.assertEqual(state.build_snapshot(support.cache_from([d, pw]))["devices"][0]["battery"], 63)

    def test_empty_palette_is_not_dynamic(self):
        sc = {"id": support.uid(), "type": "scene", "metadata": {"name": "S"}, "group": {"rid": support.uid(), "rtype": "room"},
              "palette": {"color": [], "dimming": [], "color_temperature": [], "effects": [], "effects_v2": []}, "actions": []}
        self.assertFalse(state.build_snapshot(support.cache_from([sc]))["scenes"][sc["id"]]["dynamic"])

    def test_palette_with_colours_is_dynamic(self):
        sc = {"id": support.uid(), "type": "scene", "metadata": {"name": "S"}, "group": {"rid": support.uid(), "rtype": "room"},
              "palette": {"color": [{"color": {"xy": {"x": 0.3, "y": 0.3}}}]}, "actions": []}
        self.assertTrue(state.build_snapshot(support.cache_from([sc]))["scenes"][sc["id"]]["dynamic"])

    def test_dimmer_buttons_are_labelled_by_control_id(self):
        d = support.device("Dimmer")
        buttons = []
        for n in (1, 2, 3, 4):
            b = {"id": support.uid(), "type": "button", "metadata": {"control_id": n}, "button": {"last_event": "short_release"}}
            buttons.append(b)
            d["services"].append({"rid": b["id"], "rtype": "button"})
        labels = [r["label"] for r in state.build_snapshot(support.cache_from([d] + buttons))["devices"][0]["readings"]]
        self.assertEqual(labels, ["Button 1", "Button 2", "Button 3", "Button 4"])

    def test_unreachable_light_is_flagged(self):
        z = {"id": support.uid(), "type": "zigbee_connectivity", "status": "connectivity_issue"}
        d = support.device("Bulb", [(z["id"], "zigbee_connectivity")])
        l = support.light(d["id"])
        self.assertFalse(state.build_snapshot(support.cache_from([d, z, l]))["lights"][l["id"]]["reachable"])

    def test_mirek_is_none_in_colour_mode(self):
        d = support.device()
        l = support.light(d["id"], color={"xy": {"x": 0.4, "y": 0.4}}, color_temperature={"mirek": 300, "mirek_valid": False,
                         "mirek_schema": {"mirek_minimum": 153, "mirek_maximum": 500}})
        v = state.build_snapshot(support.cache_from([d, l]))["lights"][l["id"]]
        self.assertIsNone(v["mirek"])


class Events(unittest.TestCase):
    def setUp(self):
        self.d = support.device()
        self.l = support.light(self.d["id"], color_temperature={"mirek": 300, "mirek_valid": True,
                               "mirek_schema": {"mirek_minimum": 153, "mirek_maximum": 500}})
        self.cache = support.cache_from([self.d, self.l])

    def test_update_merges_nested_fields_without_losing_siblings(self):
        changed = self.cache.apply_events([{"type": "update", "data": [{"id": self.l["id"], "type": "light",
                                           "color_temperature": {"mirek": 400}, "on": {"on": False}}]}])
        self.assertTrue(changed)
        got = self.cache.get(self.l["id"])
        self.assertEqual(got["color_temperature"]["mirek"], 400)
        self.assertIn("mirek_schema", got["color_temperature"])
        self.assertFalse(got["on"]["on"])
        self.assertEqual(got["dimming"]["brightness"], 50.0)

    def test_add_and_delete(self):
        new = support.light(self.d["id"], "New")
        self.cache.apply_events([{"type": "add", "data": [new]}])
        self.assertIsNotNone(self.cache.get(new["id"]))
        self.cache.apply_events([{"type": "delete", "data": [{"id": new["id"], "type": "light"}]}])
        self.assertIsNone(self.cache.get(new["id"]))

    def test_update_for_unknown_resource_is_ignored(self):
        self.assertFalse(self.cache.apply_events([{"type": "update", "data": [{"id": support.uid(), "type": "light"}]}]))

    def test_malformed_events_do_not_raise(self):
        self.assertFalse(self.cache.apply_events([{"type": "update", "data": [{"type": "light"}]}, {"type": "error"}]))

    def test_events_that_are_not_objects_are_skipped(self):
        batch = [1, None, "x", {"type": "update", "data": "nope"}, {"type": "update", "data": [7, None]},
                 {"type": "update", "data": [{"id": ["not", "hashable"]}]},
                 {"type": "update", "data": [{"id": self.l["id"], "on": {"on": False}}]}]
        self.assertTrue(self.cache.apply_events(batch))
        self.assertFalse(self.cache.get(self.l["id"])["on"]["on"])

    def test_a_bad_value_skips_only_that_light(self):
        # A non-numeric brightness event used to make every later snapshot fail (and killed the emitter).
        other = support.light(self.d["id"], "Other")
        self.cache.apply_events([{"type": "add", "data": [other]}])
        self.cache.apply_events([{"type": "update", "data": [{"id": self.l["id"], "dimming": {"brightness": "abc"}}]}])
        snap = state.build_snapshot(self.cache)
        self.assertIn(other["id"], snap["lights"])
        self.assertNotIn(self.l["id"], snap["lights"])
        for broken in ({"metadata": "x"}, {"on": []}, {"color": {"xy": {"x": "a", "y": None}}}):
            bad = support.light(self.d["id"], "Bad", **broken)
            snap = state.build_snapshot(support.cache_from([self.d, other, bad]))
            self.assertIn(other["id"], snap["lights"], broken)


if __name__ == "__main__":
    unittest.main()
