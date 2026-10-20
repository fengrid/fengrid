"""SQLite library store: schema, FTS5 index, and small helpers.

Pure stdlib (sqlite3) — no Qt imports. Collapses the 0.x data plane
(list.txt/list.js, meta.js + meta-state.tsv, per-pane localStorage keys,
per-pane server SQLite) into one database with unified tags and collections
(docs/architecture/0001-qt6-rewrite.md §6).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS source (
    id      INTEGER PRIMARY KEY,
    kind    TEXT NOT NULL,            -- 'system' | 'folder'
    path    TEXT NOT NULL UNIQUE,
    label   TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS asset (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL DEFAULT 'icon',
    path        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,        -- display/copy name (file stem)
    theme       TEXT,
    context     TEXT,
    ext         TEXT,
    size_px     INTEGER,              -- nominal size from the theme layout
    width       INTEGER,              -- true pixel dims (raster only)
    height      INTEGER,
    bytes       INTEGER,
    colorspace  TEXT,
    color_count INTEGER,
    mono        INTEGER,              -- 1 monochrome, 0 color, NULL unknown
    mtime       REAL
);
CREATE INDEX IF NOT EXISTS idx_asset_theme ON asset(theme);
CREATE INDEX IF NOT EXISTS idx_asset_ext   ON asset(ext);
CREATE INDEX IF NOT EXISTS idx_asset_name  ON asset(name);

CREATE TABLE IF NOT EXISTS tag (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS asset_tag (
    asset_id INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (asset_id, tag_id)
);
CREATE TABLE IF NOT EXISTS collection (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    query TEXT
);
CREATE TABLE IF NOT EXISTS collection_item (
    collection_id INTEGER NOT NULL REFERENCES collection(id) ON DELETE CASCADE,
    asset_id      INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
    position      INTEGER,
    PRIMARY KEY (collection_id, asset_id)
);
CREATE TABLE IF NOT EXISTS palette (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    tags    TEXT,
    created REAL,
    updated REAL
);
CREATE TABLE IF NOT EXISTS palette_color (
    palette_id INTEGER NOT NULL REFERENCES palette(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    hex        TEXT NOT NULL,
    locked     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (palette_id, position)
);
CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS scan_state (
    path        TEXT PRIMARY KEY,
    fingerprint TEXT,
    last_seen   REAL
);
CREATE TABLE IF NOT EXISTS snippet (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    language    TEXT NOT NULL DEFAULT 'web',
    html        TEXT NOT NULL DEFAULT '',
    css         TEXT NOT NULL DEFAULT '',
    js          TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    created     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_snippet_updated ON snippet(updated DESC);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    settings    TEXT NOT NULL DEFAULT '{}',
    created     TEXT NOT NULL DEFAULT (datetime('now')),
    updated     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS project_asset (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    asset_kind TEXT NOT NULL,        -- 'icon' | 'font' | 'snippet' | 'palette'
    asset_id   INTEGER NOT NULL,     -- row id in asset / snippet / palette
    label      TEXT NOT NULL DEFAULT '',
    UNIQUE(project_id, asset_kind, asset_id)
);
"""

# External-content FTS5 kept in sync by triggers (the indexer never UPDATEs
# asset rows; it deletes + reinserts, but the update trigger covers the
# general case anyway).
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS asset_fts
    USING fts5(name, path, theme, context, content='asset', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS asset_fts_ai AFTER INSERT ON asset BEGIN
    INSERT INTO asset_fts(rowid, name, path, theme, context)
    VALUES (new.id, new.name, new.path, new.theme, new.context);
END;
CREATE TRIGGER IF NOT EXISTS asset_fts_ad AFTER DELETE ON asset BEGIN
    INSERT INTO asset_fts(asset_fts, rowid, name, path, theme, context)
    VALUES ('delete', old.id, old.name, old.path, old.theme, old.context);
END;
CREATE TRIGGER IF NOT EXISTS asset_fts_au AFTER UPDATE ON asset BEGIN
    INSERT INTO asset_fts(asset_fts, rowid, name, path, theme, context)
    VALUES ('delete', old.id, old.name, old.path, old.theme, old.context);
    INSERT INTO asset_fts(rowid, name, path, theme, context)
    VALUES (new.id, new.name, new.path, new.theme, new.context);
END;
"""


# Column migrations for databases created before the font metadata landed
# (M1 schemas lack these). Each statement is idempotent-by-tolerance: a
# "duplicate column" error means the column already exists. Kept OUT of
# SCHEMA — executescript is all-or-nothing, and one duplicate ALTER would
# abort every connect() on an M1-era database.
_FONT_COLUMNS = (
    "ALTER TABLE asset ADD COLUMN family TEXT",
    "ALTER TABLE asset ADD COLUMN style  TEXT",
    "ALTER TABLE asset ADD COLUMN weight INTEGER",
    "ALTER TABLE asset ADD COLUMN italic INTEGER",
)


def _migrate(con: sqlite3.Connection) -> None:
    for stmt in _FONT_COLUMNS:
        try:
            con.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    con.execute("CREATE INDEX IF NOT EXISTS idx_asset_family ON asset(family)")
    _migrate_collections(con)


def _migrate_collections(con: sqlite3.Connection) -> None:
    """Collections v2: sub-collections (parent_id), collection-level tags,
    and generalized membership (collection_ref covers every asset kind —
    icon, font, snippet, palette). Legacy collection_item rows are copied
    in as 'icon' refs once; the old table stays for downgrade safety."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(collection)")}
    if "parent_id" not in cols:
        con.execute("ALTER TABLE collection ADD COLUMN parent_id INTEGER"
                    " REFERENCES collection(id) ON DELETE CASCADE")
    if "tags" not in cols:
        con.execute("ALTER TABLE collection ADD COLUMN tags TEXT")
    con.execute("""CREATE TABLE IF NOT EXISTS collection_ref (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        collection_id INTEGER NOT NULL REFERENCES collection(id) ON DELETE CASCADE,
        item_kind     TEXT NOT NULL,   -- 'icon' | 'font' | 'snippet' | 'palette'
        item_id       INTEGER NOT NULL,
        label         TEXT NOT NULL DEFAULT '',
        UNIQUE(collection_id, item_kind, item_id)
    )""")
    n = con.execute("SELECT COUNT(*) AS c FROM collection_ref").fetchone()["c"]
    if n == 0:
        con.execute(
            "INSERT OR IGNORE INTO collection_ref"
            " (collection_id, item_kind, item_id, label)"
            " SELECT collection_id, 'icon', asset_id, '' FROM collection_item")
    con.commit()


STARRED_TAG = "starred"
STARRED_COLLECTION = "Starred Assets"


def ensure_defaults(con: sqlite3.Connection) -> None:
    """The 'starred' tag and 'Starred Assets' collection exist from the
    first launch (idempotent — INSERT OR IGNORE on the unique names)."""
    con.execute("INSERT OR IGNORE INTO tag(name) VALUES (?)", (STARRED_TAG,))
    con.execute("INSERT OR IGNORE INTO collection(name) VALUES (?)",
                (STARRED_COLLECTION,))


def _starred_ids(con: sqlite3.Connection) -> tuple[int, int]:
    """(tag_id, collection_id), re-created when a user deleted either —
    starring must always work."""
    tag = con.execute("SELECT id FROM tag WHERE name = ?",
                      (STARRED_TAG,)).fetchone()
    coll = con.execute("SELECT id FROM collection WHERE name = ?",
                       (STARRED_COLLECTION,)).fetchone()
    tid = tag["id"] if tag else con.execute(
        "INSERT INTO tag(name) VALUES (?)", (STARRED_TAG,)).lastrowid
    cid = coll["id"] if coll else con.execute(
        "INSERT INTO collection(name) VALUES (?)",
        (STARRED_COLLECTION,)).lastrowid
    return tid, cid


def set_starred(con: sqlite3.Connection, asset_id: int, starred: bool) -> None:
    """Star/unstar one asset: toggles the 'starred' tag AND membership in
    the 'Starred Assets' collection — one action, two side effects, so the
    tag filter and the collection navigator always agree."""
    tid, cid = _starred_ids(con)
    if starred:
        con.execute("INSERT OR IGNORE INTO asset_tag(asset_id, tag_id)"
                    " VALUES (?, ?)", (asset_id, tid))
        con.execute(
            "INSERT OR IGNORE INTO collection_ref(collection_id, item_kind,"
            " item_id) VALUES (?, 'icon', ?)", (cid, asset_id))
    else:
        con.execute("DELETE FROM asset_tag WHERE asset_id = ? AND tag_id = ?",
                    (asset_id, tid))
        con.execute("DELETE FROM collection_ref WHERE collection_id = ?"
                    " AND item_kind = 'icon' AND item_id = ?", (cid, asset_id))
    con.commit()


COLLECTION_KINDS = ("icon", "font", "snippet", "palette")


def collection_tree(con: sqlite3.Connection) -> list[dict]:
    """Every collection with parent, tags, and per-kind member counts —
    parents before children, ready for a one-level tree render."""
    rows = [dict(r) for r in con.execute(
        "SELECT id, name, parent_id, tags FROM collection"
        " ORDER BY name COLLATE NOCASE")]
    counts: dict[int, dict] = {}
    for r in con.execute(
            "SELECT collection_id, item_kind, COUNT(*) AS n"
            " FROM collection_ref GROUP BY collection_id, item_kind"):
        counts.setdefault(r["collection_id"], {})[r["item_kind"]] = r["n"]
    for c in rows:
        c["tags"] = c["tags"] or ""
        c["counts"] = counts.get(c["id"], {})
        c["total"] = sum(c["counts"].values())
    rows.sort(key=lambda c: (c["parent_id"] or 0, c["name"].lower()))
    return rows


def create_sub_collection(con: sqlite3.Connection, name: str,
                          parent_id: int = 0, tags: str = "") -> int:
    name = (name or "").strip() or "Untitled collection"
    cur = con.execute(
        "INSERT INTO collection(name, parent_id, tags) VALUES (?, ?, ?)",
        (name, int(parent_id) if parent_id else None, tags))
    con.commit()
    return int(cur.lastrowid or 0)


def set_collection_tags(con: sqlite3.Connection, coll_id: int,
                        tags: str) -> None:
    con.execute("UPDATE collection SET tags = ? WHERE id = ?",
                (tags.strip(), coll_id))
    con.commit()


def delete_collection(con: sqlite3.Connection, coll_id: int) -> None:
    # children move up rather than vanishing with their parent
    con.execute("UPDATE collection SET parent_id = NULL WHERE parent_id = ?",
                (coll_id,))
    con.execute("DELETE FROM collection_ref WHERE collection_id = ?",
                (coll_id,))
    con.execute("DELETE FROM collection WHERE id = ?", (coll_id,))
    con.commit()


def add_collection_ref(con: sqlite3.Connection, coll_id: int, kind: str,
                       item_id: int, label: str = "") -> bool:
    """Attach any asset-kind row to a collection. Returns False for an
    unknown kind or a row that does not exist."""
    if kind not in COLLECTION_KINDS:
        return False
    if kind in ("icon", "font"):
        ok = con.execute("SELECT 1 FROM asset WHERE id = ? AND kind = ?",
                         (item_id, kind)).fetchone()
    elif kind == "snippet":
        ok = con.execute("SELECT 1 FROM snippet WHERE id = ?",
                         (item_id,)).fetchone()
    else:
        ok = con.execute("SELECT 1 FROM palette WHERE id = ?",
                         (item_id,)).fetchone()
    if not ok:
        return False
    con.execute(
        "INSERT OR IGNORE INTO collection_ref(collection_id, item_kind,"
        " item_id, label) VALUES (?, ?, ?, ?)", (coll_id, kind, item_id, label))
    con.commit()
    return True


def remove_collection_ref(con: sqlite3.Connection, ref_id: int) -> None:
    con.execute("DELETE FROM collection_ref WHERE id = ?", (ref_id,))
    con.commit()


def refs_for(con: sqlite3.Connection, coll_id: int,
             kind: str | None = None) -> list[dict]:
    sql = ("SELECT id, item_kind, item_id, label FROM collection_ref"
           " WHERE collection_id = ?")
    params: list = [coll_id]
    if kind:
        sql += " AND item_kind = ?"
        params.append(kind)
    sql += " ORDER BY item_kind, id"
    return [dict(r) for r in con.execute(sql, params)]


def is_starred(con: sqlite3.Connection, asset_id: int) -> bool:
    row = con.execute(
        "SELECT 1 FROM asset_tag at JOIN tag t ON t.id = at.tag_id"
        " WHERE at.asset_id = ? AND t.name = ?", (asset_id, STARRED_TAG),
    ).fetchone()
    return row is not None


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (and initialise) the library database. WAL + foreign keys on."""
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    _migrate(con)
    ensure_defaults(con)
    has_fts = True
    try:
        con.executescript(FTS_SCHEMA)
    except sqlite3.OperationalError:
        has_fts = False  # FTS5 unavailable in this build — LIKE fallback
    con.execute(
        "INSERT INTO setting(key, value) VALUES ('has_fts', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (int(has_fts),),
    )
    con.commit()
    return con


def has_fts(con: sqlite3.Connection) -> bool:
    row = con.execute("SELECT value FROM setting WHERE key='has_fts'").fetchone()
    return bool(row and row[0] == "1")


def search(con: sqlite3.Connection, term: str) -> list[int]:
    """Asset ids matching a name search. FTS5 prefix-match when available.

    Returns ids only; the caller composes the rest of the filter (theme,
    context, ext, tag, collection) around them.
    """
    term = (term or "").strip()
    if not term:
        rows = con.execute("SELECT id FROM asset ORDER BY theme, name").fetchall()
        return [r[0] for r in rows]
    if has_fts(con):
        q = " ".join(t + "*" for t in term.split())
        rows = con.execute(
            "SELECT a.id FROM asset_fts f JOIN asset a ON a.id = f.rowid "
            "WHERE asset_fts MATCH ? ORDER BY a.theme, a.name",
            (q,),
        ).fetchall()
    else:
        like = f"%{term}%"
        rows = con.execute(
            "SELECT id FROM asset WHERE name LIKE ? OR path LIKE ? "
            "ORDER BY theme, name",
            (like, like),
        ).fetchall()
    return [r[0] for r in rows]


def get_setting(con: sqlite3.Connection, key: str, default=None):
    row = con.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(con: sqlite3.Connection, key: str, value) -> None:
    con.execute(
        "INSERT INTO setting(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    con.commit()


def tags_for(con: sqlite3.Connection, asset_id: int) -> list[str]:
    rows = con.execute(
        "SELECT t.name FROM tag t JOIN asset_tag at ON at.tag_id = t.id "
        "WHERE at.asset_id = ? ORDER BY t.name",
        (asset_id,),
    ).fetchall()
    return [r[0] for r in rows]


def variants_for(con: sqlite3.Connection, asset_id: int) -> list[dict]:
    """Same-name assets in the same theme at other sizes (size variants)."""
    row = con.execute(
        "SELECT theme, name FROM asset WHERE id = ?", (asset_id,)
    ).fetchone()
    if not row or not row["theme"]:
        return []
    rows = con.execute(
        "SELECT id, path, size_px, ext FROM asset "
        "WHERE theme = ? AND name = ? AND id != ? AND size_px IS NOT NULL "
        "ORDER BY size_px",
        (row["theme"], row["name"], asset_id),
    ).fetchall()
    return [dict(r) for r in rows]
