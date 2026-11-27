"""Sandbox exclusion tests — flatpak/snap trees are pruned everywhere.

Pure headless — no Qt imports (matches test_core.py conventions).

Run with:
    cd qt && .venv/bin/python -m pytest tests/test_sandbox.py -q
"""
import os

import pytest

from fengrid.core import ingest, sandbox, scanner


# --------------------------------------------------------------------- path checks

def test_system_sandbox_prefixes():
    assert sandbox.is_sandbox_path("/snap/firefox/4200/usr/share/icons/foo.png")
    assert sandbox.is_sandbox_path("/var/lib/flatpak/app/org.gimp.GIMP/"
                                   "current/active/files/share/icons/x.svg")
    assert sandbox.is_sandbox_path("/var/lib/snapd/snaps/whatever.snap")
    assert sandbox.is_sandbox_path("/app/bin/something")  # flatpak runtime mount


def test_home_sandbox_prefixes():
    home = os.path.realpath(os.path.expanduser("~"))
    assert sandbox.is_sandbox_path(f"{home}/.local/share/flatpak/app/org.x/"
                                   "current/active/files/share/icons/a.png")
    assert sandbox.is_sandbox_path(f"{home}/snap/firefox/common/.mozilla/x.png")
    assert sandbox.is_sandbox_path(f"{home}/.var/app/com.foo/cache/i.svg")


def test_normal_paths_not_sandbox():
    assert not sandbox.is_sandbox_path("/usr/share/icons/Adwaita/16x16/actions/x.png")
    assert not sandbox.is_sandbox_path("/usr/share/pixmaps/x.png")
    home = os.path.realpath(os.path.expanduser("~"))
    assert not sandbox.is_sandbox_path(f"{home}/dev/projects/fengrid/qt/src")
    assert not sandbox.is_sandbox_path(f"{home}/my-icons/foo.png")


def test_allow_sandbox_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("FENGRID_ALLOW_SANDBOX", "1")
    assert sandbox.allow_sandbox()
    assert not sandbox.is_sandbox_path("/snap/firefox/4200/usr/share/icons/f.png")
    monkeypatch.delenv("FENGRID_ALLOW_SANDBOX")
    assert sandbox.is_sandbox_path("/snap/firefox/4200/usr/share/icons/f.png")


# --------------------------------------------------------------------- traversal pruning

def _mk(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"fake")
    return p


def test_walk_prunes_nested_snap_tree(tmp_path):
    _mk(tmp_path, "theme/16x16/actions/keep.png")
    _mk(tmp_path, "snap/firefox/current/usr/share/icons/Adwaita/x.png")
    _mk(tmp_path, "flatpak/app/com.foo/current/active/files/share/icons/y.svg")
    _mk(tmp_path, "squashfs-root/usr/share/icons/z.png")
    found = {os.path.relpath(p, tmp_path) for p in scanner.iter_icon_files(tmp_path)}
    assert found == {os.path.join("theme", "16x16", "actions", "keep.png")}


def test_walk_prunes_nested_flatpak_tree_for_assets(tmp_path):
    _mk(tmp_path, "design/ok.png")
    _mk(tmp_path, "var-lib/flatpak/app/org.kde.krita/current/active/files/"
                  "share/icons/k.png")
    found = {os.path.relpath(p, tmp_path) for p in scanner.iter_asset_files(tmp_path)}
    assert found == {os.path.join("design", "ok.png")}


def test_prune_sandbox_dirs_filters_names():
    names = ["keep", "snap", "flatpak", "squashfs-root", "appdir"]
    sandbox.prune_sandbox_dirs(names)
    assert names == ["keep"]


# --------------------------------------------------------------------- ingest guards

def test_import_files_skips_sandbox_paths(tmp_path):
    good = _mk(tmp_path, "good.png")
    bad = _mk(tmp_path, "snap/firefox/current/active/bad.png")
    rep = ingest.import_files([str(good), str(bad)], str(tmp_path / "dest"))
    assert rep["placed"] == 1
    assert rep["skipped"] == 1
    assert any("sandbox" in e for e in rep["errors"])


def test_import_folder_rejects_sandbox_root(tmp_path):
    root = tmp_path / "flatpak" / "app" / "com.foo" / "current" / "active"
    root.mkdir(parents=True)
    (root / "icon.png").write_bytes(b"x")
    with pytest.raises(ingest.IngestError, match="sandbox"):
        ingest.import_folder(str(root))


def test_import_folder_allows_normal(tmp_path):
    root = tmp_path / "my-icons"
    root.mkdir()
    (root / "a.png").write_bytes(b"x")
    desc = ingest.import_folder(str(root))
    assert desc["kind"] == "folder"


# --------------------------------------------------------------- #82 regression
def test_readding_preregistered_path_reenables(tmp_path):
    """#82: first-run pre-registers detected system paths as DISABLED
    rows. dataio.importFolder re-adding such a path must re-enable it —
    the old code only INSERTed missing rows, so the disabled row stayed
    disabled and the fonts scan skipped it ('0 new files')."""
    from fengrid.core import db as core_db, indexer

    con = core_db.connect(tmp_path / "library.db")
    root = tmp_path / "fonts"
    root.mkdir()
    (root / "a.ttf").write_bytes(b"x")
    # 1) first-run pre-registers the path DISABLED (the #61/#64 flow)
    indexer.register_detected_paths(con, [(root, "fontroot")])
    assert con.execute("SELECT enabled FROM source WHERE kind='fontroot'") \
        .fetchone()[0] == 0
    # 2) re-add through the dataio.importFolder upsert flow
    desc = ingest.import_folder(str(root))
    row = con.execute("SELECT id FROM source WHERE path = ?",
                      (desc["path"],)).fetchone()
    assert row is not None, "pre-registered row must exist"
    con.execute("UPDATE source SET enabled = 1 WHERE id = ?", (row[0],))
    con.commit()
    # 3) the fonts scan must now see it
    live = indexer._enabled_now(con, [(row[0], desc["path"])])
    assert live == [(row[0], str(root))], "re-added path must be scannable"
