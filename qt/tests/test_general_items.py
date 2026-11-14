"""Preview-text buckets + general-items regression tests (multi-select
slots, fonts collection/smart filtering)."""

import json
import os
import sys

import pytest
from PySide6.QtCore import Qt                    # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from fengrid.core import db as core_db            # noqa: E402
from fengrid.core import preview_text as pt       # noqa: E402
from fengrid.core import presets as core_presets   # noqa: E402


@pytest.fixture(scope="module")
def con():
    from PySide6.QtGui import QGuiApplication
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QGuiApplication.instance() is None:
        QGuiApplication([])
    c = core_db.connect(":memory:")
    core_presets.ensure_presets(c)
    yield c
    c.close()


# ------------------------------------------------------------- buckets
def test_buckets_have_three_breakpoints():
    bps = pt._data().get("breakpoints", [])
    assert len(bps) == 3
    assert pt.bucket_for(10) == "small"
    assert pt.bucket_for(30) == "medium"
    assert pt.bucket_for(60) == "large"


def test_groups_populated_and_fit_tagged():
    d = pt._data()
    assert d["groups"]["haiku"] and d["groups"]["poems"]
    assert d["groups"]["speeches"]
    fits = {"large", "medium", "small"}
    for group in d["groups"].values():
        for entry in group:
            assert entry.get("fit") in fits
            assert entry["text"].strip()


def test_pick_returns_bucket_text():
    for bucket in ("large", "medium", "small"):
        text = pt.pick(bucket)
        assert isinstance(text, str) and text
    # curated 'fit' subsets must come from the matching bucket lists
    for bucket in ("large", "medium", "small"):
        texts = {c["text"] for c in pt.candidates(bucket)}
        assert pt.pick(bucket) in texts


def test_reshuffle_one_per_bucket():
    s = pt.reshuffle()
    assert set(s) == {"large", "medium", "small"}
    assert all(v for v in s.values())


# ------------------------------------------------- fonts collections
def test_fonts_collection_and_smart_filter(con):
    from fengrid.bridges.fonts import Fonts
    src = con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder', '/tmp/f', 't', 1)").lastrowid
    aid = con.execute(
        "INSERT INTO asset(source_id, kind, name, path, family, ext)"
        " VALUES (?, 'font', 'Tuffy Bold', '/tmp/f/t.ttf', 'Tuffy',"
        " 'ttf')", (src,)).lastrowid
    aid2 = con.execute(
        "INSERT INTO asset(source_id, kind, name, path, family, ext)"
        " VALUES (?, 'font', 'Demo Regular', '/tmp/f/d.ttf', 'Demo',"
        " 'ttf')", (src,)).lastrowid
    cid = con.execute("INSERT INTO collection(name)"
                      " VALUES ('Keep')").lastrowid
    con.execute("INSERT INTO collection_ref(collection_id, item_kind,"
                " item_id) VALUES (?, 'font', ?)", (cid, aid))
    con.commit()
    fonts = Fonts(con, "/tmp")
    fonts._refresh()
    names = [f["name"] for f in fonts._families]
    assert "Tuffy" in names and "Demo" in names

    fonts.set_collection(str(cid))
    names_f = [f["name"] for f in fonts._families]
    assert names_f == ["Tuffy"]           # Demo filtered out
    assert fonts.collectionFilter == str(cid)
    fonts.set_collection(str(cid))        # toggle clears
    assert fonts.collectionFilter == ""

    # smart: match by name fragment
    sid = con.execute(
        "INSERT INTO smart_collection(name, item_kind, criteria)"
        " VALUES ('tuffy only', 'font', ?)",
        (json.dumps({"q": "tuffy"}),)).lastrowid
    con.commit()
    fonts.set_smart(str(sid))
    names_s = [f["name"] for f in fonts._families]
    assert names_s == ["Tuffy"]
    assert fonts.smartFilter == str(sid)


# ------------------------------------------------- fonts starred row (#40)
def test_fonts_starred_filter(con):
    """The rail Starred row on the fonts pane: a reactive starred count,
    a starred-families filter on the model, and star_family updating a
    live starredOnly view."""
    from fengrid.bridges.fonts import Fonts
    src = con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder', '/tmp/starred-f', 't', 1)").lastrowid
    con.execute(
        "INSERT INTO asset(source_id, kind, name, path, family, ext)"
        " VALUES (?, 'font', 'Tuffy Bold', '/tmp/starred-f/t.ttf',"
        " 'Tuffy', 'ttf')", (src,))
    con.execute(
        "INSERT INTO asset(source_id, kind, name, path, family, ext)"
        " VALUES (?, 'font', 'Demo Regular', '/tmp/starred-f/d.ttf',"
        " 'Demo', 'ttf')", (src,))
    con.commit()
    fonts = Fonts(con, "/tmp")
    fonts._refresh()
    assert fonts.starredOnly is False
    assert fonts.starredCount == 0

    # starring a family feeds the count and the starredOnly view live
    fonts.set_starred_only(True)
    assert [f["name"] for f in fonts._families] == []   # nothing starred yet
    fonts.star_family("Tuffy", True)
    assert fonts.starredCount == 1
    assert [f["name"] for f in fonts._families] == ["Tuffy"]

    # the grid model follows the same filter
    role = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 1)   # "family"
    rows = [fonts._model.data(fonts._model.index(i), role)
            for i in range(fonts._model.rowCount())]
    assert rows == ["Tuffy"]

    # collection pick drops the starred filter (mirrors colors)
    fonts.set_collection("0")
    assert fonts.starredOnly is False
    names = [f["name"] for f in fonts._families]
    assert names == ["Demo", "Tuffy"]

    # unstarring empties the starred view again
    fonts.set_starred_only(True)
    fonts.star_family("Tuffy", False)
    assert fonts.starredCount == 0
    assert [f["name"] for f in fonts._families] == []


# ------------------------------------------------- library bulk slots
def test_row_id_and_star_by_id(con):
    from fengrid.bridges.library import Library
    src = con.execute(
        "INSERT INTO source(kind, path, label, enabled)"
        " VALUES ('folder', '/tmp/i', 't', 1)").lastrowid
    aid = con.execute(
        "INSERT INTO asset(source_id, kind, name, path)"
        " VALUES (?, 'icon', 'bulk-icon', '/tmp/i/b.svg')",
        (src,)).lastrowid
    con.commit()
    lib = Library(con, "/tmp")
    lib._apply_filters()
    assert lib.row_id(0) == aid
    lib.set_starred_item(aid, True)
    assert core_db.is_starred(con, aid, kind="icon")
    lib.set_starred_item(aid, False)
    assert not core_db.is_starred(con, aid, kind="icon")
