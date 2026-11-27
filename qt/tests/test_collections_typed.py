"""Typed collections (#141): collections are asset-TYPE specific, the
sidebar list is pane-scoped, and downloaded packs file their assets
into per-type default collections.

Covers:
- the schema migration (kind column + UNIQUE(name, kind) rebuild +
  single-kind backfill from existing membership)
- single-type enforcement in add_collection_ref (typed rejects a
  mismatched kind; untyped locks to its first ref)
- sub-collection kind inheritance from a typed parent
- sync_download_collections: 'Downloaded' (per type) + a collection
  named after the pack, membership from the clone's indexed assets,
  idempotent on repeat
- collection_tree carries kind for the pane-scoped rail
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from fengrid.core import db as core_db          # noqa: E402
from fengrid.core import presets as core_presets  # noqa: E402


@pytest.fixture()
def lib(tmp_path):
    return core_db.connect(str(tmp_path / "library.db"))


def _revert_collection_to_old_schema(con):
    """Simulate a pre-#141 DB: UNIQUE(name), no kind/parent_id/tags."""
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("""
        CREATE TABLE collection_old (
            id   INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            query TEXT,
            guid TEXT,
            slug TEXT
        )""")
    con.execute(
        "INSERT INTO collection_old(id, name, query, guid, slug)"
        " SELECT id, name, query, guid, slug FROM collection")
    con.execute("DROP TABLE collection")
    con.execute("ALTER TABLE collection_old RENAME TO collection")
    con.commit()


def _ref(con, coll_id, kind, item_id):
    con.execute(
        "INSERT OR IGNORE INTO collection_ref(collection_id, item_kind,"
        " item_id) VALUES (?, ?, ?)", (coll_id, kind, item_id))


def _kind_of(con, name):
    return con.execute(
        "SELECT kind FROM collection WHERE name = ?", (name,)
    ).fetchone()["kind"]


def test_migration_backfills_single_kind_collections(lib):
    con = lib
    con.execute("INSERT INTO source(id, kind, path, label)"
                " VALUES (1, 'folder', '/tmp/a', 'A')")
    for i, n in enumerate(("Alpha", "Mixed", "Empty"), 1):
        con.execute("INSERT INTO asset(id, source_id, kind, path, name)"
                    " VALUES (?, 1, 'icon', ?, ?)", (i, f"/tmp/a/{n}", n))
    ids = {}
    for n in ("Alpha", "Mixed", "Empty"):
        ids[n] = core_db.create_sub_collection(con, n)
    _ref(con, ids["Alpha"], "icon", 1)
    _ref(con, ids["Mixed"], "icon", 1)
    # add a palette member to 'Mixed' — legacy collections may hold
    # several kinds before the rule existed
    con.execute("INSERT INTO palette(id, name) VALUES (1, 'P')")
    _ref(con, ids["Mixed"], "palette", 1)
    con.commit()

    # rebuild the table into the OLD shape, then run the migration the
    # way connect() would on a pre-#141 database
    _revert_collection_to_old_schema(con)
    core_db._migrate_collections(con)
    core_db._migrate_collection_kinds(con)

    assert _kind_of(con, "Alpha") == "icon"
    assert _kind_of(con, "Mixed") is None      # legacy mixed stays untyped
    assert _kind_of(con, "Empty") is None
    # per-kind name uniqueness: two same-name collections, different types
    core_db.create_sub_collection(con, "Alpha", kind="palette")
    assert _kind_of(con, "Alpha") == "icon"    # original untouched


def test_add_collection_ref_enforces_single_type(lib):
    con = lib
    con.execute("INSERT INTO source(id, kind, path, label)"
                " VALUES (1, 'folder', '/tmp/a', 'A')")
    con.execute("INSERT INTO asset(id, source_id, kind, path, name)"
                " VALUES (1, 1, 'icon', '/tmp/a/i', 'i')")
    con.execute("INSERT INTO asset(id, source_id, kind, path, name)"
                " VALUES (2, 1, 'font', '/tmp/a/f.woff', 'f')")
    con.execute("INSERT INTO palette(id, name) VALUES (1, 'P')")
    cid = core_db.create_sub_collection(con, "Icons", kind="icon")
    assert core_db.add_collection_ref(con, cid, "icon", 1) is True
    # a different kind is rejected — collections hold ONE type
    assert core_db.add_collection_ref(con, cid, "font", 2) is False
    assert core_db.add_collection_ref(con, cid, "palette", 1) is False
    kinds = [r["item_kind"] for r in con.execute(
        "SELECT item_kind FROM collection_ref WHERE collection_id = ?",
        (cid,))]
    assert kinds == ["icon"]

    # untyped collection locks to its FIRST ref's kind
    loose = core_db.create_sub_collection(con, "Loose")
    assert core_db.add_collection_ref(con, loose, "font", 2) is True
    assert _kind_of(con, "Loose") == "font"
    assert core_db.add_collection_ref(con, loose, "icon", 1) is False


def test_sub_collection_inherits_parent_kind(lib):
    con = lib
    parent = core_db.create_sub_collection(con, "Fonts", kind="font")
    child = core_db.create_sub_collection(con, "Display", parent_id=parent)
    assert _kind_of(con, "Display") == "font"


def _seed_downloaded_pack(con, tmp_path, pack_kind="icon"):
    """A downloaded icon pack whose clone is registered and scanned."""
    clone = tmp_path / "Flat-Icons"
    clone.mkdir(exist_ok=True)
    lib_id = con.execute(
        "INSERT INTO preset_library(name, kind) VALUES ('Icon Packs', ?)",
        (pack_kind,)).lastrowid
    eid = con.execute(
        "INSERT INTO preset_entry(library_id, name, url, downloaded,"
        " local_path) VALUES (?, 'Flat Icons', 'https://x', 1, ?)",
        (lib_id, str(clone))).lastrowid
    src = con.execute(
        "INSERT INTO source(kind, path, label)"
        " VALUES ('folder', ?, 'Flat Icons')",
        (str(clone.resolve()),)).lastrowid
    con.execute("INSERT INTO asset(source_id, kind, path, name)"
                " VALUES (?, 'icon', '/x/a.svg', 'a')", (src,))
    con.execute("INSERT INTO asset(source_id, kind, path, name)"
                " VALUES (?, 'icon', '/x/b.svg', 'b')", (src,))
    con.commit()
    return eid, str(clone.resolve())


def test_sync_download_collections_files_downloaded_assets(lib, tmp_path):
    con = lib
    _seed_downloaded_pack(con, tmp_path)
    core_presets.sync_download_collections(con)

    dl = _kind_of(con, "Downloaded")
    assert dl == "icon"                       # one 'Downloaded' per TYPE
    pack = _kind_of(con, "Flat Icons")
    assert pack == "icon"                     # named after the pack
    for name in ("Downloaded", "Flat Icons"):
        cid = con.execute("SELECT id FROM collection WHERE name = ?"
                          " AND kind = 'icon'", (name,)).fetchone()["id"]
        n = con.execute("SELECT COUNT(*) AS n FROM collection_ref"
                        " WHERE collection_id = ?", (cid,)).fetchone()["n"]
        assert n == 2, f"{name}: expected the pack's 2 assets"
    # idempotent — a second pass adds nothing
    core_presets.sync_download_collections(con)
    cid = con.execute("SELECT id FROM collection WHERE name = 'Downloaded'"
                      " AND kind = 'icon'").fetchone()["id"]
    n = con.execute("SELECT COUNT(*) AS n FROM collection_ref"
                    " WHERE collection_id = ?", (cid,)).fetchone()["n"]
    assert n == 2


def test_sync_pack_libraries_creates_tagged_pack_library(lib, tmp_path):
    """#141 round 2: a downloaded pack becomes a discrete LIBRARY — a
    tag-driven library_view named after the pack, with the pack tag on
    its indexed assets, browseable from the global Libraries list."""
    con = lib
    _seed_downloaded_pack(con, tmp_path)      # 'Flat Icons', 2 icon assets
    core_presets.sync_pack_libraries(con)

    row = con.execute(
        "SELECT id, tags, match_all FROM library_view"
        " WHERE name = 'Flat Icons'").fetchone()
    assert row is not None
    assert row["tags"] == "Flat Icons" and row["match_all"] == 0

    # the pack's indexed assets carry the pack tag (kind-aware
    # item_tag — the store the library filters actually read)
    n = con.execute(
        "SELECT COUNT(*) AS n FROM item_tag it"
        " JOIN tag t ON t.id = it.tag_id"
        " JOIN asset a ON a.id = it.item_id AND it.item_kind = a.kind"
        " WHERE t.name = 'Flat Icons'").fetchone()["n"]
    assert n == 2

    # idempotent: a second pass adds no tags and no duplicate view
    core_presets.sync_pack_libraries(con)
    assert con.execute(
        "SELECT COUNT(*) AS n FROM library_view"
        " WHERE name = 'Flat Icons'").fetchone()["n"] == 1
    n2 = con.execute(
        "SELECT COUNT(*) AS n FROM item_tag it"
        " JOIN tag t ON t.id = it.tag_id"
        " WHERE t.name = 'Flat Icons'").fetchone()["n"]
    assert n2 == 2


def test_sync_pack_libraries_skips_templates(lib, tmp_path):
    """Template packs never index assets — an always-empty library would
    be noise, so they stay out of sync_pack_libraries (they remain in
    the Preset Libraries download browser)."""
    con = lib
    _seed_downloaded_pack(con, tmp_path, pack_kind="template")
    core_presets.sync_pack_libraries(con)
    assert con.execute(
        "SELECT COUNT(*) AS n FROM library_view"
        " WHERE name = 'Site Themes'").fetchone()["n"] == 0


def test_sync_download_collections_skips_templates(lib, tmp_path):
    con = lib
    _seed_downloaded_pack(con, tmp_path, pack_kind="template")
    core_presets.sync_download_collections(con)
    rows = con.execute(
        "SELECT name FROM collection WHERE name IN"
        " ('Downloaded', 'Site Themes')").fetchall()
    assert rows == []                         # template packs never index


def test_collection_tree_carries_kind(lib):
    con = lib
    core_db.create_sub_collection(con, "Icons", kind="icon")
    core_db.create_sub_collection(con, "Untyped")
    tree = {c["name"]: c for c in core_db.collection_tree(con)}
    assert tree["Icons"]["kind"] == "icon"
    assert tree["Untyped"]["kind"] is None
