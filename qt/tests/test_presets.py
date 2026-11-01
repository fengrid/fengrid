"""Preset libraries: curated remote catalogues (fonts / icon sets /
site templates), on-demand git clone, preview generation."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fengrid.bridges.presets import Presets           # noqa: E402
from fengrid.core import db as core_db                # noqa: E402
from fengrid.core import presets as core_presets      # noqa: E402
from fengrid.core import taxonomy as core_tax         # noqa: E402
from fengrid.core.projects_git import Repo            # noqa: E402


@pytest.fixture()
def env(tmp_path):
    # QGuiApplication (offscreen) — preview rendering paints text, which
    # needs the GUI stack even in tests
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        QGuiApplication([])
    con = core_db.connect(str(tmp_path / "t.db"))
    core_presets.ensure_presets(con)
    bridge = Presets(con, str(tmp_path))
    yield bridge, con, tmp_path
    con.close()


# ------------------------------------------------------------- registry
def test_ensure_presets_registers_four_libraries(env):
    bridge, con, tmp = env
    libs = bridge.libraries
    names = [l["name"] for l in libs]
    assert names == ["Open Fonts", "Open Icon Sets",
                     "Site Templates & Themes", "Color Harmonies"]
    kinds = {l["name"]: l["kind"] for l in libs}
    assert kinds["Open Fonts"] == "font"
    assert kinds["Open Icon Sets"] == "icon"
    assert kinds["Site Templates & Themes"] == "template"
    # everything remote by default, nothing downloaded
    for l in libs:
        assert l["remote"] is True
        assert l["downloaded"] == 0
        assert l["entries"] >= 10


def test_ensure_presets_idempotent(env):
    bridge, con, tmp = env
    before = con.execute("SELECT COUNT(*) FROM preset_entry").fetchone()[0]
    core_presets.ensure_presets(con)
    after = con.execute("SELECT COUNT(*) FROM preset_entry").fetchone()[0]
    assert before == after
    assert before >= 47          # 13 fonts + 13 icons + 13 templates + 12 colors


def test_entries_carry_urls_and_tags(env):
    bridge, con, tmp = env
    fonts = bridge.libraries[0]
    rows = bridge.entries(fonts["id"])
    fira = [r for r in rows if r["name"] == "Fira Code"][0]
    assert fira["url"].startswith("https://github.com/tonsky/FiraCode")
    assert "monospace" in fira["tags"]
    assert fira["license"] != ""
    assert fira["downloaded"] is False
    # every non-palette entry across every pack has a usable clone URL
    for lib in bridge.libraries:
        for r in bridge.entries(lib["id"]):
            if lib["kind"] == "palette":
                assert r["colors"] != ""
            else:
                assert r["url"].endswith(".git")
                assert r["repo"].count("/") == 1


# -------------------------------------------------- taxonomy integration
def test_preset_kinds_are_tracked_entities(env):
    bridge, con, tmp = env
    lib = bridge.libraries[0]
    row = con.execute("SELECT id FROM preset_entry WHERE library_id = ?"
                      " LIMIT 1", (lib["id"],)).fetchone()
    eid = row["id"]
    assert core_tax._item_exists(con, "preset", lib["id"])
    assert core_tax._item_exists(con, "preset_entry", eid)
    # entries are taggable → they join the cross-type taxonomy
    core_db.add_tag(con, eid, "minimal", kind="preset_entry")
    tags = core_db.tags_for(con, eid, "preset_entry")
    assert "minimal" in tags


def test_preset_entries_appear_in_related_by_tags(env):
    bridge, con, tmp = env
    # an icon asset sharing a tag with a preset entry
    src = con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder', '/tmp/x', 't', 1)").lastrowid
    aid = con.execute(
        "INSERT INTO asset(source_id, kind, name, path)"
        " VALUES (?, 'icon', 'FeatherIcon', '/tmp/x/feather.svg')",
        (src,)).lastrowid
    core_db.add_tag(con, aid, "minimal", kind="icon")
    lib = bridge.libraries[1]                    # Open Icon Sets
    feather = [r for r in bridge.entries(lib["id"])
               if r["name"] == "Feather Icons"][0]
    core_db.add_tag(con, feather["id"], "minimal", kind="preset_entry")
    rel = core_tax.related_by_tags(con, "icon", aid)
    hit = [r for r in rel if r["kind"] == "preset_entry"
           and r["name"] == "Feather Icons"]
    assert hit and "minimal" in hit[0]["shared"]


# --------------------------------------------------------- git cloning
def _mk_source_repo(path: Path) -> Path:
    """A tiny local git repo standing in for a GitHub remote."""
    path.mkdir(parents=True, exist_ok=True)
    repo = Repo(path)
    repo.init()
    (path / "README.md").write_text(
        "# Tiny Theme\n\n![preview](social.png)\n", encoding="utf-8")
    # 1x1 png
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d4944415478da63fcffff3f030005fe02fea72d4b4c000000004945"
        "4e44ae426082")
    (path / "social.png").write_bytes(png)
    (path / "theme.css").write_text("body{color:red}", encoding="utf-8")
    repo.commit_all("init")
    return path


def test_repo_clone_local(env, tmp_path):
    bridge, con, tmp = env
    src = _mk_source_repo(tmp_path / "src-repo")
    dest = tmp_path / "cloned"
    repo = Repo.clone(str(src), dest)
    assert (dest / ".git").exists()
    assert (dest / "theme.css").is_file()
    assert repo.exists()


def test_download_clones_and_generates_preview(env, tmp_path, qtbot=None):
    bridge, con, tmp = env
    src = _mk_source_repo(tmp_path / "remote-theme")
    lib = bridge.libraries[2]                    # Site Templates & Themes
    rows = bridge.entries(lib["id"])
    rows[0]["id"]
    # point the first entry at the LOCAL repo (stands in for GitHub)
    con.execute("UPDATE preset_entry SET url = ? WHERE id = ?",
                (str(src), rows[0]["id"]))
    con.commit()

    done = []
    bridge.cloneDone.connect(
        lambda eid, ok, detail: done.append((eid, ok, detail)))
    bridge.download(rows[0]["id"])
    # the worker is a thread; the signal is queued to the main loop —
    # pump events while waiting (the test has no running event loop)
    import time
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + 30
    while not done and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.05)
    assert done and done[0][1] is True, done

    row = con.execute("SELECT * FROM preset_entry WHERE id = ?",
                      (rows[0]["id"],)).fetchone()
    assert row["downloaded"] == 1
    assert Path(row["local_path"]).is_dir()
    # preview derived from the repo's social image (README-referenced)
    assert row["preview_path"] != ""
    assert Path(row["preview_path"]).is_file()
    from PySide6.QtGui import QImage
    img = QImage(row["preview_path"])
    assert not img.isNull()
    assert img.width() == 1280 and img.height() == 640   # social size

    # forget → remote again, files gone
    local = Path(row["local_path"])
    bridge.forget(rows[0]["id"])
    row = con.execute("SELECT * FROM preset_entry WHERE id = ?",
                      (rows[0]["id"],)).fetchone()
    assert row["downloaded"] == 0
    assert not local.exists()


# ------------------------------------------------------------- previews
def test_preview_source_prefers_social_images(tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "README.md").write_text(
        "![shot](docs/screen.png)", encoding="utf-8")
    (clone / "docs").mkdir()
    (clone / "docs" / "screen.png").write_bytes(b"x")   # not a real png,
    # but existence is what the scanner checks
    src = core_presets.preview_source(clone)
    assert src is not None and src.name == "screen.png"

    # a named social image outranks README references
    (clone / "social.png").write_bytes(b"x")
    assert core_presets.preview_source(clone).name == "social.png"


def test_preview_source_empty_clone(tmp_path):
    clone = tmp_path / "empty"
    clone.mkdir()
    assert core_presets.preview_source(clone) is None


# ------------------------------------------------- fallback card render
def test_fallback_preview_rendered_when_no_imagery(env, tmp_path):
    bridge, con, tmp = env
    src_dir = tmp_path / "plain-repo"
    src_dir.mkdir(parents=True)
    repo = Repo(src_dir)
    repo.init()
    (src_dir / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    repo.commit_all("init")

    lib = bridge.libraries[2]
    row = bridge.entries(lib["id"])[0]
    con.execute("UPDATE preset_entry SET url = ? WHERE id = ?",
                (str(src_dir), row["id"]))
    con.commit()
    done = []
    bridge.cloneDone.connect(
        lambda eid, ok, detail: done.append((eid, ok, detail)))
    bridge.download(row["id"])
    import time
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + 30
    while not done and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.05)
    assert done and done[0][1] is True
    r = con.execute("SELECT preview_path FROM preset_entry WHERE id = ?",
                    (row["id"],)).fetchone()
    assert r["preview_path"] != ""
    from PySide6.QtGui import QImage
    img = QImage(r["preview_path"])
    assert img.width() == 1280 and img.height() == 640


# ------------------------------------------------- scan-source wiring (#37)
def _mk_icon_repo(path: Path) -> Path:
    """A tiny local git repo standing in for a downloaded icon pack."""
    path.mkdir(parents=True, exist_ok=True)
    repo = Repo(path)
    repo.init()
    (path / "icons").mkdir()
    (path / "icons" / "smile.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    repo.commit_all("init")
    return path


def _mark_downloaded(con, entry_id: int, local_path) -> None:
    con.execute("UPDATE preset_entry SET downloaded = 1, local_path = ?"
                " WHERE id = ?", (str(local_path), entry_id))
    con.commit()


def test_entry_scan_kind_mapping():
    assert core_presets.entry_scan_kind("icon") == "folder"
    assert core_presets.entry_scan_kind("font") == "fontroot"
    # template clones are deliberately never indexed (their imagery
    # would flood the asset grid)
    assert core_presets.entry_scan_kind("template") is None
    assert core_presets.entry_scan_kind("") is None


def test_sync_downloaded_sources_registers_icon_clone(env, tmp_path):
    bridge, con, tmp = env
    icon_lib = bridge.libraries[1]               # Open Icon Sets
    clone = tmp / "presets" / "open-icon-sets" / "feather"
    clone.mkdir(parents=True)
    (clone / "feather.svg").write_text("<svg/>", encoding="utf-8")
    eid = con.execute(
        "SELECT id FROM preset_entry WHERE library_id = ? LIMIT 1",
        (icon_lib["id"],)).fetchone()["id"]
    _mark_downloaded(con, eid, clone)

    new = core_presets.sync_downloaded_sources(con)
    assert len(new) == 1 and new[0]["kind"] == "folder"
    row = con.execute(
        "SELECT kind, enabled FROM source WHERE path = ?",
        (str(clone.resolve()),)).fetchone()
    assert row is not None and row["kind"] == "folder"
    assert row["enabled"] == 1

    # idempotent — nothing new the second time
    assert core_presets.sync_downloaded_sources(con) == []

    # a DISABLED source re-enables (re-download after a settings toggle)
    from fengrid.core import indexer
    sid = con.execute("SELECT id FROM source WHERE path = ?",
                      (str(clone.resolve()),)).fetchone()["id"]
    indexer.set_source_enabled(con, sid, False)
    new = core_presets.sync_downloaded_sources(con)
    assert len(new) == 1 and new[0]["kind"] == "folder"
    assert con.execute("SELECT enabled FROM source WHERE id = ?",
                       (sid,)).fetchone()["enabled"] == 1


def test_sync_skips_templates_and_missing_clones(env, tmp_path):
    bridge, con, tmp = env
    tpl_lib = bridge.libraries[2]                # Site Templates & Themes
    eid = con.execute(
        "SELECT id FROM preset_entry WHERE library_id = ? LIMIT 1",
        (tpl_lib["id"],)).fetchone()["id"]
    _mark_downloaded(con, eid, tmp / "nowhere")  # dir never existed
    assert core_presets.sync_downloaded_sources(con) == []
    assert con.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 0

    # a template clone that DOES exist stays unregistered
    tpl_clone = tmp / "template-clone"
    tpl_clone.mkdir()
    _mark_downloaded(con, eid, tpl_clone)
    assert core_presets.sync_downloaded_sources(con) == []
    assert con.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 0


def test_download_icon_entry_registers_scan_source(env, tmp_path):
    """Full clone flow: an ICON entry download must land a scan source
    and emit sourceAdded — this is the bug (#37)."""
    bridge, con, tmp = env
    icon_lib = bridge.libraries[1]
    src = _mk_icon_repo(tmp / "remote-icons")
    row = bridge.entries(icon_lib["id"])[0]
    con.execute("UPDATE preset_entry SET url = ? WHERE id = ?",
                (str(src), row["id"]))
    con.commit()

    done, added = [], []
    bridge.cloneDone.connect(
        lambda eid, ok, detail: done.append((eid, ok, detail)))
    bridge.sourceAdded.connect(
        lambda path, kind: added.append((path, kind)))
    bridge.download(row["id"])
    import time
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + 30
    while (not done or not added) and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.05)
    assert done and done[0][1] is True, done
    assert added and added[0][1] == "folder", added
    assert Path(added[0][0]).is_dir()
    srow = con.execute(
        "SELECT kind, enabled FROM source WHERE path = ?",
        (str(Path(added[0][0])),)).fetchone()
    assert srow is not None and srow["kind"] == "folder"


def test_forget_removes_scan_source(env, tmp_path):
    bridge, con, tmp = env
    icon_lib = bridge.libraries[1]
    clone = tmp / "presets" / "open-icon-sets" / "feather"
    clone.mkdir(parents=True)
    (clone / "feather.svg").write_text("<svg/>", encoding="utf-8")
    eid = con.execute(
        "SELECT id FROM preset_entry WHERE library_id = ? LIMIT 1",
        (icon_lib["id"],)).fetchone()["id"]
    _mark_downloaded(con, eid, clone)
    assert core_presets.sync_downloaded_sources(con)
    assert con.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 1

    bridge.forget(eid)
    assert con.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 0
    assert not clone.exists()


# -------------------------------------------------- color-harmony presets (#135)
def test_color_harmony_presets_count(env):
    bridge, con, tmp = env
    libs = {l["name"]: l for l in bridge.libraries}
    assert "Color Harmonies" in libs
    ch = libs["Color Harmonies"]
    assert ch["kind"] == "palette"
    rows = bridge.entries(ch["id"])
    assert len(rows) == 12
    for r in rows:
        assert r["colors"] != ""
        import json
        hexes = json.loads(r["colors"])
        assert len(hexes) == 5
        for hx in hexes:
            assert hx.startswith("#")
            assert len(hx) == 7


def test_apply_preset_emits_hexes(env):
    bridge, con, tmp = env
    libs = {l["name"]: l for l in bridge.libraries}
    ch = libs["Color Harmonies"]
    rows = bridge.entries(ch["id"])
    row = rows[0]  # first color harmony preset
    received = []
    bridge.presetApplied.connect(lambda eid, hexes: received.append((eid, hexes)))
    bridge.apply_preset(row["id"])
    assert len(received) == 1
    assert received[0][0] == row["id"]
    assert len(received[0][1]) == 5


# -------------------------------------------------- default library (#136)
def test_default_library_created_for_palette(env):
    bridge, con, tmp = env
    core_presets.sync_default_library(con)
    row = con.execute(
        "SELECT id FROM collection WHERE name = 'Default' AND kind = 'palette'"
    ).fetchone()
    assert row is not None


def test_default_library_contains_color_harmonies(env):
    bridge, con, tmp = env
    core_presets.sync_default_library(con)
    default_id = con.execute(
        "SELECT id FROM collection WHERE name = 'Default' AND kind = 'palette'"
    ).fetchone()["id"]
    members = con.execute(
        "SELECT COUNT(*) AS n FROM collection_ref WHERE collection_id = ?",
        (default_id,)).fetchone()["n"]
    assert members == 12  # one per color harmony preset


def test_sync_default_library_idempotent(env):
    bridge, con, tmp = env
    core_presets.sync_default_library(con)
    core_presets.sync_default_library(con)
    default_id = con.execute(
        "SELECT id FROM collection WHERE name = 'Default' AND kind = 'palette'"
    ).fetchone()["id"]
    members = con.execute(
        "SELECT COUNT(*) AS n FROM collection_ref WHERE collection_id = ?",
        (default_id,)).fetchone()["n"]
    assert members == 12
