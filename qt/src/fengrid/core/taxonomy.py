"""Taxonomy layer: saved libraries, smart collections, custom fields,
generated IDs, and typed links between first-class objects.

Design notes:
- Saved LIBRARIES are named tag sets (`library_view`) that resolve to a
  dynamic asset view — match_any (union) or match_all (intersection).
- SMART COLLECTIONS (`smart_collection`) store JSON criteria and are
  evaluated live at query time — no membership rows, so they can never go
  stale. Criteria keys: tags (list), tag_match_all (bool), theme, context,
  ext, starred (bool), q (name/path substring).
- CUSTOM FIELDS (`asset_field` + `asset_field_value`) are global
  definitions with per-asset values. Types: text, number, bool, date,
  select (options JSON {"choices": [...]}), id (auto numbering with
  {"prefix": str, "pad": int} — counter persisted in the setting table).
- LINKS (`asset_link`) are directed (from_kind/from_id → to_kind/to_id)
  with a free-text role. One-to-many = one source, many targets;
  many-to-one = many sources, one target; many-to-many = both sides free.
  Linkable kinds: the asset kinds (icon/font/snippet/palette), collection,
  library, project, smart.

All functions take an sqlite3.Connection from core.db.connect() (Row
factory required).
"""

from __future__ import annotations

import json
import re
import sqlite3

from . import db as core_db
import time

# --------------------------------------------------------------- saved libraries


def list_library_views(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT id, name, tags, match_all, created, updated"
        " FROM library_view ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def create_library_view(con: sqlite3.Connection, name: str, tags: str,
                        match_all: bool = False) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("library needs a name")
    now = time.time()
    cur = con.execute(
        "INSERT INTO library_view(name, tags, match_all, created, updated,"
        " guid) VALUES (?, ?, ?, ?, ?, ?)",
        (name, _clean_tags(tags), 1 if match_all else 0, now, now,
         core_db.new_guid()))
    con.commit()
    return int(cur.lastrowid or 0)


def update_library_view(con: sqlite3.Connection, view_id: int, name: str,
                        tags: str, match_all: bool) -> None:
    if con.execute("SELECT 1 FROM library_view WHERE id = ?",
                   (view_id,)).fetchone() is None:
        raise ValueError(f"unknown library: {view_id}")
    con.execute(
        "UPDATE library_view SET name = ?, tags = ?, match_all = ?,"
        " updated = ? WHERE id = ?",
        ((name or "").strip() or "Untitled library", _clean_tags(tags),
         1 if match_all else 0, time.time(), view_id))
    con.commit()


def delete_library_view(con: sqlite3.Connection, view_id: int) -> None:
    con.execute("DELETE FROM library_view WHERE id = ?", (view_id,))
    con.commit()


def library_view_assets(con: sqlite3.Connection, view_id: int) -> list[int]:
    """Asset ids matching the view's tag set (union or intersection)."""
    row = con.execute("SELECT tags, match_all FROM library_view WHERE id = ?",
                      (view_id,)).fetchone()
    if row is None:
        return []
    tags = [t.strip() for t in (row["tags"] or "").split(",") if t.strip()]
    if not tags:
        return []
    marks = ",".join("?" * len(tags))
    if row["match_all"]:
        sql = ("SELECT a.id FROM asset a JOIN item_tag it"
               " ON it.item_id = a.id AND it.item_kind = a.kind"
               " JOIN tag t ON t.id = it.tag_id WHERE t.name IN (%s)"
               " GROUP BY a.id HAVING COUNT(DISTINCT t.name) = ?" % marks)
        params = tags + [len(tags)]
    else:
        sql = ("SELECT DISTINCT a.id FROM asset a JOIN item_tag it"
               " ON it.item_id = a.id AND it.item_kind = a.kind"
               " JOIN tag t ON t.id = it.tag_id"
               " WHERE t.name IN (%s)" % marks)
        params = tags
    return [r["id"] for r in con.execute(sql, params)]


def _clean_tags(tags: str) -> str:
    return ",".join(t.strip() for t in (tags or "").split(",") if t.strip())


# ------------------------------------------------------------- smart collections

SMART_KINDS = ("icon", "font", "image", "video", "audio", "doc", "data",
               "spatial", "timeseries", "markdown", "snippet", "palette")


def list_smart_collections(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT id, name, item_kind, criteria, created, updated"
        " FROM smart_collection ORDER BY name COLLATE NOCASE").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["criteria"] = json.loads(d["criteria"] or "{}")
        except ValueError:
            d["criteria"] = {}
        out.append(d)
    return out


def create_smart_collection(con: sqlite3.Connection, name: str,
                            item_kind: str, criteria: dict) -> int:
    if item_kind not in SMART_KINDS:
        raise ValueError(f"unknown smart-collection kind: {item_kind}")
    name = (name or "").strip()
    if not name:
        raise ValueError("smart collection needs a name")
    cur = con.execute(
        "INSERT INTO smart_collection(name, item_kind, criteria)"
        " VALUES (?, ?, ?)",
        (name, item_kind, json.dumps(criteria or {})))
    con.commit()
    return int(cur.lastrowid or 0)


def update_smart_collection(con: sqlite3.Connection, sc_id: int, name: str,
                            criteria: dict) -> None:
    if con.execute("SELECT 1 FROM smart_collection WHERE id = ?",
                   (sc_id,)).fetchone() is None:
        raise ValueError(f"unknown smart collection: {sc_id}")
    con.execute(
        "UPDATE smart_collection SET name = ?, criteria = ?, updated ="
        " datetime('now', 'localtime') WHERE id = ?",
        ((name or "").strip() or "Untitled smart collection",
         json.dumps(criteria or {}), sc_id))
    con.commit()


def delete_smart_collection(con: sqlite3.Connection, sc_id: int) -> None:
    con.execute("DELETE FROM smart_collection WHERE id = ?", (sc_id,))
    con.commit()


def smart_asset_ids(con: sqlite3.Connection, item_kind: str,
                    criteria: dict) -> list[int]:
    """Resolve a smart collection's criteria to row ids in its own table."""
    crit = criteria or {}
    from . import kinds as core_kinds
    if item_kind in core_kinds.ALL_KINDS:
        return _smart_icon_ids(con, crit, kind=item_kind)
    # snippet / palette carry a comma-separated tags column
    table = "snippet" if item_kind == "snippet" else "palette"
    tags = [t.strip() for t in crit.get("tags", []) if t.strip()]
    where, params = [], []
    if tags:
        clause = " OR ".join(
            "lower(tags) LIKE ?" for _ in tags) if not crit.get(
            "tag_match_all") else " AND ".join(
            "lower(tags) LIKE ?" for _ in tags)
        where.append("(" + clause + ")")
        params += [f"%{t.lower()}%" for t in tags]
    if crit.get("q"):
        where.append("lower(title) LIKE ?" if item_kind == "snippet"
                     else "lower(name) LIKE ?")
        params.append("%" + str(crit["q"]).lower() + "%")
    sql = f"SELECT id FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return [r["id"] for r in con.execute(sql, params)]


def _smart_icon_ids(con: sqlite3.Connection, crit: dict,
                    kind: str = "icon") -> list[int]:
    where: list[str] = ["a.kind = ?"]
    params: list = [kind]
    tags = [t.strip() for t in crit.get("tags", []) if t.strip()]
    if tags:
        marks = ",".join("?" * len(tags))
        sub = ("SELECT it.item_id FROM item_tag it JOIN tag t"
               f" ON t.id = it.tag_id WHERE it.item_kind = ?"
               f" AND t.name IN ({marks})")
        if crit.get("tag_match_all"):
            sub += (" GROUP BY it.item_id"
                    f" HAVING COUNT(DISTINCT t.name) = {len(tags)}")
        where.append(f"a.id IN ({sub})")
        params += [kind, *tags]
    for key, col in (("theme", "a.theme"), ("context", "a.context"),
                     ("ext", "a.ext")):
        if crit.get(key):
            where.append(f"{col} = ?")
            params.append(crit[key])
    if crit.get("starred"):
        where.append(
            "a.id IN (SELECT it2.item_id FROM item_tag it2"
            " JOIN tag t2 ON t2.id = it2.tag_id"
            " WHERE it2.item_kind = ? AND t2.name = 'starred')")
        params.append(kind)
    if crit.get("q"):
        where.append("(lower(a.name) LIKE ? OR lower(a.path) LIKE ?)")
        like = "%" + str(crit["q"]).lower() + "%"
        params += [like, like]
    sql = "SELECT a.id FROM asset a"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return [r["id"] for r in con.execute(sql, params)]


# ------------------------------------------------------------------ custom fields

FIELD_TYPES = ("text", "number", "bool", "date", "select", "id")


def list_fields(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT id, name, type, options, created FROM asset_field"
        " ORDER BY name COLLATE NOCASE").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["options"] = json.loads(d["options"] or "{}")
        except ValueError:
            d["options"] = {}
        out.append(d)
    return out


def create_field(con: sqlite3.Connection, name: str, ftype: str,
                 options: dict | None = None) -> int:
    if ftype not in FIELD_TYPES:
        raise ValueError(f"unknown field type: {ftype}")
    name = (name or "").strip()
    if not name:
        raise ValueError("field needs a name")
    cur = con.execute(
        "INSERT INTO asset_field(name, type, options, created)"
        " VALUES (?, ?, ?, ?)", (name, ftype, json.dumps(options or {}),
                                 time.time()))
    con.commit()
    return int(cur.lastrowid or 0)


def delete_field(con: sqlite3.Connection, field_id: int) -> None:
    con.execute("DELETE FROM asset_field WHERE id = ?", (field_id,))
    con.commit()  # values cascade


def library_view_kind_counts(con: sqlite3.Connection, view_id: int) -> dict[str, int]:
    """Per-asset-kind row counts for a saved library view. The rail's
    pane-scoped lists need icon vs font counts so a library only shows
    on panes where it has displayable assets. Empty view → {}."""
    row = con.execute("SELECT tags, match_all FROM library_view WHERE id = ?",
                      (view_id,)).fetchone()
    if row is None:
        return {}
    tags = [t.strip() for t in (row["tags"] or "").split(",") if t.strip()]
    if not tags:
        return {}
    marks = ",".join("?" * len(tags))
    if row["match_all"]:
        sql = ("SELECT a.kind, COUNT(DISTINCT a.id) AS n FROM asset a"
               " JOIN item_tag it ON it.item_id = a.id"
               " AND it.item_kind = a.kind"
               " JOIN tag t ON t.id = it.tag_id WHERE t.name IN (%s)"
               " GROUP BY a.id, a.kind HAVING COUNT(DISTINCT t.name) = ?"
               % marks)
        params = [*tags, len(tags)]
    else:
        sql = ("SELECT a.kind, COUNT(DISTINCT a.id) AS n FROM asset a"
               " JOIN item_tag it ON it.item_id = a.id"
               " AND it.item_kind = a.kind"
               " JOIN tag t ON t.id = it.tag_id WHERE t.name IN (%s)"
               " GROUP BY a.kind" % marks)
        params = list(tags)
    return {r["kind"]: r["n"] for r in con.execute(sql, params)}


def _item_exists(con: sqlite3.Connection, kind: str, item_id: int) -> bool:
    """True when a (kind, id) pair names a real row — every asset-table
    kind lives in `asset`; snippets and palettes in their own tables."""
    from . import kinds as core_kinds
    if kind in core_kinds.ALL_KINDS:
        return con.execute("SELECT 1 FROM asset WHERE id = ? AND kind = ?",
                           (item_id, kind)).fetchone() is not None
    if kind == "snippet":
        return con.execute("SELECT 1 FROM snippet WHERE id = ?",
                           (item_id,)).fetchone() is not None
    if kind == "palette":
        return con.execute("SELECT 1 FROM palette WHERE id = ?",
                           (item_id,)).fetchone() is not None
    # first-class entities that carry their own inspector (Documentation /
    # License / Sources tabs): one git repo per Project or saved Library
    if kind == "project":
        return con.execute("SELECT 1 FROM projects WHERE id = ?",
                           (item_id,)).fetchone() is not None
    if kind == "library":
        return con.execute("SELECT 1 FROM library_view WHERE id = ?",
                           (item_id,)).fetchone() is not None
    if kind == "preset":
        return con.execute("SELECT 1 FROM preset_library WHERE id = ?",
                           (item_id,)).fetchone() is not None
    if kind == "preset_entry":
        return con.execute("SELECT 1 FROM preset_entry WHERE id = ?",
                           (item_id,)).fetchone() is not None
    return False


def set_field_value(con: sqlite3.Connection, item_id: int, field_id: int,
                    value: str, kind: str = "icon") -> None:
    if not _item_exists(con, kind, item_id):
        raise ValueError(f"unknown {kind}: {item_id}")
    if con.execute("SELECT 1 FROM asset_field WHERE id = ?",
                   (field_id,)).fetchone() is None:
        raise ValueError(f"unknown field: {field_id}")
    con.execute(
        "INSERT INTO item_field_value(item_id, item_kind, field_id, value)"
        " VALUES (?, ?, ?, ?) ON CONFLICT(item_id, item_kind, field_id)"
        " DO UPDATE SET value = excluded.value",
        (item_id, kind, field_id, value))
    con.commit()


def asset_field_values(con: sqlite3.Connection, item_id: int,
                       kind: str = "icon") -> list[dict]:
    """Every defined field joined with this item's value (missing = '')."""
    rows = con.execute(
        "SELECT f.id, f.name, f.type, f.options,"
        " COALESCE(v.value, '') AS value"
        " FROM asset_field f LEFT JOIN item_field_value v"
        " ON v.field_id = f.id AND v.item_id = ? AND v.item_kind = ?"
        " ORDER BY f.name COLLATE NOCASE", (item_id, kind)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["options"] = json.loads(d["options"] or "{}")
        except ValueError:
            d["options"] = {}
        out.append(d)
    return out


_ID_RE = re.compile(r"^(.*?)0*(\d+)$")


def generate_field_id(con: sqlite3.Connection, item_id: int,
                      field_id: int, kind: str = "icon") -> str:
    """Assign the next formatted ID for an `id`-type field.

    Counter = highest numeric suffix already minted with this field's
    prefix + 1 (suffix scan over existing values — no separate sequence
    state to corrupt). Format: prefix + zero-padded number.
    """
    row = con.execute("SELECT options FROM asset_field WHERE id = ? AND"
                      " type = 'id'", (field_id,)).fetchone()
    if row is None:
        raise ValueError(f"field {field_id} is not an id field")
    try:
        opts = json.loads(row["options"] or "{}")
    except ValueError:
        opts = {}
    prefix = str(opts.get("prefix", ""))
    pad = int(opts.get("pad", 4))
    highest = 0
    for (val,) in con.execute(
            "SELECT value FROM item_field_value WHERE field_id = ?",
            (field_id,)):
        m = _ID_RE.match(str(val or ""))
        if m and m.group(1) == prefix:
            try:
                highest = max(highest, int(m.group(2)))
            except ValueError:
                pass
    nxt = f"{prefix}{highest + 1:0{pad}d}"
    set_field_value(con, item_id, field_id, nxt, kind)
    return nxt


# ------------------------------------------------------------------------ links

LINK_KINDS = ("icon", "font", "snippet", "palette", "collection", "library",
              "project", "smart")


def add_link(con: sqlite3.Connection, from_kind: str, from_id: int,
             to_kind: str, to_id: int, role: str = "") -> int:
    if from_kind not in LINK_KINDS or to_kind not in LINK_KINDS:
        raise ValueError(f"unknown link kind: {from_kind} -> {to_kind}")
    cur = con.execute(
        "INSERT OR IGNORE INTO asset_link(from_kind, from_id, to_kind,"
        " to_id, role) VALUES (?, ?, ?, ?, ?)",
        (from_kind, from_id, to_kind, to_id, role or ""))
    con.commit()
    return int(cur.lastrowid or 0)


def remove_link(con: sqlite3.Connection, link_id: int) -> None:
    con.execute("DELETE FROM asset_link WHERE id = ?", (link_id,))
    con.commit()


def set_link_role(con: sqlite3.Connection, link_id: int, role: str) -> None:
    con.execute("UPDATE asset_link SET role = ? WHERE id = ?",
                (role or "", link_id))
    con.commit()


def _label_for(con: sqlite3.Connection, kind: str, item_id: int) -> str:
    if kind == "icon":
        r = con.execute("SELECT name FROM asset WHERE id = ?",
                        (item_id,)).fetchone()
    elif kind == "snippet":
        r = con.execute("SELECT title FROM snippet WHERE id = ?",
                        (item_id,)).fetchone()
    elif kind in ("palette",):
        r = con.execute("SELECT name FROM palette WHERE id = ?",
                        (item_id,)).fetchone()
    elif kind == "collection":
        r = con.execute("SELECT name FROM collection WHERE id = ?",
                        (item_id,)).fetchone()
    elif kind == "library":
        r = con.execute("SELECT name FROM library_view WHERE id = ?",
                        (item_id,)).fetchone()
    elif kind == "project":
        r = con.execute("SELECT name FROM projects WHERE id = ?",
                        (item_id,)).fetchone()
    elif kind == "smart":
        r = con.execute("SELECT name FROM smart_collection WHERE id = ?",
                        (item_id,)).fetchone()
    else:  # font: fonts are indexed asset rows
        r = con.execute("SELECT name FROM asset WHERE id = ?",
                        (item_id,)).fetchone()
    return r[0] if r else f"{kind}:{item_id}"


def links_for(con: sqlite3.Connection, kind: str, item_id: int,
              direction: str = "out") -> list[dict]:
    """Links anchored at (kind, item_id); direction 'out' | 'in' | 'both'."""
    out = []
    if direction in ("out", "both"):
        for r in con.execute(
                "SELECT id, to_kind, to_id, role FROM asset_link"
                " WHERE from_kind = ? AND from_id = ?", (kind, item_id)):
            out.append({"id": r["id"], "direction": "out",
                        "kind": r["to_kind"], "item_id": r["to_id"],
                        "role": r["role"],
                        "label": _label_for(con, r["to_kind"], r["to_id"])})
    if direction in ("in", "both"):
        for r in con.execute(
                "SELECT id, from_kind, from_id, role FROM asset_link"
                " WHERE to_kind = ? AND to_id = ?", (kind, item_id)):
            out.append({"id": r["id"], "direction": "in",
                        "kind": r["from_kind"], "item_id": r["from_id"],
                        "role": r["role"],
                        "label": _label_for(con, r["from_kind"], r["from_id"])})
    return out


# ---------------------------------------------------------------- tags as
# cross-type taxonomy — entities of one kind surfaced through the tags of
# another (the Properties panel's "Related by tag" section)
_RELATED_KINDS = ("icon", "font", "snippet", "palette", "project", "library",
                  "preset", "preset_entry")

_RELATED_NAME_SQL = {
    "icon": "SELECT name FROM asset WHERE id = ?",
    "font": "SELECT name FROM asset WHERE id = ?",
    "snippet": "SELECT title FROM snippet WHERE id = ?",
    "palette": "SELECT name FROM palette WHERE id = ?",
    "project": "SELECT name FROM projects WHERE id = ?",
    "library": "SELECT name FROM library_view WHERE id = ?",
    "preset": "SELECT name FROM preset_library WHERE id = ?",
    "preset_entry": "SELECT name FROM preset_entry WHERE id = ?",
}


def related_by_tags(con: sqlite3.Connection, kind: str,
                    item_id: int) -> list[dict]:
    """Entities of OTHER kinds sharing at least one tag with (kind,
    item_id), each with the list of shared tag names. Tags are the
    taxonomic link fabric between asset types."""
    own = [r["name"] for r in con.execute(
        "SELECT t.name FROM tag t JOIN item_tag it"
        " ON it.tag_id = t.id WHERE it.item_kind = ? AND it.item_id = ?"
        " ORDER BY t.name", (kind, item_id))]
    if not own:
        return []
    marks = ",".join("?" * len(own))
    out = []
    for other in _RELATED_KINDS:
        if other == kind:
            continue
        ids = [r["item_id"] for r in con.execute(
            "SELECT DISTINCT it.item_id FROM item_tag it"
            " JOIN tag t ON t.id = it.tag_id"
            f" WHERE it.item_kind = '{other}' AND t.name IN ({marks})",
            own)]
        for oid in ids:
            row = con.execute(_RELATED_NAME_SQL[other], (oid,)).fetchone()
            name = row[0] if row else ""
            if not name:
                continue
            shared = [t for t in own if con.execute(
                "SELECT 1 FROM item_tag it JOIN tag t ON t.id = it.tag_id"
                " WHERE it.item_kind = ? AND it.item_id = ? AND t.name = ?",
                (other, oid, t)).fetchone()]
            out.append({"kind": other, "id": oid, "name": name,
                        "shared": shared})
    out.sort(key=lambda r: (-len(r["shared"]), r["kind"], r["name"].lower()))
    return out
