"""Canvas core: the Projects pane's collaborative design + code canvas.

A *board* is an infinite 2-D canvas that belongs to a project. Boards
hold *nodes* — frames, shapes, text, stickies, code cells, and nodes
BOUND to Fengrid-tracked objects (icons, fonts, images and other media,
palettes, snippets, collections). Bound nodes render live from the
library: rename an icon, edit a palette, rescan a font, and every board
that uses it follows.

Collaboration model
-------------------
Every edit is an *op* — ``{"node": id, "fields": {...}, "clock": n,
"actor": a}`` — appended to ``canvas_op`` and folded into
``canvas_node``. Each node is a last-writer-wins map: every field carries
its own ``(clock, actor)`` stamp, so two people editing different
properties of the same node both keep their change, and a conflicting
edit to the same property resolves identically on every replica
(higher Lamport clock wins; the actor id breaks ties). Deletion is just
the field ``deleted = 1`` — a late edit cannot resurrect a node that was
deleted "after" it, and undo of a delete is an ordinary set.

That makes the op log replayable in any order, which is what lets the
desktop app, the REST API (``/api/v1/boards/...``) and any number of
remote peers edit one board concurrently with nothing more than
"send me the ops since seq N". Undo is collaboration-safe: it applies
the *inverse* op as a new local edit rather than rewinding history.

Integration with the other panes
--------------------------------
- bindings resolve through ``core.assetrefs`` (GUID first, so a node
  survives rescans that renumber rows), the same ``[[ ref ]]`` fabric
  snippets and Studio pages use
- collections, smart collections and saved libraries can be dropped
  onto a board as a laid-out frame of bound nodes
- usage is indexed (``bind_kind/bind_id/bind_guid``) so the inspector
  can answer "which boards use this asset?", and ``sync_links`` mirrors
  it into ``asset_link`` (role ``canvas``) for the Properties panel
- code cells can be promoted to Code-pane snippets (and stay bound)
- exports reuse the hardened escaping rules: everything user- or
  path-derived is HTML-escaped; asset files are copied, never linked

Pure Python, no Qt — unit-testable headlessly like the rest of core/.
"""
from __future__ import annotations

import html as _html
import json
import os
import shutil
import time
import uuid
from typing import Any, Iterable

from . import assetrefs
from . import db as core_db

# ───────────────────────────────────────────────────────────── vocabulary
SHAPE_TYPES = ("frame", "group", "rect", "ellipse", "line", "text",
               "sticky", "code", "connector")
BOUND_TYPES = ("icon", "image", "font", "palette", "snippet", "asset",
               "collection")
NODE_TYPES = SHAPE_TYPES + BOUND_TYPES

# containers can parent other nodes (coordinates stay board-absolute;
# parent is membership for move/export/layers, not a transform)
CONTAINER_TYPES = ("frame", "group", "collection")

# asset kind → the node type that presents it
KIND_NODE = {
    "icon": "icon", "image": "image", "font": "font",
    "palette": "palette", "snippet": "snippet",
    "video": "asset", "audio": "asset", "doc": "asset", "data": "asset",
    "spatial": "asset", "timeseries": "asset", "markdown": "asset",
    "collection": "collection",
}

# structural fields (everything else is a "p.<key>" prop field)
CORE_FIELDS = ("type", "parent", "name", "x", "y", "w", "h", "rot", "z",
               "bind", "locked", "hidden", "deleted")
_NUMERIC = ("x", "y", "w", "h", "rot", "z")
_FLAGS = ("locked", "hidden", "deleted")

MAX_NODES_PER_BOARD = 20000
MAX_PROP_BYTES = 256 * 1024          # one prop value (code cells)
MAX_OPS_PER_BATCH = 5000
MIN_SIZE = 1.0

# default styling per type — what a freshly drawn node looks like
DEFAULT_PROPS: dict[str, dict] = {
    "frame": {"fill": "#FFFFFF", "stroke": "", "strokeWidth": 0,
              "radius": 0, "clip": True},
    "group": {},
    "rect": {"fill": "#D9DEE3", "stroke": "", "strokeWidth": 0,
             "radius": 4, "opacity": 1},
    "ellipse": {"fill": "#D9DEE3", "stroke": "", "strokeWidth": 0,
                "opacity": 1},
    "line": {"stroke": "#6E7B86", "strokeWidth": 2},
    "text": {"text": "Text", "color": "#16202B", "fontSize": 16,
             "fontFamily": "", "fontWeight": 400, "align": "left"},
    "sticky": {"text": "", "fill": "#F5C25C", "color": "#16202B",
               "fontSize": 14},
    "code": {"lang": "html", "html": "<button class=\"btn\">Button"
             "</button>", "css": ".btn{padding:8px 14px;border-radius:6px}",
             "js": ""},
    "connector": {"from": "", "to": "", "stroke": "#6E7B86",
                  "strokeWidth": 2, "arrow": True},
    "icon": {"tint": ""},
    "image": {"fit": "contain", "radius": 0},
    "font": {"text": "Sphinx of black quartz, judge my vow",
             "fontSize": 28, "color": "#16202B"},
    "palette": {"layout": "row"},
    "snippet": {},
    "asset": {},
    "collection": {"fill": "#F7F8F9", "stroke": "#D5DCE0",
                   "strokeWidth": 1, "radius": 8, "clip": False},
}

DEFAULT_SIZE: dict[str, tuple[float, float]] = {
    "frame": (1280, 720), "group": (200, 200), "rect": (160, 100),
    "ellipse": (120, 120), "line": (200, 0), "text": (200, 28),
    "sticky": (200, 200), "code": (360, 220), "connector": (0, 0),
    "icon": (64, 64), "image": (320, 240), "font": (420, 110),
    "palette": (240, 48), "snippet": (360, 220), "asset": (220, 64),
    "collection": (600, 400),
}


class CanvasError(Exception):
    """User-scale canvas error (bad payload, unknown board/node…)."""


# ──────────────────────────────────────────────────────────────── schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS canvas_board (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    sort       INTEGER NOT NULL DEFAULT 0,
    settings   TEXT NOT NULL DEFAULT '{}',   -- grid, background, viewport
    clock      INTEGER NOT NULL DEFAULT 0,   -- Lamport clock high-water
    guid       TEXT,
    slug       TEXT,
    created    REAL NOT NULL,
    updated    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_canvas_board_project
    ON canvas_board(project_id, sort);

CREATE TABLE IF NOT EXISTS canvas_node (
    board_id  INTEGER NOT NULL REFERENCES canvas_board(id) ON DELETE CASCADE,
    id        TEXT NOT NULL,
    type      TEXT NOT NULL DEFAULT 'rect',
    parent    TEXT NOT NULL DEFAULT '',
    name      TEXT NOT NULL DEFAULT '',
    x REAL NOT NULL DEFAULT 0, y REAL NOT NULL DEFAULT 0,
    w REAL NOT NULL DEFAULT 100, h REAL NOT NULL DEFAULT 100,
    rot REAL NOT NULL DEFAULT 0,
    z   REAL NOT NULL DEFAULT 0,
    props     TEXT NOT NULL DEFAULT '{}',
    bind      TEXT NOT NULL DEFAULT '',      -- JSON locator or ''
    bind_kind TEXT NOT NULL DEFAULT '',      -- indexed usage lookups
    bind_id   INTEGER NOT NULL DEFAULT 0,
    bind_guid TEXT NOT NULL DEFAULT '',
    locked    INTEGER NOT NULL DEFAULT 0,
    hidden    INTEGER NOT NULL DEFAULT 0,
    deleted   INTEGER NOT NULL DEFAULT 0,
    stamps    TEXT NOT NULL DEFAULT '{}',    -- field -> [clock, actor]
    PRIMARY KEY (board_id, id)
);
CREATE INDEX IF NOT EXISTS idx_canvas_node_bind
    ON canvas_node(bind_kind, bind_id);
CREATE INDEX IF NOT EXISTS idx_canvas_node_guid
    ON canvas_node(bind_guid);

CREATE TABLE IF NOT EXISTS canvas_op (
    seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL REFERENCES canvas_board(id) ON DELETE CASCADE,
    actor    TEXT NOT NULL,
    clock    INTEGER NOT NULL,
    node_id  TEXT NOT NULL,
    fields   TEXT NOT NULL,
    ts       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_canvas_op_board ON canvas_op(board_id, seq);

CREATE TABLE IF NOT EXISTS canvas_comment (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL REFERENCES canvas_board(id) ON DELETE CASCADE,
    node_id  TEXT NOT NULL DEFAULT '',
    x REAL NOT NULL DEFAULT 0, y REAL NOT NULL DEFAULT 0,
    author   TEXT NOT NULL DEFAULT '',
    body     TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    created  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS canvas_presence (
    board_id INTEGER NOT NULL REFERENCES canvas_board(id) ON DELETE CASCADE,
    actor    TEXT NOT NULL,
    name     TEXT NOT NULL DEFAULT '',
    color    TEXT NOT NULL DEFAULT '',
    cursor_x REAL, cursor_y REAL,
    selection TEXT NOT NULL DEFAULT '[]',
    seen     REAL NOT NULL,
    PRIMARY KEY (board_id, actor)
);
"""


def migrate(con) -> None:
    """Idempotent; safe to call from every bridge/API entry point."""
    con.executescript(SCHEMA)
    con.commit()


# ───────────────────────────────────────────────────────────── identity
_ACTOR_KEY = "canvas.actor"


def local_actor(con) -> str:
    """This install's stable actor id (one per library database)."""
    a = core_db.get_setting(con, _ACTOR_KEY)
    if not a:
        a = "a-" + uuid.uuid4().hex[:12]
        core_db.set_setting(con, _ACTOR_KEY, a)
    return str(a)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> float:
    return time.time()


# ─────────────────────────────────────────────────────────── board CRUD
def _project_exists(con, project_id: int) -> None:
    if con.execute("SELECT 1 FROM projects WHERE id = ?",
                   (int(project_id),)).fetchone() is None:
        raise CanvasError(f"no project #{project_id}")


def list_boards(con, project_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT b.id, b.name, b.sort, b.guid, b.updated,"
        " (SELECT COUNT(*) FROM canvas_node n WHERE n.board_id = b.id"
        "   AND n.deleted = 0) AS nodes"
        " FROM canvas_board b WHERE b.project_id = ?"
        " ORDER BY b.sort, b.id", (int(project_id),)).fetchall()
    return [dict(r) for r in rows]


def create_board(con, project_id: int, name: str = "",
                 settings: dict | None = None) -> int:
    _project_exists(con, project_id)
    name = (name or "").strip() or "Board"
    sort = con.execute(
        "SELECT COALESCE(MAX(sort), -1) + 1 FROM canvas_board"
        " WHERE project_id = ?", (int(project_id),)).fetchone()[0]
    now = _now()
    cur = con.execute(
        "INSERT INTO canvas_board(project_id, name, sort, settings, guid,"
        " created, updated) VALUES (?,?,?,?,?,?,?)",
        (int(project_id), name, sort,
         json.dumps(settings or {"grid": 8, "background": ""}),
         core_db.new_guid(), now, now))
    con.commit()
    return int(cur.lastrowid)


def get_board(con, board_id: int) -> dict | None:
    row = con.execute("SELECT * FROM canvas_board WHERE id = ?",
                      (int(board_id),)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["settings"] = _loads(d.get("settings"), {})
    return d


def _require_board(con, board_id: int) -> dict:
    b = get_board(con, board_id)
    if b is None:
        raise CanvasError(f"no board #{board_id}")
    return b


def rename_board(con, board_id: int, name: str) -> None:
    name = (name or "").strip()
    if not name:
        raise CanvasError("board needs a name")
    con.execute("UPDATE canvas_board SET name = ?, updated = ? WHERE id = ?",
                (name, _now(), int(board_id)))
    con.commit()


def set_board_settings(con, board_id: int, patch: dict) -> dict:
    b = _require_board(con, board_id)
    s = dict(b["settings"])
    s.update({k: v for k, v in (patch or {}).items()
              if k in ("grid", "background", "viewport", "snap")})
    con.execute("UPDATE canvas_board SET settings = ? WHERE id = ?",
                (json.dumps(s), int(board_id)))
    con.commit()
    return s


def delete_board(con, board_id: int) -> None:
    con.execute("DELETE FROM canvas_board WHERE id = ?", (int(board_id),))
    con.commit()


def duplicate_board(con, board_id: int, name: str = "") -> int:
    """Fork a board: same nodes (fresh ids), fresh op history."""
    b = _require_board(con, board_id)
    nb = create_board(con, b["project_id"],
                      name or (b["name"] + " copy"), b["settings"])
    idmap = {n["id"]: new_id() for n in nodes(con, board_id)}
    ops = []
    for n in nodes(con, board_id):
        f = _node_fields(n)
        f["parent"] = idmap.get(f.get("parent") or "", "")
        if n["type"] == "connector":
            f["p.from"] = idmap.get(f.get("p.from", ""), "")
            f["p.to"] = idmap.get(f.get("p.to", ""), "")
        ops.append({"node": idmap[n["id"]], "fields": f})
    apply_local(con, nb, ops)
    return nb


# ──────────────────────────────────────────────────────────── node rows
def _loads(raw, default):
    try:
        v = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


def _row_node(r) -> dict:
    d = dict(r)
    d["props"] = _loads(d.get("props"), {})
    d["bind"] = _loads(d.get("bind"), {}) if d.get("bind") else {}
    d["locked"] = bool(d.get("locked"))
    d["hidden"] = bool(d.get("hidden"))
    d["deleted"] = bool(d.get("deleted"))
    d.pop("stamps", None)
    d.pop("board_id", None)
    return d


def nodes(con, board_id: int, include_deleted: bool = False) -> list[dict]:
    sql = "SELECT * FROM canvas_node WHERE board_id = ?"
    if not include_deleted:
        sql += " AND deleted = 0"
    sql += " ORDER BY z, id"
    return [_row_node(r) for r in con.execute(sql, (int(board_id),))]


def get_node(con, board_id: int, node_id: str) -> dict | None:
    r = con.execute("SELECT * FROM canvas_node WHERE board_id = ? AND id = ?",
                    (int(board_id), str(node_id))).fetchone()
    return _row_node(r) if r else None


def _node_fields(n: dict) -> dict:
    """Flatten a node dict into op fields (inverse of _row_node)."""
    f = {k: n.get(k) for k in CORE_FIELDS if k in n}
    for k, v in (n.get("props") or {}).items():
        f["p." + k] = v
    return f


# ───────────────────────────────────────────────────────── op machinery
def _valid_field(key: str) -> bool:
    if key in CORE_FIELDS:
        return True
    return (key.startswith("p.") and 2 < len(key) <= 66
            and key[2:].replace("_", "").replace("-", "").isalnum())


def _coerce(key: str, val: Any) -> Any:
    if key in _NUMERIC:
        try:
            v = float(val)
        except (TypeError, ValueError):
            raise CanvasError(f"{key} must be a number")
        if v != v or abs(v) > 1e7:               # NaN / runaway coords
            raise CanvasError(f"{key} out of range")
        if key in ("w", "h"):
            v = max(0.0, v)
        return v
    if key in _FLAGS:
        return 1 if val else 0
    if key == "type":
        if val not in NODE_TYPES:
            raise CanvasError(f"unknown node type {val!r}")
        return val
    if key in ("parent", "name"):
        return str(val or "")[:512]
    if key == "bind":
        if not val:
            return {}
        if not isinstance(val, dict):
            raise CanvasError("bind must be an object")
        return {k: val[k] for k in ("kind", "id", "guid", "slug", "ref",
                                     "name") if k in val}
    # props: any JSON value, size-capped
    if len(json.dumps(val)) > MAX_PROP_BYTES:
        raise CanvasError(f"{key} too large")
    return val


def _stamp_gt(a: list | None, b: list | None) -> bool:
    """(clock, actor) ordering; missing stamps lose to anything."""
    if b is None:
        return True
    if a is None:
        return False
    return (int(a[0]), str(a[1])) > (int(b[0]), str(b[1]))


def _fold(con, board_id: int, node_id: str, fields: dict, clock: int,
          actor: str) -> dict:
    """Merge one op into canvas_node (LWW per field). Returns the
    fields that actually won (empty dict = op was fully superseded)."""
    row = con.execute(
        "SELECT * FROM canvas_node WHERE board_id = ? AND id = ?",
        (board_id, node_id)).fetchone()
    stamp = [int(clock), str(actor)]
    if row is None:
        # an edit for a node we've never seen becomes a stub row, so a
        # later-arriving create still merges (order independence)
        n = {"type": "rect", "parent": "", "name": "", "x": 0.0,
             "y": 0.0, "w": 100.0, "h": 100.0, "rot": 0.0, "z": 0.0,
             "props": {}, "bind": {}, "locked": 0, "hidden": 0,
             "deleted": 1}          # invisible until its create lands
        stamps: dict = {}
        fresh = True
    else:
        n = dict(row)
        n["props"] = _loads(n["props"], {})
        n["bind"] = _loads(n["bind"], {}) if n["bind"] else {}
        stamps = _loads(n["stamps"], {})
        fresh = False
    won: dict = {}
    for k, v in fields.items():
        if not _stamp_gt(stamp, stamps.get(k)):
            continue
        stamps[k] = stamp
        won[k] = v
        if k.startswith("p."):
            if v is None:
                n["props"].pop(k[2:], None)
            else:
                n["props"][k[2:]] = v
        else:
            n[k] = v
    if not won:
        return {}
    b = n["bind"] or {}
    vals = (n["type"], n["parent"], n["name"], n["x"], n["y"], n["w"],
            n["h"], n["rot"], n["z"], json.dumps(n["props"]),
            json.dumps(b) if b else "", str(b.get("kind", "")),
            int(b.get("id") or 0), str(b.get("guid") or ""),
            int(n["locked"]), int(n["hidden"]), int(n["deleted"]),
            json.dumps(stamps))
    if fresh:
        con.execute(
            "INSERT INTO canvas_node(type, parent, name, x, y, w, h, rot,"
            " z, props, bind, bind_kind, bind_id, bind_guid, locked,"
            " hidden, deleted, stamps, board_id, id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*vals, board_id, node_id))
    else:
        con.execute(
            "UPDATE canvas_node SET type=?, parent=?, name=?, x=?, y=?,"
            " w=?, h=?, rot=?, z=?, props=?, bind=?, bind_kind=?,"
            " bind_id=?, bind_guid=?, locked=?, hidden=?, deleted=?,"
            " stamps=? WHERE board_id=? AND id=?",
            (*vals, board_id, node_id))
    return won


def _clean_ops(ops: Iterable[dict]) -> list[dict]:
    out = []
    for op in ops:
        if not isinstance(op, dict):
            raise CanvasError("ops must be objects")
        nid = str(op.get("node") or "")
        if not nid or len(nid) > 64:
            raise CanvasError("op needs a node id")
        fields = op.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise CanvasError("op needs fields")
        clean = {}
        for k, v in fields.items():
            if not _valid_field(str(k)):
                raise CanvasError(f"unknown field {k!r}")
            clean[str(k)] = None if (v is None and k.startswith("p.")) \
                else _coerce(str(k), v)
        if "type" in clean and "deleted" not in clean:
            clean["deleted"] = 0            # a typed op is a create
        out.append({"node": nid, "fields": clean,
                    "clock": op.get("clock"), "actor": op.get("actor")})
    if len(out) > MAX_OPS_PER_BATCH:
        raise CanvasError("too many ops in one batch")
    return out


def _check_capacity(con, board_id: int, ops: list[dict]) -> None:
    n = con.execute("SELECT COUNT(*) FROM canvas_node WHERE board_id = ?",
                    (board_id,)).fetchone()[0]
    if n + len(ops) > MAX_NODES_PER_BOARD * 2:      # deleted rows count too
        raise CanvasError("board is full")


def apply_local(con, board_id: int, ops: Iterable[dict],
                actor: str | None = None) -> list[dict]:
    """Apply edits made HERE: stamps each op with the next Lamport
    clock and this actor. Returns the logged ops (with seq/clock)."""
    board = _require_board(con, board_id)
    actor = actor or local_actor(con)
    clean = _clean_ops(ops)
    _check_capacity(con, board["id"], clean)
    clock = int(board["clock"])
    for op in clean:
        clock += 1
        op["clock"], op["actor"] = clock, actor
    return _commit(con, board["id"], clean, clock)


def apply_remote(con, board_id: int, ops: Iterable[dict]) -> list[dict]:
    """Merge edits from a peer (API client, another install). Each op
    must carry its own clock + actor; the board clock advances to the
    max seen, so the next local edit orders after everything merged."""
    board = _require_board(con, board_id)
    clean = _clean_ops(ops)
    _check_capacity(con, board["id"], clean)
    hi = int(board["clock"])
    for op in clean:
        try:
            op["clock"] = int(op["clock"])
        except (TypeError, ValueError):
            raise CanvasError("remote ops need an integer clock")
        a = str(op.get("actor") or "")
        if not a or len(a) > 64:
            raise CanvasError("remote ops need an actor id")
        op["actor"] = a
        hi = max(hi, op["clock"])
    return _commit(con, board["id"], clean, hi)


def _commit(con, board_id: int, ops: list[dict], clock: int) -> list[dict]:
    now = _now()
    logged = []
    try:
        for op in ops:
            won = _fold(con, board_id, op["node"], op["fields"],
                        op["clock"], op["actor"])
            if not won:
                continue
            cur = con.execute(
                "INSERT INTO canvas_op(board_id, actor, clock, node_id,"
                " fields, ts) VALUES (?,?,?,?,?,?)",
                (board_id, op["actor"], op["clock"], op["node"],
                 json.dumps(won), now))
            logged.append({"seq": int(cur.lastrowid), "node": op["node"],
                           "fields": won, "clock": op["clock"],
                           "actor": op["actor"]})
        con.execute("UPDATE canvas_board SET clock = MAX(clock, ?),"
                    " updated = ? WHERE id = ?", (clock, now, board_id))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return logged


def head(con, board_id: int) -> int:
    r = con.execute("SELECT COALESCE(MAX(seq), 0) FROM canvas_op"
                    " WHERE board_id = ?", (int(board_id),)).fetchone()
    return int(r[0])


def ops_since(con, board_id: int, seq: int = 0, limit: int = 2000,
              exclude_actor: str = "") -> list[dict]:
    sql = ("SELECT seq, actor, clock, node_id, fields FROM canvas_op"
           " WHERE board_id = ? AND seq > ?")
    params: list = [int(board_id), int(seq)]
    if exclude_actor:
        sql += " AND actor != ?"
        params.append(exclude_actor)
    sql += " ORDER BY seq LIMIT ?"
    params.append(max(1, min(int(limit), 10000)))
    return [{"seq": r["seq"], "actor": r["actor"], "clock": r["clock"],
             "node": r["node_id"], "fields": _loads(r["fields"], {})}
            for r in con.execute(sql, params)]


def compact(con, board_id: int, keep: int = 5000) -> int:
    """Trim the op log to the newest `keep` entries (node rows already
    hold the folded state; peers further behind re-sync via snapshot)."""
    cut = head(con, board_id) - int(keep)
    if cut <= 0:
        return 0
    cur = con.execute("DELETE FROM canvas_op WHERE board_id = ? AND seq <= ?",
                      (int(board_id), cut))
    con.commit()
    return cur.rowcount


def snapshot(con, board_id: int) -> dict:
    """Full state for a joining peer: board + live nodes + head seq."""
    b = _require_board(con, board_id)
    return {"board": b, "nodes": nodes(con, board_id), "head": head(con, board_id)}


# ─────────────────────────────────────────────── local edit helpers
# Each returns (logged_ops, inverse_ops). The bridge keeps the inverses
# on its undo stack; undo = apply_local(inverse) — a NEW edit, so it
# merges correctly with whatever collaborators did in between.
def _inverse(con, board_id: int, ops: list[dict]) -> list[dict]:
    inv = []
    for op in ops:
        cur = get_node(con, board_id, op["node"])
        if cur is None:
            inv.append({"node": op["node"], "fields": {"deleted": 1}})
            continue
        flat = _node_fields(cur)
        back = {}
        for k in op["fields"]:
            if k.startswith("p."):
                back[k] = flat.get(k)               # None = remove prop
            else:
                back[k] = flat.get(k, 0 if k in _NUMERIC else "")
        inv.append({"node": op["node"], "fields": back})
    return inv


def edit(con, board_id: int, ops: list[dict],
         actor: str | None = None) -> tuple[list[dict], list[dict]]:
    """Generic undoable local edit."""
    inv = _inverse(con, board_id, ops)
    return apply_local(con, board_id, ops, actor), inv


def _top_z(con, board_id: int) -> float:
    r = con.execute("SELECT COALESCE(MAX(z), 0) FROM canvas_node"
                    " WHERE board_id = ? AND deleted = 0",
                    (int(board_id),)).fetchone()
    return float(r[0]) + 1.0


def create_node(con, board_id: int, ntype: str, x: float = 0, y: float = 0,
                w: float | None = None, h: float | None = None,
                props: dict | None = None, bind: dict | None = None,
                parent: str = "", name: str = "",
                actor: str | None = None) -> tuple[str, list, list]:
    if ntype not in NODE_TYPES:
        raise CanvasError(f"unknown node type {ntype!r}")
    dw, dh = DEFAULT_SIZE.get(ntype, (100, 100))
    nid = new_id()
    p = dict(DEFAULT_PROPS.get(ntype, {}))
    p.update(props or {})
    fields = {"type": ntype, "x": x, "y": y,
              "w": dw if w is None else w, "h": dh if h is None else h,
              "z": _top_z(con, board_id), "parent": parent,
              "name": name or ntype.capitalize(), "deleted": 0}
    if bind:
        fields["bind"] = bind
    for k, v in p.items():
        fields["p." + k] = v
    logged, inv = edit(con, board_id, [{"node": nid, "fields": fields}],
                       actor)
    return nid, logged, inv


def update_node(con, board_id: int, node_id: str, fields: dict,
                actor: str | None = None) -> tuple[list, list]:
    if get_node(con, board_id, node_id) is None:
        raise CanvasError(f"no node {node_id!r}")
    return edit(con, board_id, [{"node": node_id, "fields": dict(fields)}],
                actor)


def set_props(con, board_id: int, node_id: str, props: dict,
              actor: str | None = None) -> tuple[list, list]:
    return update_node(con, board_id, node_id,
                       {"p." + k: v for k, v in (props or {}).items()},
                       actor)


def descendants(con, board_id: int, ids: Iterable[str]) -> list[str]:
    """ids plus every node parented (transitively) under them."""
    allnodes = nodes(con, board_id)
    kids: dict[str, list[str]] = {}
    for n in allnodes:
        if n["parent"]:
            kids.setdefault(n["parent"], []).append(n["id"])
    out, stack, seen = [], list(ids), set()
    while stack:
        i = stack.pop()
        if i in seen:
            continue
        seen.add(i)
        out.append(i)
        stack.extend(kids.get(i, []))
    return out


def move_nodes(con, board_id: int, ids: Iterable[str], dx: float, dy: float,
               actor: str | None = None) -> tuple[list, list]:
    """Translate nodes (children of moved containers follow)."""
    ops = []
    for nid in descendants(con, board_id, ids):
        n = get_node(con, board_id, nid)
        if n is None or n["deleted"] or n["locked"]:
            continue
        ops.append({"node": nid, "fields": {"x": n["x"] + float(dx),
                                            "y": n["y"] + float(dy)}})
    if not ops:
        return [], []
    return edit(con, board_id, ops, actor)


def delete_nodes(con, board_id: int, ids: Iterable[str],
                 actor: str | None = None) -> tuple[list, list]:
    all_ids = descendants(con, board_id, ids)
    # connectors attached to anything deleted go too
    for n in nodes(con, board_id):
        if n["type"] == "connector" and (n["props"].get("from") in all_ids
                                         or n["props"].get("to") in all_ids):
            all_ids.append(n["id"])
    ops = [{"node": i, "fields": {"deleted": 1}} for i in dict.fromkeys(all_ids)
           if get_node(con, board_id, i) is not None]
    if not ops:
        return [], []
    return edit(con, board_id, ops, actor)


def duplicate_nodes(con, board_id: int, ids: Iterable[str],
                    offset: float = 24.0,
                    actor: str | None = None) -> tuple[list[str], list, list]:
    """Copy nodes (+descendants) with fresh ids; returns new top ids."""
    ids = list(ids)
    src = descendants(con, board_id, ids)
    idmap = {i: new_id() for i in src}
    z = _top_z(con, board_id)
    ops = []
    for i in src:
        n = get_node(con, board_id, i)
        if n is None or n["deleted"]:
            continue
        f = _node_fields(n)
        f.pop("deleted", None)
        f["x"] = n["x"] + offset
        f["y"] = n["y"] + offset
        f["z"] = z
        z += 1
        f["parent"] = idmap.get(n["parent"], n["parent"])
        if n["type"] == "connector":
            f["p.from"] = idmap.get(f.get("p.from", ""), f.get("p.from", ""))
            f["p.to"] = idmap.get(f.get("p.to", ""), f.get("p.to", ""))
        f["deleted"] = 0
        ops.append({"node": idmap[i], "fields": f})
    if not ops:
        return [], [], []
    logged, inv = edit(con, board_id, ops, actor)
    return [idmap[i] for i in ids if i in idmap], logged, inv


def restack(con, board_id: int, ids: Iterable[str], where: str,
            actor: str | None = None) -> tuple[list, list]:
    """where: front | back | forward | backward."""
    ids = [i for i in ids if get_node(con, board_id, i) is not None]
    if not ids:
        return [], []
    zs = sorted(n["z"] for n in nodes(con, board_id))
    if not zs:
        return [], []
    ops = []
    if where == "front":
        top = zs[-1]
        for k, i in enumerate(ids, 1):
            ops.append({"node": i, "fields": {"z": top + k}})
    elif where == "back":
        bot = zs[0]
        for k, i in enumerate(reversed(ids), 1):
            ops.append({"node": i, "fields": {"z": bot - k}})
    elif where in ("forward", "backward"):
        sign = 1 if where == "forward" else -1
        for i in ids:
            z = get_node(con, board_id, i)["z"]
            others = [v for v in zs if (v > z if sign > 0 else v < z)]
            if not others:
                continue
            nxt = others[0] if sign > 0 else others[-1]
            # step past the neighbour without renumbering anyone
            after = [v for v in zs if (v > nxt if sign > 0 else v < nxt)]
            far = (after[0] if sign > 0 else after[-1]) if after \
                else nxt + sign
            ops.append({"node": i, "fields": {"z": (nxt + far) / 2.0}})
    else:
        raise CanvasError("where must be front/back/forward/backward")
    if not ops:
        return [], []
    return edit(con, board_id, ops, actor)


def group_nodes(con, board_id: int, ids: Iterable[str], name: str = "Group",
                frame: bool = False,
                actor: str | None = None) -> tuple[str, list, list]:
    """Wrap nodes in a group (or frame) sized to their bounds."""
    sel = [get_node(con, board_id, i) for i in ids]
    sel = [n for n in sel if n is not None and not n["deleted"]]
    if not sel:
        raise CanvasError("nothing to group")
    x0, y0, x1, y1 = bounds(sel)
    pad = 24.0 if frame else 0.0
    gid, logged, inv = create_node(
        con, board_id, "frame" if frame else "group", x0 - pad, y0 - pad,
        (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad, name=name,
        parent=sel[0]["parent"], actor=actor)
    # the container sits under its members
    zmin = min(n["z"] for n in sel)
    ops = [{"node": gid, "fields": {"z": zmin - 0.5}}]
    ops += [{"node": n["id"], "fields": {"parent": gid}} for n in sel]
    lg2, inv2 = edit(con, board_id, ops, actor)
    return gid, logged + lg2, inv2 + inv


def ungroup(con, board_id: int, group_id: str,
            actor: str | None = None) -> tuple[list, list]:
    g = get_node(con, board_id, group_id)
    if g is None or g["type"] not in CONTAINER_TYPES:
        raise CanvasError("not a group or frame")
    kids = [n for n in nodes(con, board_id) if n["parent"] == group_id]
    ops = [{"node": n["id"], "fields": {"parent": g["parent"]}} for n in kids]
    ops.append({"node": group_id, "fields": {"deleted": 1}})
    return edit(con, board_id, ops, actor)


def bounds(ns: Iterable[dict]) -> tuple[float, float, float, float]:
    ns = list(ns)
    if not ns:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(n["x"] for n in ns), min(n["y"] for n in ns),
            max(n["x"] + n["w"] for n in ns),
            max(n["y"] + n["h"] for n in ns))


def align(con, board_id: int, ids: Iterable[str], how: str,
          actor: str | None = None) -> tuple[list, list]:
    """how: left | hcenter | right | top | vcenter | bottom |
    hdist | vdist (distribute evenly)."""
    sel = [n for n in (get_node(con, board_id, i) for i in ids)
           if n is not None and not n["deleted"] and not n["locked"]]
    if len(sel) < 2:
        return [], []
    x0, y0, x1, y1 = bounds(sel)
    ops = []
    if how in ("hdist", "vdist"):
        axis, size = ("x", "w") if how == "hdist" else ("y", "h")
        sel.sort(key=lambda n: n[axis])
        total = sum(n[size] for n in sel)
        span = (x1 - x0) if how == "hdist" else (y1 - y0)
        gap = (span - total) / (len(sel) - 1)
        pos = sel[0][axis]
        for n in sel:
            ops.append({"node": n["id"], "fields": {axis: pos}})
            pos += n[size] + gap
    else:
        for n in sel:
            f = {
                "left": {"x": x0}, "right": {"x": x1 - n["w"]},
                "hcenter": {"x": (x0 + x1) / 2 - n["w"] / 2},
                "top": {"y": y0}, "bottom": {"y": y1 - n["h"]},
                "vcenter": {"y": (y0 + y1) / 2 - n["h"] / 2},
            }.get(how)
            if f is None:
                raise CanvasError(f"unknown alignment {how!r}")
            ops.append({"node": n["id"], "fields": f})
    return edit(con, board_id, ops, actor)


# ───────────────────────────────────────────────── library integration
def _asset_cols(con) -> set[str]:
    return {r[1] for r in con.execute("PRAGMA table_info(asset)")}


def binding_for(con, kind: str, item_id: int) -> dict | None:
    """Locator for a tracked object, or None when it doesn't exist."""
    kind = str(kind)
    if kind == "collection":
        r = con.execute("SELECT id, guid, slug, name FROM collection"
                        " WHERE id = ?", (int(item_id),)).fetchone()
    elif kind == "palette":
        r = con.execute("SELECT id, guid, slug, name FROM palette"
                        " WHERE id = ?", (int(item_id),)).fetchone()
    elif kind == "snippet":
        r = con.execute("SELECT id, guid, slug, title AS name FROM snippet"
                        " WHERE id = ?", (int(item_id),)).fetchone()
    else:
        r = con.execute("SELECT id, guid, slug, name FROM asset"
                        " WHERE id = ? AND kind = ?",
                        (int(item_id), kind)).fetchone()
    if r is None:
        return None
    return {"kind": kind, "id": int(r["id"]), "guid": r["guid"] or "",
            "slug": r["slug"] or "", "name": r["name"] or ""}


def binding_for_ref(con, ref: str) -> dict | None:
    """Bind via any [[ ref ]] form the rest of Fengrid understands."""
    hit = assetrefs.resolve(con, (ref or "").strip().strip("[] "))
    if hit is None:
        return None
    b = binding_for(con, hit["kind"], int(hit["id"]))
    if b is not None:
        b["ref"] = (ref or "").strip()
    return b


def _rebind(con, bind: dict) -> dict | None:
    """Current row for a stored binding: GUID first (survives rescans
    that renumber ids), then kind+id."""
    if not bind:
        return None
    guid = bind.get("guid") or ""
    if guid:
        hit = core_db.lookup_by_guid(con, guid)
        if hit:
            return binding_for(con, hit["kind"], int(hit["id"]))
    if bind.get("kind") and bind.get("id"):
        return binding_for(con, bind["kind"], int(bind["id"]))
    return None


def hydrate(con, bind: dict) -> dict:
    """Everything a renderer needs for a bound node. Always returns a
    dict; ``ok`` False means the binding is broken (render a visible
    placeholder, never drop the node)."""
    cur = _rebind(con, bind)
    if cur is None:
        return {"ok": False, "kind": (bind or {}).get("kind", ""),
                "name": (bind or {}).get("name", "") or "missing"}
    out = dict(cur, ok=True)
    kind = cur["kind"]
    if kind == "palette":
        out["hexes"] = [r[0] for r in con.execute(
            "SELECT hex FROM palette_color WHERE palette_id = ?"
            " ORDER BY position", (cur["id"],))]
    elif kind == "snippet":
        r = con.execute("SELECT title, language, html, css, js FROM snippet"
                        " WHERE id = ?", (cur["id"],)).fetchone()
        if r:
            out.update(title=r["title"], language=r["language"],
                       html=r["html"], css=r["css"], js=r["js"])
    elif kind == "collection":
        out["members"] = [dict(r) for r in con.execute(
            "SELECT item_kind, item_id FROM collection_ref"
            " WHERE collection_id = ? ORDER BY id", (cur["id"],))]
    else:
        cols = _asset_cols(con)
        want = ["path", "ext", "width", "height"]
        if "family" in cols:
            want.append("family")
        r = con.execute(f"SELECT {', '.join(want)} FROM asset WHERE id = ?",
                        (cur["id"],)).fetchone()
        if r:
            out.update({k: r[k] for k in want})
    return out


def _place_size(con, kind: str, item_id: int) -> tuple[float, float]:
    ntype = KIND_NODE.get(kind, "asset")
    w, h = DEFAULT_SIZE[ntype]
    if kind == "image":
        r = con.execute("SELECT width, height FROM asset WHERE id = ?",
                        (int(item_id),)).fetchone()
        if r and r["width"] and r["height"]:
            s = min(1.0, 320.0 / max(r["width"], r["height"]))
            w, h = r["width"] * s, r["height"] * s
    elif kind == "palette":
        n = con.execute("SELECT COUNT(*) FROM palette_color WHERE palette_id"
                        " = ?", (int(item_id),)).fetchone()[0]
        w = max(1, n) * 48.0
    return float(w), float(h)


def place_asset(con, board_id: int, kind: str, item_id: int,
                x: float = 0, y: float = 0, parent: str = "",
                actor: str | None = None) -> tuple[str, list, list]:
    """Drop a library object onto the board as a bound node."""
    bind = binding_for(con, kind, item_id)
    if bind is None:
        raise CanvasError(f"no {kind} #{item_id}")
    ntype = KIND_NODE.get(kind, "asset")
    w, h = _place_size(con, kind, item_id)
    props = {}
    if ntype == "font":
        fam = hydrate(con, bind).get("family") or bind["name"]
        props["fontFamily"] = fam
    return create_node(con, board_id, ntype, x, y, w, h, props=props,
                       bind=bind, parent=parent, name=bind["name"],
                       actor=actor)


def place_ref(con, board_id: int, ref: str, x: float = 0, y: float = 0,
              actor: str | None = None) -> tuple[str, list, list]:
    b = binding_for_ref(con, ref)
    if b is None:
        raise CanvasError(f"unresolved reference [[ {ref} ]]")
    if b["kind"] == "collection":
        return place_collection(con, board_id, b["id"], x, y, actor=actor)
    return place_asset(con, board_id, b["kind"], b["id"], x, y, actor=actor)


def _layout_members(con, board_id: int, members: list[tuple[str, int]],
                    x: float, y: float, parent: str, cols: int, gap: float,
                    actor: str | None) -> tuple[list, list, float, float]:
    logged, inv = [], []
    cx, cy, row_h, max_w = x, y, 0.0, 0.0
    for k, (kind, iid) in enumerate(members):
        if k and k % cols == 0:
            cx, cy = x, cy + row_h + gap
            row_h = 0.0
        try:
            nid, lg, iv = place_asset(con, board_id, kind, iid, cx, cy,
                                      parent=parent, actor=actor)
        except CanvasError:
            continue                     # dangling ref — skip it
        n = get_node(con, board_id, nid)
        logged += lg
        inv += iv
        cx += n["w"] + gap
        row_h = max(row_h, n["h"])
        max_w = max(max_w, cx - x - gap)
    return logged, inv, max_w, (cy + row_h - y) if members else 0.0


def place_members(con, board_id: int, title: str,
                  members: list[tuple[str, int]], x: float = 0,
                  y: float = 0, cols: int = 6, gap: float = 16.0,
                  bind: dict | None = None,
                  actor: str | None = None) -> tuple[str, list, list]:
    """A titled container of bound nodes, laid out on a grid."""
    cols = max(1, min(int(cols), 24))
    members = members[:500]
    pad, head_h = 24.0, 32.0
    fid, logged, inv = create_node(
        con, board_id, "collection", x, y, 10, 10, name=title,
        bind=bind, props={"title": title}, actor=actor)
    lg, iv, w, h = _layout_members(con, board_id, members, x + pad,
                                   y + pad + head_h, fid, cols, gap, actor)
    lg2, iv2 = edit(con, board_id, [{"node": fid, "fields": {
        "w": max(240.0, w + 2 * pad), "h": max(120.0, h + 2 * pad + head_h)}}],
        actor)
    return fid, logged + lg + lg2, iv2 + iv + inv


def place_collection(con, board_id: int, collection_id: int, x: float = 0,
                     y: float = 0, cols: int = 6,
                     actor: str | None = None) -> tuple[str, list, list]:
    bind = binding_for(con, "collection", collection_id)
    if bind is None:
        raise CanvasError(f"no collection #{collection_id}")
    members = [(r["item_kind"], int(r["item_id"])) for r in con.execute(
        "SELECT item_kind, item_id FROM collection_ref"
        " WHERE collection_id = ? ORDER BY id", (int(collection_id),))]
    return place_members(con, board_id, bind["name"], members, x, y, cols,
                         bind=bind, actor=actor)


def place_smart_collection(con, board_id: int, smart_id: int,
                           x: float = 0, y: float = 0, cols: int = 6,
                           actor: str | None = None) -> tuple[str, list, list]:
    """Snapshot a smart collection's CURRENT matches as a frame (smart
    criteria are live; the board records what was true when placed)."""
    from . import taxonomy
    r = con.execute("SELECT name, item_kind, criteria FROM smart_collection"
                    " WHERE id = ?", (int(smart_id),)).fetchone()
    if r is None:
        raise CanvasError(f"no smart collection #{smart_id}")
    kind = r["item_kind"] or "icon"
    ids = taxonomy.smart_asset_ids(con, kind, _loads(r["criteria"], {}))
    return place_members(con, board_id, r["name"],
                         [(kind, int(i)) for i in ids], x, y, cols,
                         actor=actor)


def place_library_view(con, board_id: int, view_id: int, x: float = 0,
                       y: float = 0, cols: int = 6,
                       actor: str | None = None) -> tuple[str, list, list]:
    from . import taxonomy
    r = con.execute("SELECT name FROM library_view WHERE id = ?",
                    (int(view_id),)).fetchone()
    if r is None:
        raise CanvasError(f"no library #{view_id}")
    ids = taxonomy.library_view_assets(con, int(view_id))
    members = []
    for i in ids:
        k = con.execute("SELECT kind FROM asset WHERE id = ?",
                        (int(i),)).fetchone()
        if k:
            members.append((k["kind"], int(i)))
    return place_members(con, board_id, r["name"], members, x, y, cols,
                         actor=actor)


def explode_palette(con, board_id: int, palette_id: int, x: float = 0,
                    y: float = 0,
                    actor: str | None = None) -> tuple[list[str], list, list]:
    """One swatch rect per palette color (editable shapes)."""
    hexes = [r[0] for r in con.execute(
        "SELECT hex FROM palette_color WHERE palette_id = ? ORDER BY"
        " position", (int(palette_id),))]
    ids, logged, inv = [], [], []
    for k, hx in enumerate(hexes):
        nid, lg, iv = create_node(con, board_id, "rect", x + k * 72, y, 64,
                                  64, props={"fill": hx, "radius": 8},
                                  name=hx, actor=actor)
        ids.append(nid)
        logged += lg
        inv += iv
    return ids, logged, inv


def usage(con, kind: str, item_id: int) -> list[dict]:
    """Boards (and node counts) that use a tracked object."""
    b = binding_for(con, kind, item_id)
    guid = (b or {}).get("guid") or ""
    rows = con.execute(
        "SELECT n.board_id, b.name, b.project_id, COUNT(*) AS uses"
        " FROM canvas_node n JOIN canvas_board b ON b.id = n.board_id"
        " WHERE n.deleted = 0 AND ((n.bind_kind = ? AND n.bind_id = ?)"
        "   OR (n.bind_guid != '' AND n.bind_guid = ?))"
        " GROUP BY n.board_id ORDER BY b.name",
        (kind, int(item_id), guid)).fetchall()
    return [dict(r) for r in rows]


def sync_links(con, board_id: int) -> int:
    """Mirror bound usage into asset_link (project → asset, role
    'canvas') so the Properties panel's Links section shows it.
    Returns the number of links now recorded for the project."""
    from . import taxonomy
    b = _require_board(con, board_id)
    pid = int(b["project_id"])
    used: set[tuple[str, int]] = set()
    for r in con.execute(
            "SELECT DISTINCT n.bind_kind, n.bind_id FROM canvas_node n"
            " JOIN canvas_board bb ON bb.id = n.board_id"
            " WHERE bb.project_id = ? AND n.deleted = 0 AND n.bind_id > 0",
            (pid,)):
        if r["bind_kind"] in taxonomy.LINK_KINDS:
            used.add((r["bind_kind"], int(r["bind_id"])))
    have = {(r["to_kind"], int(r["to_id"])): r["id"] for r in con.execute(
        "SELECT id, to_kind, to_id FROM asset_link WHERE from_kind ="
        " 'project' AND from_id = ? AND role = 'canvas'", (pid,))}
    for key in used - set(have):
        taxonomy.add_link(con, "project", pid, key[0], key[1], "canvas")
    for key in set(have) - used:
        taxonomy.remove_link(con, have[key])
    return len(used)


# ─────────────────────────────────────────────────────── code ↔ snippets
def code_to_snippet(con, board_id: int, node_id: str, title: str = "",
                    actor: str | None = None) -> tuple[int, list, list]:
    """Promote a code cell to a Code-pane snippet; the node turns into a
    snippet node bound to it (edits in the Code pane flow back)."""
    from . import snippets as core_snippets
    n = get_node(con, board_id, node_id)
    if n is None or n["type"] != "code":
        raise CanvasError("not a code cell")
    p = n["props"]
    sid = core_snippets.create_snippet(
        con, (title or n["name"] or "Canvas snippet").strip(),
        "From canvas board", p.get("lang") or "web", p.get("html", ""),
        p.get("css", ""), p.get("js", ""), "canvas")
    bind = binding_for(con, "snippet", int(sid))
    logged, inv = update_node(con, board_id, node_id,
                              {"type": "snippet", "bind": bind}, actor)
    return int(sid), logged, inv


# ────────────────────────────────────────────────────────────── comments
def add_comment(con, board_id: int, body: str, node_id: str = "",
                x: float = 0, y: float = 0, author: str = "") -> int:
    _require_board(con, board_id)
    body = (body or "").strip()
    if not body:
        raise CanvasError("empty comment")
    cur = con.execute(
        "INSERT INTO canvas_comment(board_id, node_id, x, y, author, body,"
        " created) VALUES (?,?,?,?,?,?,?)",
        (int(board_id), node_id or "", float(x), float(y),
         author or local_actor(con), body[:8000], _now()))
    con.commit()
    return int(cur.lastrowid)


def comments(con, board_id: int, include_resolved: bool = False) -> list[dict]:
    sql = "SELECT * FROM canvas_comment WHERE board_id = ?"
    if not include_resolved:
        sql += " AND resolved = 0"
    return [dict(r) for r in con.execute(sql + " ORDER BY created",
                                         (int(board_id),))]


def resolve_comment(con, comment_id: int, resolved: bool = True) -> None:
    con.execute("UPDATE canvas_comment SET resolved = ? WHERE id = ?",
                (1 if resolved else 0, int(comment_id)))
    con.commit()


# ────────────────────────────────────────────────────────────── presence
PRESENCE_TTL = 30.0


def touch_presence(con, board_id: int, actor: str, name: str = "",
                   color: str = "", cursor: tuple | None = None,
                   selection: list | None = None) -> None:
    cx, cy = (cursor or (None, None))[:2]
    con.execute(
        "INSERT INTO canvas_presence(board_id, actor, name, color,"
        " cursor_x, cursor_y, selection, seen) VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(board_id, actor) DO UPDATE SET name=excluded.name,"
        " color=excluded.color, cursor_x=excluded.cursor_x,"
        " cursor_y=excluded.cursor_y, selection=excluded.selection,"
        " seen=excluded.seen",
        (int(board_id), str(actor)[:64], str(name)[:80], str(color)[:16],
         cx, cy, json.dumps(list(selection or [])[:200]), _now()))
    con.commit()


def presence(con, board_id: int, exclude_actor: str = "") -> list[dict]:
    rows = con.execute(
        "SELECT actor, name, color, cursor_x, cursor_y, selection, seen"
        " FROM canvas_presence WHERE board_id = ? AND seen > ?"
        " AND actor != ? ORDER BY name",
        (int(board_id), _now() - PRESENCE_TTL, exclude_actor)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["selection"] = _loads(d["selection"], [])
        out.append(d)
    return out


# ──────────────────────────────────────────────────────────────── export
def _e(s: Any) -> str:
    return _html.escape(str(s), quote=True)


_CSS_COLOR_OK = set("#0123456789abcdefABCDEF(),.% rgbahsltransparent")


def _color(v: Any, fallback: str = "transparent") -> str:
    s = str(v or "").strip()
    if not s or len(s) > 40 or any(c not in _CSS_COLOR_OK for c in s):
        return fallback
    return s


def _num(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def _asset_href(info: dict, assets) -> str:
    """href for a file-backed binding. `assets` is either a dict that
    collects path→filename for export_bundle to copy (relative href), a
    callable path→url (live preview: fengrid-asset:// via assetrefs), or
    None (no file access: caller renders a placeholder)."""
    path = info.get("path") or ""
    if not path or assets is None:
        return ""
    if callable(assets):
        return str(assets(path) or "")
    if path not in assets:
        base = os.path.basename(path)
        stem, ext = os.path.splitext(base)
        name = base
        k = 1
        while name in assets.values():
            name = f"{stem}-{k}{ext}"
            k += 1
        assets[path] = name
    return "assets/" + assets[path]


def render_html(con, board_id: int, frame_id: str = "",
                assets=None) -> str:
    """Standalone HTML for a board (or one frame of it). Absolute
    positioning mirrors the canvas 1:1; bound nodes render from the
    library at export time. `assets` collects path→filename for the
    caller to copy (export_bundle); without it, file-backed bindings
    render as labelled placeholders (safe for any viewer)."""
    allnodes = [n for n in nodes(con, board_id) if not n["hidden"]]
    if frame_id:
        keep = set(descendants(con, board_id, [frame_id]))
        allnodes = [n for n in allnodes if n["id"] in keep]
    if not allnodes:
        x0 = y0 = 0.0
        x1, y1 = 800.0, 600.0
    else:
        x0, y0, x1, y1 = bounds(allnodes)
    css: list[str] = []
    body: list[str] = []
    for n in allnodes:
        body.append(_node_html(con, n, x0, y0, assets, css))
    b = _require_board(con, board_id)
    title = _e(b["name"])
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{title}</title>\n<meta name=\"generator\" "
        "content=\"Fengrid canvas\">\n<style>\n"
        "*{box-sizing:border-box}body{margin:0;background:#F7F8F9;"
        "font-family:system-ui,sans-serif}\n"
        f".fg-board{{position:relative;width:{x1 - x0:.0f}px;"
        f"height:{y1 - y0:.0f}px}}\n"
        ".fg-n{position:absolute;overflow:hidden}\n"
        ".fg-missing{outline:1px dashed #C44A1E;color:#C44A1E;"
        "font:12px monospace;display:flex;align-items:center;"
        "justify-content:center}\n"
        + "\n".join(css) +
        "\n</style></head>\n<body><div class=\"fg-board\">\n"
        + "\n".join(body) + "\n</div></body></html>\n")


def _node_html(con, n: dict, ox: float, oy: float, assets,
               css: list[str]) -> str:
    p = n["props"]
    box = (f"left:{n['x'] - ox:.1f}px;top:{n['y'] - oy:.1f}px;"
           f"width:{n['w']:.1f}px;height:{n['h']:.1f}px;"
           f"z-index:{int(n['z'] * 10) % 100000};")
    if n["rot"]:
        box += f"transform:rotate({_num(n['rot']):.2f}deg);"
    if "opacity" in p:
        box += f"opacity:{max(0.0, min(1.0, _num(p['opacity'], 1))):.2f};"
    t = n["type"]
    nid = _e(n["id"])
    if t in ("frame", "rect", "collection", "group"):
        if t == "group":
            return f'<div class="fg-n" data-id="{nid}" style="{box}"></div>'
        box += (f"background:{_color(p.get('fill'))};"
                f"border-radius:{_num(p.get('radius')):.0f}px;")
        if _num(p.get("strokeWidth")) > 0:
            box += (f"border:{_num(p.get('strokeWidth')):.0f}px solid "
                    f"{_color(p.get('stroke'), '#000')};")
        title = ""
        if t == "collection":
            title = (f'<div style="padding:12px 16px;font:600 13px '
                     f'system-ui">{_e(p.get("title") or n["name"])}</div>')
        return f'<div class="fg-n" data-id="{nid}" style="{box}">{title}</div>'
    if t == "ellipse":
        box += f"background:{_color(p.get('fill'))};border-radius:50%;"
        return f'<div class="fg-n" data-id="{nid}" style="{box}"></div>'
    if t == "line":
        box += (f"height:0;border-top:{_num(p.get('strokeWidth'), 1):.0f}px "
                f"solid {_color(p.get('stroke'), '#000')};overflow:visible;")
        return f'<div class="fg-n" data-id="{nid}" style="{box}"></div>'
    if t in ("text", "sticky"):
        if t == "sticky":
            box += f"background:{_color(p.get('fill'), '#F5C25C')};padding:12px;"
        align = p.get("align") if p.get("align") in (
            "left", "center", "right") else "left"
        fam = str(p.get("fontFamily") or "").replace("'", "").replace(
            '"', "").replace(";", "")[:80]
        box += (f"color:{_color(p.get('color'), '#16202B')};"
                f"font-size:{_num(p.get('fontSize'), 16):.0f}px;"
                f"font-weight:{int(_num(p.get('fontWeight'), 400))};"
                f"text-align:{align};white-space:pre-wrap;")
        if fam:
            box += f"font-family:'{_e(fam)}',system-ui;"
        return (f'<div class="fg-n" data-id="{nid}" style="{box}">'
                f"{_e(p.get('text', ''))}</div>")
    if t == "code":
        # scoped like snippet previews: an iframe-free inline embed. CSS
        # is scoped under the node id so cells cannot restyle each other.
        scope = f'[data-id="{nid}"]'
        raw_css = str(p.get("css", ""))
        css.append(_scope_css(raw_css, scope))
        return (f'<div class="fg-n" data-id="{nid}" style="{box}">'
                f"{p.get('html', '')}</div>")
    if t == "connector":
        return ""                       # drawn by the SVG export only
    # ---- bound nodes
    info = hydrate(con, n.get("bind") or {})
    if not info.get("ok"):
        return (f'<div class="fg-n fg-missing" data-id="{nid}" '
                f'style="{box}">missing: {_e(info.get("name", ""))}</div>')
    if t in ("icon", "image"):
        href = _asset_href(info, assets)
        if not href:
            return (f'<div class="fg-n fg-missing" data-id="{nid}" '
                    f'style="{box}">{_e(info["name"])}</div>')
        fit = p.get("fit") if p.get("fit") in ("contain", "cover",
                                                "fill") else "contain"
        return (f'<img class="fg-n" data-id="{nid}" style="{box}'
                f'object-fit:{fit}" src="{_e(href)}" alt="{_e(info["name"])}">')
    if t == "font":
        fam = str(info.get("family") or p.get("fontFamily") or "")
        href = _asset_href(info, assets)
        safe = fam.replace("'", "").replace('"', "")[:80]
        if href and safe:
            css.append(f"@font-face{{font-family:'{_e(safe)}';"
                       f"src:url('{_e(href)}')}}")
        box += (f"font-family:'{_e(safe)}',system-ui;"
                f"font-size:{_num(p.get('fontSize'), 28):.0f}px;"
                f"color:{_color(p.get('color'), '#16202B')};")
        return (f'<div class="fg-n" data-id="{nid}" style="{box}">'
                f"{_e(p.get('text') or safe)}</div>")
    if t == "palette":
        cells = "".join(
            f'<span title="{_e(h)}" style="flex:1;background:'
            f'{_color(h)}"></span>' for h in info.get("hexes", []))
        return (f'<div class="fg-n" data-id="{nid}" style="{box}'
                f'display:flex;border-radius:6px">{cells}</div>')
    if t == "snippet":
        scope = f'[data-id="{nid}"]'
        css.append(_scope_css(info.get("css", ""), scope))
        return (f'<div class="fg-n" data-id="{nid}" style="{box}">'
                f"{info.get('html', '')}</div>")
    # generic asset card
    href = _asset_href(info, assets)
    label = _e(info.get("name", ""))
    inner = f'<a href="{_e(href)}">{label}</a>' if href else label
    return (f'<div class="fg-n" data-id="{nid}" style="{box}'
            f'padding:10px;border:1px solid #D5DCE0;border-radius:6px;'
            f'background:#fff;font:12px system-ui">{inner}</div>')


def _scope_css(raw: str, scope: str) -> str:
    """Prefix every top-level selector with `scope` (best effort; @rules
    pass through). Keeps one cell's CSS from leaking board-wide."""
    out, depth, buf = [], 0, ""
    raw = (raw or "").replace("</", "<\\/")
    for ch in raw:
        if ch == "{":
            if depth == 0 and not buf.strip().startswith("@"):
                sels = ",".join(f"{scope} {s.strip()}"
                                for s in buf.split(",") if s.strip())
                out.append(sels + "{")
            else:
                out.append(buf + "{")
            buf = ""
            depth += 1
        elif ch == "}":
            out.append(buf + "}")
            buf = ""
            depth = max(0, depth - 1)
        else:
            buf += ch
    out.append(buf)
    return "".join(out)


def render_svg(con, board_id: int) -> str:
    """Vector export of the drawable layer (shapes, text, connectors,
    swatches). Bound raster/font nodes become labelled outlines."""
    ns = [n for n in nodes(con, board_id) if not n["hidden"]]
    x0, y0, x1, y1 = bounds(ns) if ns else (0.0, 0.0, 800.0, 600.0)
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    byid = {n["id"]: n for n in ns}
    parts = []
    for n in ns:
        p = n["props"]
        x, y = n["x"] - x0, n["y"] - y0
        rot = (f' transform="rotate({_num(n["rot"]):.2f} '
               f'{x + n["w"] / 2:.1f} {y + n["h"] / 2:.1f})"'
               if n["rot"] else "")
        stroke = ""
        if _num(p.get("strokeWidth")) > 0:
            stroke = (f' stroke="{_e(_color(p.get("stroke"), "#000"))}"'
                      f' stroke-width="{_num(p.get("strokeWidth")):.1f}"')
        t = n["type"]
        if t in ("frame", "rect", "collection", "sticky"):
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{n["w"]:.1f}" '
                f'height="{n["h"]:.1f}" rx="{_num(p.get("radius")):.1f}" '
                f'fill="{_e(_color(p.get("fill"), "none"))}"{stroke}{rot}/>')
            if t == "sticky" and p.get("text"):
                parts.append(_svg_text(x + 12, y + 24, p, rot))
        elif t == "ellipse":
            parts.append(
                f'<ellipse cx="{x + n["w"] / 2:.1f}" cy="{y + n["h"] / 2:.1f}"'
                f' rx="{n["w"] / 2:.1f}" ry="{n["h"] / 2:.1f}" '
                f'fill="{_e(_color(p.get("fill"), "none"))}"{stroke}{rot}/>')
        elif t == "line":
            parts.append(
                f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x + n["w"]:.1f}" '
                f'y2="{y + n["h"]:.1f}" stroke="'
                f'{_e(_color(p.get("stroke"), "#000"))}" stroke-width="'
                f'{_num(p.get("strokeWidth"), 1):.1f}"{rot}/>')
        elif t == "text":
            parts.append(_svg_text(x, y + _num(p.get("fontSize"), 16), p, rot))
        elif t == "connector":
            a, b = byid.get(p.get("from", "")), byid.get(p.get("to", ""))
            if a and b:
                ax, ay = a["x"] + a["w"] / 2 - x0, a["y"] + a["h"] / 2 - y0
                bx, by = b["x"] + b["w"] / 2 - x0, b["y"] + b["h"] / 2 - y0
                parts.append(
                    f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" '
                    f'y2="{by:.1f}" stroke="'
                    f'{_e(_color(p.get("stroke"), "#6E7B86"))}" '
                    f'stroke-width="{_num(p.get("strokeWidth"), 2):.1f}"'
                    + (' marker-end="url(#fg-arrow)"' if p.get("arrow") else "")
                    + "/>")
        elif t == "palette":
            info = hydrate(con, n.get("bind") or {})
            hexes = info.get("hexes") or []
            cw = n["w"] / max(1, len(hexes))
            for k, hx in enumerate(hexes):
                parts.append(f'<rect x="{x + k * cw:.1f}" y="{y:.1f}" '
                             f'width="{cw:.1f}" height="{n["h"]:.1f}" '
                             f'fill="{_e(_color(hx))}"/>')
        elif t in BOUND_TYPES or t == "code":
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{n["w"]:.1f}" '
                f'height="{n["h"]:.1f}" fill="none" stroke="#9AA6B0" '
                f'stroke-dasharray="4 3"{rot}/>')
            parts.append(f'<text x="{x + 6:.1f}" y="{y + 16:.1f}" '
                         f'font-family="monospace" font-size="11" '
                         f'fill="#5A6977">{_e(n["name"])}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" '
            f'height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}">'
            '<defs><marker id="fg-arrow" viewBox="0 0 10 10" refX="9" '
            'refY="5" markerWidth="6" markerHeight="6" orient="auto">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#6E7B86"/></marker></defs>'
            + "".join(parts) + "</svg>\n")


def _svg_text(x: float, y: float, p: dict, rot: str) -> str:
    fam = str(p.get("fontFamily") or "system-ui")[:80]
    lines = str(p.get("text", "")).split("\n")
    size = _num(p.get("fontSize"), 16)
    spans = "".join(
        f'<tspan x="{x:.1f}" dy="{0 if k == 0 else size * 1.25:.1f}">'
        f"{_e(line)}</tspan>" for k, line in enumerate(lines))
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{_e(fam)}" '
            f'font-size="{size:.0f}" fill="'
            f'{_e(_color(p.get("color"), "#16202B"))}"{rot}>{spans}</text>')


def export_bundle(con, board_id: int, dest_dir: str,
                  frame_id: str = "") -> dict:
    """index.html + board.svg + copied assets/ + board.json snapshot."""
    os.makedirs(dest_dir, exist_ok=True)
    assets: dict[str, str] = {}
    page = render_html(con, board_id, frame_id, assets)
    with open(os.path.join(dest_dir, "index.html"), "w",
              encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(dest_dir, "board.svg"), "w",
              encoding="utf-8") as f:
        f.write(render_svg(con, board_id))
    snap = snapshot(con, board_id)
    with open(os.path.join(dest_dir, "board.json"), "w",
              encoding="utf-8") as f:
        json.dump(snap, f, indent=1, default=str)
    copied, missing = 0, []
    if assets:
        adir = os.path.join(dest_dir, "assets")
        os.makedirs(adir, exist_ok=True)
        for src, name in assets.items():
            try:
                shutil.copyfile(src, os.path.join(adir, name))
                copied += 1
            except OSError:
                missing.append(src)
    return {"dir": dest_dir, "assets": copied, "missing": missing,
            "nodes": len(snap["nodes"])}


def import_snapshot(con, project_id: int, snap: dict,
                    name: str = "") -> int:
    """Create a board from a board.json snapshot (fresh ids; bindings
    re-resolve by GUID against THIS library)."""
    if not isinstance(snap, dict) or not isinstance(snap.get("nodes"), list):
        raise CanvasError("not a board snapshot")
    src_name = (snap.get("board") or {}).get("name") or "Imported board"
    bid = create_board(con, project_id, name or src_name)
    idmap = {str(n.get("id")): new_id() for n in snap["nodes"]
             if isinstance(n, dict)}
    ops = []
    for n in snap["nodes"]:
        if not isinstance(n, dict) or n.get("type") not in NODE_TYPES:
            continue
        f = _node_fields(n)
        f.pop("deleted", None)
        f["parent"] = idmap.get(str(f.get("parent") or ""), "")
        if n.get("type") == "connector":
            f["p.from"] = idmap.get(str(f.get("p.from", "")), "")
            f["p.to"] = idmap.get(str(f.get("p.to", "")), "")
        bind = f.get("bind") or {}
        if bind:
            cur = _rebind(con, bind)
            f["bind"] = cur or bind
        ops.append({"node": idmap[str(n["id"])], "fields": f})
    if ops:
        apply_local(con, bid, ops)
    return bid
