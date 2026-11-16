"""Colour maths for Hue: sRGB <-> CIE xy, gamut clamping, colour temperature.

Pure functions, no I/O. Hue lights take colour as CIE 1931 xy and can only
render colours inside their gamut triangle, so anything outside is mapped to
the nearest point on the triangle before it is sent.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

Point = Tuple[float, float]
Gamut = Tuple[Point, Point, Point]  # red, green, blue corners

# The widest gamut Hue lights use; also the right default for groups.
GAMUT_C: Gamut = ((0.6915, 0.3083), (0.17, 0.7), (0.1532, 0.0475))
WHITE_POINT: Point = (0.3127, 0.3290)


def parse_hex(value: str) -> Tuple[int, int, int]:
    """Accept '#rgb', '#rrggbb' or the same without '#'."""
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError("not a colour: %r" % value)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        raise ValueError("not a colour: %r" % value) from None


def _linear(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _gamma(c: float) -> float:
    c = max(0.0, c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def gamut_from_api(color: Optional[dict]) -> Optional[Gamut]:
    """Read a light's `color.gamut` object, if it has one."""
    g = (color or {}).get("gamut")
    try:
        return ((g["red"]["x"], g["red"]["y"]), (g["green"]["x"], g["green"]["y"]), (g["blue"]["x"], g["blue"]["y"]))
    except (TypeError, KeyError):
        return None


def _sign(p: Point, a: Point, b: Point) -> float:
    return (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])


def in_gamut(p: Point, g: Gamut) -> bool:
    d1, d2, d3 = _sign(p, g[0], g[1]), _sign(p, g[1], g[2]), _sign(p, g[2], g[0])
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _closest_on_segment(p: Point, a: Point, b: Point) -> Point:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return (ax + t * dx, ay + t * dy)


def clamp_to_gamut(p: Point, g: Gamut) -> Point:
    """Nearest point of the gamut triangle to p (p itself when inside)."""
    if in_gamut(p, g):
        return p
    best, best_d = p, float("inf")
    for a, b in ((g[0], g[1]), (g[1], g[2]), (g[2], g[0])):
        c = _closest_on_segment(p, a, b)
        d = (c[0] - p[0]) ** 2 + (c[1] - p[1]) ** 2
        if d < best_d:
            best, best_d = c, d
    return best


def hex_to_xy(value: str, gamut: Optional[Gamut] = None) -> Point:
    """sRGB hex -> xy, clamped into `gamut` (default: gamut C)."""
    r8, g8, b8 = parse_hex(value)
    r, g, b = _linear(r8 / 255), _linear(g8 / 255), _linear(b8 / 255)
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    s = X + Y + Z
    p = WHITE_POINT if s == 0 else (X / s, Y / s)
    x, y = clamp_to_gamut(p, gamut or GAMUT_C)
    return (round(x, 4), round(y, 4))


def xy_to_hex(x: float, y: float) -> str:
    """xy -> a display colour at full brightness (brightness is separate on Hue)."""
    if not y:
        return "#ffffff"
    X, Y, Z = x / y, 1.0, (1 - x - y) / y
    r = X * 1.656492 - Y * 0.354851 - Z * 0.255038
    g = -X * 0.707196 + Y * 1.655397 + Z * 0.036152
    b = X * 0.051713 - Y * 0.121364 + Z * 1.011530
    m = max(r, g, b, 1e-6)
    if m > 1:
        r, g, b = r / m, g / m, b / m
    return "#%02x%02x%02x" % tuple(int(round(min(1.0, _gamma(c)) * 255)) for c in (r, g, b))


def kelvin_to_xy(kelvin: float) -> Point:
    """Planckian locus approximation (Kim et al.), valid 1667 K - 25000 K."""
    t = max(1667.0, min(25000.0, kelvin))
    if t <= 4000:
        x = -0.2661239e9 / t ** 3 - 0.2343589e6 / t ** 2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t ** 3 + 2.1070379e6 / t ** 2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x ** 3 - 1.34811020 * x ** 2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x ** 3 - 1.37418593 * x ** 2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x ** 3 - 5.87338670 * x ** 2 + 3.75112997 * x - 0.37001483
    return (x, y)


def mirek_to_hex(mirek: float) -> str:
    """Display colour of a white at the given colour temperature (mirek = 1e6 / kelvin)."""
    x, y = kelvin_to_xy(1e6 / max(1.0, mirek))
    return xy_to_hex(x, y)


def hue_of(value: str) -> float:
    """Hue of a hex colour in [0, 1); used to compare colours across the bridge's gamut mapping."""
    import colorsys

    r, g, b = (c / 255 for c in parse_hex(value))
    return colorsys.rgb_to_hsv(r, g, b)[0]


def distance(a: str, b: str) -> float:
    """Euclidean distance between two hex colours in sRGB, 0..~441."""
    pa, pb = parse_hex(a), parse_hex(b)
    return math.sqrt(sum((u - v) ** 2 for u, v in zip(pa, pb)))
