"""Color-scheme explorer math (Colors pane, Explorer tab).

Color palette scheme engine behind the wheel UI: fixed harmony models
(mono / adjacent / triad / tetrad) with an angular `dist` parameter, a
freeform model with per-color hue offsets, an optional complementary
color on every model, a shared shade point (S/L) with per-color
overrides, cumulative fine-tune deltas, and the 5-step shade ramp the
palette display and the tables/export dialog render.

Color conversion helpers are imported from core.colors (same math the
Harmonies generator uses) — this module only adds what the explorer
needs: scheme offsets, the ramp, presets, fine-tune application and
CIELAB (for the color info dialog).
"""

from __future__ import annotations

from .colors import best_ink, color_name, contrast, hsl2rgb, rgb2hex

SCHEMES = ("mono", "adjacent", "triad", "tetrad", "freeform")

SCHEME_LABELS = {
    "mono": "Monochromatic (1-color)",
    "adjacent": "Adjacent colors (3-colors)",
    "triad": "Triad (3-colors)",
    "tetrad": "Tetrad (4-colors)",
    "freeform": "Free style",   # the UI appends "- N colors"
}

DEFAULT_DIST = 30
DEFAULT_BASE_HEX = "#AC3939"   # the reference scheme red
# the reference base's own shade point (hsl 0°, 50.2%, 44.9%) — the
# explorer opens on the same red the reference screenshots show
DEFAULT_S, DEFAULT_L = 50.2, 44.9

FREE_COUNT_RANGE = (2, 5)

# shade ramp: lightness offsets from a color's own L (saturation held),
# read off the reference tables (FE9A00 base → 74.7/56.5/49.8/34.9/16.9)
RAMP_L = (25.0, 7.0, 0.0, -15.0, -33.0)
# relative segment widths in the tables view — base widest, tapering out
RAMP_WIDTH = (0.6, 1.0, 1.6, 1.0, 0.6)

FINE_ROWS = ("hue", "saturation", "brightness", "contrast")
FINE_STEPS = (-10, -5, -1, 1, 5, 10)

# named (S, L) shade styles, row-major over the 3×8 preset grid
PRESETS = (
    ("Lightest Pale Pastel", 18, 92), ("Bright Pastel", 60, 76),
    ("Shiny", 92, 64),
    ("Very Light Pale Pastel", 22, 86), ("Very Light Pastel", 55, 86),
    ("Full Colors", 88, 50),
    ("Lighter Pale Pastel", 26, 80), ("Lighter Pastel", 58, 70),
    ("Darker Colors", 82, 36),
    ("Pale Pastel", 30, 74), ("Pastel", 60, 62), ("Dark Neon", 100, 52),
    ("Darker Pale Pastel", 32, 66), ("Darker Pastel", 62, 50),
    ("Dark", 70, 26),
    ("Dark Pale Pastel", 34, 56), ("Dark Pastel", 60, 38),
    ("Deep Colors", 88, 30),
    ("Greyish darkest", 8, 26), ("Greyish dark", 10, 40),
    ("Greyish medium dark", 12, 52),
    ("Greyish medium light", 12, 64), ("Greyish lighter", 10, 76),
    ("Greyish lightest", 8, 88),
)


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def scheme_offsets(scheme: str, dist: float = DEFAULT_DIST,
                   free_offsets: list[float] | None = None,
                   free_count: int = 4) -> list[float]:
    """Hue offsets (degrees, relative to the base hue) for a scheme.

    mono     — [0]
    adjacent — base ± dist (analogous)
    triad    — 120+dist and 240-dist: dist converges the pair toward the
               opposite point (dist 30 → 150/210, the reference layout)
    tetrad   — two complementary pairs: 0/dist and 180/180+dist
    freeform — per-color offsets (first pinned at 0), grown by the
               golden angle when the count rises
    """
    if scheme == "mono":
        return [0.0]
    if scheme == "adjacent":
        return [0.0, float(dist), -float(dist)]
    if scheme == "triad":
        return [0.0, 120.0 + dist, 240.0 - dist]
    if scheme == "tetrad":
        return [0.0, float(dist), 180.0, 180.0 + dist]
    if scheme == "freeform":
        offs = [float(o) for o in (free_offsets or [0.0])]
        base = offs[0]
        offs = [(o - base) % 360 for o in offs[:free_count]]
        while len(offs) < free_count:
            offs.append((offs[-1] + 137.5) % 360 if offs else 0.0)
        return offs
    raise ValueError(f"unknown scheme: {scheme}")


def dist_for_drag(scheme: str, idx: int, base_h: float,
                  angle: float) -> float | None:
    """The Distance an outer hue dot sits at when dragged to `angle`.

    Per scheme + dot index — a dot whose position is dist-independent
    (tetrad's opposite anchor at 180°, or any model's appended
    complementary dot) has no Distance parameter: the caller rotates the
    whole scheme instead. mono/freeform have no dist at all.
    """
    if scheme == "adjacent":
        if idx in (1, 2):
            return max(0.0, min(90.0, abs(angle_between(base_h, angle))))
        return None
    if scheme == "triad":
        # offsets 120+dist / 240-dist converge on the opposite point
        if idx == 1:
            return max(0.0, min(60.0, angle_between(base_h + 120.0, angle)))
        if idx == 2:
            return max(0.0, min(60.0, -angle_between(base_h + 240.0, angle)))
        return None
    if scheme == "tetrad":
        if idx == 1:
            return max(0.0, min(90.0, angle_between(base_h, angle)))
        if idx == 3:
            return max(0.0, min(90.0, angle_between(base_h + 180.0, angle)))
        return None
    return None


def apply_fine_tune(h: float, s: float, l: float,
                    ft: dict | None) -> tuple[float, float, float]:
    """Apply the cumulative fine-tune deltas to one (h, s, l) color.

    hue rotates, saturation shifts, brightness shifts, contrast spreads
    lightness around the 50% midpoint (positive = more spread).
    """
    ft = ft or {}
    dh = float(ft.get("hue", 0) or 0)
    ds = float(ft.get("sat", 0) or 0)
    db = float(ft.get("bright", 0) or 0)
    dc = float(ft.get("contrast", 0) or 0)
    h = (h + dh) % 360
    s = clamp(s + ds)
    k = 1.0 + dc / 100.0
    l = clamp(50.0 + (l - 50.0) * k)
    l = clamp(l + db)
    return h, s, l


def invert_fine_tune(h: float, s: float, l: float,
                     ft: dict | None) -> tuple[float, float, float]:
    """Raw (h, s, l) that produces the given final color under `ft` —
    used when the user types a Base RGB value while deltas are live."""
    ft = ft or {}
    db = float(ft.get("bright", 0) or 0)
    dc = float(ft.get("contrast", 0) or 0)
    ds = float(ft.get("sat", 0) or 0)
    dh = float(ft.get("hue", 0) or 0)
    l_sp = clamp(l - db)
    k = 1.0 + dc / 100.0
    l_raw = clamp(50.0 + (l_sp - 50.0) / k) if abs(k) > 1e-6 else 50.0
    return (h - dh) % 360, clamp(s - ds), l_raw


def ramp_for(h: float, s: float, l: float) -> list[str]:
    """The 5-step shade ramp of one color: light → base → dark."""
    out = []
    for off in RAMP_L:
        li = clamp(l + off, 2.0, 98.0)
        out.append(rgb2hex(*hsl2rgb(h % 360, s, li)))
    return out


def build_palette(base_h: float, s0: float, l0: float, scheme: str,
                  dist: float = DEFAULT_DIST, add_comp: bool = False,
                  free_offsets: list[float] | None = None,
                  free_count: int = 4,
                  shade_overrides: list | None = None,
                  hue_overrides: list | None = None,
                  ft: dict | None = None) -> list[dict]:
    """The full explorer palette: one entry per scheme color (plus the
    optional complementary color last).

    Every entry carries its final h/s/l + hex, the shade ramp, the
    contrast ratios against white/black (the Harmonies editor shows
    those, so the Explorer does too), a UI ink, and the flags the wheel
    and palette display need (is_base / is_comp / ind — `ind` marks a
    color the user moved off the model's default position with a Shift
    drag: an individual hue offset or shade).
    """
    offs = scheme_offsets(scheme, dist, free_offsets, free_count)
    entries = [(dh, False) for dh in offs]
    # "add complementary" appends the base hue's opposite — unless the
    # model already places a color there (tetrad's pairs, triad at
    # dist 60, mono+comp = the complementary model itself)
    if add_comp and not any(abs((dh - 180) % 360) < 1e-6
                            for dh, _ in entries):
        entries.append((180.0, True))
    overrides = list(shade_overrides or [])
    hovers = list(hue_overrides or [])
    out = []
    for i, (dh, is_comp) in enumerate(entries):
        ds, dl = (overrides[i] if i < len(overrides) else (0.0, 0.0))
        ho = float(hovers[i]) if i < len(hovers) else 0.0
        h, s, l = apply_fine_tune((base_h + dh + ho) % 360,
                                  clamp(s0 + ds), clamp(l0 + dl), ft)
        rgb = hsl2rgb(h, s, l)
        hx = rgb2hex(*rgb)
        out.append({
            "dh": dh, "is_comp": is_comp, "is_base": i == 0,
            "ind": abs(ho) > 1e-6 or abs(ds) > 1e-6 or abs(dl) > 1e-6,
            "h": h, "s": s, "l": l, "hex": hx,
            "ramp": ramp_for(h, s, l),
            "name": color_name(hx),
            "ink": best_ink(rgb),
            "cw": round(contrast(rgb, (255, 255, 255)), 1),
            "cb": round(contrast(rgb, (16, 20, 24)), 1),
            "wcagW": "AAA" if contrast(rgb, (255, 255, 255)) >= 7
                     else "AA" if contrast(rgb, (255, 255, 255)) >= 4.5
                     else "AA·lg" if contrast(rgb, (255, 255, 255)) >= 3
                     else "fail",
            "wcagB": "AAA" if contrast(rgb, (16, 20, 24)) >= 7
                     else "AA" if contrast(rgb, (16, 20, 24)) >= 4.5
                     else "AA·lg" if contrast(rgb, (16, 20, 24)) >= 3
                     else "fail",
        })
    return out


def angle_between(a: float, b: float) -> float:
    """Shortest signed arc a → b in degrees (-180..180]."""
    return (b - a + 180.0) % 360.0 - 180.0


def rgb2lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB → CIELAB (D65). For the color info dialog."""
    def lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in rgb)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def random_base(rng) -> tuple[float, float, float]:
    """A random base configuration (hue, s, l) for Randomize."""
    h = rng.randrange(360)
    s = rng.randrange(35, 95)
    l = rng.randrange(30, 70)
    return float(h), float(s), float(l)
