"""Key/value settings — app-global prefs + per-database values.

Two stores, one vocabulary (thin wrappers over core.db):

- **GLOBAL keys** (see GLOBAL_KEYS — theme, icon size, search mode,
  editor keymap, colors rule, startup pane, update check, last export
  dir) live in the APP REGISTRY connection bound via
  `bind_registry()`. They are user preferences: switching databases
  must not repaint the app. `bind_registry(None)` restores the plain
  single-DB behaviour (tests, unbound environments).
- **Everything else** (first_run_done, last_scan, has_fts, demo/feature
  flags …) is stored on the connection passed in — per database.

Until `bind_registry()` runs, global keys fall back to the passed
connection, so code that never binds a registry behaves exactly like
the pre-multi-database releases.
"""

from __future__ import annotations

import sqlite3

from .db import get_setting as _get
from .db import set_setting as _set

# user preferences that must survive a database switch (app registry)
GLOBAL_KEYS = frozenset({
    "theme",
    "icon_size",
    "search_mode",
    "editor_keymap",
    "colors_rule",
    "startup_pane",
    "update_check",
    "last_export_dir",
})

_REGISTRY: sqlite3.Connection | None = None


def bind_registry(con: sqlite3.Connection | None) -> None:
    """Point GLOBAL_KEYS at the app registry (None = single-DB mode)."""
    global _REGISTRY
    _REGISTRY = con


def _dst(con: sqlite3.Connection, key: str) -> sqlite3.Connection:
    if _REGISTRY is not None and key in GLOBAL_KEYS:
        return _REGISTRY
    return con


def get(con: sqlite3.Connection, key: str, default=None):
    return _get(_dst(con, key), key, default)


def set(con: sqlite3.Connection, key: str, value) -> None:
    _set(_dst(con, key), key, value)


def get_bool(con: sqlite3.Connection, key: str, default: bool = False) -> bool:
    """Boolean settings persist through str(value) — 'True'/'False'.

    Accepts the common spellings so hand-edited or migrated rows
    ('1', 'true', 'yes') still read correctly.
    """
    raw = _get(_dst(con, key), key, None)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def set_bool(con: sqlite3.Connection, key: str, value: bool) -> None:
    _set(_dst(con, key), key, bool(value))