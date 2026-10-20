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
from ..core import indexer, migrate, scanner, settings
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
        self._theme = ""
        self._context = ""
        self._ext = ""
        self._tag = ""
        self._collection = ""       # "" = all, otherwise collection id (str)

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
        self._con.execute(
            "INSERT OR IGNORE INTO collection_item(collection_id, asset_id,"
            " position) VALUES (?, ?,"
            " (SELECT COALESCE(MAX(position), -1) + 1 FROM collection_item"
            "  WHERE collection_id = ?))",
            (coll_id, row["id"], coll_id))
        self._con.commit()
        self._refresh_lists()
        name = self._con.execute(
            "SELECT name FROM collection WHERE id = ?", (coll_id,)).fetchone()
        self.message.emit(f"Added '{row['name']}' to '{name[0] if name else '?'}'")

    @Slot(int)
    def delete_collection(self, coll_id: int) -> None:
        self._con.execute("DELETE FROM collection WHERE id = ?", (coll_id,))
        self._con.commit()
        if self._collection == str(coll_id):
            self._collection = ""
            self.filtersChanged.emit()
            self._apply_filters()
        self._refresh_lists()

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
        colls = [{"id": r[0], "name": r[1], "n": r[2]} for r in con.execute(
            "SELECT c.id, c.name, COUNT(ci.asset_id) AS n FROM collection c"
            " LEFT JOIN collection_item ci ON ci.collection_id = c.id"
            " GROUP BY c.id ORDER BY c.name")]
        self._lists = {"themes": themes, "contexts": contexts, "exts": exts,
                       "tags": tags, "collections": colls}
        self.listsChanged.emit()

    def _apply_filters(self) -> None:
        con = self._con
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
        if self._collection:
            sql.append("JOIN collection_item ci ON ci.asset_id = a.id")
            where.append("ci.collection_id = ?")
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
