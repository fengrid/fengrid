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

-- Projects pane revision control: settings snapshots taken from the
-- configurator ("Save revision"), restorable in any order.
CREATE TABLE IF NOT EXISTS project_revision (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    label       TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    settings    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_project_revision
    ON project_revision(project_id, id DESC);

-- Saved libraries: named tag sets that resolve to a dynamic asset view
CREATE TABLE IF NOT EXISTS library_view (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    tags      TEXT NOT NULL DEFAULT '',   -- comma-separated tag names
    match_all INTEGER NOT NULL DEFAULT 0, -- 1 = asset must carry every tag
    created   REAL NOT NULL,
    updated   REAL NOT NULL
);

-- Smart collections: stored criteria, evaluated live (no membership rows)
CREATE TABLE IF NOT EXISTS smart_collection (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    item_kind TEXT NOT NULL DEFAULT 'icon',   -- which pane it filters
    criteria  TEXT NOT NULL DEFAULT '{}',     -- JSON, see core/taxonomy.py
    created   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Custom fields (the taxonomy layer): global definitions + per-asset values
CREATE TABLE IF NOT EXISTS asset_field (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE,
    type    TEXT NOT NULL,                  -- text|number|bool|date|select|id
    options TEXT NOT NULL DEFAULT '',       -- JSON: select choices / id prefix+pad
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS asset_field_value (
    asset_id INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
    field_id INTEGER NOT NULL REFERENCES asset_field(id) ON DELETE CASCADE,
    value    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (asset_id, field_id)
);

-- Typed links between any two first-class objects (asset kinds, collections,
-- libraries, projects). Direction carries the one-to-many / many-to-many
-- distinction; many-to-one is many links pointing at the same target.
CREATE TABLE IF NOT EXISTS asset_link (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_kind TEXT NOT NULL,
    from_id   INTEGER NOT NULL,
    to_kind   TEXT NOT NULL,
    to_id     INTEGER NOT NULL,
    role      TEXT NOT NULL DEFAULT '',     -- free-text relationship label
    created   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(from_kind, from_id, to_kind, to_id, role)
);
CREATE INDEX IF NOT EXISTS idx_link_from ON asset_link(from_kind, from_id);
CREATE INDEX IF NOT EXISTS idx_link_to ON asset_link(to_kind, to_id);

CREATE TABLE IF NOT EXISTS storage_mount (
    id         INTEGER PRIMARY KEY,
    backend    TEXT NOT NULL,             -- smb | nfs | sshfs | s3 | local
    uri        TEXT NOT NULL,
    local_path TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL DEFAULT 'folder',  -- source kind it feeds
    created    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Watch folders / dropboxes (periodic change detection; transports in
-- core/watch.py — local, storage mounts, remote pulls, coming-soon)
CREATE TABLE IF NOT EXISTS watch_source (
    id        INTEGER PRIMARY KEY,
    path      TEXT NOT NULL,              -- local path or remote spec
    label     TEXT NOT NULL DEFAULT '',
    transport TEXT NOT NULL DEFAULT 'local',
    interval  INTEGER NOT NULL DEFAULT 60,
    enabled   INTEGER NOT NULL DEFAULT 1,
    created   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS watch_state (
    watch_id  INTEGER PRIMARY KEY REFERENCES watch_source(id) ON DELETE CASCADE,
    last_run  REAL NOT NULL DEFAULT 0,
    last_sig  TEXT NOT NULL DEFAULT '',
    last_hits INTEGER NOT NULL DEFAULT 0
);
"""

# External-content FTS5 kept in sync by triggers (the indexer UPDATEs an
# existing asset row in place so its id — and every taxonomy row pointing
# at it — survives re-identification; asset_fts_au reindexes on UPDATE,
# and the insert/delete triggers cover new and purged rows).
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
    _migrate_taxonomy_items(con)


def _migrate_taxonomy_items(con: sqlite3.Connection) -> None:
    """Taxonomy v3: tags and custom fields become kind-aware, covering every
    asset kind — icon, font, snippet, palette — instead of only rows in
    `asset`. Legacy asset_tag / asset_field_value rows are copied in as
    'icon'/'font' item rows once; the old tables stay for downgrade safety."""
    con.execute("""CREATE TABLE IF NOT EXISTS item_tag (
        item_id   INTEGER NOT NULL,
        item_kind TEXT NOT NULL DEFAULT 'icon',
        tag_id    INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
        PRIMARY KEY (item_id, item_kind, tag_id)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS item_field_value (
        item_id   INTEGER NOT NULL,
        item_kind TEXT NOT NULL DEFAULT 'icon',
        field_id  INTEGER NOT NULL REFERENCES asset_field(id) ON DELETE CASCADE,
        value     TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (item_id, item_kind, field_id)
    )""")
    n = con.execute("SELECT COUNT(*) AS c FROM item_tag").fetchone()["c"]
    if n == 0:
        # legacy icon rows carry the asset row's own kind, so fonts survive too
        con.execute("""INSERT OR IGNORE INTO item_tag (item_id, item_kind, tag_id)
            SELECT a.id, a.kind, at.tag_id FROM asset_tag at
            JOIN asset a ON a.id = at.asset_id""")
    # snippet / palette rows carry legacy comma-separated tags columns —
    # import those into item_tag as well so the Properties panel sees them
    for table, kind in (("snippet", "snippet"), ("palette", "palette")):
        for r in con.execute(
                f"SELECT id, tags FROM {table} WHERE tags != ''").fetchall():
            for t in (r["tags"] or "").split(","):
                t = t.strip()
                if not t:
                    continue
                trow = con.execute("SELECT id FROM tag WHERE name = ?",
                                   (t,)).fetchone()
                tid = trow[0] if trow else con.execute(
                    "INSERT INTO tag(name) VALUES (?)", (t,)).lastrowid
                con.execute(
                    "INSERT OR IGNORE INTO item_tag(item_id, item_kind,"
                    " tag_id) VALUES (?, ?, ?)", (r["id"], kind, int(tid or 0)))

    n = con.execute(
        "SELECT COUNT(*) AS c FROM item_field_value").fetchone()["c"]
    if n == 0:
        con.execute("""INSERT OR IGNORE INTO item_field_value
            (item_id, item_kind, field_id, value)
            SELECT a.id, a.kind, afv.field_id, afv.value
            FROM asset_field_value afv
            JOIN asset a ON a.id = afv.asset_id""")
    con.commit()


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


def set_starred(con: sqlite3.Connection, item_id: int, starred: bool,
                kind: str = "icon") -> None:
    """Star/unstar any asset kind: toggles the 'starred' tag AND membership
    in the 'Starred Assets' collection — one action, two side effects, so the
    tag filter and the collection navigator always agree."""
    tid, cid = _starred_ids(con)
    if starred:
        con.execute("INSERT OR IGNORE INTO item_tag(item_id, item_kind,"
                    " tag_id) VALUES (?, ?, ?)", (item_id, kind, tid))
        con.execute(
            "INSERT OR IGNORE INTO collection_ref(collection_id, item_kind,"
            " item_id) VALUES (?, ?, ?)", (cid, kind, item_id))
    else:
        con.execute("DELETE FROM item_tag WHERE item_id = ? AND item_kind = ?"
                    " AND tag_id = ?", (item_id, kind, tid))
        con.execute("DELETE FROM collection_ref WHERE collection_id = ?"
                    " AND item_kind = ? AND item_id = ?",
                    (cid, kind, item_id))
    con.commit()


def rename_tag(con: sqlite3.Connection, old: str, new: str) -> bool:
    """Rename a tag in place (asset_tag rows follow via the FK). Returns
    False when the old tag is missing or the new name already exists."""
    new = (new or "").strip()
    row = con.execute("SELECT id FROM tag WHERE name = ?", (old,)).fetchone()
    if row is None or not new:
        return False
    if con.execute("SELECT 1 FROM tag WHERE name = ? AND id != ?",
                   (new, row["id"])).fetchone() is not None:
        return False
    con.execute("UPDATE tag SET name = ? WHERE id = ?", (new, row["id"]))
    con.commit()
    return True


def delete_tag(con: sqlite3.Connection, name: str) -> bool:
    """Delete a tag and its memberships (asset_tag rows go with it)."""
    row = con.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()
    if row is None:
        return False
    con.execute("DELETE FROM asset_tag WHERE tag_id = ?", (row["id"],))
    con.execute("DELETE FROM tag WHERE id = ?", (row["id"],))
    con.commit()
    return True


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


def is_starred(con: sqlite3.Connection, item_id: int,
               kind: str = "icon") -> bool:
    row = con.execute(
        "SELECT 1 FROM item_tag it JOIN tag t ON t.id = it.tag_id"
        " WHERE it.item_id = ? AND it.item_kind = ? AND t.name = ?",
        (item_id, kind, STARRED_TAG),
    ).fetchone()
    return row is not None


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (and initialise) the library database. WAL + foreign keys on."""
    # timeout=30: with two scan workers writing concurrently, polite
    # waits must outlast a chunked commit window (default 5s was too
    # tight once fonts+icons collided at startup)
    con = sqlite3.connect(str(path), timeout=30)
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


def add_tag(con: sqlite3.Connection, item_id: int, name: str,
            kind: str = "icon") -> bool:
    """Attach a tag (creating it when new) to any asset kind. Returns
    False for a blank name or an unknown item."""
    name = (name or "").lstrip("#").strip()
    if not name:
        return False
    from . import taxonomy as core_tax
    if not core_tax._item_exists(con, kind, item_id):
        return False
    row = con.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()
    tid = row[0] if row else con.execute(
        "INSERT INTO tag(name) VALUES (?)", (name,)).lastrowid
    con.execute("INSERT OR IGNORE INTO item_tag(item_id, item_kind, tag_id)"
                " VALUES (?, ?, ?)", (item_id, kind, int(tid or 0)))
    con.commit()
    return True


def remove_tag(con: sqlite3.Connection, item_id: int, name: str,
               kind: str = "icon") -> None:
    con.execute(
        "DELETE FROM item_tag WHERE item_id = ? AND item_kind = ?"
        " AND tag_id = (SELECT id FROM tag WHERE name = ?)",
        (item_id, kind, name))
    con.commit()


def sync_item_tags(con: sqlite3.Connection, item_id: int, kind: str,
                   tags_csv: str) -> None:
    """Make item_tag the single source of truth for an editor save.

    Mirrors the CSV `tags` column into item_tag: attaches every tag in
    the CSV and detaches any item_tag rows not in it. Call after the
    editor's create/update so both representations agree going forward.
    """
    names = {t.lstrip("#").strip() for t in (tags_csv or "").split(",")
             if t.lstrip("#").strip()}
    current = set(tags_for(con, item_id, kind))
    for name in names - current:
        add_tag(con, item_id, name, kind)
    for name in current - names:
        remove_tag(con, item_id, name, kind)


# Back-compat alias used by the editor bridges (code.py / colors.py).
_sync_item_tags = sync_item_tags


def tags_for(con: sqlite3.Connection, asset_id: int,
             kind: str = "icon") -> list[str]:
    rows = con.execute(
        "SELECT t.name FROM tag t JOIN item_tag it ON it.tag_id = t.id "
        "WHERE it.item_id = ? AND it.item_kind = ? ORDER BY t.name",
        (asset_id, kind),
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
