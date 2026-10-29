"""Crisp icon rasterization across display scales (#89).

Icons.url() must rasterize axis-aligned strokes with every pixel
column either ~fully covered or ~empty. Partial-coverage column pairs
are the "fuzzy plus icon" fuzz: a DPR-blind hairline rasterizes as
(0.67/0.67) or (0.71/0.34) column pairs on fractional-DPR desktops
(Linux 125%/150% scaling). The DPR-aware stroke width + viewBox snap
in Icons.url() keeps every column ~full or ~empty at 100-200%.

This drives the REAL QML singleton (via a temp probe file, same
pattern as test_url_paths.py) and rasterizes the returned data URL
with QSvgRenderer — the rasterizer Qt's SVG image provider uses.
"""
import math
import os
import re
import sys
import urllib.parse
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtCore import QByteArray
from PySide6.QtSvg import QSvgRenderer

QML_DIR = Path(__file__).resolve().parents[1] / "qml"
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_PROBE = """import QtQuick
import "{QMCDIR}"
QtObject {
    function icon(name, color, fill, px, dpr, minStroke) {
        return Icons.url(name, color, fill, px, dpr, minStroke)
    }
}
"""

_APP = None


def _qapp():
    global _APP
    _APP = _APP or QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


@pytest.fixture()
def icons(tmp_path):
    _qapp()
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    comps = QML_DIR / "components"
    probe = tmp_path / "probe.qml"
    # directory imports must be RELATIVE to the probe file
    probe.write_text(_PROBE.replace(
        "{QMCDIR}", os.path.relpath(comps, tmp_path)))
    engine = QQmlEngine()
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(probe)))
    root = comp.create()
    assert root is not None, [str(e) for e in comp.errors()]
    yield root
    del root, comp, engine


def _raster(svg_text, dev_px):
    """Render the SVG at dev_px x dev_px device pixels."""
    r = QSvgRenderer(QByteArray(svg_text.encode()))
    assert r.isValid(), "invalid SVG"
    img = QImage(dev_px, dev_px, QImage.Format_ARGB32)
    img.fill(0x00000000)  # transparent (NOT fill(0) — coerces to opaque black)
    p = QPainter(img)
    r.render(p)
    p.end()
    return img


def _vertical_stroke_profile(svg_text, dev_px):
    """Per-column alpha coverage over rows inside the vertical stroke,
    below the horizontal bar of the plus glyph (unit y 14..19 — the
    bar sits at y=12 and its round caps end before unit 13.5)."""
    m = re.search(r"viewBox='(-?[\d.]+) (-?[\d.]+) 28 28'", svg_text)
    assert m, svg_text[:120]
    x0 = float(m.group(1))
    img = _raster(svg_text, dev_px)
    y_lo = int(math.ceil((14 - x0) * dev_px / 28))
    y_hi = int(math.floor((19 - x0) * dev_px / 28))
    assert y_hi - y_lo >= 1, f"row window too small: {y_lo}..{y_hi}"
    prof = []
    for c in range(img.width()):
        s = 0
        for y in range(y_lo, y_hi):
            s += img.pixelColor(c, y).alphaF()
        prof.append(s / (y_hi - y_lo))
    return prof


@pytest.mark.parametrize("px", [12, 16, 24])
@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 1.75, 2.0])
def test_plus_stroke_columns_are_crisp(icons, px, dpr):
    """Every pixel column of the plus's vertical stroke is ~full or
    ~empty — no partial-coverage edges at any display scale."""
    data_url = icons.icon("plus", "#ffffff", "none", px, dpr, 0)
    assert data_url.startswith("data:image/svg+xml;utf8,")
    svg = urllib.parse.unquote(data_url.split(",", 1)[1])

    prof = _vertical_stroke_profile(svg, round(px * dpr))
    covered = [i for i, v in enumerate(prof) if v > 0.9]
    assert covered, f"stroke missing entirely: {prof}"
    for i, v in enumerate(prof):
        assert v <= 0.1 or v >= 0.9, (
            f"partial-coverage column {i}={v:.2f} "
            f"(px={px}, dpr={dpr}) — fuzzy stroke")


@pytest.mark.parametrize("px", [12, 16, 24])
def test_plus_stroke_occupies_expected_columns(icons, px):
    """Sanity: at dpr=1 the stroke is a single full column, on the
    pixel-centered phase the snap chose."""
    data_url = icons.icon("plus", "#ffffff", "none", px, 1.0, 0)
    svg = urllib.parse.unquote(data_url.split(",", 1)[1])
    prof = _vertical_stroke_profile(svg, px)
    full = [i for i, v in enumerate(prof) if v >= 0.9]
    assert len(full) == 1, f"expected exactly one full column, got {prof}"


def _ink_counts(img):
    """(solid pixels, soft-edge %, partial-coverage columns).

    'Solid' = alphaF >= 0.85 — pixels that fully carry the stroke.
    An arc stroke at 1 device px has NO solid core: every curved
    pixel is a partial-coverage pixel (#97 round 2's measured
    mechanism — the lock chip scored 6 solid px of 256).
    """
    w = img.width()
    solid = soft = 0
    col = [0.0] * w
    for x in range(w):
        s = 0
        for y in range(w):
            a = img.pixelColor(x, y).alphaF()
            s += a
            if a >= 0.85:
                solid += 1
            elif a > 0.15:
                soft += 1
        col[x] = s / w
    pcols = sum(1 for c in col if 0.1 < c < 0.9)
    return solid, 100.0 * soft / (w * w), pcols


@pytest.mark.parametrize("name,px,solid_min", [
    ("lock", 16, 40),      # hairline: 6 — fails pre-fix
    ("unlock", 16, 40),    # hairline: 5
    ("x", 16, 15),         # hairline: 0 (pure diagonals)
    ("trash", 12, 40),     # hairline: 17
])
def test_chip_glyphs_keep_a_solid_stroke_core(icons, name, px, solid_min):
    """#97: chrome glyph sites that render below 24 device px opt into
    a 2-device-px stroke floor (IconImage.minStroke) — a 1-px arc
    cannot hold a solid core (1.25*R/24 rounds to 1 below ~19 device
    px), which IS the fuzz the reporter kept seeing after the
    declared-raster fix: that fix measured no soft-edge delta
    (23.8% simulated resample vs 25.4% 1:1 raster)."""
    data_url = icons.icon(name, "#E7EDF2", "none", px, 1.0, 2)
    svg = urllib.parse.unquote(data_url.split(",", 1)[1])
    R = round(px * 1.0)
    # the floor must NOT alter the declared raster (1:1 draw invariant)
    m = re.search(r"width='(\d+)' height='(\d+)'", svg)
    assert m, svg[:80]
    assert m.groups() == (str(R), str(R)), svg[:80]
    solid, soft_pct, pcols = _ink_counts(_raster(svg, R))
    assert solid >= solid_min, (
        f"{name}@{px}px min-stroke 2 kept only {solid} solid px "
        f"(need {solid_min}) — the stroke has no core, chips render "
        f"as halos (soft-edge {soft_pct:.1f}%)")
    assert soft_pct <= 22.0, f"{name}@{px}px still {soft_pct:.1f}% soft-edge (pre-fix hairline scored 24.6-29.8%)"


@pytest.mark.parametrize("name,px,solid_max", [("lock", 24, 20), ("x", 24, 10)])
def test_hairline_cadence_unchanged_at_full_size(icons, name, px, solid_max):
    """Guard rail: glyphs at >=24 device px WITHOUT minStroke keep the
    1.25px/24 hairline (k=1) — the floor must not leak into the
    default look of larger icons/tiles."""
    data_url = icons.icon(name, "#E7EDF2", "none", px, 1.0, 0)
    svg = urllib.parse.unquote(data_url.split(",", 1)[1])
    solid, _, _ = _ink_counts(_raster(svg, px))
    assert solid <= solid_max, (
        f"{name}@{px}px gained {solid} solid px without an opt-in — "
        f"the stroke-core floor leaked into the hairline cadence")
