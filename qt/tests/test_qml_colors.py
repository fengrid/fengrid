"""Interaction test for the Colors pane lock buttons.

Regression test for the lock feature: the swatch card's selection
MouseArea used to stack ABOVE the lock/remove buttons (sibling order) and
swallowed their clicks — locks could never be SET from the UI. This test
drives real window-level mouse events through the actual delivery path
(the window routes to the topmost item at the position, which is exactly
what real input does) and asserts the bridge state flips.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt, QUrl
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


@pytest.fixture()
def colors_ui(tmp_path):
    _qapp()
    from fengrid.bridges.colors import Colors
    from fengrid.bridges.library import Library
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    theme = Theme(con, str(FONTS))
    colors_bridge = Colors(con)
    library = Library(con, str(tmp_path / "t.db"), no_scan=True)

    engine = QQmlEngine()
    engine.rootContext().setContextProperty("theme", theme)
    engine.rootContext().setContextProperty("colors", colors_bridge)
    engine.rootContext().setContextProperty("library", library)
    engine.rootContext().setContextProperty("previewProfile", None)
    engine.rootContext().setContextProperty("terms", None)
    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(str(QML_DIR / "components" / "Colors.qml")))
    root = comp.create(engine.rootContext())
    assert root is not None, comp.errors()
    root.setWidth(1100)
    root.setHeight(700)

    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    _qapp().processEvents()

    yield {"root": root, "win": win, "colors": colors_bridge, "con": con}

    # teardown in the proven order (bridges alive while the engine dies)
    win.close()
    root.setParentItem(None)
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()


def _window_click(win, scene_pos):
    """Press + release at a scene position on the WINDOW — delivery goes to
    the topmost item at that position, i.e. the real stacking order."""
    for typ, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                         (QEvent.MouseButtonRelease, Qt.LeftButton)):
        ev = QMouseEvent(typ, scene_pos, scene_pos, Qt.LeftButton, buttons,
                         Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(win, ev)
        _qapp().processEvents()


def _window_move(win, scene_pos):
    ev = QMouseEvent(QEvent.MouseMove, scene_pos, scene_pos, Qt.NoButton,
                     Qt.NoButton, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(win, ev)
    _qapp().processEvents()


def _sw_tool_buttons(root):
    """The 24x24 swatch tool buttons (lock / remove), scene-sorted."""
    hits = []
    stack = [root]
    while stack:
        o = stack.pop()
        cls = o.metaObject().className()
        # inline-component buttons report as "SwTool_QMLTYPE_n", not Button
        if cls.startswith("SwTool") and abs(o.width() - 24) < 0.5 \
                and abs(o.height() - 24) < 0.5:
            hits.append(o)
        stack.extend(o.childItems())
    hits.sort(key=lambda b: (b.mapToScene(QPointF(0, 0)).y(),
                             b.mapToScene(QPointF(0, 0)).x()))
    return hits


def test_lock_button_click_flips_lock_state(colors_ui):
    ed = colors_ui
    bridge, win, root = ed["colors"], ed["win"], ed["root"]

    buttons = _sw_tool_buttons(root)
    assert len(buttons) >= 2, "swatch tool buttons not found"

    # select swatch 0 by clicking its card body: the selected card's tools
    # stay visible (not hover-gated), making the clicks deterministic
    center = buttons[0].mapToScene(QPointF(12, 12))
    card_center = QPointF(center.x() - 30, center.y() + 40)
    _window_move(win, card_center)
    _window_click(win, card_center)
    _qapp().processEvents()
    assert bridge.selectedIdx == 0, "swatch not selected by card click"

    def click_lock():
        # delegates are re-created on every swatchesChanged — re-find
        btn = _sw_tool_buttons(root)[0]
        pos = btn.mapToScene(QPointF(12, 12))
        assert btn.isVisible(), "lock button not visible on selected card"
        _window_click(win, pos)

    assert bridge.swatches[0]["locked"] is False
    click_lock()
    _qapp().processEvents()
    assert bridge.swatches[0]["locked"] is True, \
        "click did not reach the lock button — stacking still broken"

    # second click un-locks
    click_lock()
    _qapp().processEvents()
    assert bridge.swatches[0]["locked"] is False


def test_lock_survives_rule_switch_and_generate(colors_ui):
    ed = colors_ui
    bridge = ed["colors"]
    bridge.toggle_lock(0)
    bridge.toggle_lock(2)
    locked_before = (bridge.swatches[0]["hex"], bridge.swatches[2]["hex"])
    assert bridge.swatches[0]["locked"] and bridge.swatches[2]["locked"]

    bridge.set_rule("complementary")
    bridge.generate()
    bridge.set_rule("analogous")
    bridge.generate()

    # locks survive both rerolls byte-for-byte
    assert bridge.swatches[0]["hex"] == locked_before[0]
    assert bridge.swatches[2]["hex"] == locked_before[1]
    assert bridge.swatches[0]["locked"] and bridge.swatches[2]["locked"]
