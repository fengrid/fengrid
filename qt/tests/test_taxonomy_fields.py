"""#105 — custom fields: per-asset values, per-class definitions.

The reporter's contract: a field is DEFINED for an asset class, its
VALUE is specific to each individual asset. These tests pin the three
breaks that shipped: per-item isolation on write/read, class scoping
of definitions (NULL kind = every class), and the migration that adds
the kind column to pre-#105 databases.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fengrid.core import db as core_db
from fengrid.core import taxonomy as core_tax


@pytest.fixture()
def con(tmp_path):
    return core_db.connect(tmp_path / "lib.db")


def _icon(con, name):
    src = con.execute(
        "INSERT INTO source(kind, path, label) VALUES ('folder', ?, ?)",
        (f"/tmp/src-{name}", name)).lastrowid
    cur = con.execute(
        "INSERT INTO asset(name, path, kind, source_id)"
        " VALUES (?, ?, 'icon', ?)", (name, f"/tmp/{name}.svg", src))
    con.commit()
    return int(cur.lastrowid)


# ------------------------------------------------- per-asset isolation
def test_value_is_per_asset_not_per_class(con):
    """#105 headline: writing a value for one icon must NOT leak to
    another icon of the same class."""
    fid = core_tax.create_field(con, "Used", "bool")
    a, b = _icon(con, "a"), _icon(con, "b")
    core_tax.set_field_value(con, a, fid, "1", kind="icon")
    rows_a = {r["name"]: r["value"]
              for r in core_tax.asset_field_values(con, a, "icon")}
    rows_b = {r["name"]: r["value"]
              for r in core_tax.asset_field_values(con, b, "icon")}
    assert rows_a["Used"] == "1"
    assert rows_b["Used"] == ""          # untouched asset stays empty
    core_tax.set_field_value(con, b, fid, "0", kind="icon")
    rows_a = {r["name"]: r["value"]
              for r in core_tax.asset_field_values(con, a, "icon")}
    assert rows_a["Used"] == "1"         # b's write did not clobber a


# ------------------------------------------------- per-class definitions
def test_definition_scoped_to_class(con):
    """A field defined for snippets must not appear on icons, and a
    NULL-kind (all-classes) field appears everywhere."""
    snip_only = core_tax.create_field(con, "Run Snippet", "text",
                                      kind="snippet")
    every = core_tax.create_field(con, "Used", "bool")
    icon_names = [r["name"]
                  for r in core_tax.asset_field_values(con, 1, "icon")]
    assert "Run Snippet" not in icon_names
    assert "Used" in icon_names
    icon_fields = [r["name"] for r in core_tax.list_fields(con, "icon")]
    assert icon_fields == ["Used"]
    snippet_fields = [r["name"] for r in core_tax.list_fields(con,
                                                              "snippet")]
    assert set(snippet_fields) == {"Run Snippet", "Used"}
    assert snip_only > 0 and every > 0


def test_set_field_value_rejects_wrong_class(con):
    """Writing an icon value into a snippet-scoped field is a bug, not
    a silent cross-class write."""
    fid = core_tax.create_field(con, "Run Snippet", "text", kind="snippet")
    with pytest.raises(ValueError):
        core_tax.set_field_value(con, 1, fid, "x", kind="icon")


def test_unknown_kind_rejected(con):
    with pytest.raises(ValueError):
        core_tax.create_field(con, "Bad", "text", kind="palette2")


# ------------------------------------------------- multi-select bulk set
def test_bulk_set_defines_field_for_selection(con):
    """#105: multi-select + define a field → every selected asset gets
    the value; unknown ids are skipped, not fatal."""
    fid = core_tax.create_field(con, "Used", "bool")
    a, b = _icon(con, "a"), _icon(con, "b")
    n = core_tax.set_field_values_bulk(con, [a, b, 99999], fid, "1",
                                       kind="icon")
    assert n == 2
    for iid in (a, b):
        rows = {r["name"]: r["value"]
                for r in core_tax.asset_field_values(con, iid, "icon")}
        assert rows["Used"] == "1"


# ------------------------------------------------- migration of old DBs
def test_migration_adds_kind_column(tmp_path):
    """A pre-#105 database (asset_field without kind) must upgrade:
    the column exists, existing definitions read as NULL (= every
    class), and their values survive."""
    path = tmp_path / "old.db"
    # full current SCHEMA minus the #105 kind column = a faithful
    # pre-#105 database
    legacy_schema = "\n".join(
        line for line in core_db.SCHEMA.splitlines()
        if "kind    TEXT," not in line)
    con = sqlite3.connect(path)
    con.executescript(legacy_schema)
    con.execute("INSERT INTO source(kind, path, label)"
                " VALUES ('folder', '/tmp/legacy-src', 'legacy')")
    con.execute("INSERT INTO asset(name, path, kind, source_id)"
                " VALUES ('legacy-icon', '/tmp/legacy.svg', 'icon', 1)")
    con.execute("INSERT INTO asset_field(name, type, created)"
                " VALUES ('Legacy', 'text', 0)")
    # pre-#105 SCHEMA still carries the legacy value table; the
    # migration copies it into item_field_value on connect
    con.execute("INSERT INTO asset_field_value(asset_id, field_id, value)"
                " VALUES (1, 1, 'keepme')")
    con.commit()
    con.close()

    con = core_db.connect(path)
    cols = [r[1] for r in con.execute("PRAGMA table_info(asset_field)")]
    assert "kind" in cols
    row = con.execute(
        "SELECT name, kind FROM asset_field WHERE name = 'Legacy'"
    ).fetchone()
    assert row["kind"] is None
    vals = core_tax.asset_field_values(con, 1, "icon")
    assert {r["name"]: r["value"] for r in vals}["Legacy"] == "keepme"
