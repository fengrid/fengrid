"""Prefs bridge + first-run source-toggle semantics.

Covers the settings keys the Settings/first-run surfaces own (icon
size, startup pane, update check, first-run flag) and the upsert path
set_path_enabled() — the first-run screen toggles system roots BEFORE
any scan has registered them, so the row may not exist yet.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fengrid.bridges.prefs import Prefs          # noqa: E402
from fengrid.core import db, indexer, settings    # noqa: E402


def _prefs(tmp_path):
    con = db.connect(tmp_path / "t.db")
    return con, Prefs(con, str(tmp_path / "t.db"))


def test_prefs_defaults_on_fresh_db(tmp_path):
    con, p = _prefs(tmp_path)
    assert p.firstRunNeeded is True      # flag unset -> setup owed
    assert p.updateCheck is True         # ships enabled
    assert p.iconSize == 32
    assert p.startupPane == 0
    # detected paths are absolute (resolved) so they string-match the
    # source rows the scanner registers
    for path in list(p.systemIconPaths) + list(p.systemFontDirs):
        assert os.path.isabs(path)
    con.close()


def test_prefs_persist_and_clamp(tmp_path):
    con, p = _prefs(tmp_path)

    p.set_icon_size(999)
    assert p.iconSize == 256
    p.set_icon_size(8)
    assert p.iconSize == 16
    p.set_icon_size(64)
    assert p.iconSize == 64
    assert str(settings.get(con, "icon_size")) in ("64", "64.0")

    p.set_startup_pane(3)
    assert p.startupPane == 3
    p.set_startup_pane(99)               # clamped to pane range
    assert p.startupPane == 4

    p.set_update_check(False)
    assert p.updateCheck is False
    assert settings.get_bool(con, "update_check") is False
    p.set_update_check(True)
    assert settings.get_bool(con, "update_check") is True

    # web previews (#32): tri-state pref, invalid values ignored
    assert p.webPreviews == "auto"       # default
    p.set_web_previews("bogus")
    assert p.webPreviews == "auto"
    p.set_web_previews("on")
    assert p.webPreviews == "on"
    assert settings.get(con, "web_previews") == "on"
    p.set_web_previews("off")
    assert p.webPreviews == "off"
    p.set_web_previews("auto")
    assert p.webPreviews == "auto"
    con.close()


def test_first_run_flag_flips_and_emits(tmp_path):
    con, p = _prefs(tmp_path)
    seen = []
    p.firstRunNeededChanged.connect(
        lambda: seen.append(p.firstRunNeeded))

    p.complete_first_run()
    assert p.firstRunNeeded is False
    assert settings.get_bool(con, "first_run_done") is True

    p.start_first_run()                  # "Run setup again…" from Settings
    assert p.firstRunNeeded is True
    assert settings.get_bool(con, "first_run_done") is False

    # reopen: a fresh Prefs on the same db sees the reset flag
    p2 = Prefs(con, str(tmp_path / "t.db"))
    assert p2.firstRunNeeded is True
    assert seen == [False, True]
    con.close()


def test_set_path_enabled_upserts_before_first_scan(tmp_path):
    """First-run toggles a detected root. Since #61 every detected path
    is pre-registered DISABLED, so both toggles are live: unchecking
    persists a disabled row (ensure_sources skips it), and CHECKING a
    never-seen path REGISTERS it enabled (checkbox scans exactly the
    selected path)."""
    con = db.connect(tmp_path / "t.db")

    missing = tmp_path / "not-registered"
    indexer.set_path_enabled(con, str(missing), "system", False)
    row = con.execute("SELECT enabled, kind FROM source WHERE path = ?",
                      (str(missing.resolve()),)).fetchone()
    assert row is not None, "disabled flag must persist as a row"
    assert row["enabled"] == 0 and row["kind"] == "system"

    # a later scan must not resurrect it as enabled
    enabled = indexer.ensure_sources(con, [Path(str(missing))],
                                     kinds=("system", "folder"))
    assert all(p != str(missing.resolve()) for _, p in enabled), \
        "disabled path leaked into the scan list"

    fresh = tmp_path / "fresh-root"
    fresh.mkdir()
    indexer.set_path_enabled(con, str(fresh), "system", True)
    row = con.execute("SELECT enabled FROM source WHERE path = ?",
                      (str(fresh.resolve()),)).fetchone()
    assert row is not None and row["enabled"] == 1, \
        "checking an unregistered path must register it enabled (#61)"
    enabled = indexer.ensure_sources(con, [Path(str(fresh))],
                                     kinds=("system", "folder"))
    assert str(fresh.resolve()) in [p for _, p in enabled]


def test_register_detected_paths_preregisters_disabled(tmp_path):
    """#61 first-run contract: every detected path is pre-registered
    DISABLED (checkboxes start unchecked), existing rows are untouched,
    and a rescan NEVER resurrects the unselected ones."""
    con = db.connect(tmp_path / "t.db")
    picked = tmp_path / "picked"; picked.mkdir()
    indexer.register_detected_paths(con, [
        (tmp_path / "icons1", "system"),
        (tmp_path / "icons2", "system"),
        (picked, "system"),
    ])
    rows = {r["path"]: r["enabled"] for r in con.execute(
        "SELECT path, enabled FROM source")}
    assert rows[str((tmp_path / "icons1").resolve())] == 0
    assert rows[str((tmp_path / "icons2").resolve())] == 0
    assert rows[str(picked.resolve())] == 0          # pre-registered off

    # the user checks one path -> enabled; a later scan must scan ONLY it
    indexer.set_path_enabled(con, str(picked), "system", True)
    enabled = indexer.ensure_sources(
        con, [tmp_path / "icons1", tmp_path / "icons2", picked],
        kinds=("system", "folder"))
    assert [p for _, p in enabled] == [str(picked.resolve())], \
        "unselected paths leaked into the scan set"

    # registration is idempotent: existing rows keep their flags
    indexer.register_detected_paths(con, [(picked, "system")])
    assert con.execute("SELECT COUNT(*) c FROM source").fetchone()["c"] == 3
    con.close()