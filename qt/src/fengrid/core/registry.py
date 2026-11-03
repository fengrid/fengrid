"""App registry: the layer that exists OUTSIDE any Fengrid database.

One Fengrid database = one SQLite file (assets, sources, taxonomy,
projects + its per-DB settings). The registry (`<data_dir>/registry.db`)
knows which DBs exist, which is active, which are starred (Quick
Access), and holds the APP-GLOBAL user preferences (theme, icon size,
…) so switching databases doesn't repaint the whole app.

`settings.bind_registry()` routes the GLOBAL_KEYS through this
connection; everything else keeps flowing to the active DB.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from . import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS registry_db (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    label       TEXT NOT NULL,
    starred     INTEGER NOT NULL DEFAULT 0,
    last_opened INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def open_registry(data_dir: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the app registry under data_dir."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(data_dir / "registry.db"))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    con.commit()
    return con


def label_for(path: str | Path, default_path: str | Path | None = None) -> str:
    """Human label for a DB path: its file stem, nicer for the default."""
    path = str(Path(path))
    if default_path is not None and path == str(Path(default_path)):
        return "fengrid"
    return Path(path).stem or Path(path).name


def upsert(con: sqlite3.Connection, path: str | Path, label: str | None = None,
           starred: bool | None = None, touch: bool = False,
           default_path: str | Path | None = None) -> None:
    """Register/refresh a known database (unique path)."""
    path = str(Path(path))
    row = con.execute("SELECT id, starred FROM registry_db WHERE path = ?",
                      (path,)).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO registry_db(path, label, starred, last_opened)"
            " VALUES (?, ?, ?, ?)",
            (path, label or label_for(path, default_path),
             int(bool(starred)), int(time.time()) if touch else 0))
    else:
        sets, args = [], []
        if label is not None:
            sets.append("label = ?")
            args.append(label)
        if starred is not None:
            sets.append("starred = ?")
            args.append(int(bool(starred)))
        if touch:
            sets.append("last_opened = ?")
            args.append(int(time.time()))
        if sets:
            con.execute(f"UPDATE registry_db SET {', '.join(sets)}"
                        " WHERE id = ?", [*args, row["id"]])
    con.commit()


def list_dbs(con: sqlite3.Connection) -> list[dict]:
    """Every known database, most recently opened first."""
    rows = con.execute(
        "SELECT path, label, starred, last_opened FROM registry_db"
        " ORDER BY last_opened DESC, label").fetchall()
    return [dict(r) for r in rows]


def star(con: sqlite3.Connection, path: str | Path, on: bool) -> None:
    con.execute("UPDATE registry_db SET starred = ? WHERE path = ?",
                (int(on), str(Path(path))))
    con.commit()


def active_path(con: sqlite3.Connection) -> str | None:
    from .db import get_setting
    v = get_setting(con, "active_db", None)
    return str(v) if v else None


def set_active(con: sqlite3.Connection, path: str | Path) -> None:
    from .db import set_setting
    set_setting(con, "active_db", str(Path(path)))


def clear_recent(con: sqlite3.Connection,
                 keep_path: str | Path | None = None) -> None:
    """Forget history (stars survive when the entry is kept)."""
    if keep_path is not None:
        con.execute("DELETE FROM registry_db WHERE path != ?",
                    (str(Path(keep_path)),))
    else:
        con.execute("DELETE FROM registry_db")
    con.commit()


def seed_globals(db_con: sqlite3.Connection,
                 reg_con: sqlite3.Connection) -> None:
    """First-run migration into the registry: copy each global pref from
    the active DB the first time it is missing in the registry. After
    that the registry wins — prefs survive database switches."""
    for key in settings.GLOBAL_KEYS:
        from .db import get_setting as _g, set_setting as _s
        if _g(reg_con, key, None) is None:
            v = _g(db_con, key, None)
            if v is not None:
                _s(reg_con, key, v)


def is_fengrid_db(path: str | Path) -> bool:
    """Cheap validation before opening a user-picked file: it must be a
    SQLite file carrying fengrid's `setting` table."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name IN ('setting', 'source') LIMIT 1").fetchone()
            return row is not None
        finally:
            con.close()
    except sqlite3.Error:
        return False