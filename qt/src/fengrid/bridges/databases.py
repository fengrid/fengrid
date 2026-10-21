"""Databases bridge: the multi-database menu (Recent / Quick Access).

One Fengrid database is active at a time; the registry remembers every
database ever opened (most recent first), stars pin entries into Quick
Access, and switching is a clean process relaunch — every bridge holds
the single active connection, so re-exec is the only safe way to swap
it (the chunked scan commits make an interrupted scan restart-safe).

`FENGRID_NO_RELAUNCH=1` suppresses the exec (tests, embedders): the
registry still flips, so the behaviour stays observable.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import db as core_db
from ..core import registry


def _ago(ts: int) -> str:
    """Human 'last opened' suffix for Recent rows."""
    if not ts:
        return "never opened"
    delta = max(0, int(time.time()) - int(ts))
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60} min ago"
    if delta < 86400:
        return f"{delta // 3600} h ago"
    if delta < 2 * 86400:
        return "yesterday"
    return f"{delta // 86400} d ago"


class Databases(QObject):
    message = Signal(str)
    changed = Signal()          # recent/stars/current moved — menu rebinds

    def __init__(self, db_path: str, reg_con, data_dir: str,
                 default_path: str | None = None, parent=None):
        super().__init__(parent)
        self._session = str(Path(db_path))
        self._reg = reg_con
        self._data_dir = data_dir
        self._default = str(default_path or db_path)
        # the database we actually opened is always known + current
        registry.upsert(self._reg, self._session,
                        default_path=self._default, touch=True)
        registry.set_active(self._reg, self._session)

    # ------------------------------------------------------------- state
    def _rows(self) -> list[dict]:
        out = []
        for row in registry.list_dbs(self._reg):
            out.append({
                "path": row["path"],
                "label": row["label"],
                "starred": bool(row["starred"]),
                "exists": os.path.isfile(row["path"]),
                "when": _ago(row["last_opened"]),
                "current": row["path"] == self._session,
            })
        return out

    @Property(str, notify=changed)
    def currentPath(self) -> str:
        return self._session

    @Property(str, notify=changed)
    def currentLabel(self) -> str:
        for row in self._rows():
            if row["current"]:
                return row["label"]
        return registry.label_for(self._session, self._default)

    @Property(bool, notify=changed)
    def currentStarred(self) -> bool:
        for row in self._rows():
            if row["current"]:
                return row["starred"]
        return False

    @Property("QVariantList", notify=changed)
    def recent(self):
        """Every OTHER known database, most recently opened first."""
        return [r for r in self._rows() if not r["current"]]

    @Property("QVariantList", notify=changed)
    def quick(self):
        """Starred others — the Quick Access menu."""
        return [r for r in self._rows()
                if not r["current"] and r["starred"]]

    @Property(str, constant=True)
    def defaultDir(self) -> str:
        """file:// dir the New/Open dialogs start in."""
        return "file://" + self._data_dir

    # -------------------------------------------------------------- slots
    @Slot()
    def starCurrent(self) -> None:
        registry.star(self._reg, self._session, not self.currentStarred)
        self.changed.emit()

    @Slot()
    def clearRecent(self) -> None:
        registry.clear_recent(self._reg, keep_path=self._session)
        registry.upsert(self._reg, self._session,
                        default_path=self._default, touch=True)
        self.changed.emit()

    @Slot(str)
    def createDatabase(self, path: str) -> None:
        """New empty Fengrid DB (schema built by db.connect) → active →
        relaunch into it."""
        p = Path(path).expanduser()
        if p.exists():
            self.message.emit(f"Already exists: {p.name}")
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        con = core_db.connect(str(p))
        con.close()
        self._activate(p)

    @Slot(str)
    def openDatabase(self, path: str) -> None:
        p = Path(path).expanduser()
        if not p.is_file():
            self.message.emit(f"Not found: {p.name}")
            return
        if not registry.is_fengrid_db(p):
            self.message.emit(f"Not a Fengrid database: {p.name}")
            return
        self._activate(p)

    @Slot(str)
    def switchTo(self, path: str) -> None:
        """Recent/Quick Access entry — same acceptance rules as open."""
        self.openDatabase(path)

    # ------------------------------------------------------------ internal
    def _activate(self, p: Path) -> None:
        # flip the session too — with relaunch suppressed (tests) the
        # bridge must behave as if we were already inside p
        self._session = str(p)
        registry.upsert(self._reg, p, touch=True)
        registry.set_active(self._reg, p)
        self.changed.emit()
        self._relaunch()

    def _relaunch(self) -> None:
        if os.environ.get("FENGRID_NO_RELAUNCH"):
            self.message.emit("Database switched (relaunch suppressed)")
            return
        # keep the user's flags but drop the per-run --db override: the
        # registry's active entry wins on the next start
        args, skip = [], False
        for a in sys.argv[1:]:
            if skip:
                skip = False
                continue
            if a == "--db":
                skip = True
                continue
            if a.startswith("--db="):
                continue
            args.append(a)
        exe = sys.executable
        try:
            if getattr(sys, "frozen", False):
                os.execv(exe, [exe, *args])
            else:
                os.execv(exe, [exe, "-m", "fengrid", *args])
        except OSError as e:                # exec failed — stay alive
            self.message.emit(f"Could not relaunch: {e}")