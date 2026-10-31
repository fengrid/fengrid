"""SQLite library store: schema, FTS5 index, and small helpers.

Pure stdlib (sqlite3) — no Qt imports. Collapses the 0.x data plane
(list.txt/list.js, meta.js + meta-state.tsv, per-pane localStorage keys,
per-pane server SQLite) into one database with unified tags and collections
(docs/architecture/0001-qt6-rewrite.md §6).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path


def new_guid() -> str:
    """Canonical 36-char GUID — generated once when a row is first
    tracked, stable for its lifetime."""
    return str(uuid.uuid4())


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
    mtime       REAL,
    guid        TEXT,                 -- generated unique GUID (set at ingest)
    slug        TEXT                  -- user-defined short link name ('' default)
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
    name TEXT NOT NULL,
    kind TEXT,                          -- asset type this collection holds
                                        -- (#141: single-type collections;
                                        --  NULL = legacy/untyped)
    query TEXT,
    guid TEXT,
    slug TEXT,
    UNIQUE(name, kind)
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
    updated REAL,
    guid    TEXT,
    slug    TEXT
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
    updated     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    guid        TEXT,
    slug        TEXT
);
CREATE INDEX IF NOT EXISTS idx_snippet_updated ON snippet(updated DESC);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    settings    TEXT NOT NULL DEFAULT '{}',
    created     TEXT NOT NULL DEFAULT (datetime('now')),
    updated     TEXT NOT NULL DEFAULT (datetime('now')),
    guid        TEXT,
    slug        TEXT
);
CREATE TABLE IF NOT EXISTS preset_library (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL DEFAULT '',
    summary    TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    remote_url TEXT NOT NULL DEFAULT '',
    branch     TEXT NOT NULL DEFAULT '',
    remote     INTEGER NOT NULL DEFAULT 1,
    position   INTEGER NOT NULL DEFAULT 0,
    guid       TEXT,
    slug       TEXT
);
CREATE TABLE IF NOT EXISTS preset_entry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id   INTEGER NOT NULL
                 REFERENCES preset_library(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    repo         TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    branch       TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    license      TEXT NOT NULL DEFAULT '',
    homepage     TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '',
    position     INTEGER NOT NULL DEFAULT 0,
    downloaded   INTEGER NOT NULL DEFAULT 0,
    local_path   TEXT NOT NULL DEFAULT '',
    preview_path TEXT NOT NULL DEFAULT '',
    guid         TEXT,
    slug         TEXT
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
    updated   REAL NOT NULL,
    guid      TEXT,
    slug      TEXT
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
    kind    TEXT,                           -- NULL = every asset class (#105)
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

-- Live content for structured-data assets (data / timeseries kinds):
-- the REST API and sensors read/write the payload here. Revision bumps
-- on every write so clients can detect changes; timeseries points ride
-- inside the payload ({points: [...]}).
CREATE TABLE IF NOT EXISTS asset_data (
    asset_id INTEGER PRIMARY KEY REFERENCES asset(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 1,
    payload  TEXT NOT NULL DEFAULT '{}',   -- JSON document
    updated  REAL NOT NULL DEFAULT 0
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
CREATE TRIGGER IF NOT EXISTS asset_fts_au AFTER UPDATE ON asset
    WHEN old.name IS NOT new.name OR old.path IS NOT new.path
      OR old.theme IS NOT new.theme OR old.context IS NOT new.context
BEGIN
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
    _migrate_guid_slug(con)
    _migrate_collections(con)
    _migrate_collection_kinds(con)
    _migrate_taxonomy_items(con)
    _migrate_grid_indexes(con)
    _migrate_source_index(con)
    _migrate_prune_sandbox_sources(con)
    _migrate_field_kind(con)
    _migrate_fts_trigger_v2(con)

    # #105: custom fields must be definable per asset class — the column
    # is missing on pre-#105 databases; NULL means "every class".
def _migrate_field_kind(con: sqlite3.Connection) -> None:
    try:
        con.execute("ALTER TABLE asset_field ADD COLUMN kind TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise


def _migrate_prune_sandbox_sources(con: sqlite3.Connection) -> None:
    """#61: drop disabled per-app sandbox icon roots left in the source
    table by earlier builds.

    platform_candidates() no longer returns the per-app flatpak/snap
    trees (see scanner.py), but a DB created by the old code keeps the
    rows — on one machine 118 of 121 sources — and the first-run
    screen's per-row `pathEnabled()` → `library.sources` reads are
    O(N²) in the source count (measured 20.7s engine.load, 26–31s per
    setup toggle). Only DISABLED rows are removed: an enabled row is a
    user choice and purge + re-add happens on disable anyway. The one
    enabled sandbox row from the diag DB is left untouched.
    """
    con.execute(
        "DELETE FROM source WHERE kind = 'system' AND enabled = 0 AND ("
        "  path LIKE '%/flatpak/app/%/files/share/icons'"
        "  OR path LIKE '/snap/%/usr/share/icons'"
        ")")


def _migrate_grid_indexes(con: sqlite3.Connection) -> None:
    """Scale indexes for six-figure+ asset counts (all columns exist in
    the base SCHEMA / the ALTERs above — safe to CREATE IF NOT EXISTS).

    - idx_asset_grid: the icons grid always filters kind and orders
      (theme, name); the trailing id makes the order deterministic so
      keyset pagination (bridges.library load_more) can walk the index
      in one ordered range scan instead of sorting ~1M rows per
      filter change.
    - kind-prefixed pairs for the rail COUNT(*) GROUP BY aggregates
      (theme/context/ext/family): index-only scans at any table size.
    - idx_item_tag_tagid: _refresh_lists counts tags by tag_id, which
      is the LAST column of item_tag's PK — unindexed before this.
    """
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_grid"
        " ON asset(kind, theme, name, id)")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_kind_context"
        " ON asset(kind, context)")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_kind_ext ON asset(kind, ext)")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_kind_family"
        " ON asset(kind, family)")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_item_tag_tagid"
        " ON item_tag(item_kind, tag_id)")


def _migrate_source_index(con: sqlite3.Connection) -> None:
    """idx_asset_source: every per-source asset lookup was a full-table
    scan — not only sources_summary()'s LEFT JOIN … GROUP BY, which ran
    that scan PER SOURCE on the MAIN thread during first-run setup and
    froze the UI for minutes while the initial icon+font scans wrote
    (#61 freeze dumps: main thread 78s inside the aggregate), but also
    the purge/sweep/disable lookups (indexer WHERE source_id = ?),
    including the one inside scan_fonts itself.
    """
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_source"
        " ON asset(source_id)")


def _migrate_fts_trigger_v2(con: sqlite3.Connection) -> None:
    """Recreate the FTS sync trigger with a WHEN clause so fingerprint
    rescans that only touch mtime/size columns don't pay a full FTS
    delete+insert per row (that churn dominated 1M-row rescan cost).
    Gated by a setting flag so the DROP+CREATE runs once per database."""
    try:
        if get_setting(con, "fts_trigger_v2") == "1":
            return
        con.execute("DROP TRIGGER IF EXISTS asset_fts_au")
        con.executescript("""
CREATE TRIGGER IF NOT EXISTS asset_fts_au AFTER UPDATE ON asset
    WHEN old.name IS NOT new.name OR old.path IS NOT new.path
      OR old.theme IS NOT new.theme OR old.context IS NOT new.context
BEGIN
    INSERT INTO asset_fts(asset_fts, rowid, name, path, theme, context)
    VALUES ('delete', old.id, old.name, old.path, old.theme, old.context);
    INSERT INTO asset_fts(rowid, name, path, theme, context)
    VALUES (new.id, new.name, new.path, new.theme, new.context);
END;
""")
        set_setting(con, "fts_trigger_v2", "1")
    except sqlite3.OperationalError:
        # FTS5 unavailable in this build (no asset_fts table) — the LIKE
        # fallback path never touches these triggers; leave as-is
        pass


# Every tracked object carries a generated GUID (assigned at first
# ingest/creation, backfilled here for pre-existing rows) and a user
# slug (empty by default, unique when set). Slug uniqueness is GLOBAL
# across all tracked tables — [[ slug ]] references must resolve to
# exactly one object — so it is enforced in set_slug() rather than by
# per-table indexes.
_SLUG_TABLES = (
    "asset", "snippet", "palette", "collection", "library_view", "projects",
    "preset_library", "preset_entry",
)


def _migrate_guid_slug(con: sqlite3.Connection) -> None:
    for table in _SLUG_TABLES:
        cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if "guid" not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN guid TEXT")
        if "slug" not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN slug TEXT")
    # backfill GUIDs — one uuid4 per row missing one (id-preserving:
    # existing taxonomy/link rows keep pointing at the same ids)
    for table in _SLUG_TABLES:
        rows = con.execute(
            f"SELECT id FROM {table} WHERE guid IS NULL OR guid = ''"
        ).fetchall()
        for r in rows:
            con.execute(f"UPDATE {table} SET guid = ? WHERE id = ?",
                        (new_guid(), r["id"]))
    # the guid index lives HERE (not in SCHEMA): on legacy databases the
    # column only exists once the ALTERs above have run
    con.execute("CREATE INDEX IF NOT EXISTS idx_asset_guid ON asset(guid)")
    con.commit()


def set_slug(con: sqlite3.Connection, kind: str, item_id: int,
             slug: str) -> str:
    """Set an object's user-facing slug (the [[ slug ]] link name).

    Slugs are normalized to lowercase-hyphen and must be globally unique
    across every tracked table; '' clears the slug. Returns the stored
    value; raises ValueError on an invalid or taken slug.
    """
    table = _SLUG_TABLE_FOR[kind]
    slug = (slug or "").strip().lower()
    slug = "-".join(slug.split())
    if slug:
        import re as _re
        if not _re.fullmatch(r"[a-z0-9][a-z0-9._-]*", slug):
            raise ValueError(
                f"invalid slug {slug!r}: use letters, digits, . _ -")
        for other in _SLUG_TABLES:
            row = con.execute(
                f"SELECT 1 FROM {other} WHERE slug = ? AND id != ?",
                (slug, item_id if other == table else -1)).fetchone()
            if row is not None:
                raise ValueError(f"slug {slug!r} is already taken")
    con.execute(f"UPDATE {table} SET slug = ? WHERE id = ?",
                (slug, item_id))
    con.commit()
    return slug


_SLUG_TABLE_FOR = {
    "icon": "asset", "font": "asset", "image": "asset", "video": "asset",
    "audio": "asset", "doc": "asset", "data": "asset",
    "spatial": "asset", "timeseries": "asset", "markdown": "asset",
    "snippet": "snippet", "palette": "palette", "collection": "collection",
    "library": "library_view", "project": "projects",
    "preset": "preset_library", "preset_entry": "preset_entry",
}


def lookup_by_slug(con: sqlite3.Connection, slug: str) -> dict | None:
    """[[ slug ]] resolution: first match across the tracked tables.

    Asset-table hits report the row's real kind (icon/image/data/…), not
    the alias that happened to match first."""
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    row = con.execute(
        "SELECT id, kind, guid FROM asset WHERE slug = ?", (slug,)
    ).fetchone()
    if row is not None:
        return {"kind": row["kind"], "id": row["id"], "guid": row["guid"],
                "table": "asset"}
    for kind, table in (("snippet", "snippet"), ("palette", "palette"),
                        ("collection", "collection"),
                        ("library", "library_view"),
                        ("project", "projects"),
                        ("preset", "preset_library"),
                        ("preset_entry", "preset_entry")):
        row = con.execute(
            f"SELECT id, guid FROM {table} WHERE slug = ?", (slug,)
        ).fetchone()
        if row is not None:
            return {"kind": kind, "id": row["id"], "guid": row["guid"],
                    "table": table}
    return None


def lookup_by_guid(con: sqlite3.Connection, guid: str) -> dict | None:
    """[[ GUID ]] resolution across the tracked tables (the row's real
    kind is reported for asset-table hits)."""
    guid = (guid or "").strip()
    if not guid:
        return None
    row = con.execute(
        "SELECT id, kind, slug FROM asset WHERE guid = ?", (guid,)
    ).fetchone()
    if row is not None:
        return {"kind": row["kind"], "id": row["id"],
                "slug": row["slug"] or "", "table": "asset"}
    for kind, table in (("snippet", "snippet"), ("palette", "palette"),
                        ("collection", "collection"),
                        ("library", "library_view"),
                        ("project", "projects"),
                        ("preset", "preset_library"),
                        ("preset_entry", "preset_entry")):
        row = con.execute(
            f"SELECT id, slug FROM {table} WHERE guid = ?", (guid,)
        ).fetchone()
        if row is not None:
            return {"kind": kind, "id": row["id"], "slug": row["slug"] or "",
                    "table": table}
    return None


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


def _migrate_collection_kinds(con: sqlite3.Connection) -> None:
    """#141: collections become asset-TYPE specific. Adds the kind
    column, backfills it from existing membership (a collection whose
    refs are all one kind adopts that kind; mixed/empty stay NULL =
    untyped legacy), and relaxes name uniqueness to per-kind so the
    default 'Downloaded' collection can exist once per asset type.
    sqlite cannot drop the implicit UNIQUE(name) index, so the table is
    rebuilt in place when an old-schema DB is opened."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(collection)")}
    if "kind" not in cols:
        con.execute("ALTER TABLE collection ADD COLUMN kind TEXT")
    uniques = [
        [c["name"] for c in con.execute(f"PRAGMA index_info({r['name']})")]
        for r in con.execute("PRAGMA index_list(collection)")
        if r["unique"] and r["origin"] == "u"
    ]
    if not any(cols_set == ["name", "kind"] for cols_set in uniques):
        # old schema: UNIQUE(name) — rebuild with UNIQUE(name, kind).
        # FK references to collection(id) keep working: the new table is
        # created under a temp name, populated, the old one dropped
        # (foreign_keys off), and the temp renamed onto the original
        # name — ids are copied verbatim, so collection_ref rows and
        # the self-referencing parent_id all stay valid.
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("BEGIN")
        con.execute("""
            CREATE TABLE collection_new (
                id   INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT,
                query TEXT,
                guid TEXT,
                slug TEXT,
                parent_id INTEGER REFERENCES collection_new(id)
                          ON DELETE CASCADE,
                tags TEXT,
                UNIQUE(name, kind)
            )""")
        con.execute(
            "INSERT INTO collection_new(id, name, kind, query, guid,"
            " slug, parent_id, tags)"
            " SELECT id, name, kind, query, guid, slug, parent_id, tags"
            " FROM collection")
        con.execute("DROP TABLE collection")
        con.execute("ALTER TABLE collection_new RENAME TO collection")
        con.commit()
        con.execute("PRAGMA foreign_keys=ON")
    # backfill: single-kind collections adopt their type
    for row in con.execute("SELECT id FROM collection").fetchall():
        kinds = [r[0] for r in con.execute(
            "SELECT DISTINCT item_kind FROM collection_ref"
            " WHERE collection_id = ?", (row["id"],))]
        if len(kinds) == 1:
            con.execute("UPDATE collection SET kind = ? WHERE id = ?"
                        " AND kind IS NULL", (kinds[0], row["id"]))
    # heal duplicate NULL-kind rows (NULLs are distinct under
    # UNIQUE(name, kind): a pre-fix ensure_defaults stacked one
    # 'Starred Assets' per launch). Keep the oldest of each group.
    con.execute(
        "DELETE FROM collection_ref WHERE collection_id IN ("
        "  SELECT id FROM ("
        "    SELECT c.id FROM collection c JOIN collection m"
        "      ON m.name = c.name AND m.kind IS c.kind"
        "     WHERE c.id > m.id))")
    con.execute(
        "DELETE FROM collection WHERE id IN ("
        "  SELECT id FROM ("
        "    SELECT c.id FROM collection c JOIN collection m"
        "      ON m.name = c.name AND m.kind IS c.kind"
        "     WHERE c.id > m.id))")
    con.commit()


STARRED_TAG = "starred"
STARRED_COLLECTION = "Starred Assets"


def ensure_defaults(con: sqlite3.Connection) -> None:
    """The 'starred' tag and 'Starred Assets' collection exist from the
    first launch. Idempotent — but note kind-aware matching: under
    UNIQUE(name, kind) a NULL kind is DISTINCT from itself in sqlite's
    unique index, so INSERT OR IGNORE alone would stack a new copy on
    every launch (#141)."""
    con.execute("INSERT OR IGNORE INTO tag(name) VALUES (?)", (STARRED_TAG,))
    row = con.execute(
        "SELECT id FROM collection WHERE name = ? AND kind IS NULL",
        (STARRED_COLLECTION,)).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO collection(name, kind, guid) VALUES (?, NULL, ?)",
            (STARRED_COLLECTION, new_guid()))
    con.commit()


def _starred_ids(con: sqlite3.Connection) -> tuple[int, int]:
    """(tag_id, collection_id), re-created when a user deleted either —
    starring must always work."""
    tag = con.execute("SELECT id FROM tag WHERE name = ?",
                      (STARRED_TAG,)).fetchone()
    coll = con.execute(
        "SELECT id FROM collection WHERE name = ? AND kind IS NULL",
        (STARRED_COLLECTION,)).fetchone()
    tid = tag["id"] if tag else con.execute(
        "INSERT INTO tag(name) VALUES (?)", (STARRED_TAG,)).lastrowid
    cid = coll["id"] if coll else con.execute(
        "INSERT INTO collection(name, kind) VALUES (?, NULL)",
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


COLLECTION_KINDS = ("icon", "font", "image", "video", "audio", "doc",
                    "data", "spatial", "timeseries", "markdown",
                    "snippet", "palette")


def collection_tree(con: sqlite3.Connection) -> list[dict]:
    """Every collection with parent, kind, tags, and per-kind member
    counts — parents before children, ready for a one-level tree render."""
    rows = [dict(r) for r in con.execute(
        "SELECT id, name, parent_id, tags, kind FROM collection"
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
                          parent_id: int = 0, tags: str = "",
                          kind: str = "") -> int:
    name = (name or "").strip() or "Untitled collection"
    parent_id = int(parent_id) if parent_id else 0
    if not kind and parent_id:
        # a sub-collection of a typed parent belongs to the same type
        prow = con.execute("SELECT kind FROM collection WHERE id = ?",
                           (parent_id,)).fetchone()
        kind = (prow["kind"] if prow else None) or ""
    cur = con.execute(
        "INSERT INTO collection(name, parent_id, tags, kind, guid)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, parent_id or None, tags, kind or None, new_guid()))
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
    unknown kind, a row that does not exist, or a kind mismatch —
    collections are single-type (#141). An untyped collection locks to
    the kind of its first ref."""
    if kind not in COLLECTION_KINDS:
        return False
    if kind == "snippet":
        ok = con.execute("SELECT 1 FROM snippet WHERE id = ?",
                         (item_id,)).fetchone()
    elif kind == "palette":
        ok = con.execute("SELECT 1 FROM palette WHERE id = ?",
                         (item_id,)).fetchone()
    else:
        ok = con.execute("SELECT 1 FROM asset WHERE id = ? AND kind = ?",
                         (item_id, kind)).fetchone()
    if not ok:
        return False
    crow = con.execute("SELECT kind FROM collection WHERE id = ?",
                       (coll_id,)).fetchone()
    if crow is None:
        return False
    if crow["kind"] is None:
        # first ref into an untyped collection sets its type
        con.execute("UPDATE collection SET kind = ? WHERE id = ?",
                    (kind, coll_id))
    elif crow["kind"] != kind:
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


def filesystem_type(path: str | os.PathLike,
                    mounts_path: str = "/proc/mounts") -> str:
    """Filesystem type hosting `path` (Linux /proc/mounts; '' elsewhere).

    #61 diagnostics: a read stall on a non-WAL-capable filesystem
    (network home mounts, some FUSE/overlay setups) looks exactly like
    a logic freeze in the freeze-watchdog dumps — the dumps name the
    statement, never the storage. Every crash-log launch line now
    records this so the next report answers it outright.
    """
    if sys.platform != "linux":
        return ""
    real = os.path.realpath(str(path))
    best_mnt, best_fs = "", ""
    try:
        with open(mounts_path, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt = (parts[1].replace("\\040", " ")
                       .replace("\\011", "\t").replace("\\134", "\\"))
                if mnt == "/" or real == mnt \
                        or real.startswith(mnt.rstrip("/") + "/"):
                    if len(mnt) >= len(best_mnt):
                        best_mnt, best_fs = mnt, parts[2]
    except OSError:
        return ""
    return best_fs


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (and initialise) the library database. WAL + foreign keys on."""
    # timeout=30: with two scan workers writing concurrently, polite
    # waits must outlast a chunked commit window (default 5s was too
    # tight once fonts+icons collided at startup)
    con = sqlite3.connect(str(path), timeout=30)
    con.row_factory = sqlite3.Row
    mode = con.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    # NORMAL under WAL: commits don't fsync on every transaction — the
    # chunked scan commits (400 rows apiece) otherwise pay a full disk
    # flush each, and a 1M-file import pays it 2500 times. WAL +
    # NORMAL is the SQLite-recommended durability pairing; power loss
    # can only lose the last transactions, never corrupt the DB.
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    if str(mode).lower() != "wal":
        # #61: WAL silently unavailable (network/overlay filesystems
        # refuse it) means rollback-journal mode — every operation takes
        # fcntl locks that can stall for whole lock-timeout periods and
        # freeze the UI with NO writers anywhere in the dumps.
        fs = filesystem_type(path)
        print(
            f"warning: {path} is on filesystem '{fs or 'unknown'}' —"
            f" SQLite WAL unavailable (journal mode '{mode}'); database"
            " operations will be slow and can stall for seconds under"
            " load. Consider a data directory on a local disk (--db or"
            " XDG_DATA_HOME).", file=sys.stderr)
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


# ── structured-data content (data / timeseries kinds) ────────────────
# Sensors and services push updates through the REST API; the GUI reads
# the same rows. Payload is one JSON document per asset; every write
# bumps `revision` so pollers can detect change.

def get_asset_data(con: sqlite3.Connection, asset_id: int) -> dict | None:
    import json as _json
    row = con.execute(
        "SELECT revision, payload, updated FROM asset_data WHERE asset_id = ?",
        (asset_id,)).fetchone()
    if row is None:
        return None
    try:
        doc = _json.loads(row["payload"])
    except ValueError:
        doc = {}
    return {"asset_id": int(asset_id), "revision": row["revision"],
            "payload": doc, "updated": row["updated"]}


def put_asset_data(con: sqlite3.Connection, asset_id: int,
                   payload: dict) -> dict:
    """Create or fully replace an asset's data payload."""
    import json as _json
    row = con.execute("SELECT revision FROM asset_data WHERE asset_id = ?",
                      (asset_id,)).fetchone()
    rev = (row["revision"] + 1) if row else 1
    con.execute(
        "INSERT INTO asset_data(asset_id, revision, payload, updated)"
        " VALUES (?, ?, ?, ?)"
        " ON CONFLICT(asset_id) DO UPDATE SET revision = excluded.revision,"
        " payload = excluded.payload, updated = excluded.updated",
        (asset_id, rev, _json.dumps(payload or {}), time.time()))
    con.commit()
    return get_asset_data(con, asset_id) or {
        "asset_id": int(asset_id), "revision": rev, "payload": payload or {},
        "updated": 0.0}


def patch_asset_data(con: sqlite3.Connection, asset_id: int,
                     merge: dict) -> dict:
    """Merge keys into an existing payload (shallow; nested paths via
    dotted keys are NOT expanded — clients send full subtrees)."""
    import json as _json
    cur = get_asset_data(con, asset_id) or {"payload": {}, "revision": 0}
    doc = dict(cur["payload"])
    doc.update(merge or {})
    return put_asset_data(con, asset_id, doc)


def delete_asset_data(con: sqlite3.Connection, asset_id: int) -> bool:
    cur = con.execute("DELETE FROM asset_data WHERE asset_id = ?",
                      (asset_id,))
    con.commit()
    return cur.rowcount > 0


def append_asset_points(con: sqlite3.Connection, asset_id: int,
                        points: list) -> dict:
    """Timeseries append: points [{t, v} or {t, k: v, ...}] land at the
    end of payload.points; the document stays bounded by _MAX_TS_POINTS."""
    import json as _json
    if not isinstance(points, list):
        raise ValueError("points must be a list")
    cur = get_asset_data(con, asset_id) or {"payload": {}, "revision": 0}
    doc = dict(cur["payload"])
    existing = doc.get("points") or []
    doc["points"] = (existing + list(points))[-_MAX_TS_POINTS:]
    return put_asset_data(con, asset_id, doc)


_MAX_TS_POINTS = 100000
