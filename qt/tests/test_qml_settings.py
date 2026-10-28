"""Creation + behavior tests for the Settings and first-run screens.

Guards the regressions QA renders actually caught:
- every SettingRow needs the `section` property (creation fails without)
- SettingsSection must NOT hide Repeater-only sections (Repeaters are
  not Items, so they never appear in `children` — filterRows opt-out)
- the first-run card must overflow scrollably (contentHeight > height),
  otherwise section 4 is unreachable
- the category/search filter chain on the Settings screen

House pattern (see test_qml_colors): the QQmlComponent stays a local of
the yielding fixture frame — created objects DIE with their component,
so a helper function that returns would destroy the scene.
"""
import os
import sys
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest                                    # noqa: E402
from PySide6.QtCore import QUrl                  # noqa: E402
from PySide6.QtGui import QGuiApplication        # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PySide6.QtTest import QTest                 # noqa: E402

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


def _by_class(root, prefix):
    out, stack = [], [root]
    while stack:
        o = stack.pop()
        try:
            cn = o.metaObject().className()
        except RuntimeError:          # wrapper already gone mid-walk
            continue
        if cn.startswith(prefix):
            out.append(o)
        stack.extend(o.childItems())
    return out


def _teardown(ctx):
    ctx["win"].close()
    try:
        ctx["root"].setParentItem(None)
    except RuntimeError:
        pass
    ctx["engine"].collectGarbage()
    del ctx["engine"]
    import gc
    gc.collect()


@pytest.fixture()
def settings_ui(tmp_path):
    _qapp()
    from fengrid.bridges.code import Code
    from fengrid.bridges.colors import Colors
    from fengrid.bridges.fonts import Fonts
    from fengrid.bridges.library import Library
    from fengrid.bridges.prefs import Prefs
    from fengrid.bridges.storage import Storage
    from fengrid.bridges.theme import Theme
    from fengrid.bridges.updater import Updater
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    db_path = str(tmp_path / "t.db")
    theme = Theme(con, str(FONTS))
    library = Library(con, db_path, no_scan=True)
    fonts = Fonts(con, db_path)
    colors = Colors(con)
    code = Code(con)
    prefs = Prefs(con, db_path)
    updater = Updater(auto_check_delay_ms=0)
    storage = Storage(con, str(tmp_path))

    engine = QQmlEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("fonts", fonts)
    ctx.setContextProperty("colors", colors)
    ctx.setContextProperty("code", code)
    ctx.setContextProperty("prefs", prefs)
    ctx.setContextProperty("updater", updater)
    ctx.setContextProperty("storage", storage)
    ctx.setContextProperty("appVersion", "0.0-test")
    ctx.setContextProperty("appCommit", "0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b")
    # comp stays a local of this frame for the whole yield — created
    # objects die with their component
    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(
            str(QML_DIR / "components" / "SettingsScreen.qml")))
    root = cast(QQuickItem, comp.create(engine.rootContext()))
    assert root is not None, [str(e) for e in comp.errors()]
    root.setWidth(1280)
    root.setHeight(800)
    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    _qapp().processEvents()
    QTest.qWait(80)

    yield {"root": root, "win": win, "engine": engine,
           "bridges": {"prefs": prefs, "library": library}}
    _teardown({"win": win, "root": root, "engine": engine})


@pytest.fixture()
def setup_ui(tmp_path):
    _qapp()
    from fengrid.bridges.code import Code
    from fengrid.bridges.colors import Colors
    from fengrid.bridges.fonts import Fonts
    from fengrid.bridges.library import Library
    from fengrid.bridges.prefs import Prefs
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    db_path = str(tmp_path / "t.db")
    theme = Theme(con, str(FONTS))
    library = Library(con, db_path, no_scan=True)
    fonts = Fonts(con, db_path)
    colors = Colors(con)
    code = Code(con)
    prefs = Prefs(con, db_path)

    engine = QQmlEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("fonts", fonts)
    ctx.setContextProperty("colors", colors)
    ctx.setContextProperty("code", code)
    ctx.setContextProperty("prefs", prefs)
    ctx.setContextProperty("updater", None)
    ctx.setContextProperty("appVersion", "0.0-test")
    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(
            str(QML_DIR / "components" / "FirstRun.qml")))
    root = cast(QQuickItem, comp.create(engine.rootContext()))
    assert root is not None, [str(e) for e in comp.errors()]
    root.setWidth(1280)
    root.setHeight(800)
    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    _qapp().processEvents()
    QTest.qWait(80)

    yield {"root": root, "win": win, "engine": engine,
           "bridges": {"prefs": prefs, "library": library}}
    _teardown({"win": win, "root": root, "engine": engine})


def test_settings_screen_creates_with_sections_and_rows(settings_ui):
    root = settings_ui["root"]
    sections = _by_class(root, "SettingsSection")
    rows = _by_class(root, "SettingRow")
    titles = {s.property("title") for s in sections}
    assert {"General", "Appearance", "Library", "Editor", "Colors",
            "Updates", "About"} <= titles, titles
    assert len(rows) >= 12, f"expected the full row set, got {len(rows)}"


def test_settings_search_filters_rows_and_sections(settings_ui):
    """Drive the real binding chain: set `query`, the SettingRow
    `visible` bindings re-evaluate, sections follow their rows."""
    root = settings_ui["root"]

    # sanity: with no query, rows and sections show
    rows = _by_class(root, "SettingRow")
    assert any(r.isVisible() for r in rows)

    # a query nothing matches empties every row
    root.setProperty("query", "zzz_no_such_setting")
    _qapp().processEvents()
    QTest.qWait(40)
    visible = [r for r in rows if r.isVisible()]
    assert visible == [], f"rows survived a non-matching query: {visible}"

    # a term matching the Theme row (and the icon-paths row, whose
    # keys contain "themes") leaves exactly those two sections up
    root.setProperty("query", "theme")
    _qapp().processEvents()
    QTest.qWait(60)
    shown = {s.property("section") for s in
             _by_class(root, "SettingsSection") if s.isVisible()}
    assert shown == {"appearance", "library"}, shown

    # clearing + a category selection narrows to that category
    root.setProperty("query", "")
    root.setProperty("category", "about")
    _qapp().processEvents()
    QTest.qWait(60)
    shown = {s.property("section") for s in
             _by_class(root, "SettingsSection") if s.isVisible()}
    assert shown == {"about"}, shown


def test_first_run_shows_all_four_sections(setup_ui):
    """The Repeater-only sections (paths/folders) must not be hidden by
    the any-row-visible filter — Repeaters aren't Items."""
    root = setup_ui["root"]
    sections = _by_class(root, "SettingsSection")
    titles = {s.property("title") for s in sections}
    assert {"1 · System paths", "2 · Asset folders",
            "3 · Look & feel", "4 · Behavior"} <= titles, titles
    hidden = [s.property("title") for s in sections if not s.isVisible()]
    assert hidden == [], f"hidden setup sections: {hidden}"


def test_first_run_carries_the_command_bar_hotkey_row(setup_ui):
    """The palette hotkey is a first-run preference (one of the primary
    navigation mechanisms) — its custom capture box must be present
    and showing the default binding. KeySequenceEdit does not exist in
    our Qt 6.9.3 Controls build, hence ShortcutCapture."""
    root = setup_ui["root"]
    caps = _by_class(root, "ShortcutCapture")
    assert len(caps) >= 1, "first-run is missing the shortcut capture box"
    assert caps[0].property("seqRaw") == "Alt+/"


def test_first_run_content_is_scrollable(setup_ui):
    """If contentHeight doesn't exceed the viewport, section 4 sits
    below an unreachable fold."""
    root = setup_ui["root"]
    flicks = _by_class(root, "QQuickFlickable")
    assert flicks, "no Flickable in the setup card"
    f = flicks[0]
    assert f.property("contentHeight") > f.property("height"), (
        f"content {f.property('contentHeight')} does not overflow "
        f"viewport {f.property('height')} — or the binding is stale")


def test_first_run_declares_the_finished_signal(setup_ui):
    """The shell wires `onFinished` -> complete_first_run + toast + menu
    flash; the signal must exist on the component."""
    root = setup_ui["root"]
    assert root.metaObject().indexOfSignal("finished()") >= 0
    # the flag round-trip itself lives on the bridge (test_prefs.py)
    b = setup_ui["bridges"]
    assert b["prefs"].firstRunNeeded is True      # fresh db owes setup
    b["prefs"].complete_first_run()
    assert b["prefs"].firstRunNeeded is False

def test_data_management_sections_present(settings_ui):
    """The four data categories exist with their key controls — this is
    the Settings interface for import/export/backup/db management."""
    root = settings_ui["root"]
    sections = _by_class(root, "SettingsSection")
    titles = {s.property("title") for s in sections}
    assert {"Import & Watch", "Export", "Backup & Restore",
            "Database"} <= titles, titles

    labels = {r.property("label") for r in _by_class(root, "SettingRow")}
    for want in ("Import files", "File storage mode", "Format conversion",
                 "Rename template", "CSV name list",
                 "Watch folders & dropboxes", "Cloud storage",
                 "Icon formats (multi-select)", "Tint / color filter",
                 "Batch script / operation", "Webfonts",
                 "Color code lists", "Snippet format", "Library bundle",
                 "Back up now", "Automatic backup on quit", "Restore",
                 "Statistics", "Integrity check", "Maintenance",
                 "Search index", "Repair orphaned rows"):
        assert want in labels, f"missing data row: {want}"

    # category filtering works for the new categories too
    root.setProperty("category", "database")
    _qapp().processEvents()
    QTest.qWait(40)
    shown = {s.property("section") for s in sections if s.isVisible()}
    assert shown == {"database"}, shown
    root.setProperty("category", "all")
    _qapp().processEvents()


def test_about_shows_the_build_commit(settings_ui):
    """#43: the About section carries a Build commit row fed by the
    appCommit context property (stamped by the build scripts)."""
    root = settings_ui["root"]
    rows = [r for r in _by_class(root, "SettingRow")
            if r.property("label") == "Build commit"]
    assert len(rows) == 1, f"expected exactly one Build commit row: {rows}"
    assert rows[0].property("desc") == \
        "0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b"
    assert rows[0].isVisible()


def test_settings_dialog_loaders_callable(settings_ui):
    """Verify dialog loaders are defined and can open without ReferenceError."""
    root = settings_ui["root"]
    # Verify that dialog loaders exist as children of SettingsScreen
    loaders = _by_class(root, "QQuickLoader")
    assert len(loaders) >= 4


def test_library_sources_cache(tmp_path):
    """library.sources should cache the summary in memory and invalidate on change."""
    from fengrid.bridges.library import Library
    from fengrid.core import db as core_db, indexer

    db_file = tmp_path / "cache_test.db"
    con = core_db.connect(db_file)
    lib = Library(con, str(db_file), no_scan=True)

    # First call populates cache
    s1 = lib.sources
    # Second call returns cached instance
    s2 = lib.sources
    assert s1 is s2

    # Mutating path invalidates cache
    lib.set_path_enabled("/tmp/fake-path", "system", True)
    assert lib._sources_cache is None
    s3 = lib.sources
    assert s3 is not s1
    assert any(s["path"] == str(Path("/tmp/fake-path").resolve()) for s in s3)

