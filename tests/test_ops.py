import unittest

import support
from hue_backend import ops


def world():
    d = support.device("Bulb")
    l = support.light(d["id"], color={"xy": {"x": 0.4, "y": 0.4}, "gamut": {"red": {"x": 0.6915, "y": 0.3083},
                      "green": {"x": 0.17, "y": 0.7}, "blue": {"x": 0.1532, "y": 0.0475}}},
                      color_temperature={"mirek": 300, "mirek_valid": True, "mirek_schema": {"mirek_minimum": 200, "mirek_maximum": 450}})
    g = support.grouped()
    r = support.room("Room", [d["id"]], g["id"])
    return support.cache_from([d, l, g, r]), l, g, r


class Plan(unittest.TestCase):
    def test_set_light_builds_one_put_per_id(self):
        cache, l, _, _ = world()
        reqs = ops.plan({"cmd": "set", "kind": "light", "ids": [l["id"]], "on": True, "pct": 40, "duration": 400}, cache)
        self.assertEqual(len(reqs), 1)
        self.assertEqual((reqs[0].method, reqs[0].path, reqs[0].klass), ("PUT", "resource/light/" + l["id"], "light"))
        self.assertEqual(reqs[0].body, {"on": {"on": True}, "dimming": {"brightness": 40.0}, "dynamics": {"duration": 400}})

    def test_set_group_targets_the_grouped_light_with_the_group_rate_class(self):
        cache, _, g, _ = world()
        req = ops.plan({"cmd": "set", "kind": "group", "ids": [g["id"]], "on": False}, cache)[0]
        self.assertEqual((req.path, req.klass), ("resource/grouped_light/" + g["id"], "group"))

    def test_brightness_is_clamped_to_the_valid_range(self):
        cache, l, _, _ = world()
        self.assertEqual(ops.plan({"cmd": "set", "ids": [l["id"]], "pct": 0}, cache)[0].body["dimming"]["brightness"], 1.0)
        self.assertEqual(ops.plan({"cmd": "set", "ids": [l["id"]], "pct": 250}, cache)[0].body["dimming"]["brightness"], 100.0)

    def test_mirek_is_clamped_to_the_lights_own_range(self):
        cache, l, _, _ = world()
        self.assertEqual(ops.plan({"cmd": "set", "ids": [l["id"]], "mirek": 153}, cache)[0].body["color_temperature"]["mirek"], 200)
        self.assertEqual(ops.plan({"cmd": "set", "ids": [l["id"]], "mirek": 500}, cache)[0].body["color_temperature"]["mirek"], 450)

    def test_colour_is_sent_as_xy(self):
        cache, l, _, _ = world()
        body = ops.plan({"cmd": "set", "ids": [l["id"]], "hex": "#ff0000"}, cache)[0].body
        self.assertEqual(set(body["color"]["xy"]), {"x", "y"})

    def test_hex_wins_over_mirek(self):
        cache, l, _, _ = world()
        body = ops.plan({"cmd": "set", "ids": [l["id"]], "hex": "#00ff00", "mirek": 300}, cache)[0].body
        self.assertIn("color", body)
        self.assertNotIn("color_temperature", body)

    def test_identify_replaces_everything_else(self):
        cache, l, _, _ = world()
        self.assertEqual(ops.plan({"cmd": "set", "ids": [l["id"]], "identify": True, "on": True}, cache)[0].body,
                         {"identify": {"action": "identify"}})

    def test_effects_apply_to_lights_only(self):
        cache, l, g, _ = world()
        self.assertIn("effects_v2", ops.plan({"cmd": "set", "ids": [l["id"]], "effect": "candle"}, cache)[0].body)
        with self.assertRaises(ops.InvalidCommand):  # on a group the effect is dropped, leaving nothing to set
            ops.plan({"cmd": "set", "kind": "group", "ids": [g["id"]], "effect": "candle"}, cache)

    def test_scene_recall_modes(self):
        cache, *_ = world()
        sid = support.uid()
        self.assertEqual(ops.plan({"cmd": "scene.recall", "id": sid, "mode": "dynamic_palette"}, cache)[0].body,
                         {"recall": {"action": "dynamic_palette"}})
        with self.assertRaises(ops.InvalidCommand):
            ops.plan({"cmd": "scene.recall", "id": sid, "mode": "bogus"}, cache)

    def test_scene_create_snapshots_the_room(self):
        cache, l, _, r = world()
        req = ops.plan({"cmd": "scene.create", "name": "Mine", "group": r["id"]}, cache)[0]
        self.assertEqual((req.method, req.path), ("POST", "resource/scene"))
        self.assertEqual(req.body["group"], {"rid": r["id"], "rtype": "room"})
        self.assertEqual(req.body["actions"][0]["target"]["rid"], l["id"])
        self.assertIn("on", req.body["actions"][0]["action"])

    def test_scene_create_in_an_empty_room_is_refused(self):
        empty = support.room("Empty", [])
        with self.assertRaises(ops.InvalidCommand):
            ops.plan({"cmd": "scene.create", "name": "X", "group": empty["id"]}, support.cache_from([empty]))

    def test_rename_light_renames_its_device(self):
        cache, l, *_ = world()
        req = ops.plan({"cmd": "rename", "rtype": "light", "id": l["id"], "name": "Desk"}, cache)[0]
        self.assertTrue(req.path.startswith("resource/device/"))
        self.assertEqual(req.body, {"metadata": {"name": "Desk"}})

    def test_names_are_validated(self):
        cache, l, *_ = world()
        for bad in ("", "   ", "x" * 33, None, 5):
            with self.assertRaises(ops.InvalidCommand):
                ops.plan({"cmd": "rename", "rtype": "scene", "id": support.uid(), "name": bad}, cache)

    def test_ids_must_be_uuids_so_nothing_odd_reaches_a_url(self):
        cache, *_ = world()
        for bad in ("../../config", "abc", "", None, "x" * 36, support.uid() + "\n"):
            with self.assertRaises(ops.InvalidCommand):
                ops.plan({"cmd": "scene.delete", "id": bad}, cache)

    def test_effect_names_are_allow_listed(self):
        cache, l, *_ = world()
        for name in ("candle", "no_effect", "sunrise"):
            body = ops.plan({"cmd": "set", "ids": [l["id"]], "effect": name, "timed": {"effect": name}}, cache)[0].body
            self.assertEqual((body["effects_v2"]["action"]["effect"], body["timed_effects"]["effect"]), (name, name))
        for bad in ("Candle", "can dle", "../x", "candle\n", "x" * 41, 5, ["candle"], {"a": 1}):
            with self.assertRaises(ops.InvalidCommand, msg=bad):
                ops.plan({"cmd": "set", "ids": [l["id"]], "effect": bad}, cache)
            with self.assertRaises(ops.InvalidCommand, msg=bad):
                ops.plan({"cmd": "set", "ids": [l["id"]], "timed": {"effect": bad}}, cache)

    def test_a_light_whose_cached_owner_is_not_a_uuid_cannot_be_renamed_through_it(self):
        cache, l, *_ = world()
        l["owner"]["rid"] = "../../config"
        with self.assertRaises(ops.InvalidCommand):
            ops.plan({"cmd": "rename", "rtype": "light", "id": l["id"], "name": "Desk"}, cache)

    def test_unknown_command_and_resource_kinds_are_refused(self):
        cache, *_ = world()
        with self.assertRaises(ops.InvalidCommand):
            ops.plan({"cmd": "format.disk"}, cache)
        with self.assertRaises(ops.InvalidCommand):
            ops.plan({"cmd": "enable", "rtype": "light", "id": support.uid(), "enabled": True}, cache)
        with self.assertRaises(ops.InvalidCommand):
            ops.plan({"cmd": "rename", "rtype": "bridge", "id": support.uid(), "name": "x"}, cache)

    def test_zone_create_and_members(self):
        cache, l, *_ = world()
        c = ops.plan({"cmd": "zone.create", "name": "Desk", "lights": [l["id"]]}, cache)[0]
        self.assertEqual(c.body["children"], [{"rid": l["id"], "rtype": "light"}])
        with self.assertRaises(ops.InvalidCommand):
            ops.plan({"cmd": "zone.create", "name": "Desk", "lights": []}, cache)

    def test_powerup_presets_are_checked(self):
        cache, l, *_ = world()
        self.assertEqual(ops.plan({"cmd": "powerup", "id": l["id"], "preset": "safety"}, cache)[0].body, {"powerup": {"preset": "safety"}})
        with self.assertRaises(ops.InvalidCommand):
            ops.plan({"cmd": "powerup", "id": l["id"], "preset": "explode"}, cache)

    def test_malformed_fields_become_invalid_not_crashes(self):
        cache, l, *_ = world()
        with self.assertRaises(ops.InvalidCommand):
            ops.plan({"cmd": "set", "ids": [l["id"]], "pct": "lots"}, cache)


if __name__ == "__main__":
    unittest.main()
