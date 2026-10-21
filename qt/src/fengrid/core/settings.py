"""Key/value settings on the library's `setting` table (replaces gib-* keys).

Thin wrappers over core.db; kept as a module so the Qt bridges and the tests
share one vocabulary.
"""

from __future__ import annotations

import sqlite3

from .db import get_setting as _get
from .db import set_setting as _set


def get(con: sqlite3.Connection, key: str, default=None):
    return _get(con, key, default)


def set(con: sqlite3.Connection, key: str, value) -> None:
    _set(con, key, value)


def get_bool(con: sqlite3.Connection, key: str, default: bool = False) -> bool:
    """Boolean settings persist through str(value) — 'True'/'False'.

    Accepts the common spellings so hand-edited or migrated rows
    ('1', 'true', 'yes') still read correctly.
    """
    raw = _get(con, key, None)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def set_bool(con: sqlite3.Connection, key: str, value: bool) -> None:
    _set(con, key, bool(value))
