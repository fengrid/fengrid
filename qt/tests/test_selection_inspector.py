"""Multi-selection inspector + bulk export: checkbox selection in the
icons grid drives an aggregate properties summary (library.selection_details)
and the Export action exports the whole selection as one package
(library.selection_paths → dataio.exportIcons(paths, …)).

Bridge-level tests assert the aggregates directly; the QML test drives
InspectorPanel into its multi-selection mode and asserts the summary UI.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject

QML_DIR = Path(__file__).resolve().parents[1] / "qml"
SRC = Path(__file__).resolve().parents[1] / "src"
FONTS = Path(__file__).resolve().parents[2] / "fonts"
sys.path.insert(0, str(SRC))

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        from PySide6.QtGui import QGuiApplication
        _APP = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


def _var(value):
    """QML var properties come back as QJSValue — unwrap to Python."""
    return value.toVariant() if hasattr(value, "toVariant") else value


def _seed_icons(con, tmp_path):
    """Three icon assets with distinct measurable properties + tags."""
    sid = con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder', ?, 't', 1)", (str(tmp_path),)).lastrowid
    rows = [
        # name, path, ext, bytes, width, height, mono, color_count, theme
        ("alpha", "a.png", "png", 1000, 16, 16, 1, 2, "fen"),
        ("bravo", "b.png", "png", 2500, 64, 64, 0, 24, "fen"),
        ("charlie", "c.svg", "svg", 400, None, None, None, None, "lucide"),
    ]
    ids = []
    for i, (name, fname, ext, nbytes, w, h, mono, cc, theme) in enumerate(rows):
        aid = con.execute(
            "INSERT INTO asset(source_id, kind, name, path, ext, bytes,"
            " width, height, size_px, mono, color_count, theme)"
            " VALUES (?, 'icon', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, name, str(tmp_path / fname), ext, nbytes, w, h,
             w, mono, cc, theme)).lastrowid
        ids.append(aid)
    # 'ui' is shared by ALL three; 'misc' only by alpha
    for name in ("ui", "misc"):
        con.execute("INSERT INTO tag(name) VALUES (?)", (name,))
    for aid in ids:
        con.execute(
            "INSERT INTO item_tag(item_id, item_kind, tag_id)"
            " VALUES (?, 'icon', (SELECT id FROM tag WHERE name = 'ui'))",
            (aid,))
    con.execute(
        "INSERT INTO item_tag(item_id, item_kind, tag_id)"
        " VALUES (?, 'icon', (SELECT id FROM tag WHERE name = 'misc'))",
        (ids[0],))
    # star bravo
    con.execute(
        "INSERT INTO item_tag(item_id, item_kind, tag_id)"
        " VALUES (?, 'icon', (SELECT id FROM tag WHERE name = 'starred'))",
        (ids[1],))
    con.commit()
    return ids


@pytest.fixture()
def lib_env(tmp_path):
    _qapp()
    from fengrid.bridges.library import Library
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    ids = _seed_icons(con, tmp_path)
    library = Library(con, str(tmp_path / "t.db"), no_scan=True)
    yield {"library": library, "con": con, "ids": ids, "tmp": tmp_path}
    library._on_about_to_quit()
    con.close()


# ------------------------------------------------------------ aggregates
def test_selection_details_aggregates(lib_env):
    d = _var(lib_env["library"].selection_details(lib_env["ids"]))
    assert d["count"] == 3
    assert d["bytes"] == 1000 + 2500 + 400
    fmts = {f["ext"]: f["n"] for f in d["formats"]}
    assert fmts == {"png": 2, "svg": 1}
    assert d["minW"] == 16 and d["maxW"] == 64
    assert d["minH"] == 16 and d["maxH"] == 64
    assert d["mono"] == 1 and d["color"] == 1
    assert d["avgColors"] == round((2 + 24) / 2, 1)
    assert d["sharedTags"] == ["ui"]          # 'misc' is alpha-only
    assert d["starred"] == 1
    assert d["themes"] == ["fen", "lucide"]
    assert len(d["paths"]) == 3 and len(d["names"]) == 3


def test_selection_details_filters_unknown_ids(lib_env):
    ids = lib_env["ids"]
    d = _var(lib_env["library"].selection_details(
        [ids[0], ids[1], 99999, "junk", -3, 0]))
    assert d["count"] == 2
    # font rows must never leak into the icon selection summary
    con = lib_env["con"]
    con.execute(
        "INSERT INTO asset(source_id, kind, name, path, family)"
        " VALUES ((SELECT MIN(id) FROM source), 'font', 'F', '/x/f.ttf', 'F')")
    con.commit()
    d2 = _var(lib_env["library"].selection_details([ids[0], ids[1]]))
    assert d2["count"] == 2


def test_selection_details_empty_is_empty(lib_env):
    assert _var(lib_env["library"].selection_details([])) == {}
    assert _var(lib_env["library"].selection_details(None)) == {}
    assert _var(lib_env["library"].selection_details([99999])) == {}


def test_selection_paths_order_and_content(lib_env):
    paths = _var(lib_env["library"].selection_paths(
        list(reversed(lib_env["ids"]))))
    assert len(paths) == 3
    assert all(str(p).endswith((".png", ".svg")) for p in paths)
    # order follows the id list, not the database
    assert paths[-1].endswith("a.png")


def test_copy_names_joins_selection(lib_env):
    from PySide6.QtGui import QGuiApplication
    lib_env["library"].copy_names(lib_env["ids"][:2])
    assert QGuiApplication.clipboard().text() == "alpha\nbravo"


def test_bulk_export_job_writes_every_selected_asset(lib_env):
    """The inspector/bulk-menu Export path: dataio.exportIcons with the
    selection's paths must write one output per selected asset in ONE
    job (driven through a real event loop — bridge-threading bugs only
    surface on the bridge, not on the core function)."""
    import time

    from PIL import Image

    from fengrid.bridges.data import DataIO

    ids, tmp = lib_env["ids"], lib_env["tmp"]
    # real image files — the core exporter opens them (SVG rasterization
    # in the worker thread is covered by the core export tests; this one
    # pins the multi-path batch through the bridge job)
    Image.new("RGBA", (16, 16), (200, 60, 60, 255)).save(tmp / "a.png")
    Image.new("RGBA", (32, 32), (60, 60, 200, 255)).save(tmp / "b.png")
    (tmp / "c.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        '<circle cx="8" cy="8" r="6" fill="#39B8C4"/></svg>',
        encoding="utf-8")
    dest = tmp / "export-out"
    app = _qapp()
    dio = DataIO(lib_env["con"], str(tmp / "t.db"), str(tmp))
    done = []
    dio.jobDone.connect(lambda kind, summary: done.append(kind))
    dio.exportIcons(lib_env["library"].selection_paths(ids), str(dest),
                    '{"icon_fmts":["png"],"icon_size":"orig"}')
    deadline = time.monotonic() + 15
    while not done and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert done == ["export"]
    # every selected asset landed in one folder, one output each
    assert sorted(p.name for p in dest.glob("*")) == ["a.png", "b.png", "c.png"]


# --------------------------------------------------------------- QML panel
def _walk(item):
    """All descendant QObjects (comp.create() hands back a plain QObject
    wrapper — childItems is not reachable, findChildren recurses)."""
    return item.findChildren(QObject)


@pytest.fixture()
def panel_ui(lib_env):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    from fengrid.bridges.taxonomy import Taxonomy
    from fengrid.bridges.theme import Theme

    con, library = lib_env["con"], lib_env["library"]
    theme = Theme(con, str(FONTS))
    taxonomy = Taxonomy(con, str(lib_env["tmp"]))

    engine = QQmlEngine()
    engine.rootContext().setContextProperty("theme", theme)
    engine.rootContext().setContextProperty("library", library)
    engine.rootContext().setContextProperty("taxonomy", taxonomy)
    engine.rootContext().setContextProperty("dataio", None)
    engine.rootContext().setContextProperty("prefs", None)
    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(
            str(QML_DIR / "components" / "InspectorPanel.qml")))
    panel = comp.create(engine.rootContext())
    assert panel is not None, comp.errors()
    panel.setProperty("width", 300)
    panel.setProperty("height", 700)
    panel.setProperty("visible", True)
    _qapp().processEvents()

    yield {"panel": panel, "library": library, "ids": lib_env["ids"]}

    panel.setParentItem(None) if hasattr(panel, "setParentItem") else None
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()


def test_panel_single_view_by_default(panel_ui):
    panel = panel_ui["panel"]
    assert panel.property("multi") in (False, None)
    assert _var(panel.property("sel")) in ({}, None)


def test_panel_multi_selection_summary(panel_ui):
    panel, ids = panel_ui["panel"], panel_ui["ids"]
    panel.setProperty("selectedIds", ids)
    _qapp().processEvents()

    assert bool(panel.property("multi")) is True
    sel = _var(panel.property("sel"))
    assert sel["count"] == 3

    rows = _var(panel.property("selRows"))
    by_label = {r["l"]: r["v"] for r in rows}
    assert by_label["Items"] == "3"
    assert by_label["Size"] == "3.8 KB"
    assert "png ×2" in by_label["Formats"]
    assert "svg ×1" in by_label["Formats"]
    assert by_label["Pixels"] == "16–64 px"
    assert "1 mono" in by_label["Mode"]

    # header text carries the count; the export button names the package
    texts = [o.property("text") for o in _walk(panel)
             if o.metaObject().className() == "QQuickText"
             and o.property("text")]
    assert any("3 selected" in str(t) for t in texts)
    buttons = [o.property("text") for o in _walk(panel)
               if "Button" in o.metaObject().className()
               and o.property("text")]
    assert any("Export 3 selected" in str(t) for t in buttons)


def test_panel_falls_back_to_single_after_clear(panel_ui):
    panel, ids = panel_ui["panel"], panel_ui["ids"]
    panel.setProperty("selectedIds", ids)
    _qapp().processEvents()
    assert bool(panel.property("multi")) is True
    panel.setProperty("selectedIds", [])
    _qapp().processEvents()
    assert bool(panel.property("multi")) is False
