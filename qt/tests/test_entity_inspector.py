"""Entity inspector: Documentation / License / Sources for Projects and
saved Libraries, cross-type tag relations, per-kind library/tag counts."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from fengrid.bridges.taxonomy import Taxonomy           # noqa: E402
from fengrid.bridges.library import Library             # noqa: E402
from fengrid.bridges.colors import Colors, _tags_match  # noqa: E402
from fengrid.core import db as core_db                  # noqa: E402
from fengrid.core import licenses as core_licenses      # noqa: E402
from fengrid.core import taxonomy as core_tax           # noqa: E402
from fengrid.core.projects_git import Repo              # noqa: E402


@pytest.fixture()
def env(tmp_path):
    from PySide6.QtCore import QCoreApplication
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    con = core_db.connect(str(tmp_path / "t.db"))
    tax = Taxonomy(con, str(tmp_path))
    yield tax, con, tmp_path
    con.close()


MIT = ("MIT License\n\nCopyright (c) 2026 Native IT (S. Davis)\n\n"
       "Permission is hereby granted, free of charge, to any person "
       "obtaining a copy of this software and associated documentation "
       "files (the \"Software\"), to deal in the Software without "
       "restriction, including without limitation the rights to use, "
       "copy, modify, merge, publish, distribute, sublicense, and/or "
       "sell copies of the Software, and to permit persons to whom the "
       "Software is furnished to do so, subject to the following "
       "conditions:\n\nThe above copyright notice and this permission "
       "notice shall be included in all copies or substantial portions "
       "of the Software.\n\nTHE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT "
       "WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.\n")


def _mksource(con, path):
    return con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder', ?, 't', 1)", (path,)).lastrowid


def _mkasset(con, kind, name, path):
    sid = _mksource(con, path)
    return con.execute(
        "INSERT INTO asset(source_id, kind, name, path) VALUES (?, ?, ?, ?)",
        (sid, kind, name, path)).lastrowid


def _mkproject(con, name):
    cur = con.execute(
        "INSERT INTO projects (name, settings, created) VALUES (?, ?, '')",
        (name, json.dumps({})))
    con.commit()
    return cur.lastrowid


# ------------------------------------------------------------------ license
def test_recognize_mit():
    out = core_licenses.recognize(MIT)
    assert out is not None
    assert out["spdx"] == "MIT"
    assert "permissions" in out and "limitations" in out


def test_recognize_unknown_is_none():
    assert core_licenses.recognize("my own weird legal text v1") is None


# --------------------------------------------------------- entity meta
def test_entity_meta_readme_license(env):
    tax, con, tmp = env
    pid = _mkproject(con, "Docs Demo")
    repo_dir = Path(tax._repo_dir("project", "Docs Demo"))
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "README.md").write_text(
        "# Docs Demo\n\nA sample project.\n", encoding="utf-8")
    (repo_dir / "LICENSE.md").write_text(MIT, encoding="utf-8")

    meta = tax.item_properties("project", pid)["meta"]
    assert meta["readme"]["exists"] is True
    assert "A sample project." in meta["readme"]["text"]
    assert meta["license"]["exists"] is True
    assert meta["license"]["standard"]["spdx"] == "MIT"


def test_entity_meta_missing_files(env):
    tax, con, tmp = env
    pid = _mkproject(con, "Empty Entity")
    meta = tax.item_properties("project", pid)["meta"]
    assert meta["readme"]["exists"] is False
    assert meta["license"]["standard"] is None
    # missing entity (bad id) must not throw
    meta2 = tax.item_properties("project", 9999)["meta"]
    assert meta2["readme"]["exists"] is False


# ------------------------------------------------- meta shape (#58)
# The Properties panel evaluates EVERY page's bindings (docs, license,
# font, palette, snippet) against whatever payload is current — including
# during the itemKind change window before reload() swaps payloads, and
# at startup against the last-saved palette's row. A meta key a payload
# lacks reads as `undefined`, which the engine logs as 'Unable to assign
# [undefined] to bool/QString' and a missing list's `.length` throws
# TypeError — the #58 startup flood.

_META_SHAPE_KEYS = {
    "readme": dict, "license": dict, "family": str, "name": str,
    "path": str, "title": str, "colors": list,
}


def _assert_meta_shape(meta):
    for key, typ in _META_SHAPE_KEYS.items():
        assert key in meta, f"meta missing {key!r}"
        assert isinstance(meta[key], typ), (
            f"meta[{key!r}] is {type(meta[key]).__name__},"
            f" not {typ.__name__}")
    assert isinstance(meta["readme"]["exists"], bool)
    assert isinstance(meta["readme"]["path"], str)
    assert isinstance(meta["readme"]["text"], str)
    assert isinstance(meta["license"]["exists"], bool)
    assert isinstance(meta["license"]["path"], str)


def test_meta_shape_every_kind(env):
    tax, con, tmp = env
    icon_id = _mkasset(con, "icon", "a.svg", "/tmp/58a")
    font_id = _mkasset(con, "font", "A.ttf", "/tmp/58A.ttf")
    con.execute("UPDATE asset SET family = 'A' WHERE id = ?", (font_id,))
    con.commit()
    pal = con.execute("INSERT INTO palette(name) VALUES ('P')").lastrowid
    snip = con.execute("INSERT INTO snippet(title) VALUES ('S')").lastrowid
    proj = _mkproject(con, "Shape Proj")
    cases = [("icon", icon_id), ("font", font_id), ("palette", pal),
             ("snippet", snip), ("project", proj), ("library", proj),
             ("preset", 9999), ("preset_entry", 9999),
             ("icon", 9999), ("font", 9999), ("palette", 9999),
             ("snippet", 9999), ("bogus", 1)]
    for kind, iid in cases:
        _assert_meta_shape(tax.item_properties(kind, iid)["meta"])


# ------------------------------------------------------------ git summary
def test_git_summary_roundtrip(env):
    tax, con, tmp = env
    pid = _mkproject(con, "Git Entity")
    # not initialized yet
    out = tax.git_summary("project", pid)
    assert out["exists"] is False

    tax.git_init("project", pid)
    repo = Repo(tax._repo_dir("project", "Git Entity"))
    (Path(repo.path) / "notes.txt").write_text("hello", encoding="utf-8")
    sha = repo.commit_all("first snapshot")
    assert sha

    out = tax.git_summary("project", pid)
    assert out["exists"] is True
    assert out["clean"] is True
    assert out["branch"]
    assert out["last_commit"]["subject"] == "first snapshot"

    # uncommitted change flips clean
    (Path(repo.path) / "more.txt").write_text("x", encoding="utf-8")
    out = tax.git_summary("project", pid)
    assert out["clean"] is False


# ---------------------------------------------------- related by tags
def test_related_by_tags_cross_kind(env):
    tax, con, tmp = env
    # one icon asset + one palette, sharing the tag "brand"
    aid = _mkasset(con, "icon", "logo-icon", "/x/logo.svg")
    core_db.add_tag(con, aid, "brand", kind="icon")
    pal = con.execute(
        "INSERT INTO palette (name, tags) VALUES ('Brand Set',"
        " 'brand, warm')").lastrowid
    core_db.add_tag(con, pal, "brand", kind="palette")
    con.commit()

    rel = core_tax.related_by_tags(con, "icon", aid)
    hits = [r for r in rel if r["kind"] == "palette"]
    assert hits and hits[0]["name"] == "Brand Set"
    assert "brand" in hits[0]["shared"]

    # and in the other direction (palette → icon)
    rev = core_tax.related_by_tags(con, "palette", pal)
    assert any(r["kind"] == "icon" and r["id"] == aid for r in rev)

    # bridge slot returns the same payload
    assert tax.related_by_tags("icon", aid) == rel


def test_related_no_tags_empty(env):
    tax, con, tmp = env
    aid = _mkasset(con, "icon", "plain", "/x/p.svg")
    con.commit()
    assert core_tax.related_by_tags(con, "icon", aid) == []


# ------------------------------------------------ per-kind tag counts
def test_tag_counts_per_kind(env):
    tax, con, tmp = env
    lib = Library(con, str(tmp))
    aid = _mkasset(con, "icon", "a1", "/x/a.svg")
    fid = _mkasset(con, "font", "f1", "/x/f.ttf")
    core_db.add_tag(con, aid, "brand", kind="icon")
    core_db.add_tag(con, fid, "brand", kind="font")
    core_db.add_tag(con, aid, "icon-only", kind="icon")
    con.commit()
    lib._refresh_lists()
    rows = {r["name"]: r for r in lib.tags}
    assert rows["brand"]["n"] == 1            # icon count unchanged
    assert rows["brand"]["counts"]["icon"] == 1
    assert rows["brand"]["counts"]["font"] == 1
    assert rows["icon-only"]["counts"].get("font", 0) == 0


# ------------------------------------------------- library tag filters
def test_set_library_tags_filters_panels(env):
    tax, con, tmp = env
    colors = Colors(con)
    p1 = con.execute(
        "INSERT INTO palette (name, tags) VALUES ('Warm',"
        " 'warm, sunset')").lastrowid
    con.execute(
        "INSERT INTO palette (name, tags) VALUES ('Cool',"
        " 'cool, sea')").lastrowid
    con.commit()
    colors._refresh_palettes()
    assert len(colors.palettes) == 2

    colors.set_library_tags("warm", False)
    assert [p["name"] for p in colors.palettes] == ["Warm"]
    assert colors.libraryTagFilter == "warm"

    # second identical call clears
    colors.set_library_tags("warm", False)
    assert colors.libraryTagFilter == ""
    assert len(colors.palettes) == 2

    # match_all requires every tag
    colors.set_library_tags("warm,sunset", True)
    assert [p["name"] for p in colors.palettes] == ["Warm"]


def test_tags_match_helper():
    assert _tags_match("a, b", ["a"], True) is True
    assert _tags_match("a", ["a", "b"], True) is False
    assert _tags_match("a", ["a", "b"], False) is True
    assert _tags_match(None, ["a"], False) is False


# -------------------------------------------- library view kind counts
def test_library_view_kind_counts(env):
    tax, con, tmp = env
    aid = _mkasset(con, "icon", "ic", "/x/ic.svg")
    fid = _mkasset(con, "font", "ft", "/x/ft.ttf")
    core_db.add_tag(con, aid, "web", kind="icon")
    core_db.add_tag(con, fid, "web", kind="font")
    vid = core_tax.create_library_view(con, "Web Bits", "web", True)
    con.commit()
    counts = core_tax.library_view_kind_counts(con, vid)
    assert counts == {"icon": 1, "font": 1}
    # bridge view rows carry the same counts (refresh picks up the view)
    tax._refresh()
    rows = {v["name"]: v for v in tax.libraryViews}
    assert rows["Web Bits"]["counts"] == {"icon": 1, "font": 1}
