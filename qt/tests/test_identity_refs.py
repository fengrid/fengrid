"""GUID + slug identity, new asset kinds, and [[ asset ]] reference links.

Covers the multi-kind asset batch: every tracked object carries a
generated GUID (backfilled for pre-existing rows), slugs are globally
unique, the kinds registry classifies media/data files, and [[ slug ]] /
[[ GUID ]] / [[ type/…/name ]] references resolve through core.assetrefs.
"""

import json
import os
import sqlite3

import pytest

from fengrid.core import assetrefs
from fengrid.core import db as core_db
from fengrid.core import kinds as core_kinds


@pytest.fixture()
def lib(tmp_path):
    con = core_db.connect(tmp_path / "lib.db")
    con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder', ?, 'test', 1)", (str(tmp_path),))
    src = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    ids = {}
    now = 1000.0
    for name, kind, path in (
            ("photo", "image", "/tmp/f/photo.png"),
            ("clip", "video", "/tmp/f/clip.mp4"),
            ("note", "markdown", "/tmp/f/note.md"),
            ("sensor", "data", "/tmp/f/sensor.json"),
            ("grid", "spatial", "/tmp/f/grid.geojson"),
            ("temp", "timeseries", "/tmp/f/temp.h5"),
            ("cut", "audio", "/tmp/f/cut.mp3"),
            ("paper", "doc", "/tmp/f/paper.pdf")):
        con.execute(
            "INSERT INTO asset(source_id, kind, path, name, mtime, guid)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (src, kind, path, name, now, core_db.new_guid()))
        ids[name] = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.commit()
    yield {"con": con, "ids": ids, "tmp": tmp_path}
    con.close()


# ───────────────────────────────────────────────────── kinds registry
def test_kind_mapping():
    assert core_kinds.kind_for_ext("png") == "icon"
    assert core_kinds.kind_for_ext("mp4") == "video"
    assert core_kinds.kind_for_ext("geojson") == "spatial"
    assert core_kinds.kind_for_ext("h5") == "timeseries"
    assert core_kinds.kind_for_ext("md") == "markdown"
    assert core_kinds.kind_for_ext("json") == "data"
    assert core_kinds.kind_for_ext("ttf") == "font"
    assert core_kinds.kind_for_ext("xyz") is None


# ──────────────────────────────────────────────────── guid + slug
def test_every_asset_gets_guid(lib):
    con = lib["con"]
    n = con.execute(
        "SELECT COUNT(*) FROM asset WHERE guid IS NULL OR guid = ''"
    ).fetchone()[0]
    assert n == 0
    guids = {r["guid"] for r in con.execute("SELECT guid FROM asset")}
    assert len(guids) == 8          # all unique


def test_guid_backfilled_on_migrate(tmp_path):
    """A pre-existing database (no guid columns) gains columns + guids."""
    old = tmp_path / "old.db"
    con = sqlite3.connect(str(old))
    # the M1-era asset table: full metadata, no guid/slug columns yet
    con.execute("""CREATE TABLE asset (
        id INTEGER PRIMARY KEY,
        source_id INTEGER, kind TEXT, path TEXT UNIQUE, name TEXT,
        theme TEXT, context TEXT, ext TEXT, size_px INTEGER,
        width INTEGER, height INTEGER, bytes INTEGER, colorspace TEXT,
        color_count INTEGER, mono INTEGER, mtime REAL)""")
    con.execute("CREATE TABLE source (id INTEGER PRIMARY KEY, kind TEXT,"
                " path TEXT UNIQUE, label TEXT, enabled INTEGER)")
    con.execute("INSERT INTO asset (source_id, kind, path, name)"
                " VALUES (1, 'icon', '/tmp/legacy.png', 'legacy')")
    con.commit()
    con.close()
    con = core_db.connect(str(old))
    row = con.execute("SELECT guid FROM asset WHERE name = 'legacy'"
                      ).fetchone()
    assert row["guid"], "legacy row must gain a guid"


def test_slug_set_and_uniqueness(lib):
    con = lib["con"]
    photo = lib["ids"]["photo"]
    stored = core_db.set_slug(con, "image", photo, "Hero Photo")
    assert stored == "hero-photo"
    # taken by another asset — rejected across tables
    with pytest.raises(ValueError):
        core_db.set_slug(con, "data", lib["ids"]["sensor"], "hero-photo")
    # same row re-setting its own slug is fine
    assert core_db.set_slug(con, "image", photo, "hero-photo") == "hero-photo"
    # invalid characters rejected
    with pytest.raises(ValueError):
        core_db.set_slug(con, "image", photo, "bad slug!!")
    # clearing works
    assert core_db.set_slug(con, "image", photo, "") == ""


def test_slug_lookup(lib):
    con = lib["con"]
    core_db.set_slug(con, "image", lib["ids"]["photo"], "hero")
    hit = core_db.lookup_by_slug(con, "hero")
    assert hit["kind"] == "image" and hit["id"] == lib["ids"]["photo"]
    assert core_db.lookup_by_slug(con, "nope") is None
    g = con.execute("SELECT guid FROM asset WHERE id = ?",
                    (lib["ids"]["photo"],)).fetchone()[0]
    hit = core_db.lookup_by_guid(con, g)
    assert hit["kind"] == "image" and hit["slug"] == "hero"
    assert core_db.lookup_by_guid(con, "00000000-0000-0000-0000-"
                                  "000000000000") is None


def test_collection_library_project_guids(lib):
    con = lib["con"]
    con.execute("INSERT INTO collection(name, guid) VALUES ('c', ?)",
                (core_db.new_guid(),))
    con.execute("INSERT INTO palette(name, guid) VALUES ('p', ?)",
                (core_db.new_guid(),))
    con.execute("INSERT INTO snippet(title, guid) VALUES ('s', ?)",
                (core_db.new_guid(),))
    con.execute("INSERT INTO projects(name, guid) VALUES ('pr', ?)",
                (core_db.new_guid(),))
    for table in ("collection", "palette", "snippet", "projects"):
        n = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE guid IS NULL"
            " OR guid = ''").fetchone()[0]
        assert n == 0, table


# ─────────────────────────────────────── [[ asset ]] reference links
def test_ref_by_slug(lib):
    con = lib["con"]
    core_db.set_slug(con, "image", lib["ids"]["photo"], "hero")
    hit = assetrefs.resolve(con, "hero")
    assert hit["kind"] == "image" and hit["path"].endswith("photo.png")
    url = assetrefs.url_for(hit)
    assert url.startswith("fengrid-asset://") and "photo.png" in url


def test_ref_by_guid(lib):
    con = lib["con"]
    g = con.execute("SELECT guid FROM asset WHERE name = 'clip'"
                    ).fetchone()[0]
    hit = assetrefs.resolve(con, g)
    assert hit["kind"] == "video" and hit["id"] == lib["ids"]["clip"]


def test_ref_by_path(lib):
    con = lib["con"]
    # type/namespace/asset-name form (namespace = the folder root label)
    hit = assetrefs.resolve(con, "image/f/photo")
    assert hit is not None and hit["kind"] == "image"
    assert hit["name"] == "photo"
    # markdown alias resolves too
    hit = assetrefs.resolve(con, "markdown/f/note")
    assert hit["kind"] == "markdown"
    # code alias → snippet table
    con.execute("INSERT INTO snippet(title, guid) VALUES ('Demo', ?)",
                (core_db.new_guid(),))
    hit = assetrefs.resolve(con, "code/demo")
    assert hit["kind"] == "snippet"


def test_expand_leaves_unresolved_visible(lib):
    con = lib["con"]
    core_db.set_slug(con, "image", lib["ids"]["photo"], "hero")
    text = 'before [[ hero ]] middle [[ ghost ]] after'
    out, unresolved = assetrefs.expand(con, text)
    assert "fengrid-asset://" in out and "[[ ghost ]]" in out
    assert unresolved == ["ghost"]


# ───────────────────────────── structured-data content CRUD
def test_data_payload_crud(lib):
    con = lib["con"]
    did = lib["ids"]["sensor"]
    doc = core_db.put_asset_data(con, did, {"temp": 20.0})
    assert doc["revision"] == 1
    doc = core_db.patch_asset_data(con, did, {"unit": "C"})
    assert doc["payload"] == {"temp": 20.0, "unit": "C"}
    assert doc["revision"] == 2
    assert core_db.delete_asset_data(con, did) is True
    assert core_db.get_asset_data(con, did) is None


def test_timeseries_append(lib):
    con = lib["con"]
    tid = lib["ids"]["temp"]
    core_db.append_asset_points(con, tid, [{"t": 1, "v": 1.0}])
    doc = core_db.append_asset_points(con, tid, [{"t": 2, "v": 2.0}])
    assert doc["payload"]["points"] == [{"t": 1, "v": 1.0},
                                        {"t": 2, "v": 2.0}]
    with pytest.raises(ValueError):
        core_db.append_asset_points(con, tid, "not-a-list")
