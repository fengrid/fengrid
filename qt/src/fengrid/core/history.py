"""Undo/Redo history for Fengrid's editable state.

A bounded, session-scoped undo stack that any bridge can push snapshots
onto: fields, settings, tags, palette edits, snippet bodies, project
configuration. Design rules (spec: strict memory limit, disabled for
bulk):

  - each entry stores a SMALL reversible snapshot (a JSON-serialisable
    "apply" payload plus an "undo" payload), never whole tables
  - the stack is capped at MAX_ENTRIES *and* MAX_BYTES; pushing past
    the cap drops the OLDEST entries (LRU)
  - bulk operations (scans, imports, batch jobs, restores) push nothing
    and clear the stack — undoing half of a 50k-file import is worse
    than not offering it
  - apply/undo closures live in the OWNING bridge; history.py only
    tracks entries and coordinates which undoable operation is next
"""
from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Callable

MAX_ENTRIES = 200
MAX_BYTES = 2 * 1024 * 1024          # 2 MB of payload text, hard cap


class HistoryEntry:
    __slots__ = ("label", "key", "apply_data", "undo_data", "ts", "bytes")

    def __init__(self, label: str, apply_data: Any, undo_data: Any,
                 key: str | None = None):
        self.label = label
        self.key = key if key is not None else label
        self.apply_data = apply_data
        self.undo_data = undo_data
        self.ts = time.time()
        self.bytes = len(json.dumps(
            {"a": apply_data, "u": undo_data}, default=str))


class History:
    """Linear undo/redo stack with pointer, owned per-bridge."""

    def __init__(self, max_entries: int = MAX_ENTRIES,
                 max_bytes: int = MAX_BYTES):
        self._undo: deque[HistoryEntry] = deque()
        self._redo: deque[HistoryEntry] = deque()
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._bytes = 0

    # ------------------------------------------------------------- push
    def push(self, label: str, apply_data: Any, undo_data: Any,
             key: str | None = None) -> None:
        """Record one user-scale change. Bulk callers MUST NOT call
        this — they call clear() instead (see `bulk_guard`)."""
        entry = HistoryEntry(label, apply_data, undo_data, key=key)
        self._undo.append(entry)
        self._redo.clear()               # a new action kills the redo arm
        self._bytes += entry.bytes
        self._trim()

    def coalesce(self, label: str, apply_data: Any, undo_data: Any,
                 match: str | None = None, window: float = 1.5) -> None:
        """Push, but merge into the previous entry when it is the same
        kind of change (same `match` key, default the label) made within
        `window` seconds. Continuous edits — slider drags, spinner
        spins — then form ONE undo step instead of flooding the stack.
        The merged entry keeps the FIRST undo_data (the pre-run state)
        and takes the LATEST apply_data (the final state)."""
        key = match if match is not None else label
        if self._undo:
            top = self._undo[-1]
            if top.key == key and time.time() - top.ts <= window:
                # top stays on the undo arm: replace its apply payload
                new = HistoryEntry(label, apply_data, top.undo_data,
                                   key=top.key)
                self._bytes -= top.bytes
                self._undo[-1] = new
                self._bytes += new.bytes
                self._trim()
                return
        self.push(label, apply_data, undo_data, key=key)

    def _trim(self) -> None:
        while len(self._undo) > self._max_entries or (
                self._bytes > self._max_bytes and len(self._undo) > 1):
            dropped = self._undo.popleft()
            self._bytes -= dropped.bytes

    # ------------------------------------------------------- traversal
    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def pop_undo(self) -> HistoryEntry | None:
        if not self._undo:
            return None
        entry = self._undo.pop()
        self._redo.append(entry)
        return entry

    def pop_redo(self) -> HistoryEntry | None:
        if not self._redo:
            return None
        entry = self._redo.pop()
        self._undo.append(entry)
        return entry

    def peek_undo_label(self) -> str:
        return self._undo[-1].label if self._undo else ""

    def peek_redo_label(self) -> str:
        return self._redo[-1].label if self._redo else ""

    # ------------------------------------------------------------ bulk
    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._bytes = 0

    @property
    def bytes_used(self) -> int:
        return self._bytes

    @property
    def depth(self) -> int:
        return len(self._undo)


class bulk_guard:
    """Context manager for bulk operations: suppresses recording and
    clears the stack on exit (spec: history disabled for bulk actions —
    an undo that restores half of a mass update is a lie)."""

    def __init__(self, history: History):
        self._h = history
        self._saved_push = None

    def __enter__(self) -> "bulk_guard":
        self._h.clear()
        self._saved_push = self._h.push
        self._h.push = lambda *a, **k: None   # type: ignore[method-assign]
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._h.push = self._saved_push       # type: ignore[method-assign]
        self._h.clear()
        return False
