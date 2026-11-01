"""#141: the Font and Color panes get the Icon pane's libraries and
collections treatment.

- Fonts pane: a rail Libraries row filters families through their font
  assets' tags (set_library_tags / libraryTagFilter — the missing
  mirror of colors/code).
- Colors pane: applying a palette preset files it as a palette tagged
  'preset' (save_as_preset), counted by presetPaletteCount for the
  rail's Saved Presets row.
- Library counts: palettes and snippets are not asset rows, so
  library_view_kind_counts matches their own tags column.
- Pack libraries tag assets through item_tag (the store every filter
  reads) — the earlier asset_tag write was invisible to the rail.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fengrid.bridges.colors import Colors                 # noqa: E402
from fengrid.bridges.fonts import Fonts                   # noqa: E402
from fengrid.core import colors as core_colors            # noqa: E402
from fengrid.core import db as core_db                    # noqa: E402
from fengrid.core import presets as core_presets          # noqa: E402
from fengrid.core import taxonomy as core_tax             # noqa: E402


@pytest.fixture()
def env(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        QGuiApplication([])
    con = core_db.connect(str(tmp_path / "t.db"))
    yield con, tmp_path
    con.close()


def _seed_source(con, tmp_path, name="src"):
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return con.execute(
        "INSERT INTO source(kind, path, label) VALUES ('folder', ?, ?)",
        (str(path), name)).lastrowid


def _font_asset(con, src_id, family, tags, i=0):
    aid = con.execute(
        "INSERT INTO asset(source_id, kind, path, name, family, ext)"
        " VALUES (?, 'font', ?, ?, ?, 'ttf')",
        (src_id, f"/fonts/{family}-{i}.ttf", family, family)).lastrowid
    for t in tags:
        core_db.add_tag(con, aid, t, kind="font")
    return aid


# ------------------------------------------------------------ fonts pane
def test_fonts_library_tags_filter_families(env, tmp_path):
    con, tmp = env
    src = _seed_source(con, tmp)
    _font_asset(con, src, "Alpha", ["mono", "rounded"])
    _font_asset(con, src, "Beta", ["mono"])
    _font_asset(con, src, "Gamma", ["serif"])
    con.commit()
    bridge = Fonts(con, str(tmp / "t.db"))

    names = [f["name"] for f in bridge._families]
    assert set(names) == {"Alpha", "Beta", "Gamma"}

    # match_all: only Alpha owns an asset carrying BOTH tags
    bridge.set_library_tags("mono,rounded", True)
    assert [f["name"] for f in bridge._families] == ["Alpha"]
    assert bridge.libraryTagFilter == "mono,rounded"

    # any-match: every family owning a 'mono' asset
    bridge.set_library_tags("mono", False)
    assert set(f["name"] for f in bridge._families) == {"Alpha", "Beta"}

    # a second call with the same list clears the filter (toggle)
    bridge.set_library_tags("mono", False)
    assert bridge.libraryTagFilter == ""
    assert set(f["name"] for f in bridge._families) == {
        "Alpha", "Beta", "Gamma"}


def test_fonts_library_filter_composes_with_collection_filter(env, tmp_path):
    con, tmp = env
    src = _seed_source(con, tmp)
    _font_asset(con, src, "Alpha", ["mono"])
    _font_asset(con, src, "Beta", ["mono"])
    _font_asset(con, src, "Gamma", ["serif"])
    con.commit()
    bridge = Fonts(con, str(tmp / "t.db"))

    coll = con.execute(
        "INSERT INTO collection(name, kind) VALUES ('Work', 'font')"
    ).lastrowid
    beta = con.execute(
        "SELECT id FROM asset WHERE family = 'Beta'").fetchone()["id"]
    con.execute("INSERT INTO collection_ref(collection_id, item_kind,"
                " item_id) VALUES (?, 'font', ?)", (coll, beta))
    con.commit()

    bridge.set_library_tags("mono", False)
    bridge.set_collection(str(coll))
    assert [f["name"] for f in bridge._families] == ["Beta"]


# ----------------------------------------------------------- colors pane
def test_apply_preset_files_a_tagged_palette(env):
    con, tmp = env
    bridge = Colors(con)
    bridge.load_hexes(["#ff0000", "#00ff00", "#0000ff"])
    bridge.save_as_preset("Harmony 01")

    row = con.execute(
        "SELECT id FROM palette WHERE name = 'Harmony 01'").fetchone()
    assert row is not None
    tags = [r[0] for r in con.execute(
        "SELECT t.name FROM item_tag it JOIN tag t ON t.id = it.tag_id"
        " WHERE it.item_id = ? AND it.item_kind = 'palette'",
        (row["id"],))]
    assert tags == ["preset"]
    assert bridge.presetPaletteCount == 1
    hexes = [c["hex"] for c in core_colors.palette_colors(con, row["id"])]
    assert hexes == ["#ff0000", "#00ff00", "#0000ff"]


def test_reapplying_a_preset_updates_instead_of_duplicating(env):
    con, tmp = env
    bridge = Colors(con)
    bridge.load_hexes(["#ff0000", "#00ff00", "#0000ff"])
    bridge.save_as_preset("Harmony 01")
    pid = con.execute(
        "SELECT id FROM palette WHERE name = 'Harmony 01'").fetchone()["id"]

    bridge.load_hexes(["#123456", "#654321"])
    bridge.save_as_preset("Harmony 01")
    assert con.execute(
        "SELECT COUNT(*) FROM palette WHERE name = 'Harmony 01'"
    ).fetchone()[0] == 1
    assert bridge.presetPaletteCount == 1
    hexes = [c["hex"] for c in core_colors.palette_colors(con, pid)]
    assert hexes == ["#123456", "#654321"]


def test_other_palettes_do_not_count_as_presets(env):
    con, tmp = env
    bridge = Colors(con)
    core_colors.save_palette(con, "Manual", ["#111111"], tags="warm")
    assert bridge.presetPaletteCount == 0


# --------------------------------------------------- library view counts
def test_kind_counts_include_palettes_and_snippets(env, tmp_path):
    con, tmp = env
    src = _seed_source(con, tmp)
    for i, tags in enumerate((["warm"], ["cool"])):
        aid = con.execute(
            "INSERT INTO asset(source_id, kind, path, name)"
            " VALUES (?, 'icon', ?, ?)",
            (src, f"/icons/w{i}.svg", f"w{i}")).lastrowid
        for t in tags:
            core_db.add_tag(con, aid, t, kind="icon")
    core_colors.save_palette(con, "P1", ["#111111"], tags="warm,evening")
    core_colors.save_palette(con, "P2", ["#222222"], tags="cozy")
    core_colors.save_palette(con, "P3", ["#333333"], tags="warm,cozy")
    con.execute("INSERT INTO snippet(title, tags) VALUES ('S1', 'warm')")
    con.commit()

    # any-match view
    vid = core_tax.create_library_view(con, "Warm", "warm,cozy", False)
    counts = core_tax.library_view_kind_counts(con, vid)
    assert counts["icon"] == 1
    assert counts["palette"] == 3
    assert counts["snippet"] == 1

    # match-all view: only the palette carrying BOTH tags
    vid2 = core_tax.create_library_view(con, "WarmCozy", "warm,cozy", True)
    counts2 = core_tax.library_view_kind_counts(con, vid2)
    assert counts2["palette"] == 1
    assert "snippet" not in counts2
    assert "icon" not in counts2


# -------------------------------------------- pack libraries tag assets
def test_pack_library_tags_reach_the_read_path(env, tmp_path):
    """The end-to-end guard for the item_tag fix: a downloaded pack's
    library must select its assets through taxonomy.library_view_assets
    (the read path the rail's library filtering uses)."""
    con, tmp = env
    core_presets.ensure_presets(con)
    src = _seed_source(con, tmp, "packx")
    for i in range(2):
        con.execute(
            "INSERT INTO asset(source_id, kind, path, name)"
            " VALUES (?, 'icon', ?, ?)",
            (src, f"/packx/i{i}.svg", f"i{i}"))
    lib_id = con.execute(
        "INSERT INTO preset_library(name, kind, remote)"
        " VALUES ('Pack X', 'icon', 1)").lastrowid
    con.execute(
        "INSERT INTO preset_entry(library_id, name, repo, downloaded,"
        " local_path) VALUES (?, 'Pack X', 'x/packx', 1, ?)",
        (lib_id, str(tmp / "packx")))
    con.commit()

    core_presets.sync_pack_libraries(con)
    view = con.execute(
        "SELECT id FROM library_view WHERE name = 'Pack X'").fetchone()
    assert view is not None
    ids = core_tax.library_view_assets(con, view["id"])
    assert len(ids) == 2, "pack assets not reachable through item_tag"
    counts = core_tax.library_view_kind_counts(con, view["id"])
    assert counts.get("icon") == 2
