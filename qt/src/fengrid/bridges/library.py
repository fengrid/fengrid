"""Library bridge: the Qt model over the SQLite core (icons v1).

Design notes:
- Filters compose around core.db.search (FTS5 when available) and rebuild the
  model from SQL — correct at six-figure counts, trivially cheap at 761.
- Rescan runs on a QThread with its own DB connection (WAL allows concurrent
  readers); results arrive via queued signals, never shared connections.
- Export is native (Pillow) — no server. SVG sources render through
  QSvgRenderer first; .xpm falls back to ImageMagick via argv when present.
"""

from __future__ import annotations

import os
import queue
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QCoreApplication,
                            QByteArray, QModelIndex, QObject, Qt, QThread,
                            QTimer, Signal, Slot, Property)
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from .. import __version__
from ..core import db as core_db
from ..core import export as core_export
from ..core import taxonomy as core_tax
from ..core import indexer, migrate, scanner, search as core_search

# #61: a sources_summary call slower than this lands in crash.log — the
# freeze dumps kept implicating this read with three contradictory
# theories; the measured duration separates a slow read from a slow
# QML load happening around it.
_SLOW_SUMMARY_S = 0.25
from ..core import paths as core_paths
from ..core import settings
from ..core.export import ExportError

# QML-facing role names must not collide with context-property names: a role
# named `theme` shadowed the Theme bridge inside grid delegates, so token
# bindings resolved against a plain theme string instead of the bridge.
_ROLE_NAMES = ("name", "path", "assetTheme", "context", "ext", "sizePx",
               "width", "height", "mono", "bytes", "id", "starred")
# row-dict keys backing each role (the assetTheme role reads the `theme` key)
_ROLE_KEYS = ("name", "path", "theme", "context", "ext", "sizePx",
              "width", "height", "mono", "bytes", "id", "starred")

_MAX_FILTER_ROWS = 20000


def _page_limit() -> int:
    """Grid page size. FENGRID_GRID_PAGE overrides it (QA renders of the
    pagination chip + pagination stress tests; production never sets it)."""
    raw = os.environ.get("FENGRID_GRID_PAGE", "")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _MAX_FILTER_ROWS


# cumulative keyset-pagination ceiling for the grid model — loadMore()
# stops appending here (each row dict ≈ 1 KB in memory; 100k ≈ 100 MB)
_MAX_MODEL_ROWS = 100_000


class AssetModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self):
        return {Qt.ItemDataRole.UserRole + i + 1: QByteArray(n.encode())
                for i, n in enumerate(_ROLE_NAMES)}

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        i = role - Qt.ItemDataRole.UserRole - 1
        return self._rows[index.row()].get(_ROLE_KEYS[i])

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def append_rows(self, extra: list[dict]) -> None:
        """Keyset pagination: append a page WITHOUT resetting the model
        (a reset would snap the grid's scroll position back to the top
        and drop every delegate's live state)."""
        if not extra:
            return
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(extra) - 1)
        self._rows.extend(extra)
        self.endInsertRows()

    def row(self, i: int):
        return self._rows[i] if 0 <= i < len(self._rows) else None

    def rows(self) -> list[dict]:
        return self._rows


def _lists_snapshot(db_path: str) -> dict:
    """PERF-6 (#28): the five rail aggregates, computed on a worker-owned
    connection (WAL reader — never touches the main thread's handle).
    Pure data; no Qt objects cross the thread boundary."""
    # READ-ONLY open: never run schema/migrations from a worker thread —
    # core_db.connect()'s executescript/migrate raced the main thread's
    # own setup and aborted the process under concurrent test startup.
    # A bare rw-open fallback covers the read-only WAL edge case
    # ("disk I/O error" when the -shm can't be initialised read-only).
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                              timeout=30)
        con.execute("SELECT 1")               # force the open to validate
    except sqlite3.OperationalError:
        con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        return _lists_queries(con)
    finally:
        con.close()


def _lists_queries(con: sqlite3.Connection) -> dict:
    # icon-scoped: font rows live in the same asset table and would
    # otherwise pollute the icon rail with "truetype"/"opentype" themes
    # and ttf/otf type entries (user report 2026-10-20)
    themes = [{"name": r[0], "n": r[1]} for r in con.execute(
        "SELECT theme, COUNT(*) FROM asset"
        " WHERE kind = 'icon' AND theme IS NOT NULL"
        " GROUP BY theme ORDER BY theme")]
    contexts = [{"name": r[0], "n": r[1]} for r in con.execute(
        "SELECT context, COUNT(*) FROM asset"
        " WHERE kind = 'icon' AND context IS NOT NULL"
        " GROUP BY context ORDER BY context")]
    exts = [{"name": r[0], "n": r[1]} for r in con.execute(
        "SELECT ext, COUNT(*) FROM asset"
        " WHERE kind = 'icon' AND ext IS NOT NULL"
        " GROUP BY ext ORDER BY ext")]
    tags = []
    kind_counts: dict[str, dict] = {}
    for r in con.execute(
            "SELECT t.name, it.item_kind, COUNT(*) AS n"
            " FROM tag t JOIN item_tag it ON it.tag_id = t.id"
            " GROUP BY t.id, it.item_kind ORDER BY t.name"):
        kind_counts.setdefault(r["name"], {})[r["item_kind"]] = r["n"]
    # name order preserved from the GROUP BY; n stays the ICON count
    # (the icon rail's long-standing display), counts adds per-kind
    for name in kind_counts:
        tags.append({"name": name, "n": kind_counts[name].get("icon", 0),
                     "counts": kind_counts[name]})
    # collections v2: tree order + per-kind counts from collection_ref
    counts: dict[int, dict] = {}
    for r in con.execute(
            "SELECT collection_id, item_kind, COUNT(*) AS n"
            " FROM collection_ref GROUP BY collection_id, item_kind"):
        counts.setdefault(r["collection_id"], {})[r["item_kind"]] = r["n"]
    colls = []
    for r in con.execute(
            "SELECT id, name, parent_id, tags, kind FROM collection"
            " ORDER BY name COLLATE NOCASE"):
        c = {"id": r["id"], "name": r["name"],
             "parentId": r["parent_id"] or 0, "tags": r["tags"] or "",
             "kind": r["kind"]}
        c["counts"] = counts.get(r["id"], {})
        c["n"] = sum(c["counts"].values())
        colls.append(c)
    colls.sort(key=lambda c: (c["parentId"], c["name"].lower()))
    return {"themes": themes, "contexts": contexts, "exts": exts,
            "tags": tags, "collections": colls}


class _ListsWorker(QObject):
    """Owns the `done` signal for the PERF-6 lists worker.

    The pumping side is a DAEMON `threading.Thread` (not a QThread):
    a QThread that outlives its owner aborts the process at teardown
    ("QThread: Destroyed while thread is still running" — qFatal), and
    nothing forces every Library user (tests included) to call
    _on_about_to_quit. A daemon thread dies with the process instead,
    and emitting a QObject Signal from a foreign thread is queued to
    the main thread as usual.
    """
    done = Signal(dict)

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None

    def pump(self) -> None:
        while True:
            db_path = self._queue.get()
            if db_path is None:                   # explicit shutdown
                break
            try:
                self.done.emit(_lists_snapshot(db_path))
            except Exception:                     # noqa: BLE001
                # an unreadable db must not hang the rail — empty lists
                self.done.emit({"themes": [], "contexts": [], "exts": [],
                                "tags": [], "collections": []})


class _ScanWorker(QObject):
    done = Signal(dict)
    failed = Signal(str)
    # throttled: one emit per file flooded the main loop (60k queued
    # invocations per scan) and starved the UI — user read it as a freeze
    progress = Signal(int, str)
    total = Signal(int)

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._last_emit = 0.0

    def _progress(self, n: int, path: str) -> None:
        now = time.monotonic()
        if now - self._last_emit < 0.05:
            return                      # ≤20 updates/s; `done` covers the end
        self._last_emit = now
        self.progress.emit(n, path)

    @Slot()
    def run(self):
        try:
            con = core_db.connect(self._db_path)
            try:
                roots = scanner.platform_candidates()
                # "folder" must be in kinds — user-added sources are kind
                # 'folder' and were silently skipped by the default ("system",)
                sources = indexer.ensure_sources(con, roots,
                                                 kinds=("system", "folder"))
                # pre-count enabled sources for the launch splash's
                # determinate progress bar (warm page cache makes the
                # second walk the scan does anyway nearly free)
                rows = con.execute(
                    "SELECT path FROM source WHERE enabled = 1"
                    " AND kind IN ('system', 'folder')").fetchall()
                total = 0
                for r in rows:
                    for _dirpath, _dirs, files in os.walk(r["path"]):
                        total += len(files)
                self.total.emit(total)
                report = indexer.scan(
                    con, sources, progress=self._progress)
            finally:
                con.close()
            self.done.emit(report)
        except Exception as exc:        # a dead worker must NEVER leave
            # the bridge's `scanning` stuck true (perpetual spinner +
            # every rescan control disabled — the "frozen app" state)
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            # one-shot worker: after the slot returns the thread's event
            # loop would idle forever — quit it so the QThread finishes
            # (destroying a still-running thread aborts the process)
            QThread.currentThread().quit()


class Library(QObject):
    message = Signal(str)
    exportDone = Signal(str)
    exportFailed = Signal(str)
    scanStarted = Signal()
    scanFinished = Signal(dict)
    scanProgress = Signal(int)
    listsChanged = Signal()
    tagsRevision = Signal()
    filtersChanged = Signal()
    scanningChanged = Signal()
    scanCountChanged = Signal()
    scanPathChanged = Signal()
    # grid pagination: total matching rows + whether more pages exist
    gridTotalChanged = Signal()
    scanTotalChanged = Signal()
    lastExportDirChanged = Signal()
    sourcesChanged = Signal()

    def __init__(self, con, db_path: str, no_scan: bool = False, parent=None):
        super().__init__(parent)
        self._con = con
        self._db_path = db_path
        self._model = AssetModel(self)

        self._search = ""
        # default search mode persists across sessions (Settings → Search)
        _mode = settings.get(con, "search_mode", "smart")
        self._search_mode = _mode if _mode in core_search.MODES else "smart"
        self._theme = ""
        self._context = ""
        self._ext = ""
        self._tag = ""
        self._collection = ""       # "" = all, otherwise collection id (str)
        # multi-tag view filter (saved libraries) + active smart collection —
        # both are taxonomy-layer overlays over the single-tag filter
        self._tags_filter: list[str] = []
        self._tags_all = False
        self._active_view = 0       # library_view id, 0 = none
        self._active_smart = 0      # smart_collection id, 0 = none
        self._smart_crit: dict = {}

        self._scanning = False
        self._rescan_pending = False
        self._scan_count = 0
        self._scan_total = 0
        self._scan_path = ""
        self._last_scan = settings.get(con, "last_scan", "") or ""
        self._last_export_dir = settings.get(con, "last_export_dir", "") or ""
        self._index_by_id: dict[int, int] = {}
        self._thread: QThread | None = None
        self._worker: _ScanWorker | None = None

        self._lists: dict[str, list] = {"themes": [], "contexts": [], "exts": [],
                                        "tags": [], "collections": []}
        self._sources_cache: list[dict] | None = None
        # rail-list refresh coalescing: mutations mark dirty and ONE
        # debounced flush rebuilds the lists (at 1M assets the five
        # GROUP BY aggregates cost real time — paying them per mutation
        # of a 1000-item bulk star froze the UI; with the debounce the
        # whole batch costs one refresh)
        self._lists_dirty = False
        self._lists_timer: QTimer | None = None
        # PERF-6 (#28): persistent background lists worker (daemon thread)
        self._lists_thread: threading.Thread | None = None
        self._lists_worker = None
        self._lists_running = False
        # grid pagination state (idx_asset_grid keyset pages; see loadMore)
        self._grid_total = 0
        self._grid_capped = False
        self._apply_filters()
        self._refresh_lists(background=True)   # PERF-6: aggregates off-main
        QCoreApplication.instance().aboutToQuit.connect(self._on_about_to_quit)

    def _mark_lists_dirty(self) -> None:
        """Coalesced refresh: mutations schedule one lists rebuild 150 ms
        out instead of running the aggregates inline (and N times for an
        N-item batch — a 1000-item bulk star paid the five GROUP BY
        aggregates 1000 times). Reads that need freshness NOW call
        _refresh_lists directly (tests do)."""
        self._lists_dirty = True
        if self._lists_timer is None:
            self._lists_timer = QTimer(self)
            self._lists_timer.setSingleShot(True)
            self._lists_timer.setInterval(150)
            self._lists_timer.timeout.connect(self._flush_lists)
        self._lists_timer.start()

    def _flush_lists(self) -> None:
        if not self._lists_dirty:
            return
        self._lists_dirty = False
        self._refresh_lists(background=True)   # PERF-6: aggregates off-main

    def _on_about_to_quit(self) -> None:
        # the scan worker runs on its own connection; give the thread a chance
        # to stop before its object is torn down, otherwise Qt logs
        # "QThread: Destroyed while thread is still running" on exit
        self._rescan_pending = False  # a queued drain must not restart a scan
        if self._lists_worker is not None:      # stop the daemon pump
            self._lists_worker._queue.put(None)
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(10000)

    # ------------------------------------------------------------------ model
    @Property("QVariant", constant=True)
    def model(self):
        return self._model

    @Property(int, notify=listsChanged)
    def totalAssets(self):
        return self._con.execute("SELECT COUNT(*) FROM asset").fetchone()[0]

    @Property(int, notify=listsChanged)
    def iconCount(self):
        # icon-only count for the rail's "All assets" row (totalAssets
        # includes font rows and would inflate the icons-pane figure)
        return self._con.execute(
            "SELECT COUNT(*) FROM asset WHERE kind = 'icon'").fetchone()[0]

    @Property(bool, notify=listsChanged)
    def needsScan(self):
        return self.totalAssets == 0

    @Property(str, notify=scanningChanged)
    def lastScan(self):
        return self._last_scan

    @Property(bool, notify=scanningChanged)
    def scanning(self):
        return self._scanning

    @Property(int, notify=scanCountChanged)
    def scanCount(self):
        return self._scan_count

    @Property(int, notify=scanTotalChanged)
    def scanTotal(self) -> int:
        """Pre-counted file total for the launch splash bar (0 = not yet
        known → the bar runs indeterminate)."""
        return self._scan_total

    @Property(int, notify=gridTotalChanged)
    def gridTotal(self) -> int:
        """Rows matching the ACTIVE filters in the database (all pages,
        not just what the model loaded) — the pagination chip's 'of N'."""
        return self._grid_total

    @Property(bool, notify=gridTotalChanged)
    def gridCapped(self) -> bool:
        """True while more matching rows exist than the model holds —
        the grid shows the 'showing X of N' chip and loadMore() on
        scroll-end keeps appending keyset pages."""
        return self._grid_capped

    @Property(str, notify=scanPathChanged)
    def scanPath(self) -> str:
        """Latest file under the scanner — live splash status text."""
        return self._scan_path

    @Property(str, notify=lastExportDirChanged)
    def lastExportDir(self):
        # live read: the dataio bridge also writes this key (settings
        # screens are rebuilt on open, so no extra notify is needed)
        return settings.get(self._con, "last_export_dir", "") \
            or self._last_export_dir

    @Property(str, constant=True)
    def appVersion(self):
        return __version__

    # ------------------------------------------------------------- filter state
    @Property(str, notify=filtersChanged)
    def themeFilter(self):
        return self._theme

    @Property(str, notify=filtersChanged)
    def contextFilter(self):
        return self._context

    @Property(str, notify=filtersChanged)
    def extFilter(self):
        return self._ext

    @Property(str, notify=filtersChanged)
    def tagFilter(self):
        return self._tag

    @Property(str, notify=filtersChanged)
    def activeLibraryView(self):
        return "" if not self._active_view else str(self._active_view)

    @Property(str, notify=filtersChanged)
    def activeSmart(self):
        return "" if not self._active_smart else str(self._active_smart)

    @Property(str, notify=filtersChanged)
    def collectionFilter(self):
        return self._collection

    # ------------------------------------------------------------------- lists
    @Property("QVariantList", notify=listsChanged)
    def themes(self):
        return self._lists["themes"]

    @Property("QVariantList", notify=listsChanged)
    def contexts(self):
        return self._lists["contexts"]

    @Property("QVariantList", notify=listsChanged)
    def exts(self):
        return self._lists["exts"]

    @Property("QVariantList", notify=listsChanged)
    def tags(self):
        return self._lists["tags"]

    @Property("QVariantList", notify=listsChanged)
    def collections(self):
        return self._lists["collections"]

    # ------------------------------------------------------------------- slots
    @Property(str, notify=filtersChanged)
    def searchMode(self):
        return self._search_mode

    @Slot(str)
    def set_search_mode(self, mode: str) -> None:
        """smart (FTS) | fuzzy | regex | content — content also surfaces
        snippet matches through a message; the grid shows asset hits."""
        if mode not in core_search.MODES or mode == self._search_mode:
            return
        self._search_mode = mode
        settings.set(self._con, "search_mode", mode)
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot(str, result="QVariant")
    def content_snippets(self, term: str) -> list:
        """Snippet content-search hits for the toast/quick list (the grid
        itself shows asset hits in content mode)."""
        return [{"id": r["id"], "title": r["title"]}
                for r in self._con.execute(
                    "SELECT id, title FROM snippet WHERE lower(title) LIKE ?"
                    " OR lower(description) LIKE ? OR lower(tags) LIKE ?"
                    " OR lower(html) LIKE ? OR lower(css) LIKE ?"
                    " OR lower(js) LIKE ? LIMIT 20",
                    ["%" + term.lower() + "%"] * 6).fetchall()]

    # ── generic starring (any asset kind) — the PropertiesPanel toggle
    # uses this so palettes/snippets/fonts land in the Starred collection
    # exactly like icons do ──
    @Slot(str, int, bool)
    def set_item_starred(self, kind: str, item_id: int, starred: bool) -> None:
        core_db.set_starred(self._con, int(item_id), bool(starred), kind=kind)
        self._mark_lists_dirty()
        if starred:
            self.message.emit(
                f"Starred {kind} #{item_id} — added to Starred Assets")
        else:
            self.message.emit(f"Unstarred {kind} #{item_id}")

    @Slot(str, result=int)
    def starred_count(self, kind: str) -> int:
        """Starred-item count for one kind — the rail's Starred row."""
        row = self._con.execute(
            "SELECT COUNT(*) FROM item_tag it JOIN tag t ON t.id = it.tag_id"
            " WHERE t.name = ? AND it.item_kind = ?",
            ("starred", kind)).fetchone()
        return int(row[0])

    @Slot(str, str)
    def rename_tag(self, old: str, new: str) -> None:
        if core_db.rename_tag(self._con, old, new):
            self._mark_lists_dirty()
            self._apply_filters()
            self.tagsRevision.emit()
            self.message.emit(f"Tag renamed: {new.strip()}")
        else:
            self.message.emit("Rename failed (missing or duplicate name)")

    @Slot(str)
    def delete_tag(self, name: str) -> None:
        if core_db.delete_tag(self._con, name):
            self._mark_lists_dirty()
            if self._tag == name:
                self._tag = ""
                self.filtersChanged.emit()
            self._apply_filters()
            self.tagsRevision.emit()
            self.message.emit(f"Tag deleted: {name}")
        else:
            self.message.emit("Tag not found")

    @Slot(str)
    def set_search(self, term: str) -> None:
        self._search = term or ""
        self._apply_filters()

    @Slot(str)
    def set_theme(self, name: str) -> None:
        self._theme = "" if name == self._theme else (name or "")
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot(str)
    def set_context(self, name: str) -> None:
        self._context = "" if name == self._context else (name or "")
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot(str)
    def set_ext(self, name: str) -> None:
        self._ext = "" if name == self._ext else (name or "")
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot(str)
    def set_tag(self, name: str) -> None:
        self._tag = "" if name == self._tag else (name or "")
        # a single-tag pick supersedes any active view/smart overlay
        self._tags_filter = []
        self._active_view = 0
        self._active_smart = 0
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot(str, bool)
    def set_tags(self, tags_csv: str, match_all: bool) -> None:
        """Multi-tag filter (a saved library's tag set)."""
        tag_list = [t.strip() for t in (tags_csv or "").split(",")
                    if t.strip()]
        self._tags_filter = tag_list
        self._tags_all = bool(match_all)
        self._active_smart = 0
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot(str)
    def set_library_view(self, view_id: str) -> None:
        """Activate a saved library view (toggles off on a second click)."""
        vid = int(view_id) if str(view_id).strip().isdigit() else 0
        if vid and vid == self._active_view:
            vid = 0
        self._active_view = vid
        self._active_smart = 0
        if vid:
            row = self._con.execute(
                "SELECT tags, match_all FROM library_view WHERE id = ?",
                (vid,)).fetchone()
            if row is None:
                self._active_view = 0
                self._tags_filter = []
            else:
                self._tags_filter = [t.strip() for t in
                                     (row["tags"] or "").split(",")
                                     if t.strip()]
                self._tags_all = bool(row["match_all"])
                self._theme = self._context = self._ext = ""
        else:
            self._tags_filter = []
            self._tags_all = False
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot(str)
    def set_smart_collection(self, sc_id: str) -> None:
        """Activate a smart collection: resets the single filters and applies
        the stored criteria as the current view (toggles off on re-click)."""
        sid = int(sc_id) if str(sc_id).strip().isdigit() else 0
        if sid and sid == self._active_smart:
            sid = 0
        self._active_smart = sid
        self._active_view = 0
        self._tags_filter = []
        self._tags_all = False
        self._smart_crit = {}
        self._theme = self._context = self._ext = ""
        self._tag = ""
        if sid:
            row = self._con.execute(
                "SELECT criteria FROM smart_collection WHERE id = ?",
                (sid,)).fetchone()
            if row is not None:
                import json as _json
                try:
                    self._smart_crit = _json.loads(row["criteria"] or "{}")
                except ValueError:
                    self._smart_crit = {}
                self._theme = str(self._smart_crit.get("theme") or "")
                self._context = str(self._smart_crit.get("context") or "")
                self._ext = str(self._smart_crit.get("ext") or "")
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot(str)
    def set_collection(self, coll: str) -> None:
        self._collection = "" if str(coll) == self._collection else str(coll or "")
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot()
    def clear_filters(self) -> None:
        self._theme = self._context = self._ext = ""
        self._tag = self._collection = ""
        self._tags_filter = []
        self._tags_all = False
        self._active_view = 0
        self._active_smart = 0
        self._smart_crit = {}
        self.filtersChanged.emit()
        self._apply_filters()

    @Slot(str, int, result="QVariantList")
    def palette_search(self, query: str, limit: int = 12) -> list:
        """Command-bar asset lookup (Spotlight-style) — deliberately
        independent of the grid's search/filters: typing in the palette
        must not mutate the current view, picking a result reveals it."""
        q = (query or "").strip()
        if not q:
            return []
        like = f"%{q}%"
        rows = self._con.execute(
            "SELECT id, name, path, kind, family FROM asset"
            " WHERE name LIKE ? OR path LIKE ?"
            " ORDER BY (name LIKE ?) DESC, LENGTH(name), name LIMIT ?",
            (like, like, q + "%", max(1, min(int(limit), 50)))).fetchall()
        return [{"id": r["id"], "name": r["name"], "path": r["path"],
                 "kind": r["kind"], "family": r["family"] or ""}
                for r in rows]

    @Slot(str, result=int)
    def index_of_path(self, path: str) -> int:
        """Row of `path` in the CURRENT (filtered) model — the palette's
        reveal target (grid.currentIndex is a plain model row); -1 when
        the active filters hide it."""
        for i in range(self._model.rowCount()):
            row = self._model.row(i)
            if row and row.get("path") == path:
                return i
        return -1

    @Slot(int)
    def copy_name(self, index: int) -> None:
        row = self._model.row(index)
        if not row:
            return
        QGuiApplication.clipboard().setText(row["name"])
        self.message.emit(f"Copied '{row['name']}'")

    @Slot(str)
    def copy_text(self, text: str) -> None:
        """Clipboard helper for inspector fields (GUID copy etc.)."""
        if not text:
            return
        QGuiApplication.clipboard().setText(str(text))
        self.message.emit("Copied to clipboard")

    @Slot(int, result="QVariantMap")
    def get_details(self, index: int) -> dict:
        row = self._model.row(index)
        if not row:
            return {}
        d = dict(row)
        d["kind"] = "icon"
        d["tags"] = core_db.tags_for(self._con, row["id"], kind="icon")
        d["variants"] = core_db.variants_for(self._con, row["id"])
        d["starred"] = core_db.is_starred(self._con, row["id"], kind="icon")
        d["fields"] = core_tax.asset_field_values(self._con, row["id"],
                                                  kind="icon")
        return d

    @Slot(int, result=int)
    def row_of_asset(self, asset_id: int) -> int:
        return self._index_by_id.get(int(asset_id), -1)

    # ------------------------------------------------- multi-selection
    def _clean_ids(self, ids) -> list[int]:
        """Checkbox multi-selection ids → deduped positive ints."""
        out = []
        for v in ids or []:
            try:
                i = int(v)
            except (TypeError, ValueError):
                continue
            if i > 0:
                out.append(i)
        return list(dict.fromkeys(out))

    @Slot("QVariantList", result="QVariantMap")
    def selection_details(self, ids) -> dict:
        """Aggregate properties over the checkbox multi-selection — the
        inspector's multi-select summary. One read-only query over the
        id list (clamped to kind='icon': the grid selection is icons
        only); ids outside the current filter still count, unknown ids
        silently drop. Returns {} for an empty selection."""
        id_list = self._clean_ids(ids)
        if not id_list:
            return {}
        marks = ",".join("?" * len(id_list))
        rows = self._con.execute(
            f"SELECT id, name, path, ext, bytes, width, height, size_px,"
            f" mono, color_count, theme, context FROM asset"
            f" WHERE kind = 'icon' AND id IN ({marks})", id_list).fetchall()
        if not rows:
            return {}
        n = len(rows)
        total_bytes = 0
        fmts: dict[str, int] = {}
        widths: list[int] = []
        heights: list[int] = []
        sizes: set[int] = set()
        mono = color = 0
        color_counts: list[int] = []
        themes: set[str] = set()
        contexts: set[str] = set()
        paths: list[str] = []
        names: list[str] = []
        for r in rows:
            total_bytes += r["bytes"] or 0
            ext = (r["ext"] or "").lower()
            if ext:
                fmts[ext] = fmts.get(ext, 0) + 1
            if r["width"]:
                widths.append(r["width"])
            if r["height"]:
                heights.append(r["height"])
            if r["size_px"]:
                sizes.add(r["size_px"])
            if r["mono"] == 1:
                mono += 1
            elif r["mono"] == 0:
                color += 1
            if r["color_count"] is not None:
                color_counts.append(r["color_count"])
            if r["theme"]:
                themes.add(r["theme"])
            if r["context"]:
                contexts.add(r["context"])
            paths.append(r["path"])
            names.append(r["name"])
        # tags over the selection: 'starred' counted separately, tags
        # applied to EVERY selected asset surface as "shared tags"
        per_tag: dict[str, set] = {}
        starred = 0
        for r in self._con.execute(
                f"SELECT it.item_id, t.name FROM item_tag it"
                f" JOIN tag t ON t.id = it.tag_id"
                f" WHERE it.item_kind = 'icon' AND it.item_id IN ({marks})",
                id_list).fetchall():
            if r["name"] == "starred":
                starred += 1
                continue
            per_tag.setdefault(r["name"], set()).add(r["item_id"])
        shared = sorted(t for t, members in per_tag.items()
                        if len(members) == n)
        d: dict = {
            "count": n,
            "names": names,
            "paths": paths,
            "bytes": total_bytes,
            "formats": [{"ext": e, "n": c} for e, c in
                        sorted(fmts.items(), key=lambda kv: (-kv[1], kv[0]))],
            "mono": mono,
            "color": color,
            "starred": starred,
            "sharedTags": shared,
            "themes": sorted(themes),
            "contexts": sorted(contexts),
        }
        if widths:
            d["minW"] = min(widths)
            d["maxW"] = max(widths)
        if heights:
            d["minH"] = min(heights)
            d["maxH"] = max(heights)
        if sizes:
            d["sizes"] = sorted(sizes)
        if color_counts:
            d["avgColors"] = round(sum(color_counts) / len(color_counts), 1)
        return d

    @Slot("QVariantList", result="QVariantList")
    def selection_paths(self, ids) -> list:
        """Filesystem paths of the checkbox selection, in selection
        order — the bulk-export job's input list."""
        id_list = self._clean_ids(ids)
        if not id_list:
            return []
        rows = self._con.execute(
            "SELECT id, path FROM asset WHERE kind = 'icon'"
            f" AND id IN ({','.join('?' * len(id_list))})", id_list).fetchall()
        by_id = {r["id"]: r["path"] for r in rows}
        # selection order, not database order
        return [by_id[i] for i in id_list if i in by_id]

    @Slot("QVariantList")
    def copy_names(self, ids) -> None:
        """Clipboard: one name per line for the whole selection."""
        names = self.selection_details(ids).get("names") or []
        if not names:
            return
        QGuiApplication.clipboard().setText("\n".join(str(x) for x in names))
        self.message.emit(f"Copied {len(names)} names")

    # ------------------------------------------------------------ starring
    @Slot(int, result=bool)
    def is_starred(self, index: int) -> bool:
        row = self._model.row(index)
        if not row:
            return False
        return core_db.is_starred(self._con, row["id"], kind="icon")

    @Slot(int, bool)
    def set_starred_item(self, item_id: int, starred: bool) -> None:
        """Star/unstar an icon asset BY ID (multi-select bulk actions)."""
        core_db.set_starred(self._con, int(item_id), bool(starred),
                            kind="icon")
        self._mark_lists_dirty()
        self.tagsRevision.emit()
        self._apply_filters()

    def set_starred(self, index: int, starred: bool) -> None:
        row = self._model.row(index)
        if not row:
            return
        core_db.set_starred(self._con, row["id"], bool(starred), kind="icon")
        self._mark_lists_dirty()
        self.tagsRevision.emit()
        self._apply_filters()
        if starred:
            self.message.emit(f"Starred '{row['name']}' — added to Starred Assets")
        else:
            self.message.emit(f"Unstarred '{row['name']}'")

    @Slot(int, str)
    def add_tag(self, index: int, name: str) -> None:
        row = self._model.row(index)
        name = (name or "").lstrip("#").strip()
        if not row or not name:
            return
        con = self._con
        tid = con.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()
        if tid:
            tid = tid[0]
        else:
            tid = con.execute("INSERT INTO tag(name) VALUES (?)", (name,)).lastrowid
        con.execute("INSERT OR IGNORE INTO item_tag(item_id, item_kind,"
                    " tag_id) VALUES (?, 'icon', ?)", (row["id"], tid))
        con.commit()
        self._mark_lists_dirty()
        self.tagsRevision.emit()
        self.message.emit(f"Tagged '{row['name']}' with #{name}")

    @Slot(int, str)
    def remove_tag(self, index: int, name: str) -> None:
        row = self._model.row(index)
        if not row:
            return
        self._con.execute(
            "DELETE FROM item_tag WHERE item_id = ? AND item_kind = 'icon'"
            " AND tag_id = (SELECT id FROM tag WHERE name = ?)",
            (row["id"], name))
        self._con.commit()
        self._mark_lists_dirty()
        self.tagsRevision.emit()

    # ------------------------------------------------ collections v2 (tree,
    # tags, all asset kinds)
    @Slot(str, int, str, result=int)
    def create_sub_collection(self, name: str, parent_id: int = 0,
                              tags: str = "", kind: str = "") -> int:
        cid = core_db.create_sub_collection(self._con, name, parent_id,
                                            tags, kind)
        self._mark_lists_dirty()
        self.message.emit(f"Collection '{(name or '').strip()}' created")
        return cid

    @Slot(int, str)
    def set_collection_tags(self, coll_id: int, tags: str) -> None:
        core_db.set_collection_tags(self._con, coll_id, tags)
        self._mark_lists_dirty()

    @Slot(int)
    def delete_collection(self, coll_id: int) -> None:
        core_db.delete_collection(self._con, coll_id)
        if str(coll_id) == self._collection:
            self._collection = ""
            self.filtersChanged.emit()
        self._mark_lists_dirty()
        self._apply_filters()
        self.message.emit("Collection deleted")

    @Slot(int, str, int, str, result=bool)
    def add_ref(self, coll_id: int, kind: str, item_id: int,
                label: str = "") -> bool:
        ok = core_db.add_collection_ref(self._con, coll_id, kind, item_id,
                                        label)
        self._mark_lists_dirty()
        if ok:
            self.message.emit(f"Added to collection ({kind})")
        else:
            self.message.emit("Could not add — item not found")
        return ok

    @Slot(int)
    def remove_ref(self, ref_id: int) -> None:
        core_db.remove_collection_ref(self._con, ref_id)
        self._mark_lists_dirty()
        self._apply_filters()

    @Slot(int, result="QVariant")
    def collection_members(self, coll_id: int) -> list:
        return core_db.refs_for(self._con, coll_id)

    @Slot(str, str, result=int)
    def create_collection(self, name: str, kind: str = "") -> int:
        name = (name or "").strip()
        if not name:
            return -1
        kind = (kind or "").strip()
        row = self._con.execute(
            "SELECT id FROM collection WHERE name = ? AND kind IS ?",
            (name, kind or None)).fetchone()
        if row:
            self._mark_lists_dirty()
            return row[0]
        cur = self._con.execute(
            "INSERT INTO collection(name, kind) VALUES (?, ?)",
            (name, kind or None))
        self._con.commit()
        self._mark_lists_dirty()
        self.message.emit(f"Collection '{name}' created")
        return cur.lastrowid

    @Slot(int, int)
    def add_to_collection(self, index: int, coll_id: int) -> None:
        row = self._model.row(index)
        if not row:
            return
        ok = core_db.add_collection_ref(self._con, coll_id, "icon",
                                        row["id"], row["name"])
        self._mark_lists_dirty()
        if ok:
            self.message.emit(f"Added '{row['name']}' to collection")
        else:
            self.message.emit("Could not add to collection")

    # ------------------------------------------------- generic (per-kind)
    @Slot(str, int, bool)
    def star_item(self, kind: str, item_id: int, starred: bool) -> None:
        """Star/unstar ANY tracked kind by row id — the shared context
        menu entry (fonts, palettes, snippets, icons…)."""
        core_db.set_starred(self._con, int(item_id), bool(starred),
                            kind=kind)
        self._mark_lists_dirty()
        self.tagsRevision.emit()
        self.message.emit("Starred" if starred else "Unstarred")

    @Slot(int, str, int, str)
    def add_item_to_collection(self, coll_id: int, kind: str,
                               item_id: int, name: str = "") -> None:
        ok = core_db.add_collection_ref(self._con, int(coll_id), kind,
                                        int(item_id), name)
        self._mark_lists_dirty()
        self.message.emit("Added to collection" if ok
                          else "Could not add to collection")

    @Slot(int, result=int)
    def row_id(self, i: int) -> int:
        """Asset id at a model row (multi-select range fills)."""
        r = self._model.row(int(i))
        return int(r["id"]) if r else -1

    @Slot(str, int, result=bool)
    def is_item_starred(self, kind: str, item_id: int) -> bool:
        return core_db.is_starred(self._con, int(item_id), kind=kind)

    @Slot(str)
    @Slot(str, str)
    def add_folder(self, path: str, kind: str = "folder") -> None:
        """Register an asset folder ('folder' = icons, 'fontroot' =
        fonts) and rescan. Icon folders rescan here; for font folders
        the caller rescans fonts (fonts bridge owns that worker)."""
        # dialog callers may hand over a file:// URL — QUrl.toLocalFile
        # converts Windows drive-letter URLs (file:///D:/…) correctly;
        # a substring slice would leave "/D:/…" and isdir would fail (#41)
        p = str(Path(core_paths.local_path(path)).expanduser())
        if not os.path.isdir(p):
            self.message.emit(f"Not a folder: {p}")
            return
        indexer.add_folder_source(self._con, p, kind=kind)
        self.message.emit(f"Added folder: {p}")
        self._sources_cache = None
        self.sourcesChanged.emit()
        if kind == "fontroot":
            return
        self.rescan()

    @Slot(int)
    def remove_folder(self, source_id: int) -> None:
        """Forget a source: its assets, taxonomy links and fingerprints
        are purged by indexer.remove_source; models refresh here."""
        if indexer.remove_source(self._con, source_id):
            self.message.emit("Removed source")
        else:
            self.message.emit("Source not found")
        self._sources_cache = None
        self.sourcesChanged.emit()
        self.refresh()

    @Slot(str, str, bool)
    def set_path_enabled(self, path: str, kind: str, enabled: bool) -> None:
        """Toggle a detected system path or user folder (Settings /
        first-run). The flag is persisted immediately; the purge or
        re-index happens in the next scan, which the caller triggers."""
        indexer.set_path_enabled(self._con, path, kind, enabled)
        self._sources_cache = None
        self.sourcesChanged.emit()

    @Slot()
    def refresh(self) -> None:
        """Public model refresh for QML after source mutations that
        don't run a scan (toggles, removes)."""
        self._mark_lists_dirty()
        self._apply_filters()

    @Property("QVariantList", notify=sourcesChanged)
    def sources(self):
        """All registered sources with per-source asset counts — the
        Settings / first-run library section binds to this."""
        if self._sources_cache is not None:
            return self._sources_cache
        t0 = time.perf_counter()
        out = []
        for s in indexer.sources_summary(self._con):
            s = dict(s)
            s["enabled"] = bool(s["enabled"])
            out.append(s)
        self._sources_cache = out
        dt = time.perf_counter() - t0
        if dt > _SLOW_SUMMARY_S:
            # #61: this read kept showing up in freeze dumps with
            # contradictory theories (slow query, lock contention,
            # storage stall — each disproven by the next dump). Record
            # the ACTUAL duration so the next report distinguishes a
            # genuinely slow read from a slow QML load around it.
            self._log_slow(f"sources_summary {dt:.2f}s")
        return out

    def _log_slow(self, line: str) -> None:
        try:
            with open(os.path.join(os.path.dirname(self._db_path)
                                   if self._db_path else ".",
                                   "crash.log"), "a",
                      encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} — slow: "
                        f"{line}\n")
        except OSError:
            pass

    @Slot(str)
    def remove_folder_path(self, path: str) -> None:
        """Detach path used by Storage: forget the source feeding a
        removed mount (resolve first — sources store resolved paths)."""
        try:
            resolved = str(Path(path).expanduser().resolve())
        except OSError:
            resolved = path
        row = self._con.execute("SELECT id FROM source WHERE path = ?",
                                (resolved,)).fetchone() \
            or self._con.execute("SELECT id FROM source WHERE path = ?",
                                 (path,)).fetchone()
        if row is None:
            return
        self.remove_folder(row["id"])

    @Slot(str)
    def import_state_json(self, path: str) -> None:
        try:
            data = migrate.load_json(path)
            counts = migrate.import_state(self._con, data)
        except Exception as e:  # user-supplied file — report, don't crash
            self.exportFailed.emit(f"Import failed: {e}")
            return
        self._mark_lists_dirty()
        self._apply_filters()
        self.tagsRevision.emit()
        self.message.emit(
            f"Imported: {counts['tag_links']} tag links,"
            f" {counts['collection_links']} collection items")

    @Slot(int, str, str, str)
    def export_asset(self, index: int, fmt: str, size: str, dest_dir: str) -> None:
        row = self._model.row(index)
        if not row:
            self.exportFailed.emit("no asset selected")
            return
        if not dest_dir:
            self.exportFailed.emit("choose a folder first")
            return
        dest = str(Path(dest_dir).expanduser())
        size_val = None if size in (None, "", "orig") else int(size)
        ext = (row.get("ext") or "").lower()
        try:
            if ext == "svg":
                tmp = self._render_svg(row["path"], size_val or 512)
                try:
                    out = core_export.export(tmp, dest, row["name"], fmt, None)
                finally:
                    os.unlink(tmp)
            else:
                out = core_export.export(row["path"], dest, row["name"], fmt,
                                         size_val)
        except ExportError as e:
            self.exportFailed.emit(str(e))
            return
        settings.set(self._con, "last_export_dir", dest)
        self.lastExportDirChanged.emit()
        self.exportDone.emit(str(out))

    @Slot()
    def rescan(self) -> None:
        if self._scanning:
            # queue instead of dropping: the first-run screen adds folders
            # WHILE the initial scan runs — a dropped call would leave the
            # new folder unindexed until the next manual rescan
            self._rescan_pending = True
            return
        self._scanning = True
        self._scan_count = 0
        self._scan_total = 0
        self._scan_path = ""
        self.scanningChanged.emit()
        self.scanCountChanged.emit()
        self.scanTotalChanged.emit()
        self.scanPathChanged.emit()
        self.scanStarted.emit()

        th = QThread(self)
        wk = _ScanWorker(self._db_path)
        self._thread, self._worker = th, wk
        wk.moveToThread(th)
        wk.progress.connect(self._on_scan_progress)
        wk.total.connect(self._on_scan_total)
        wk.failed.connect(self._on_scan_failed)
        wk.done.connect(self._on_scan_done)
        th.started.connect(wk.run)
        th.finished.connect(wk.deleteLater)
        th.finished.connect(th.deleteLater)
        th.finished.connect(lambda t=th: self._clear_thread_refs(t))
        th.start()

    # ------------------------------------------------------------------ internals
    def _clear_thread_refs(self, t) -> None:
        # only clear OUR generation: with one-shot workers (they quit
        # their event loop when done) a finished event can arrive after
        # a newer rescan already installed the next thread
        if self._thread is t:
            self._thread = None
            self._worker = None

    def _on_scan_progress(self, n: int, path: str = "") -> None:
        self._scan_count = n
        self.scanCountChanged.emit()
        if path and path != self._scan_path:
            self._scan_path = path
            self.scanPathChanged.emit()

    def _on_scan_total(self, n: int) -> None:
        self._scan_total = int(n)
        self.scanTotalChanged.emit()

    def _on_scan_failed(self, err: str) -> None:
        # the worker died — never leave `scanning` stuck true (that state
        # kept the spinner alive and disabled every rescan control; the
        # user read it as a frozen app)
        self._scanning = False
        self.scanningChanged.emit()
        self.scanFinished.emit({})
        self.message.emit(f"Scan failed: {err}")

    def _on_scan_done(self, report: dict) -> None:
        self._scanning = False
        self._last_scan = time.strftime("%H:%M:%S")
        settings.set(self._con, "last_scan", self._last_scan)
        self.scanningChanged.emit()
        # #141: a scan may have just indexed a downloaded pack's clone —
        # reconcile the download collections (idempotent, cheap when
        # nothing new landed)
        from ..core import presets as core_presets
        try:
            core_presets.sync_download_collections(self._con)
        except Exception:                          # noqa: BLE001
            pass
        self._mark_lists_dirty()
        self._apply_filters()
        self.scanFinished.emit(report)
        self.message.emit(
            f"Indexed: {report['new']} new, {report['changed']} changed,"
            f" {report['pruned']} pruned ({report['total']} files)")
        # Do NOT emit sourcesChanged here — the background refresh
        # (_mark_lists_dirty -> _flush_lists -> _refresh_lists(background=True))
        # will emit listsChanged when the aggregates are ready. Emitting
        # sourcesChanged on the main thread triggers sources_summary()
        # which freezes the UI on software-rendered machines (#61).
        if self._rescan_pending:
            # deferred, not direct: the finished worker's thread refs are
            # still being cleared in this signal's delivery chain, and a
            # direct rescan() would race _clear_thread_refs
            self._rescan_pending = False
            QTimer.singleShot(0, self.rescan)

    def _refresh_lists(self, background: bool = False) -> None:
        """Rebuild the five rail aggregates.

        PERF-6 (#28): at six-figure asset counts the GROUP BYs cost
        seconds — on the main thread they stall first paint and every
        debounced flush. With ``background`` the aggregates run on a
        PERSISTENT worker thread (one per Library, own read-only WAL
        connection) and the result is swapped in on the main thread
        when it lands; the UI paints with (possibly stale) lists and
        fills in when ready. Synchronous mode (default) is kept for
        tests and forced refreshes.
        """
        if not background:
            # sync path keeps the pre-PERF-6 behaviour exactly: read via
            # the caller's own connection (tests pass odd db_paths — a
            # data dir, a not-yet-created file — and must keep working)
            self._lists = _lists_queries(self._con)
            self.listsChanged.emit()
            return
        if self._lists_running:
            self._lists_dirty = True      # trailing refresh after it lands
            return
        self._ensure_lists_thread()
        self._lists_running = True
        self._lists_worker._queue.put(self._db_path)

    def _ensure_lists_thread(self) -> None:
        if self._lists_thread is not None:
            return
        worker = _ListsWorker(self._db_path)
        worker.done.connect(self._on_lists_ready)      # queued → main thread
        thread = threading.Thread(target=worker.pump,
                                  name="fengrid-lists", daemon=True)
        thread.start()
        self._lists_thread = thread
        self._lists_worker = worker

    def _on_lists_ready(self, snapshot: dict) -> None:
        self._lists_running = False
        self._lists = snapshot
        self.listsChanged.emit()
        # a mutation may have landed while the worker ran — one trailing
        # refresh coalesces all of them
        if self._lists_dirty:
            self._lists_dirty = False
            self._refresh_lists(background=True)

    @staticmethod
    def _row_to_dict(r) -> dict:
        d = dict(r)
        d["sizePx"] = d.pop("size_px")
        return d

    def _grid_core(self) -> tuple[list, list, list]:
        """Shared filter builder for the icons grid: (sql, where, params).
        The page query and the pagination COUNT MUST see identical
        joins/filters — they both consume this."""
        con = self._con
        # `starred` rides along as a computed role so card badges and the
        # context menu need no extra query per delegate
        sql = ["SELECT a.*, EXISTS("
               " SELECT 1 FROM item_tag sit JOIN tag st ON st.id = sit.tag_id"
               " WHERE sit.item_id = a.id AND sit.item_kind = 'icon'"
               " AND st.name = 'starred')"
               " AS starred FROM asset a"]
        where: list[str] = ["a.kind = 'icon'"]   # this pane is icons only
        params: list = []

        term = (self._search or "").strip()
        if term:
            if core_db.has_fts(con):
                sql.append("JOIN asset_fts f ON f.rowid = a.id")
                where.append("asset_fts MATCH ?")
                params.append(" ".join(t + "*" for t in term.split()))
            else:
                where.append("(a.name LIKE ? OR a.path LIKE ?)")
                params += [f"%{term}%", f"%{term}%"]
        if self._theme:
            where.append("a.theme = ?")
            params.append(self._theme)
        if self._context:
            where.append("a.context = ?")
            params.append(self._context)
        if self._ext:
            where.append("a.ext = ?")
            params.append(self._ext)
        if self._tag:
            sql.append("JOIN item_tag it ON it.item_id = a.id"
                       " AND it.item_kind = 'icon'"
                       " JOIN tag t ON t.id = it.tag_id")
            where.append("t.name = ?")
            params.append(self._tag)
        # saved-library multi-tag overlay (match_all = AND every tag)
        if self._tags_filter:
            if self._tags_all:
                for t in self._tags_filter:
                    where.append("EXISTS (SELECT 1 FROM item_tag xt"
                                 " JOIN tag xtn ON xtn.id = xt.tag_id"
                                 " WHERE xt.item_id = a.id"
                                 " AND xt.item_kind = 'icon'"
                                 " AND xtn.name = ?)")
                    params.append(t)
            else:
                marks = ",".join("?" * len(self._tags_filter))
                where.append("a.id IN (SELECT yt.item_id FROM item_tag yt"
                             " JOIN tag ytn ON ytn.id = yt.tag_id"
                             " WHERE yt.item_kind = 'icon'"
                             f" AND ytn.name IN ({marks}))")
                params += self._tags_filter
        # active smart collection: tag/starred/q criteria ride on top (the
        # theme/context/ext criteria were copied into the single filters
        # when the smart row was activated)
        if self._active_smart and self._smart_crit:
            crit = self._smart_crit
            sc_tags = [t.strip() for t in crit.get("tags", []) if t.strip()]
            if sc_tags:
                if crit.get("tag_match_all"):
                    for t in sc_tags:
                        where.append(
                            "EXISTS (SELECT 1 FROM item_tag zt"
                            " JOIN tag ztn ON ztn.id = zt.tag_id"
                            " WHERE zt.item_id = a.id"
                            " AND zt.item_kind = 'icon'"
                            " AND ztn.name = ?)")
                        params.append(t)
                else:
                    marks2 = ",".join("?" * len(sc_tags))
                    where.append("a.id IN (SELECT wt.item_id FROM item_tag wt"
                                 " JOIN tag wtn ON wtn.id = wt.tag_id"
                                 " WHERE wt.item_kind = 'icon'"
                                 f" AND wtn.name IN ({marks2}))")
                    params += sc_tags
            if crit.get("starred"):
                where.append(
                    "a.id IN (SELECT st.item_id FROM item_tag st"
                    " JOIN tag stn ON stn.id = st.tag_id"
                    " WHERE st.item_kind = 'icon'"
                    " AND stn.name = 'starred')")
            if crit.get("q"):
                where.append("(lower(a.name) LIKE ? OR lower(a.path) LIKE ?)")
                like = "%" + str(crit["q"]).lower() + "%"
                params += [like, like]
        if self._collection:
            sql.append("JOIN collection_ref cr ON cr.item_kind = 'icon'"
                       " AND cr.item_id = a.id")
            where.append("cr.collection_id = ?")
            params.append(int(self._collection))
        return sql, where, params

    def _grid_page(self, keyset: tuple | None = None) -> tuple[str, list]:
        """(query, params) for one grid page. `keyset` = (theme, name, id)
        of the last loaded row — a row-value seek into
        idx_asset_grid(kind, theme, name, id), so page N+1 costs an
        ordered range scan instead of re-sorting the whole filtered set.
        SQLite sorts NULLs FIRST, so a page ending inside the unthemed
        block (user-folder assets carry no theme) can't use the row-value
        form ('>' with a NULL member never matches) — that case gets the
        explicit NULL-aware condition."""
        sql, where, params = self._grid_core()
        if keyset is not None:
            kt, kn, kid = keyset
            if kt is None:
                where.append("(a.theme IS NOT NULL OR a.name > ?"
                             " OR (a.name = ? AND a.id > ?))")
                params += [kn, kn, kid]
            else:
                where.append("(a.theme, a.name, a.id) > (?, ?, ?)")
                params += [kt, kn, kid]
        query = " ".join(sql)
        if where:
            query += " WHERE " + " AND ".join(where)
        # trailing a.id tiebreak: duplicate (theme, name) pairs (same-named
        # files in two sources) made the LIMIT boundary unstable — a row
        # could land on two pages or on none
        query += " ORDER BY a.theme, a.name, a.id LIMIT ?"
        params.append(_page_limit())
        return query, params

    def _grid_count(self) -> int:
        """Rows matching the ACTIVE filters across ALL pages — identical
        joins/filters to _grid_page, wrapped in COUNT(*)."""
        sql, where, params = self._grid_core()
        q = " ".join(["SELECT COUNT(*) FROM asset a"] + sql[1:])
        if where:
            q += " WHERE " + " AND ".join(where)
        return self._con.execute(q, params).fetchone()[0]

    def _apply_filters(self) -> None:
        con = self._con
        term = (self._search or "").strip()
        # alternate search modes bypass the FTS query path
        if term and self._search_mode in ("fuzzy", "regex", "content"):
            try:
                rows = core_search.search_assets(con, term, self._search_mode)
            except core_search.SearchError as exc:
                self.message.emit(str(exc))
                rows = []
            self._model.set_rows(rows)
            self._grid_total = len(rows)
            self._grid_capped = False
            self.gridTotalChanged.emit()
            self.listsChanged.emit()
            return

        query, params = self._grid_page()
        rows = [self._row_to_dict(r) for r in con.execute(query, params)]
        self._model.set_rows(rows)
        self._index_by_id = {row["id"]: i for i, row in enumerate(rows)}
        self._grid_total = self._grid_count()
        self._grid_capped = (len(rows) >= _page_limit()
                             and self._grid_total > len(rows))
        self.gridTotalChanged.emit()

    @Slot()
    def loadMore(self) -> None:
        """Append the next keyset page for the active filters (the grid
        calls this at scroll end while gridCapped is true). Refuses once
        the model holds _MAX_MODEL_ROWS rows — past that the user needs
        a narrower filter, not an unbounded in-memory model."""
        rows = self._model.rows()
        if not rows or not self._grid_capped or len(rows) >= _MAX_MODEL_ROWS:
            return
        last = rows[-1]
        query, params = self._grid_page(
            (last.get("theme"), last["name"], last["id"]))
        extra = [self._row_to_dict(r)
                 for r in self._con.execute(query, params)]
        if not extra:
            self._grid_capped = False
            self.gridTotalChanged.emit()
            return
        base = len(rows)
        self._model.append_rows(extra)
        for off, row in enumerate(extra):
            self._index_by_id[row["id"]] = base + off
        if len(self._model.rows()) >= self._grid_total:
            self._grid_capped = False
        self.gridTotalChanged.emit()

    def _render_svg(self, path: str, side: int) -> Path:
        # str filename: Qt 6 removed the implicit QUrl→QString conversion
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            raise ExportError("invalid SVG file")
        img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()
        tmp = Path(tempfile.gettempdir()) / f"fengrid-svg-{os.getpid()}.png"
        if not img.save(str(tmp), "PNG"):
            raise ExportError("SVG rendering failed")
        return tmp
