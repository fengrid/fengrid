"""App registry + multi-database behaviour.

One SQLite file = one Fengrid database; the registry knows recent /
starred / active entries and owns the GLOBAL user prefs, so switching
databases doesn't repaint the app. Switching itself re-execs the
process — `FENGRID_NO_RELAUNCH=1` suppresses the exec so tests can
observe the registry flip instead of dying.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fengrid.bridges.databases import Databases, _ago   # noqa: E402
from fengrid.core import db, registry, settings          # noqa: E402


def _two_dbs(tmp_path):
    p1 = tmp_path / "library.db"
    p2 = tmp_path / "work.db"
    db.connect(p1).close()
    db.connect(p2).close()
    return p1, p2


def test_registry_crud(tmp_path):
    reg = registry.open_registry(tmp_path)
    p1, p2 = _two_dbs(tmp_path)

    registry.upsert(reg, p1, default_path=p1, touch=True)
    registry.upsert(reg, p2, touch=True)
    registry.star(reg, p2, True)

    rows = registry.list_dbs(reg)
    # p1 is the default path → its label is the friendly "fengrid"
    assert {r["label"] for r in rows} == {"fengrid", "work"}
    assert {r["label"]: r["starred"] for r in rows}["work"] == 1

    registry.set_active(reg, p2)
    assert Path(registry.active_path(reg)) == p2

    registry.clear_recent(reg, keep_path=p2)
    assert [r["label"] for r in registry.list_dbs(reg)] == ["work"]
    reg.close()


def test_global_keys_route_to_registry(tmp_path):
    """GLOBAL prefs land in the registry; per-DB keys stay on the DB —
    and unbound (pre-multi-db) behaviour is exactly the old one."""
    reg = registry.open_registry(tmp_path)
    con = db.connect(tmp_path / "t.db")
    from fengrid.core.db import get_setting, get_setting as gs

    settings.bind_registry(reg)
    try:
        settings.set(con, "theme", "light")            # global
        settings.set(con, "last_scan", "12:34:00")     # per-DB
        settings.set_bool(con, "update_check", False)  # global
        settings.set(con, "command_shortcut", "Ctrl+K")  # global

        assert get_setting(reg, "theme", None) == "light"
        assert get_setting(con, "theme", None) is None, \
            "global key leaked into the database"
        assert get_setting(con, "last_scan", None) == "12:34:00"
        assert get_setting(reg, "last_scan", None) is None
        assert settings.get_bool(con, "update_check", True) is False
        assert get_setting(reg, "command_shortcut", None) == "Ctrl+K"
        assert get_setting(con, "command_shortcut", None) is None, \
            "command bar hotkey must survive a database switch"
        # reads follow the same routing
        assert settings.get(con, "theme", "dark") == "light"
    finally:
        settings.bind_registry(None)

    # unbound: single-DB mode, the pre-multi-db behaviour
    settings.set(con, "theme", "dark")
    assert get_setting(con, "theme", None) == "dark"
    con.close()
    reg.close()


def test_seed_globals_first_wins(tmp_path):
    """Existing databases migrate their prefs into the registry once;
    afterwards the registry wins (prefs survive switches)."""
    reg = registry.open_registry(tmp_path)
    con = db.connect(tmp_path / "t.db")
    from fengrid.core.db import get_setting, set_setting

    set_setting(con, "editor_keymap", "vim")
    registry.seed_globals(con, reg)
    assert get_setting(reg, "editor_keymap", None) == "vim"

    # registry already has it — a DIFFERENT db value must not win
    set_setting(con, "editor_keymap", "emacs")
    registry.seed_globals(con, reg)
    assert get_setting(reg, "editor_keymap", None) == "vim"

    # per-DB keys never migrate
    set_setting(con, "first_run_done", "True")
    registry.seed_globals(con, reg)
    assert get_setting(reg, "first_run_done", None) is None
    con.close()
    reg.close()


def test_is_fengrid_db(tmp_path):
    good = tmp_path / "good.db"
    db.connect(good).close()
    assert registry.is_fengrid_db(good) is True

    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert registry.is_fengrid_db(empty) is False

    other = tmp_path / "other.db"
    import sqlite3
    c = sqlite3.connect(other)
    c.execute("CREATE TABLE notes(x)")
    c.commit()
    c.close()
    assert registry.is_fengrid_db(other) is False
    assert registry.is_fengrid_db(tmp_path / "missing.db") is False


def test_databases_bridge_flows(tmp_path, monkeypatch):
    monkeypatch.setenv("FENGRID_NO_RELAUNCH", "1")
    reg = registry.open_registry(tmp_path)
    p1, p2 = _two_dbs(tmp_path)
    default = tmp_path / "library.db"
    d = Databases(str(p1), reg, str(tmp_path), default_path=str(default))

    assert d.currentLabel == "fengrid"       # default db gets the nice name
    assert d.recent == [] and d.quick == []
    messages = []
    d.message.connect(messages.append)

    # star + quick access
    d.starCurrent()
    assert d.currentStarred is True
    registry.upsert(reg, p2, touch=True)
    registry.star(reg, p2, True)
    assert [r["label"] for r in d.quick] == ["work"]
    assert [r["label"] for r in d.recent] == ["work"]

    # switching flips the active entry (relaunch suppressed)
    d.switchTo(str(p2))
    assert Path(registry.active_path(reg)) == p2
    assert any("relaunch suppressed" in m for m in messages)

    # rejects non-databases
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database at all")
    before = registry.active_path(reg)
    d.openDatabase(str(junk))
    assert Path(registry.active_path(reg)) == Path(before)
    assert any("Not a Fengrid database" in m for m in messages)

    # creating refuses to clobber, then creates + activates
    d.createDatabase(str(p2))
    assert any("Already exists" in m for m in messages)
    fresh = tmp_path / "fresh.db"
    d.createDatabase(str(fresh))
    assert fresh.is_file() and registry.is_fengrid_db(fresh)
    assert Path(registry.active_path(reg)) == fresh

    # clear recent keeps the current entry (session followed _activate)
    d.clearRecent()
    assert [r["label"] for r in registry.list_dbs(reg)] == ["fresh"]
    assert d.currentLabel == "fresh"
    reg.close()


def test_ago_labels():
    import time
    assert _ago(0) == "never opened"
    assert _ago(int(time.time()) - 30) == "just now"
    assert _ago(int(time.time()) - 7200) == "2 h ago"
    assert _ago(int(time.time()) - 3 * 86400) == "3 d ago"