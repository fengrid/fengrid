"""Issue #39/#52: the Fonts pane gets the Icons pane's multi-select —
checkbox click toggles, Ctrl-click toggles, Shift-click fills a range —
and the CSS/webfont export dialog takes its family set from that
selection instead of its own chip cloud.

Drives REAL window-level mouse events (with keyboard modifiers) through
the actual delivery path into Fonts.qml and asserts the bridge/dialog
state. `family_at` on FamilyModel is the Shift-range row→family map; the
dialog's openWith() accepts an array of families (a string still works).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt, QUrl
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication, QMouseEvent
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


def _var(value):
    """QML var properties come back as QJSValue — unwrap to Python."""
    return value.toVariant() if hasattr(value, "toVariant") else value


def _seed_fonts(con, tmp_path):
    """Three families (A/B/C) directly in the asset table — the fonts
    bridge's _refresh() groups kind='font' rows by family."""
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

    engine = QQmlEngine()
    engine.rootContext().setContextProperty("theme", theme)
    engine.rootContext().setContextProperty("fonts", fonts_bridge)
    engine.rootContext().setContextProperty("library", library)
    engine.rootContext().setContextProperty("taxonomy", taxonomy)
    engine.rootContext().setContextProperty("previewProfile", None)
    engine.rootContext().setContextProperty("terms", None)
    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(str(QML_DIR / "components" / "Fonts.qml")))
    root = comp.create(engine.rootContext())
    assert root is not None, comp.errors()
    root.setWidth(1100)
    root.setHeight(700)

    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    _qapp().processEvents()

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
           "con": con}

    win.close()
    root.setParentItem(None)
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()
    con.close()


def _cards(win):
    """The family cards (famCard rectangles, ~212x112), scene-sorted."""
    hits = []
    stack = [win.contentItem()]
    while stack:
        o = stack.pop()
        cls = o.metaObject().className()
        if "QQuickRectangle" in cls and abs(o.width() - 212) < 1.0 \
                and abs(o.height() - 112) < 1.0:
            hits.append(o)
        if hasattr(o, "childItems"):
            stack.extend(o.childItems())
    hits.sort(key=lambda b: (b.mapToScene(QPointF(0, 0)).y(),
                             b.mapToScene(QPointF(0, 0)).x()))
    return hits

def _sel_boxes(win):
    """16x16 selection checkboxes inside the fonts grid, scene-sorted."""
    hits = []
    stack = [win.contentItem()]
    while stack:
        o = stack.pop()
        cls = o.metaObject().className()
        if "QQuickRectangle" in cls and abs(o.width() - 16) < 0.5 \
                and abs(o.height() - 16) < 0.5:
            hits.append(o)
        if hasattr(o, "childItems"):
            stack.extend(o.childItems())
    hits.sort(key=lambda b: (b.mapToScene(QPointF(0, 0)).y(),
                             b.mapToScene(QPointF(0, 0)).x()))
    return hits


def _click(win, item, modifiers=Qt.KeyboardModifier.NoModifier):
    """Hover + mouse click at an item's center through the window
    delivery path, carrying the given keyboard modifiers. The hover
    matters: empty checkboxes are hover-only (#39/#52 semantics)."""
    scene = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    hover = QMouseEvent(QEvent.MouseMove, scene, scene, Qt.NoButton,
                        Qt.NoButton, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(win, hover)
    _qapp().processEvents()
    for typ in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        ev = QMouseEvent(typ, scene, scene, Qt.LeftButton, Qt.LeftButton,
                         modifiers)
        QCoreApplication.sendEvent(win, ev)
        _qapp().processEvents()


def test_checkbox_click_toggles_family(fonts_ui):
    ui = fonts_ui
    win, grid, bridge = ui["win"], ui["grid"], ui["fonts"]
    boxes = _sel_boxes(win)
    assert len(boxes) == 3
    # checkbox click toggles the family into the checked set
    _click(win, boxes[0])
    root = ui["root"]
    assert list(_var(root.property("checkedFams"))) == ["Alpha"]
    # second click unticks
    _click(win, boxes[0])
    assert list(_var(root.property("checkedFams"))) == []


def test_ctrl_click_toggles(fonts_ui):
    ui = fonts_ui
    win, root = ui["win"], ui["root"]
    cards = _cards(win)
    _click(win, cards[1], Qt.KeyboardModifier.ControlModifier)
    assert list(_var(root.property("checkedFams"))) == ["Beta"]
    _click(win, cards[2], Qt.KeyboardModifier.ControlModifier)
    assert sorted(_var(root.property("checkedFams"))) == ["Beta", "Gamma"]
    _click(win, cards[1], Qt.KeyboardModifier.ControlModifier)
    assert list(_var(root.property("checkedFams"))) == ["Gamma"]


def test_shift_click_fills_range(fonts_ui):
    ui = fonts_ui
    win, root = ui["win"], ui["root"]
    cards = _cards(win)
    # anchor: ctrl-click the first card
    _click(win, cards[0], Qt.KeyboardModifier.ControlModifier)
    # shift-click the last card fills Alpha..Gamma
    _click(win, cards[2], Qt.KeyboardModifier.ShiftModifier)
    assert sorted(_var(root.property("checkedFams"))) == \
        ["Alpha", "Beta", "Gamma"]


def test_plain_click_clears_selection_and_selects(fonts_ui):
    ui = fonts_ui
    win, root, bridge = ui["win"], ui["root"], ui["fonts"]
    cards = _cards(win)
    _click(win, cards[0], Qt.KeyboardModifier.ControlModifier)
    assert list(_var(root.property("checkedFams"))) == ["Alpha"]
    # plain click: clears the checked set, selects the family
    _click(win, cards[1])
    assert list(_var(root.property("checkedFams"))) == []
    assert bridge.selectedFamily == "Beta"


def _find_dialog(root):
    """The FontsCssDialog is a QQuickPopup — a QObject, not an item —
    so it is found through the QObject children, not childItems()."""
    stack = [root]
    while stack:
        o = stack.pop()
        if hasattr(o, "metaObject") and \
                "FontsCssDialog" in o.metaObject().className():
            return o
        if hasattr(o, "children"):
            stack.extend(o.children())
    return None


def _export_buttons(win):
    """The toolbar ExportButton inline components (implicitHeight 26)."""
    hits = []
    stack = [win.contentItem()]
    while stack:
        o = stack.pop()
        if hasattr(o, "metaObject") and \
                o.metaObject().className().startswith("ExportButton"):
            hits.append(o)
        if hasattr(o, "childItems"):
            stack.extend(o.childItems())
    hits.sort(key=lambda b: (b.mapToScene(QPointF(0, 0)).y(),
                             b.mapToScene(QPointF(0, 0)).x()))
    return hits


def test_export_button_opens_dialog_with_checked_families(fonts_ui):
    """End-to-end #52: check two families in the grid, click Export CSS,
    and the dialog's family set IS the checked set — no chip picking."""
    ui = fonts_ui
    win, root = ui["win"], ui["root"]
    cards = _cards(win)
    _click(win, cards[0], Qt.KeyboardModifier.ControlModifier)
    _click(win, cards[2], Qt.KeyboardModifier.ControlModifier)
    assert sorted(_var(root.property("checkedFams"))) == ["Alpha", "Gamma"]
    btns = _export_buttons(win)
    assert len(btns) >= 1, "export buttons not found"
    _click(win, btns[0])          # "Export CSS — 2 families"
    dialog = _find_dialog(root)
    assert dialog is not None, "FontsCssDialog not found"
    assert list(_var(dialog.property("chosen"))) == ["Alpha", "Gamma"]
    assert dialog.property("visible") in (True, None)
