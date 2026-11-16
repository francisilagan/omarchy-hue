import unittest

import support  # noqa: F401
from hue_backend import colour


class Colour(unittest.TestCase):
    def test_parse_hex_forms(self):
        self.assertEqual(colour.parse_hex("#ff8000"), (255, 128, 0))
        self.assertEqual(colour.parse_hex("ff8000"), (255, 128, 0))
        self.assertEqual(colour.parse_hex("#f80"), (255, 136, 0))

    def test_parse_hex_rejects_garbage(self):
        for bad in ("", "#12", "#gggggg", "#1234567"):
            with self.assertRaises(ValueError):
                colour.parse_hex(bad)

    def test_white_maps_to_the_philips_white_point(self):
        # Philips' documented RGB->XYZ matrix puts white at about (0.3227, 0.3290),
        # slightly warmer than sRGB's D65; that is what Hue lights expect.
        x, y = colour.hex_to_xy("#ffffff")
        self.assertAlmostEqual(x, 0.3227, delta=0.003)
        self.assertAlmostEqual(y, 0.3290, delta=0.003)

    def test_out_of_gamut_colour_is_clamped_into_the_triangle(self):
        narrow = ((0.65, 0.30), (0.30, 0.60), (0.16, 0.08))  # a smaller gamut than C
        x, y = colour.hex_to_xy("#00ff00", narrow)
        self.assertTrue(colour.in_gamut((x, y), narrow), (x, y))

    def test_in_gamut_colour_is_left_alone(self):
        p = (0.4, 0.4)
        self.assertEqual(colour.clamp_to_gamut(p, colour.GAMUT_C), p)

    def test_round_trip_keeps_the_hue(self):
        # Brightness is separate on Hue, so only hue is expected to survive a round trip.
        for hx in ("#ff3b30", "#34c759", "#0a84ff", "#bf5af2", "#ffd60a"):
            back = colour.xy_to_hex(*colour.hex_to_xy(hx))
            diff = abs(colour.hue_of(hx) - colour.hue_of(back))
            self.assertLess(min(diff, 1 - diff), 0.03, (hx, back))

    def test_mirek_ends_are_warm_and_cool(self):
        warm, cool = colour.parse_hex(colour.mirek_to_hex(500)), colour.parse_hex(colour.mirek_to_hex(153))
        self.assertGreater(warm[0], warm[2])  # warm: more red than blue
        self.assertGreaterEqual(cool[2], cool[0] - 5)  # cool: blue at least matches red

    def test_gamut_from_api(self):
        api = {"gamut": {"red": {"x": 1, "y": 2}, "green": {"x": 3, "y": 4}, "blue": {"x": 5, "y": 6}}}
        self.assertEqual(colour.gamut_from_api(api), ((1, 2), (3, 4), (5, 6)))
        self.assertIsNone(colour.gamut_from_api({}))
        self.assertIsNone(colour.gamut_from_api(None))


if __name__ == "__main__":
    unittest.main()
