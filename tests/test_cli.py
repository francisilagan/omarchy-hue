import io
import json
import unittest
import unittest.mock

import support
from hue_backend import bridge, cli
from hue_backend.credentials import Credentials
from hue_backend.state import build_snapshot


def home():
    """Two rooms (3 + 2 lights, 1 on in the first) and one light in no room."""
    dev = [support.device("D%d" % i) for i in range(6)]
    lights = [support.light(d["id"], "L%d" % i, on=(i == 0)) for i, d in enumerate(dev)]
    ga, gb = support.grouped(), support.grouped()
    ra = support.room("Alpha", [d["id"] for d in dev[:3]], ga["id"])
    rb = support.room("Beta", [d["id"] for d in dev[3:5]], gb["id"])
    for d, l in zip(dev, lights):
        d["services"] = [{"rid": l["id"], "rtype": "light"}]
    return dev + lights + [ra, rb, ga, gb], ra, rb, ga, gb


class FakeClient:
    def __init__(self, resources, fail=None):
        self.resources_data, self.calls, self.fail, self.closed = resources, [], fail, False

    def resources(self):
        if self.fail:
            raise self.fail
        return self.resources_data

    def request(self, method, path, body=None, klass=""):
        self.calls.append((method, path, body, klass))
        return bridge.Reply([], [])

    def close(self):
        self.closed = True


CREDS = Credentials(host="h", key="k")


def run(argv, resources=None, creds=CREDS, fail=None):
    out, err = io.StringIO(), io.StringIO()
    client = FakeClient(resources if resources is not None else home()[0], fail)
    code = cli.run(argv, out=out, err=err, load_credentials=lambda: creds, client_factory=lambda c, timeout=0: client)
    return code, out.getvalue(), err.getvalue(), client


class Status(unittest.TestCase):
    def test_counts_and_per_room_tooltip_in_bridge_room_order(self):
        code, out, _, _ = run(["status"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["text"], "\U000f06e8 1/6")
        self.assertEqual(data["class"], "on")
        self.assertEqual(data["tooltip"], "Alpha: 1/3 on\nBeta: 0/2 on\n?: 0/1 on\n\nClick: toggle all lights")

    def test_output_is_ascii_escaped_json_with_key_order_text_tooltip_class(self):
        out = run(["status"])[1]
        self.assertTrue(out.startswith('{"text": "\\udb81\\udee8 1/6", "tooltip": "'))
        self.assertTrue(out.endswith('", "class": "on"}\n'))

    def test_all_off_uses_the_off_glyph(self):
        res = [dict(r, on={"on": False}) if r["type"] == "light" else r for r in home()[0]]
        data = json.loads(run(["status"], res)[1])
        self.assertEqual((data["text"], data["class"]), ("\U000f0e4f 0/6", "off"))

    def test_unpaired_and_unreachable_print_the_old_offline_line_and_exit_zero(self):
        expected = '{"text": "\\udb81\\udee9 --", "tooltip": "Hue bridge unreachable", "class": "offline"}\n'
        code, out, err, _ = run(["status"], creds=None)
        self.assertEqual((code, out, err), (0, expected, ""))
        code, out, err, _ = run(["status"], fail=bridge.BridgeError("unreachable", "x"))
        self.assertEqual((code, out, err), (0, expected, ""))

    def test_client_is_closed(self):
        self.assertTrue(run(["status"])[3].closed)


class Toggle(unittest.TestCase):
    def test_any_light_on_turns_every_room_off(self):
        res, _, _, ga, gb = home()
        code, out, _, client = run(["toggle"], res)
        self.assertEqual((code, out), (0, ""))
        self.assertEqual([c[1] for c in client.calls], ["resource/grouped_light/" + ga["id"], "resource/grouped_light/" + gb["id"]])
        self.assertTrue(all(c[2] == {"on": {"on": False}} for c in client.calls))

    def test_all_off_turns_every_room_on(self):
        res = [dict(r, on={"on": False}) if r["type"] == "light" else r for r in home()[0]]
        client = run(["toggle"], res)[3]
        self.assertTrue(all(c[2] == {"on": {"on": True}} for c in client.calls))
        self.assertEqual(len(client.calls), 2)

    def test_failure_is_a_quiet_stderr_line_and_exit_one(self):
        code, out, err, _ = run(["toggle"], creds=None)
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("hue: not paired"))
        self.assertEqual(run(["toggle"], fail=bridge.BridgeError("unreachable", "down"))[:3], (1, "", "hue: down\n"))


class RoomAndScene(unittest.TestCase):
    def test_room_on_with_brightness_targets_the_rooms_grouped_light(self):
        res, ra, _, ga, _ = home()
        code, _, _, client = run(["room", ra["id"], "--on", "--brightness", "25"], res)
        self.assertEqual(code, 0)
        self.assertEqual(client.calls, [("PUT", "resource/grouped_light/" + ga["id"],
                                         {"on": {"on": True}, "dimming": {"brightness": 25.0}}, "group")])

    def test_several_rooms_off(self):
        res, ra, rb, _, _ = home()
        client = run(["room", ra["id"], rb["id"], "--off"], res)[3]
        self.assertEqual(len(client.calls), 2)

    def test_unknown_room_and_missing_action_fail_without_requests(self):
        res, ra, *_ = home()
        code, _, err, client = run(["room", support.uid(), "--on"], res)
        self.assertEqual((code, client.calls), (1, []))
        self.assertIn("no such room", err)
        code, _, err, client = run(["room", ra["id"]], res)
        self.assertEqual((code, client.calls), (1, []))

    def test_scene_recall_skips_loading_resources(self):
        sid = support.uid()
        code, _, _, client = run(["scene", sid], fail=bridge.BridgeError("unreachable", "never loaded"))
        self.assertEqual(code, 0)
        self.assertEqual(client.calls, [("PUT", "resource/scene/" + sid, {"recall": {"action": "active"}}, "")])

    def test_bad_scene_id_is_rejected(self):
        code, _, err, client = run(["scene", "nope"])
        self.assertEqual((code, client.calls), (1, []))

    def test_usage_errors_exit_two(self):
        with unittest.mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(run([])[0], 2)


if __name__ == "__main__":
    unittest.main()
