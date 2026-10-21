"""Command bar / palette: shortcut preference semantics, the two
independent search slots (assets + snippets), and the QML components
(ShortcutCapture, CommandPalette) — creation, grouping, activation."""
import json
import os
import sys

import pytest
from PySide6.QtCore import QMetaObject, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
QML_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "qml"))

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        _APP = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


# ── preference semantics ────────────────────────────────────────────
def test_command_shortcut_defaults_format_and_persist(tmp_path):
    from fengrid.bridges.prefs import Prefs
    from fengrid.core import db, settings

    con = db.connect(tmp_path / "t.db")
    path = str(tmp_path / "t.db")
    p = Prefs(con, path)
    # the documented default: Option+` on macs maps from Alt+`
    assert p.commandShortcut == "Alt+`"
    assert p.formattedShortcut == "Alt + `"

    p.set_command_shortcut("Ctrl+Shift+P")
    assert p.formattedShortcut == "Ctrl + Shift + P"
    assert settings.get(con, "command_shortcut", None) == "Ctrl+Shift+P"

    # empty is rejected — the placeholder tip must never lie
    p.set_command_shortcut("")
    assert p.commandShortcut == "Alt+`"

    # a fresh Prefs over the same DB sees the stored value
    p2 = Prefs(con, path)
    assert p2.commandShortcut == "Alt+`"


def test_command_shortcut_survives_db_switch(tmp_path):
    """Global routing: the binding lives in the registry, so switching
    databases (one active at a time) keeps the user's hotkey."""
    from fengrid.bridges.prefs import Prefs
    from fengrid.core import db, registry, settings

    reg = registry.open_registry(tmp_path)
    con = db.connect(tmp_path / "t.db")
    settings.bind_registry(reg)
    try:
        Prefs(con, str(tmp_path / "t.db")).set_command_shortcut("Ctrl+K")
        # routed read follows the registry…
        assert settings.get(con, "command_shortcut", None) == "Ctrl+K"
        # …while a direct DB read proves nothing leaked into the file
        assert db.get_setting(con, "command_shortcut", None) is None
        # a fresh Prefs over the same (still-routed) DB sees the value
        fresh = Prefs(con, str(tmp_path / "t.db"))
        assert fresh.commandShortcut == "Ctrl+K"
        assert fresh.formattedShortcut == "Ctrl + K"
    finally:
        settings.bind_registry(None)
    con.close()
    reg.close()


# ── search slots (independent of grid filters) ──────────────────────
def _seed_assets(con, tmp_path):
    con.execute(
        "INSERT INTO source(kind, path, label) VALUES('folder', ?, 'x')",
        (str(tmp_path),))
    sid = con.execute("SELECT id FROM source").fetchone()[0]
    rows = [("icon", "audio-volume-high.svg"),
            ("icon", "audio-input-microphone.svg"),
            ("icon", "alarm-symbolic.svg")]
    paths = []
    for kind, name in rows:
        p = str(tmp_path / name)
        paths.append(p)
        con.execute(
            "INSERT INTO asset(source_id, kind, path, name, family)"
            " VALUES(?, ?, ?, ?, '')", (sid, kind, p, name))
    con.commit()
    return paths


def test_library_palette_search_and_index(tmp_path):
    from fengrid.bridges.library import Library
    from fengrid.core import db

    _qapp()          # Library's ctor hooks QCoreApplication.aboutToQuit
    con = db.connect(tmp_path / "t.db")
    paths = _seed_assets(con, tmp_path)
    lib = Library(con, str(tmp_path / "t.db"), no_scan=True)

    assert lib.palette_search("", 10) == []
    assert lib.palette_search("   ", 10) == []
    hits = lib.palette_search("audio", 10)
    assert [h["name"] for h in hits] == [
        "audio-volume-high.svg", "audio-input-microphone.svg"], \
        "prefix matches rank first, then shorter names"
    assert hits[0]["kind"] == "icon" and "family" in hits[0]
    assert lib.palette_search("zzz_none", 10) == []

    # index_of_path reads the CURRENT model: pre-seeded rows are there
    assert lib.index_of_path(paths[0]) >= 0
    assert lib.index_of_path("/nope/missing.svg") == -1


def test_code_palette_search_snippets(tmp_path):
    from fengrid.bridges.code import Code
    from fengrid.core import db

    con = db.connect(tmp_path / "t.db")
    con.execute(
        "INSERT INTO snippet(title, description, language, html)"
        " VALUES('Fengrid Flexbox', 'centering things', 'web',"
        " '<div class=grid>hello</div>')")
    con.commit()
    code = Code(con)

    assert code.palette_search("", 5) == []
    hits = code.palette_search("flexbox", 5)
    assert len(hits) == 1 and hits[0]["title"] == "Fengrid Flexbox"
    # body match (Dash/Alfred-style content search)
    assert len(code.palette_search("hello", 5)) == 1
    assert code.palette_search("zzz_none", 5) == []


# ── QML components ──────────────────────────────────────────────────
@pytest.fixture()
def bar_ui(tmp_path):
    _qapp()
    from fengrid.bridges.code import Code
    from fengrid.bridges.library import Library
    from fengrid.bridges.prefs import Prefs
    from fengrid.bridges.theme import Theme
    from fengrid.core import db

    con = db.connect(tmp_path / "t.db")
    db_path = str(tmp_path / "t.db")
    _seed_assets(con, tmp_path)
    con.execute(
        "INSERT INTO snippet(title, language, html)"
        " VALUES('Audio hint snippet', 'web', '<b>x</b>')")
    con.commit()

    theme = Theme(con, db_path)
    library = Library(con, db_path, no_scan=True)
    code = Code(con)
    prefs = Prefs(con, db_path)

    engine = QQmlEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("code", code)
    ctx.setContextProperty("prefs", prefs)
    ctx.setContextProperty("dbs", None)

    win = QQuickWindow()
    comp = QQmlComponent(engine, f"file://{QML_DIR}/components/ShortcutCapture.qml")
    cap = comp.create(ctx)          # no anchors — free-standing ok
    comp2 = QQmlComponent(engine, f"file://{QML_DIR}/components/CommandPalette.qml")
    pal = comp2.create(ctx)
    assert cap is not None, [str(e.toString()) for e in comp.errors()]
    assert pal is not None, [str(e.toString()) for e in comp2.errors()]

    yield {"cap": cap, "pal": pal, "prefs": prefs, "win": win}
    cap.deleteLater()
    pal.deleteLater()
    win.close()
    engine.collectGarbage()


def _wait(ms):
    QTest.qWait(ms)


def test_shortcut_capture_component(bar_ui):
    cap, prefs = bar_ui["cap"], bar_ui["prefs"]
    # displays the current binding out of the box
    assert cap.property("seqRaw") == "Alt+`"
    assert cap.property("display") == "Alt + `"
    # live-follow: an external change (Reset button) re-syncs us
    prefs.set_command_shortcut("Ctrl+K")
    _wait(50)
    assert cap.property("seqRaw") == "Ctrl+K"
    # not armed until clicked
    assert cap.property("capturing") is False


def test_command_palette_groups_and_queries(bar_ui):
    pal = bar_ui["pal"]
    # empty query → the full command list (commands always present)
    QMetaObject.invokeMethod(pal, "rebuild")
    _wait(30)
    n_cmds = pal.property("resultCount")
    assert n_cmds >= 20, f"expected all commands, got {n_cmds}"

    # asset query: 2 audio assets + the fixture's "Audio hint snippet"
    # (commands don't match) = the three groups collapsing to 3 rows
    pal.setProperty("query", "audio")
    _wait(250)                      # 120 ms debounce + model rebuild
    assert pal.property("resultCount") == 3, \
        f"expected 2 audio assets + 1 audio snippet, got {pal.property('resultCount')}"

    # snippet query via the independent Code slot
    pal.setProperty("query", "flexbox-ish")
    pal.setProperty("query", "snippet")
    _wait(250)
    assert pal.property("resultCount") >= 1

    # open/close is a plain property (Main + Shortcut bind it)
    pal.setProperty("open", True)
    assert pal.property("open") is True
    pal.setProperty("open", False)
    assert pal.property("open") is False


def test_command_palette_activation_signals(bar_ui):
    pal = bar_ui["pal"]
    got = []
    pal.activated.connect(lambda kind, payload: got.append(
        (kind, json.loads(payload))))

    # current row = first command of the empty-query list
    QMetaObject.invokeMethod(pal, "rebuild")
    _wait(30)
    QMetaObject.invokeMethod(pal, "activateCurrent")
    _wait(30)
    assert got, "activation must emit"
    kind, payload = got[-1]
    assert kind == "command" and "id" in payload
    assert pal.property("open") is False, "activation closes the palette"

    # no matches → fallback with the raw query (grid quick-search flow)
    pal.setProperty("query", "zzz_no_such_row")
    _wait(250)
    assert pal.property("resultCount") == 0
    QMetaObject.invokeMethod(pal, "activateCurrent")
    _wait(30)
    kind, payload = got[-1]
    assert kind == "fallback" and payload["query"] == "zzz_no_such_row"
