"""Best-effort import/export of 0.x user state (gib-* localStorage keys).

The icons pane kept tags/collections in localStorage (index.html:1340-1422,
:2090-2091); this importer accepts an exported JSON file shaped as either:

    {"tags": {"tag-name": ["Asset name", ...]},
     "collections": {"col-name": ["Asset name", ...]}}

or a flat {"tag-name": [names...]} map, and matches assets by name
(case-insensitive stem match). Idempotent: existing rows are skipped.

Round-trip export is provided for tests and for moving a library between
machines.
"""

from __future__ import annotations

import json
import sqlite3


def export_state(con: sqlite3.Connection) -> dict:
    tags: dict[str, list[str]] = {}
    for row in con.execute(
        "SELECT t.name AS tag, a.name AS asset FROM tag t"
        " JOIN asset_tag at ON at.tag_id = t.id"
        " JOIN asset a ON a.id = at.asset_id ORDER BY t.name, a.name"
    ):
        tags.setdefault(row["tag"], []).append(row["asset"])
    colls: dict[str, list[str]] = {}
    for row in con.execute(
        "SELECT c.name AS col, a.name AS asset FROM collection c"
        " JOIN collection_item ci ON ci.collection_id = c.id"
        " JOIN asset a ON a.id = ci.asset_id ORDER BY c.name, a.name"
    ):
        colls.setdefault(row["col"], []).append(row["asset"])
    return {"tags": tags, "collections": colls}


def import_state(con: sqlite3.Connection, data: dict) -> dict:
    counts = {"tags": 0, "tag_links": 0, "collections": 0, "collection_links": 0,
              "unmatched": 0}
    tags = data.get("tags", data) if isinstance(data, dict) else {}
    colls = data.get("collections", {}) if isinstance(data, dict) else {}

    for tag_name, asset_names in (tags or {}).items():
        if not isinstance(tag_name, str) or not isinstance(asset_names, list):
            continue
        tag_name = tag_name.lstrip("#").strip()
        if not tag_name:
            continue
        tag_id = _ensure_tag(con, tag_name, counts)
        for name in asset_names:
            aid = _find_asset(con, str(name))
            if aid is None:
                counts["unmatched"] += 1
                continue
            con.execute(
                "INSERT OR IGNORE INTO asset_tag(asset_id, tag_id) VALUES (?, ?)",
                (aid, tag_id),
            )
            counts["tag_links"] += con.total_changes  # proxy; recounted below

    for coll_name, asset_names in (colls or {}).items():
        if not isinstance(coll_name, str) or not isinstance(asset_names, list):
            continue
        coll_name = coll_name.strip()
        if not coll_name:
            continue
        coll_id = _ensure_collection(con, coll_name, counts)
        for pos, name in enumerate(asset_names):
            aid = _find_asset(con, str(name))
            if aid is None:
                counts["unmatched"] += 1
                continue
            con.execute(
                "INSERT OR IGNORE INTO collection_item(collection_id, asset_id,"
                " position) VALUES (?, ?, ?)",
                (coll_id, aid, pos),
            )
            counts["collection_links"] += 1

    con.commit()
    # replace the proxy counters with real ones
    counts["tag_links"] = con.execute("SELECT COUNT(*) FROM asset_tag").fetchone()[0]
    counts["collection_links"] = con.execute(
        "SELECT COUNT(*) FROM collection_item").fetchone()[0]
    return counts


def _ensure_tag(con, name, counts) -> int:
    row = con.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    cur = con.execute("INSERT INTO tag(name) VALUES (?)", (name,))
    counts["tags"] += 1
    return cur.lastrowid


def _ensure_collection(con, name, counts) -> int:
    row = con.execute(
        "SELECT id FROM collection WHERE name = ?", (name,)
    ).fetchone()
    if row:
        return row[0]
    cur = con.execute("INSERT INTO collection(name) VALUES (?)", (name,))
    counts["collections"] += 1
    return cur.lastrowid


def _find_asset(con, name: str):
    row = con.execute(
        "SELECT id FROM asset WHERE lower(name) = lower(?) LIMIT 1", (name,)
    ).fetchone()
    return row[0] if row else None


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
