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
import tempfile
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
from ..core import indexer, migrate, scanner, search as core_search
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

    def row(self, i: int):
        return self._rows[i] if 0 <= i < len(self._rows) else None

    def rows(self) -> list[dict]:
        return self._rows


class _ScanWorker(QObject):
    done = Signal(dict)
    progress = Signal(int)

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path

    @Slot()
    def run(self):
        con = core_db.connect(self._db_path)
        try:
            sources = indexer.ensure_sources(con, scanner.platform_candidates())
            report = indexer.scan(
                con, sources,
                progress=lambda n, p: self.progress.emit(n))
        finally:
            con.close()
        self.done.emit(report)


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
    lastExportDirChanged = Signal()

    def __init__(self, con, db_path: str, no_scan: bool = False, parent=None):
        super().__init__(parent)
        self._con = con
        self._db_path = db_path
        self._model = AssetModel(self)

        self._search = ""
        self._search_mode = "smart"
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
        self._scan_count = 0
        self._last_scan = settings.get(con, "last_scan", "") or ""
        self._last_export_dir = settings.get(con, "last_export_dir", "") or ""
        self._index_by_id: dict[int, int] = {}
        self._thread: QThread | None = None
        self._worker: _ScanWorker | None = None

        self._lists: dict[str, list] = {"themes": [], "contexts": [], "exts": [],
                                        "tags": [], "collections": []}
        self._apply_filters()
        self._refresh_lists()
        QCoreApplication.instance().aboutToQuit.connect(self._on_about_to_quit)

    def _on_about_to_quit(self) -> None:
        # the scan worker runs on its own connection; give the thread a chance
        # to stop before its object is torn down, otherwise Qt logs
        # "QThread: Destroyed while thread is still running" on exit
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

    @Property(str, notify=lastExportDirChanged)
    def lastExportDir(self):
        return self._last_export_dir

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

    @Slot(str, str)
    def rename_tag(self, old: str, new: str) -> None:
        if core_db.rename_tag(self._con, old, new):
            self._refresh_lists()
            self._apply_filters()
            self.tagsRevision.emit()
            self.message.emit(f"Tag renamed: {new.strip()}")
        else:
            self.message.emit("Rename failed (missing or duplicate name)")

    @Slot(str)
    def delete_tag(self, name: str) -> None:
        if core_db.delete_tag(self._con, name):
            self._refresh_lists()
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

    @Slot(int)
    def copy_name(self, index: int) -> None:
        row = self._model.row(index)
        if not row:
            return
        QGuiApplication.clipboard().setText(row["name"])
        self.message.emit(f"Copied '{row['name']}'")

    @Slot(int, result="QVariantMap")
    def get_details(self, index: int) -> dict:
        row = self._model.row(index)
        if not row:
            return {}
        d = dict(row)
        d["tags"] = core_db.tags_for(self._con, row["id"])
        d["variants"] = core_db.variants_for(self._con, row["id"])
        d["starred"] = core_db.is_starred(self._con, row["id"])
        return d

    @Slot(int, result=int)
    def row_of_asset(self, asset_id: int) -> int:
        return self._index_by_id.get(int(asset_id), -1)

    # ------------------------------------------------------------ starring
    @Slot(int, result=bool)
    def is_starred(self, index: int) -> bool:
        row = self._model.row(index)
        if not row:
            return False
        return core_db.is_starred(self._con, row["id"])

    @Slot(int, bool)
    def set_starred(self, index: int, starred: bool) -> None:
        row = self._model.row(index)
        if not row:
            return
        core_db.set_starred(self._con, row["id"], bool(starred))
        self._refresh_lists()
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
        con.execute("INSERT OR IGNORE INTO asset_tag(asset_id, tag_id) VALUES (?, ?)",
                    (row["id"], tid))
        con.commit()
        self._refresh_lists()
        self.tagsRevision.emit()
        self.message.emit(f"Tagged '{row['name']}' with #{name}")

    @Slot(int, str)
    def remove_tag(self, index: int, name: str) -> None:
        row = self._model.row(index)
        if not row:
            return
        self._con.execute(
            "DELETE FROM asset_tag WHERE asset_id = ? AND tag_id ="
            " (SELECT id FROM tag WHERE name = ?)", (row["id"], name))
        self._con.commit()
        self._refresh_lists()
        self.tagsRevision.emit()

    # ------------------------------------------------ collections v2 (tree,
    # tags, all asset kinds)
    @Slot(str, int, str, result=int)
    def create_sub_collection(self, name: str, parent_id: int = 0,
                              tags: str = "") -> int:
        cid = core_db.create_sub_collection(self._con, name, parent_id, tags)
        self._refresh_lists()
        self.message.emit(f"Collection '{(name or '').strip()}' created")
        return cid

    @Slot(int, str)
    def set_collection_tags(self, coll_id: int, tags: str) -> None:
        core_db.set_collection_tags(self._con, coll_id, tags)
        self._refresh_lists()

    @Slot(int)
    def delete_collection(self, coll_id: int) -> None:
        core_db.delete_collection(self._con, coll_id)
        if str(coll_id) == self._collection:
            self._collection = ""
            self.filtersChanged.emit()
        self._refresh_lists()
        self._apply_filters()
        self.message.emit("Collection deleted")

    @Slot(int, str, int, str, result=bool)
    def add_ref(self, coll_id: int, kind: str, item_id: int,
                label: str = "") -> bool:
        ok = core_db.add_collection_ref(self._con, coll_id, kind, item_id,
                                        label)
        self._refresh_lists()
        if ok:
            self.message.emit(f"Added to collection ({kind})")
        else:
            self.message.emit("Could not add — item not found")
        return ok

    @Slot(int)
    def remove_ref(self, ref_id: int) -> None:
        core_db.remove_collection_ref(self._con, ref_id)
        self._refresh_lists()
        self._apply_filters()

    @Slot(int, result="QVariant")
    def collection_members(self, coll_id: int) -> list:
        return core_db.refs_for(self._con, coll_id)

    @Slot(str, result=int)
    def create_collection(self, name: str) -> int:
        name = (name or "").strip()
        if not name:
            return -1
        row = self._con.execute(
            "SELECT id FROM collection WHERE name = ?", (name,)).fetchone()
        if row:
            self._refresh_lists()
            return row[0]
        cur = self._con.execute(
            "INSERT INTO collection(name) VALUES (?)", (name,))
        self._con.commit()
        self._refresh_lists()
        self.message.emit(f"Collection '{name}' created")
        return cur.lastrowid

    @Slot(int, int)
    def add_to_collection(self, index: int, coll_id: int) -> None:
        row = self._model.row(index)
        if not row:
            return
        ok = core_db.add_collection_ref(self._con, coll_id, "icon",
                                        row["id"], row["name"])
        self._refresh_lists()
        if ok:
            self.message.emit(f"Added '{row['name']}' to collection")
        else:
            self.message.emit("Could not add to collection")

    @Slot(str)
    def add_folder(self, path: str) -> None:
        p = str(Path(path).expanduser())
        if not os.path.isdir(p):
            self.message.emit(f"Not a folder: {p}")
            return
        indexer.add_folder_source(self._con, p)
        self.message.emit(f"Added folder: {p}")
        self.rescan()

    @Slot(str)
    def import_state_json(self, path: str) -> None:
        try:
            data = migrate.load_json(path)
            counts = migrate.import_state(self._con, data)
        except Exception as e:  # user-supplied file — report, don't crash
            self.exportFailed.emit(f"Import failed: {e}")
            return
        self._refresh_lists()
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
            return
        self._scanning = True
        self._scan_count = 0
        self.scanningChanged.emit()
        self.scanStarted.emit()

        self._thread = QThread(self)
        self._worker = _ScanWorker(self._db_path)
        self._worker.moveToThread(self._thread)
        self._worker.progress.connect(self._on_scan_progress)
        self._worker.done.connect(self._on_scan_done)
        self._thread.started.connect(self._worker.run)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_thread_refs)
        self._thread.start()

    # ------------------------------------------------------------------ internals
    def _clear_thread_refs(self) -> None:
        self._thread = None
        self._worker = None

    def _on_scan_progress(self, n: int) -> None:
        self._scan_count = n
        self.scanCountChanged.emit()

    def _on_scan_done(self, report: dict) -> None:
        self._scanning = False
        self._last_scan = time.strftime("%H:%M:%S")
        settings.set(self._con, "last_scan", self._last_scan)
        self.scanningChanged.emit()
        self._refresh_lists()
        self._apply_filters()
        self.scanFinished.emit(report)
        self.message.emit(
            f"Indexed: {report['new']} new, {report['changed']} changed,"
            f" {report['pruned']} pruned ({report['total']} files)")

    def _refresh_lists(self) -> None:
        con = self._con
        themes = [{"name": r[0], "n": r[1]} for r in con.execute(
            "SELECT theme, COUNT(*) FROM asset WHERE theme IS NOT NULL"
            " GROUP BY theme ORDER BY theme")]
        contexts = [{"name": r[0], "n": r[1]} for r in con.execute(
            "SELECT context, COUNT(*) FROM asset WHERE context IS NOT NULL"
            " GROUP BY context ORDER BY context")]
        exts = [{"name": r[0], "n": r[1]} for r in con.execute(
            "SELECT ext, COUNT(*) FROM asset WHERE ext IS NOT NULL"
            " GROUP BY ext ORDER BY ext")]
        tags = [{"name": r[0], "n": r[1]} for r in con.execute(
            "SELECT t.name, COUNT(at.asset_id) AS n FROM tag t"
            " LEFT JOIN asset_tag at ON at.tag_id = t.id"
            " GROUP BY t.id ORDER BY t.name")]
        # collections v2: tree order + per-kind counts from collection_ref
        counts: dict[int, dict] = {}
        for r in con.execute(
                "SELECT collection_id, item_kind, COUNT(*) AS n"
                " FROM collection_ref GROUP BY collection_id, item_kind"):
            counts.setdefault(r["collection_id"], {})[r["item_kind"]] = r["n"]
        colls = []
        for r in con.execute(
                "SELECT id, name, parent_id, tags FROM collection"
                " ORDER BY name COLLATE NOCASE"):
            c = {"id": r["id"], "name": r["name"],
                 "parentId": r["parent_id"] or 0, "tags": r["tags"] or ""}
            c["counts"] = counts.get(r["id"], {})
            c["n"] = sum(c["counts"].values())
            colls.append(c)
        colls.sort(key=lambda c: (c["parentId"], c["name"].lower()))
        self._lists = {"themes": themes, "contexts": contexts, "exts": exts,
                       "tags": tags, "collections": colls}
        self.listsChanged.emit()

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
            self.listsChanged.emit()
            return

        # `starred` rides along as a computed role so card badges and the
        # context menu need no extra query per delegate
        sql = ["SELECT a.*, EXISTS("
               " SELECT 1 FROM asset_tag sat JOIN tag st ON st.id = sat.tag_id"
               " WHERE sat.asset_id = a.id AND st.name = 'starred')"
               " AS starred FROM asset a"]
        where: list[str] = []
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
            sql.append("JOIN asset_tag at ON at.asset_id = a.id"
                       " JOIN tag t ON t.id = at.tag_id")
            where.append("t.name = ?")
            params.append(self._tag)
        # saved-library multi-tag overlay (match_all = AND every tag)
        if self._tags_filter:
            if self._tags_all:
                for t in self._tags_filter:
                    where.append("EXISTS (SELECT 1 FROM asset_tag xt"
                                 " JOIN tag xtn ON xtn.id = xt.tag_id"
                                 " WHERE xt.asset_id = a.id AND xtn.name = ?)")
                    params.append(t)
            else:
                marks = ",".join("?" * len(self._tags_filter))
                where.append("a.id IN (SELECT yt.asset_id FROM asset_tag yt"
                             " JOIN tag ytn ON ytn.id = yt.tag_id"
                             f" WHERE ytn.name IN ({marks}))")
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
                            "EXISTS (SELECT 1 FROM asset_tag zt"
                            " JOIN tag ztn ON ztn.id = zt.tag_id"
                            " WHERE zt.asset_id = a.id AND ztn.name = ?)")
                        params.append(t)
                else:
                    marks2 = ",".join("?" * len(sc_tags))
                    where.append("a.id IN (SELECT wt.asset_id FROM asset_tag wt"
                                 " JOIN tag wtn ON wtn.id = wt.tag_id"
                                 f" WHERE wtn.name IN ({marks2}))")
                    params += sc_tags
            if crit.get("starred"):
                where.append(
                    "a.id IN (SELECT st.asset_id FROM asset_tag st"
                    " JOIN tag stn ON stn.id = st.tag_id"
                    " WHERE stn.name = 'starred')")
            if crit.get("q"):
                where.append("(lower(a.name) LIKE ? OR lower(a.path) LIKE ?)")
                like = "%" + str(crit["q"]).lower() + "%"
                params += [like, like]
        if self._collection:
            sql.append("JOIN collection_ref cr ON cr.item_kind = 'icon'"
                       " AND cr.item_id = a.id")
            where.append("cr.collection_id = ?")
            params.append(int(self._collection))

        query = " ".join(sql)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY a.theme, a.name LIMIT ?"
        params.append(_MAX_FILTER_ROWS)

        rows = []
        for r in con.execute(query, params):
            d = dict(r)
            d["sizePx"] = d.pop("size_px")
            rows.append(d)
        self._model.set_rows(rows)
        self._index_by_id = {row["id"]: i for i, row in enumerate(rows)}

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
