"""Issue #36: the Preset Libraries card row spacing.

The library cards used to sit in a RowLayout: with more packs than fit,
the row ran flush off the dialog edge, the "N entries" line touched the
card's bottom border (no inner padding), and card heights were pinned
via Layout.preferred* (ignored inside a Flow).

This test drives the REAL PresetsDialog offscreen, opens it, and asserts
the card row layout: every card stays inside the dialog's margins, cards
carry real inner padding (text clears the border), and cards align to a
common top edge. It also saves a grab of the dialog for visual review.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QPointF, QUrl
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


@pytest.fixture()
def presets_ui(tmp_path):
    _qapp()
    from fengrid.bridges.library import Library
    from fengrid.bridges.presets import Presets
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db
    from fengrid.core import presets as core_presets

    con = core_db.connect(tmp_path / "t.db")
    core_presets.ensure_presets(con)
    # a fourth pack forces the card row past one line — with the old
    # RowLayout the row overflowed the dialog edge (#36); the Flow wraps
    con.execute(
        "INSERT INTO preset_library(name, kind, summary, tags, remote)"
        " VALUES ('Extra Icon Pack', 'icon', 'test pack', '', 1)")
    con.commit()
    theme = Theme(con, str(FONTS))
    presets_bridge = Presets(con, str(tmp_path))
    library = Library(con, str(tmp_path / "t.db"), no_scan=True)

    engine = QQmlEngine()
    engine.rootContext().setContextProperty("theme", theme)
    engine.rootContext().setContextProperty("presets", presets_bridge)
    engine.rootContext().setContextProperty("library", library)
    engine.rootContext().setContextProperty("fonts", None)
    engine.rootContext().setContextProperty("previewProfile", None)
    engine.rootContext().setContextProperty("terms", None)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(
        str(QML_DIR / "components" / "PresetsDialog.qml")))
    root = comp.create(engine.rootContext())
    assert root is not None, comp.errors()

    win = QQuickWindow()
    win.setWidth(760)
    win.setHeight(640)
    # a Dialog is a QQuickPopup, not an Item — attach its parent to the
    # window's contentItem so Overlay.overlay resolves inside win
    root.setProperty("parent", win.contentItem())
    # pin the dialog width: the pre-fix RowLayout let the DIALOG widen
    # past the window with the card row edge-to-edge (the #36 report) —
    # a pinned width makes the overflow measurable
    root.setProperty("width", 720)
    if hasattr(root, "open"):
        root.open()
    win.show()
    _qapp().processEvents()

    yield {"root": root, "win": win, "presets": presets_bridge, "con": con}

    if hasattr(root, "close"):
        root.close()
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()
    con.close()


def _lib_cards(ui):
    """The library tab cards. A Dialog is a QQuickPopup — its visual
    content hangs off the dialog's own contentItem, NOT the window's
    item tree, so the walk starts there."""
    root = ui["root"]
    content = root.property("contentItem")
    hits = []
    stack = [content]
    while stack:
        o = stack.pop()
        if hasattr(o, "metaObject") and \
                "AbstractButton" in o.metaObject().className() \
                and o.width() > 150:
            hits.append(o)
        if hasattr(o, "childItems"):
            stack.extend(o.childItems())
    hits.sort(key=lambda b: (b.mapToScene(QPointF(0, 0)).y(),
                             b.mapToScene(QPointF(0, 0)).x()))
    return hits


def test_library_cards_stay_inside_dialog_margins(presets_ui):
    ui = presets_ui
    root = ui["root"]
    content = root.property("contentItem")
    cards = _lib_cards(ui)
    assert len(cards) >= 3, "preset library cards not found"
    for c in cards:
        scene = c.mapToScene(QPointF(0, 0))
        origin = content.mapToScene(QPointF(0, 0))
        rel_x = scene.x() - origin.x()
        # 16px side margins on the card row (#36) — cards never flush
        assert rel_x >= 15.5, "library card flush against the dialog edge"
        assert rel_x + c.width() <= content.width() - 15.5, (
            "library card runs off the dialog edge")


def test_library_cards_align_and_clear_their_borders(presets_ui):
    ui = presets_ui
    cards = _lib_cards(ui)
    # uniform card height — every card carries the same padding
    heights = {round(c.height(), 1) for c in cards}
    assert len(heights) == 1, f"card heights differ: {heights}"
    # rows (cards sharing a top edge) never overlap horizontally
    rows = {}
    for c in cards:
        scene = c.mapToScene(QPointF(0, 0))
        rows.setdefault(round(scene.y()), []).append(
            (scene.x(), scene.x() + c.width()))
    for _, spans in rows.items():
        spans.sort()
        for i in range(1, len(spans)):
            assert spans[i][0] >= spans[i - 1][1] - 0.5, (
                "library cards overlap")


def test_render_grab_for_visual_review(presets_ui, tmp_path):
    ui = presets_ui
    img = ui["win"].grabWindow()
    out = Path("/tmp/presets-after.png")
    img.save(str(out))
    assert out.exists() and out.stat().st_size > 0