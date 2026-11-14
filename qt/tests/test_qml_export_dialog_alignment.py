"""#113: the export dialogs' destination rows — Browse button alignment.

The defect class: FormInput stacks its label ABOVE the field (~47px of
column), so a 30px Browse FgButton sharing that RowLayout defaulted to
Qt.AlignVCenter against the WHOLE stack — it floated beside the label,
roughly 8px above the destination field's top edge (issue #113's two
attachments). The fix pins the trailing button of every destination row
to Qt.AlignBottom: row height is the FormInput stack, the field box is
the column's last child, and both controls are 30px tall, so bottom-
flush alignment makes the tops flush too — and the invariant survives
any future label-metric change.

This test drives the REAL FontsCssDialog and ExportDialog offscreen,
opens them, and asserts the Browse button shares the destination field
box's top AND bottom edges. It fails on pre-fix code by the measured
float, and it covers both dialogs because both carried the same
misaligned row (the class, not the one reported call site).
"""
import gc
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

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


def _browse_row_geometry(root):
    """Top/bottom edges of the destination field box and the Browse
    button, both measured relative to their shared RowLayout."""
    content = root.property("contentItem")
    stack = [content]
    btn = None
    while stack:
        o = stack.pop()
        cn = (o.metaObject().className()
              if hasattr(o, "metaObject") else "")
        if "Button" in cn and o.property("text") == "Browse…":
            btn = o
            break
        if hasattr(o, "childItems"):
            stack.extend(o.childItems())
    assert btn is not None, "Browse… button not found in the dialog"
    row = btn.parent()

    field_item = None
    for child in row.childItems():
        if hasattr(child, "metaObject") and \
                "FormInput" in child.metaObject().className():
            field_item = child
            break
    assert field_item is not None, "destination FormInput not found"

    box = None
    for child in field_item.childItems():
        if hasattr(child, "metaObject") and \
                "Rectangle" in child.metaObject().className():
            box = child
            break
    assert box is not None, "destination field box not found"

    field_top = field_item.y() + box.y()
    field_bottom = field_top + box.height()
    btn_top = btn.y()
    btn_bottom = btn_top + btn.height()
    return {"field_top": field_top, "field_bottom": field_bottom,
            "btn_top": btn_top, "btn_bottom": btn_bottom,
            "field_h": box.height(), "btn_h": btn.height()}


@pytest.fixture()
def fonts_css_ui(tmp_path):
    # Everything stays on THIS frame through the yield — a Dialog
    # component created inside a helper that returns destroys the scene
    # before the test body runs (gotcha: QQmlComponent instances die
    # with their component; keep comp alive on the yielding frame).
    _qapp()
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    theme = Theme(con, str(FONTS))
    engine = QQmlEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    for name in ("fonts", "library", "prefs", "previewProfile", "terms"):
        ctx.setContextProperty(name, None)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(
        str(QML_DIR / "components" / "FontsCssDialog.qml")))
    root = comp.create(ctx)
    assert root is not None, comp.errors()

    win = QQuickWindow()
    win.setWidth(760)
    win.setHeight(640)
    root.setProperty("parent", win.contentItem())
    root.openWith([])
    win.show()
    _qapp().processEvents()

    yield {"root": root, "win": win, "engine": engine, "comp": comp,
           "con": con, "theme": theme}

    if hasattr(root, "close"):
        root.close()
    # ordered teardown: destroy the QML tree FIRST (engine gc) so the
    # dying theme bridge is never re-read by a live binding — the
    # reverse order floods stderr with exit-time "tokens of null"
    engine.collectGarbage()
    del engine, comp, theme
    gc.collect()
    con.close()


@pytest.fixture()
def export_dialog_ui(tmp_path):
    _qapp()
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    theme = Theme(con, str(FONTS))
    engine = QQmlEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    for name in ("fonts", "library", "prefs", "previewProfile", "terms"):
        ctx.setContextProperty(name, None)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(
        str(QML_DIR / "components" / "ExportDialog.qml")))
    root = comp.create(ctx)
    assert root is not None, comp.errors()

    win = QQuickWindow()
    win.setWidth(760)
    win.setHeight(640)
    root.setProperty("parent", win.contentItem())
    root.openWith([], "")
    win.show()
    _qapp().processEvents()

    yield {"root": root, "win": win, "engine": engine, "comp": comp,
           "con": con, "theme": theme}

    if hasattr(root, "close"):
        root.close()
    # ordered teardown: destroy the QML tree FIRST (engine gc) so the
    # dying theme bridge is never re-read by a live binding — the
    # reverse order floods stderr with exit-time "tokens of null"
    engine.collectGarbage()
    del engine, comp, theme
    gc.collect()
    con.close()


def test_fonts_css_dialog_browse_shares_field_edges(fonts_css_ui):
    """#113: the Browse button must align flush with the destination
    field box — same top AND same bottom (both 30px controls)."""
    g = _browse_row_geometry(fonts_css_ui["root"])
    assert g["field_h"] >= 25 and g["btn_h"] >= 25, \
        f"implausible control heights: {g}"
    assert abs(g["field_top"] - g["btn_top"]) <= 1.0, \
        f"Browse floats beside the label, not the field: {g}"
    assert abs(g["field_bottom"] - g["btn_bottom"]) <= 1.0, \
        f"Browse bottom edge does not meet the field bottom: {g}"


def test_export_dialog_browse_shares_field_edges(export_dialog_ui):
    """Same class, second site: the shared ExportDialog's destination
    row misaligned the same way (empty label still occupies a line in
    the FormInput column)."""
    g = _browse_row_geometry(export_dialog_ui["root"])
    assert g["field_h"] >= 25 and g["btn_h"] >= 25, \
        f"implausible control heights: {g}"
    assert abs(g["field_top"] - g["btn_top"]) <= 1.0, \
        f"Browse floats beside the label, not the field: {g}"
    assert abs(g["field_bottom"] - g["btn_bottom"]) <= 1.0, \
        f"Browse bottom edge does not meet the field bottom: {g}"
