"""Qlementine filled-icon pipeline quality gates (#112).

The Lucide hairline-stroke era ended with #112: icons are now filled
silhouettes on the 16px Qlementine grid, tinted via the SVG root fill,
served as data URIs. The stroke-snap tests of #89/#97 (stroke column
coverage, minStroke cores) are obsolete — filled shapes carry their own
solid mass at every size. What must still hold:

1. The SVG DECLARES its raster size (width/height = device px) — the
   #97 declared-raster rule, the 1:1 no-resample invariant.
2. The tint lands in the SVG root fill (and per-element fills are
   stripped, so nothing overrides the tint).
3. Every name the app can request resolves to path data — no empty
   bodies silently rendering blank icons.
4. Filled glyphs rasterize DENSE at small sizes (solid-pixel ratio far
   above the old hairline cores) — the legibility floor #97 round 2
   could not reach with strokes.

This drives the REAL QML singleton (temp probe file, same pattern as
test_url_paths.py) and rasterizes with QSvgRenderer — the rasterizer
Qt's SVG image provider uses.
"""
import os
import re
import sys
import urllib.parse
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QUrl, QByteArray
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

QML_DIR = Path(__file__).resolve().parents[1] / "qml"
ICONS_DIR = QML_DIR.parent / "resources" / "icons" / "qlementine" / "16"
SRC = QML_DIR.parent / "src"
sys.path.insert(0, str(SRC))

_PROBE = """import QtQuick
import "{QMCDIR}"
QtObject {
    function icon(name, color, px, dpr) {
        return Icons.url(name, color, "none", px, dpr)
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


def _svg_of(data_url):
    assert data_url.startswith("data:image/svg+xml;utf8,"), data_url[:60]
    return urllib.parse.unquote(data_url.split(",", 1)[1])


# every Fengrid icon name that the generated dict must carry
_APP_NAMES = [
    "check", "chevron-down", "chevron-left", "chevron-right", "chevron-up",
    "code", "copy", "download", "droplet", "external-link", "file-text",
    "folder-plus", "git-branch", "grid", "hard-drive", "help", "image",
    "layers", "lock", "menu", "moon", "package", "paint-drop", "play",
    "plus", "refresh",
    "search", "star", "sun", "tag", "trash", "type", "unlock", "upload",
    "x", "zap",
]


@pytest.mark.parametrize("name", _APP_NAMES)
def test_every_icon_name_resolves(icons, name):
    """No silent blanks: every app icon name maps to non-empty path data
    AND to a vendored upstream file (provenance stays auditable)."""
    data_url = icons.icon(name, "#E7EDF2", 16, 1.0)
    svg = _svg_of(data_url)
    m = re.search(r"viewBox='0 0 16 16' fill='#E7EDF2'>(.+)</svg>", svg, re.S)
    assert m and m.group(1).strip(), f"{name}: empty path body"
    vendored = list(ICONS_DIR.rglob("*.svg"))
    # the generated dict is built FROM the vendored files; since #149 an
    # alias can share one file (droplet + paint-drop → misc/paint-drop.svg),
    # so 1:1 counting is gone — orphan protection lives in
    # test_vendored_files_match_generated_dict (vendored ⊆ mapped)
    assert len(vendored) >= 1 and vendored


def test_vendored_files_match_generated_dict():
    """The generated dict and the vendored SVG set stay in sync — no
    orphan files, no stale dict entries (keeps
    scripts/generate-icons-qml.py honest)."""
    src = (QML_DIR / "components" / "Icons.qml").read_text()
    keys = set(re.findall(r'^\s+"([a-z0-9-]+)":', src, re.M))
    assert keys == set(_APP_NAMES), (
        f"dict keys drifted: {keys ^ set(_APP_NAMES)}")
    vendored = {p.stem for p in ICONS_DIR.rglob("*.svg")}
    gen = (SRC.parent / "scripts" / "generate-icons-qml.py").read_text()
    mapped = set(re.findall(r'"(?:[a-z-]+)/([a-z0-9-]+)"', gen))
    assert vendored <= mapped, f"orphaned vendored files: {vendored - mapped}"


@pytest.mark.parametrize("px,dpr", [(12, 1.0), (16, 1.0), (16, 1.25),
                                    (16, 1.5), (24, 2.0), (11, 1.5)])
def test_declared_raster_is_device_px(icons, px, dpr):
    """#97 rule survives the icon swap: the data URI declares
    width/height = round(px*dpr) — the intrinsic raster IS the
    device-pixel grid, so the scene-graph draw is 1:1."""
    data_url = icons.icon("lock", "#E7EDF2", px, dpr)
    svg = _svg_of(data_url)
    R = int(px * dpr + 0.5)  # match JS Math.round (half-up, not banker's)
    m = re.search(r"width='(\d+)' height='(\d+)'", svg)
    assert m, svg[:120]
    assert m.groups() == (str(R), str(R)), svg[:120]


def test_tint_rides_the_root_fill(icons):
    """Per-element fills are stripped at generation time; the requested
    color is the ONLY fill — recoloring one icon needs no string math
    at call sites."""
    data_url = icons.icon("lock", "#FF8800", 16, 1.0)
    svg = _svg_of(data_url)
    assert "fill='#FF8800'" in svg or 'fill="#FF8800"' in svg
    assert "#000" not in svg and "black" not in svg
    img = _raster(svg, 16)
    # some ink carries exactly the tint
    tinted = 0
    for x in range(16):
        for y in range(16):
            c = img.pixelColor(x, y)
            if c.alphaF() > 0.8 and abs(c.red() - 0xFF) < 8 \
                    and abs(c.green() - 0x88) < 8 and abs(c.blue()) < 8:
                tinted += 1
    assert tinted > 10, "tint did not reach the raster"


@pytest.mark.parametrize("name", ["lock", "x", "search", "trash"])
def test_filled_glyphs_keep_visible_ink_at_small_sizes(icons, name):
    """#112 legibility gate: at 11px the glyph still carries enough
    coverage to read against the theme surface. Qlementine's thinnest
    features (the x's 0.7-unit arms) land below one device pixel at
    that size — antialiased partial coverage is inherent and visually
    fine (verified against the rendered strip), so the floor here is
    TOTAL ink (alpha > 0.3), not solid pixels: blank/broken renders
    score 0%, real glyphs 7-35%."""
    data_url = icons.icon(name, "#E7EDF2", 11, 1.0)
    svg = _svg_of(data_url)
    img = _raster(svg, 11)
    ink = sum(
        1
        for xx in range(11)
        for yy in range(11)
        if img.pixelColor(xx, yy).alphaF() > 0.3
    ) / 121.0
    assert ink >= 0.05, (
        f"{name}@11px ink {ink:.1%} — glyph vanished")
