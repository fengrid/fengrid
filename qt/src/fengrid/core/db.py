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
CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS scan_state (
    path        TEXT PRIMARY KEY,
    fingerprint TEXT,
    last_seen   REAL
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


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (and initialise) the library database. WAL + foreign keys on."""
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    _migrate(con)
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
