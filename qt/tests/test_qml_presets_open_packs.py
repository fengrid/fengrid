"""#141: the rail's Preset Libraries button opens the pack matching the
ACTIVE pane's asset kind — including the Colors pane (palette kind),
which previously fell through to the first pack (Open Fonts)."""
import os
import sys
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
    root.setProperty("parent", win.contentItem())
    if hasattr(root, "open"):
        root.open()
    win.show()
    _qapp().processEvents()
    yield {"root": root, "presets": presets_bridge}
    if hasattr(root, "close"):
        root.close()
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()
    con.close()


@pytest.mark.parametrize("paneKind,packName", [
    ("icon", "Open Icon Sets"),
    ("font", "Open Fonts"),
    ("palette", "Color Harmonies"),
])
def test_rail_button_opens_the_pane_own_pack(presets_ui, paneKind, packName):
    ui = presets_ui
    packs = {p["name"]: p["id"] for p in ui["presets"].libraries}
    ui["root"].openLibrary(-1, paneKind)
    assert ui["root"].property("currentLib") == packs[packName], (
        f"{paneKind} pane must open {packName}")
