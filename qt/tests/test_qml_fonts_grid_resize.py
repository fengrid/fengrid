"""Issue #137: the grid-size slider re-scales the Fonts preview grid —
the resize path must NOT re-cross the Python bridge from every card.

Pre-fix, the specimen `text` binding invoked fonts.preview_text(px) once
per card on every grid resize: measured on a 514-family library that is
~280 bridge calls and a ≥3 s binding storm per slider notch (the
reported "very resource intensive and slow"; on larger libraries the
mid-drag backlog froze the app, reading as a crash). The fix computes
the size class in QML and picks the passage from the bridge's per-bucket
specimen PROPERTIES (cached C++ reads).

Regression proof: change prefs.fontGridSize under a live Fonts.qml and
assert the grid re-scales (cellWidth follows the fontScale map) with
ZERO preview_text slot invocations and the right bucket specimen
showing. This test FAILS on the pre-fix binding — the slot ran once per
instantiated card on every change.
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

QML_DIR = Path(__file__).resolve().parents[1] / "qml"
SRC = Path(__file__).resolve().parents[1] / "src"
FONTS = Path(__file__).resolve().parents[2] / "fonts"
sys.path.insert(0, str(SRC))

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        _APP = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


def _seed_fonts(con, tmp_path):
    """Three families directly in the asset table (same seeding as the
    multi-select fixture — the bridge's _refresh() groups by family)."""
    sid = con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('fontroot', ?, 't', 1)", (str(tmp_path),)).lastrowid
    for fam in ("Alpha", "Beta", "Gamma"):
        con.execute(
            "INSERT INTO asset(source_id, kind, name, path, family)"
            " VALUES (?, 'font', ?, ?, ?)",
            (sid, fam, str(tmp_path / f"{fam}.ttf"), fam))
    con.commit()


@pytest.fixture()
def fonts_ui(tmp_path):
    _qapp()
    from fengrid.bridges.fonts import Fonts
    from fengrid.bridges.library import Library
    from fengrid.bridges.prefs import Prefs
    from fengrid.bridges.taxonomy import Taxonomy
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    _seed_fonts(con, tmp_path)
    theme = Theme(con, str(FONTS))
    fonts_bridge = Fonts(con, str(tmp_path / "t.db"))
    fonts_bridge._refresh()
    library = Library(con, str(tmp_path / "t.db"), no_scan=True)
    taxonomy = Taxonomy(con, str(tmp_path))
    prefs = Prefs(con, str(tmp_path))

    engine = QQmlEngine()
    engine.rootContext().setContextProperty("theme", theme)
    engine.rootContext().setContextProperty("fonts", fonts_bridge)
    engine.rootContext().setContextProperty("library", library)
    engine.rootContext().setContextProperty("taxonomy", taxonomy)
    engine.rootContext().setContextProperty("previewProfile", None)
    engine.rootContext().setContextProperty("terms", None)
    engine.rootContext().setContextProperty("prefs", prefs)
    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(str(QML_DIR / "components" / "Fonts.qml")))
    root = comp.create(engine.rootContext())
    assert root is not None, comp.errors()
    root.setWidth(1100)
    root.setHeight(700)

    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    _settle(_qapp(), 0.6)

    grid = None
    stack = [root]
    while stack:
        o = stack.pop()
        if "GridView" in o.metaObject().className():
            grid = o
            break
        if hasattr(o, "childItems"):
            stack.extend(o.childItems())
    assert grid is not None, "fonts grid not found"
    assert int(grid.property("count")) == 3

    yield {"root": root, "win": win, "grid": grid, "fonts": fonts_bridge,
           "prefs": prefs, "con": con}

    win.close()
    root.setParentItem(None)
    engine.collectGarbage()
    del engine


def _settle(qapp, seconds):
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.02)


def _find_preview_text(root, fonts_bridge):
    """The specimen Text: a QQuickText whose text equals one of the
    bridge's curated passages (family names/counts are short strings)."""
    passages = {fonts_bridge.specimenSmall, fonts_bridge.specimenMedium,
                fonts_bridge.specimenLarge}
    stack = [root]
    while stack:
        o = stack.pop()
        if "Text" in o.metaObject().className():
            t = str(o.property("text") or "")
            if t in passages:
                return o
        if hasattr(o, "childItems"):
            stack.extend(o.childItems())
    return None


def test_specimen_properties_expose_the_three_size_classes(tmp_path):
    """Bridge unit side: boundaries pinned from preview_text.json, one
    non-empty passage per class (the picker's data)."""
    _qapp()
    from fengrid.bridges.fonts import Fonts
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    fonts_bridge = Fonts(con, str(tmp_path / "t.db"))
    assert fonts_bridge.smallMaxPx == 19
    assert fonts_bridge.mediumMaxPx == 47
    small = fonts_bridge.specimenSmall
    medium = fonts_bridge.specimenMedium
    large = fonts_bridge.specimenLarge
    for text in (small, medium, large):
        assert isinstance(text, str) and len(text) > 10
    # three distinct curated passages — the classes swap real content
    assert len({small, medium, large}) == 3
    # reshuffle rotates every property under one signal
    fonts_bridge.reshuffle_preview_text()
    assert len(fonts_bridge.specimenSmall) > 10
    assert len(fonts_bridge.specimenMedium) > 10
    assert len(fonts_bridge.specimenLarge) > 10


def test_preview_text_slot_still_resolves_buckets(tmp_path):
    """The slot keeps serving single-shot callers (inspector specimen)."""
    _qapp()
    from fengrid.bridges.fonts import Fonts
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    fonts_bridge = Fonts(con, str(tmp_path / "t.db"))
    assert fonts_bridge.preview_text(12) == fonts_bridge.specimenSmall
    assert fonts_bridge.preview_text(30) == fonts_bridge.specimenMedium
    assert fonts_bridge.preview_text(80) == fonts_bridge.specimenLarge


def test_grid_resize_re_scales_without_bridge_calls(fonts_ui):
    """#137 core: a prefs.fontGridSize change re-scales the grid AND swaps
    the specimen size class with ZERO preview_text invocations."""
    grid, fonts_bridge, prefs = (fonts_ui["grid"], fonts_ui["fonts"],
                                 fonts_ui["prefs"])
    initial_cell = int(grid.property("cellWidth"))
    # fixture fresh prefs default font_grid_size = 32 → fontScale 0.5 → 110
    assert initial_cell == 110

    calls = {"n": 0}
    orig = fonts_bridge.preview_text

    def counting(px):
        calls["n"] += 1
        return orig(int(px))

    fonts_bridge.preview_text = counting

    # large class: 128/64 → scale 2.0 → cell 440, specimenPx 52 (>47)
    prefs.set_font_grid_size(128)
    _settle(_qapp(), 1.0)
    assert int(grid.property("cellWidth")) == 440
    assert calls["n"] == 0, "resize path re-crossed the Python bridge"
    shown = _find_preview_text(fonts_ui["root"], fonts_bridge)
    assert shown is not None
    assert str(shown.property("text")) == fonts_bridge.specimenLarge

    # small class: 16/64 → clamped scale 0.45 → cell 99, specimenPx 12
    prefs.set_font_grid_size(16)
    _settle(_qapp(), 1.0)
    assert int(grid.property("cellWidth")) == 99
    assert calls["n"] == 0, "resize path re-crossed the Python bridge"
    shown = _find_preview_text(fonts_ui["root"], fonts_bridge)
    assert shown is not None
    assert str(shown.property("text")) == fonts_bridge.specimenSmall
    assert abs(float(shown.property("font").pixelSize()) - 12) < 0.01

    # medium class: 80/64 → scale 1.25 → cell 275, specimenPx 33
    prefs.set_font_grid_size(80)
    _settle(_qapp(), 1.0)
    assert int(grid.property("cellWidth")) == 275
    assert calls["n"] == 0
    shown = _find_preview_text(fonts_ui["root"], fonts_bridge)
    assert shown is not None
    assert str(shown.property("text")) == fonts_bridge.specimenMedium
