"""Projects pane layout: the live preview lives in a BOTTOM band.

Loads the real Projects.qml offscreen and asserts the Code-pane-style
two-row arrangement: upper row = studio screens + property inspector,
lower row = the preview/dock/status Rectangle spanning the full width.
"""
import gc
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem  # noqa: F401 — ensures shiboken

# casts component roots to QQuickItem (setWidth/childItems resolve)

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


def _pump(ms=150):
    t0 = time.time()
    while time.time() - t0 < ms / 1000.0:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def _walk(item, cls_names):
    stack = [item]
    found = []
    while stack:
        o = stack.pop()
        name = o.metaObject().className()
        if any(c in name for c in cls_names):
            found.append(o)
        stack.extend(o.childItems())
    return found


def _map_to_root(item, root):
    """Accumulated (x, y) of item in root's coordinate space."""
    x = y = 0.0
    it = item
    while it is not None and it is not root:
        x += it.property("x") or 0
        y += it.property("y") or 0
        it = it.parentItem()
    return x, y


@pytest.fixture()
def projects_qml(tmp_path):
    # QGuiApplication must exist before Theme registers fonts (QFontDatabase)
    _qapp()
    from fengrid.bridges.colors import Colors
    from fengrid.bridges.demo import Demo
    from fengrid.bridges.fonts import Fonts
    from fengrid.bridges.library import Library
    from fengrid.bridges.projects import Projects
    from fengrid.bridges.studio import Studio
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    db_path = str(tmp_path / "t.db")
    theme = Theme(con, str(FONTS))
    projects = Projects(con)
    studio = Studio(con)
    fonts = Fonts(con, db_path)
    colors = Colors(con)
    library = Library(con, db_path, no_scan=True)
    demo = Demo(con, str(tmp_path / "demo-assets"), str(tmp_path / "fonts"))

    engine = QQmlEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("projects", projects)
    ctx.setContextProperty("studio", studio)
    ctx.setContextProperty("fonts", fonts)
    ctx.setContextProperty("colors", colors)
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("demo", demo)
    ctx.setContextProperty("previewProfile", None)
    ctx.setContextProperty("softwareRenderer", True)

    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(str(QML_DIR / "components" / "Projects.qml")))
    root = comp.create(ctx)
    assert root is not None, comp.errors()
    # Projects.qml instantiates as a plain QObject wrapper in PySide6 —
    # setWidth/setHeight don't resolve; QML properties do
    root.setWidth(1280)
    root.setHeight(800)
    _pump(120)

    yield {"root": root, "engine": engine, "projects": projects,
           "studio": studio, "con": con}

    # teardown in the proven order (bridges alive while the engine dies)
    root.setParentItem(None)
    engine.collectGarbage()
    del engine
    gc.collect()
    con.close()


def test_preview_is_bottom_band(projects_qml):
    """The preview Loader's band sits in the lower half and spans ~full width."""
    root = projects_qml["root"]
    _pump(120)
    root_w = root.property("width")
    root_h = root.property("height")

    # The preview band contains the WYSIWYG hint text; find the play-icon
    # hint Text and walk to its enclosing preview Item (pvArea).
    texts = _walk(root, ["QQuickText"])
    hint = None
    for t in texts:
        txt = t.property("text") or ""
        if "Live preview renders automatically" in txt:
            hint = t
            break
    assert hint is not None, "preview hint text not found"

    # pvArea = the Item that fills the preview band; its band parent is a
    # The preview band = the enclosing QQuickRectangle of the hint text
    # (the anchored lower Rectangle holding preview + dock + status).
    band = hint
    while band is not None and "QQuickRectangle" not in band.metaObject().className():
        band = band.parentItem()
    assert band is not None, "preview band Rectangle not found"

    x, y = _map_to_root(band, root)
    w = band.property("width")
    h = band.property("height")
    # full-width: the band starts at the main area's left edge (only the
    # fixed side rail sits left of it)
    assert x < 260, f"preview band not at the left edge (x={x})"
    assert w > root_w * 0.6, (
        f"preview band spans only {w}/{root_w} of the pane width")
    # bottom band: the band's top is below the upper row (~55% height) and
    # it reaches the bottom of the pane
    assert y > root_h * 0.4, f"preview band not in the lower half (y={y})"
    assert abs((y + h) - root_h) < 2, (
        f"preview band does not reach the pane bottom ({y}+{h} vs {root_h})")
    # bottom band: starts below the upper row (which is ~55% of the height)
    assert y > root_h * 0.4, f"preview band not in the lower half (y={y})"


def test_inspector_in_upper_row(projects_qml):
    """The property inspector stays in the upper row, pinned right."""
    root = projects_qml["root"]
    _pump(120)
    root_w = root.property("width")
    root_h = root.property("height")

    texts = _walk(root, ["QQuickText"])
    target = None
    for t in texts:
        if t.property("text") == "INSPECTOR":
            target = t
            break
    assert target is not None, "INSPECTOR header not found"

    rect = target
    while rect is not None and "QQuickRectangle" not in rect.metaObject().className():
        rect = rect.parentItem()
    assert rect is not None, "inspector Rectangle not found"

    x, y = _map_to_root(rect, root)
    w = rect.property("width")
    h = rect.property("height")
    # upper row only: bottom must stay above the preview band
    assert y + h < root_h * 0.62, (
        f"inspector extends into the preview band (bottom={y + h}, "
        f"root_h={root_h})")
    # pinned right
    assert x + w > root_w * 0.6, f"inspector not on the right (x={x}, w={w})"
