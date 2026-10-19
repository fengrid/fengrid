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
