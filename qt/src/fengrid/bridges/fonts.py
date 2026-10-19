"""Fonts bridge: the Qt model over the SQLite core (fonts v1).

Same shape as bridges/library.py: filters rebuild the model from SQL, the
rescan runs on a QThread with its own DB connection, and export goes through
core/fonts (CSS + zip — no server, matching the native-export policy).
Family previews render in QML via font.family — system fonts are already
registered with QFontDatabase, so no WebEngine is involved in this pane.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QByteArray, QModelIndex,
                            QObject, Property, Qt, QThread, Signal, Slot)
from PySide6.QtGui import QGuiApplication

from ..core import db as core_db
from ..core import fonts as core_fonts
from ..core import indexer, settings

_ROLE_NAMES = ("family", "files", "sample", "weights")
_ROLE_KEYS = ("family", "files", "sample", "weights")


class FamilyModel(QAbstractListModel):
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


class _FontScanWorker(QObject):
    done = Signal(dict)
    progress = Signal(int)

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self.cancelled = False

    @Slot()
    def run(self):
        con = core_db.connect(self._db_path)
        try:
            roots = core_fonts.platform_font_dirs()
            sources = indexer.ensure_sources(con, roots, kinds=("fontroot",))
            report = indexer.scan_fonts(
                con, sources,
                progress=lambda n, p: self.progress.emit(n),
                should_stop=lambda: self.cancelled)
        finally:
            con.close()
        self.done.emit(report)


class Fonts(QObject):
    message = Signal(str)
    exportDone = Signal(str)
    exportFailed = Signal(str)
    scanStarted = Signal()
    scanFinished = Signal(dict)
    scanProgress = Signal(int)
    familiesChanged = Signal()
    selectionChanged = Signal()
    scanningChanged = Signal()
    scanCountChanged = Signal()

    def __init__(self, con, db_path: str, parent=None):
        super().__init__(parent)
        self._con = con
        self._db_path = db_path
        self._model = FamilyModel(self)
        self._filter = ""
        self._selected = ""
        self._scanning = False
        self._scan_count = 0
        self._thread = None
        self._worker = None
        self._refresh()
        QGuiApplication.instance().aboutToQuit.connect(self._on_about_to_quit)

    def _on_about_to_quit(self) -> None:
        # cancel-then-wait: the worker checks the flag per file, so a long
        # first scan cannot wedge the exit path (see indexer.scan_fonts)
        if self._thread is not None:
            self._worker.cancelled = True
            self._thread.quit()
            self._thread.wait(10000)

    # ------------------------------------------------------------------ model
    @Property("QVariant", constant=True)
    def model(self):
        return self._model

    @Property(int, notify=familiesChanged)
    def totalFonts(self):
        return self._con.execute(
            "SELECT COUNT(*) FROM asset WHERE kind = 'font'").fetchone()[0]

    @Property(int, notify=familiesChanged)
    def totalFamilies(self):
        return self._model.rowCount()

    @Property(bool, notify=scanningChanged)
    def scanning(self):
        return self._scanning

    @Property(int, notify=scanCountChanged)
    def scanCount(self):
        return self._scan_count

    @Property(str, notify=selectionChanged)
    def selectedFamily(self):
        return self._selected

    # ------------------------------------------------------------------- slots
    @Slot(str)
    def set_filter(self, term: str) -> None:
        self._filter = (term or "").strip().lower()
        self._refresh()

    @Slot(str)
    def select(self, family: str) -> None:
        self._selected = "" if family == self._selected else (family or "")
        self.selectionChanged.emit()

    @Slot(str, result="QVariantList")
    def family_files(self, family: str) -> list:
        return core_fonts.family_files(self._con, family) \
            if family else []

    @Slot(str, str)
    def export_css(self, family: str, dest_dir: str) -> None:
        self._export(core_fonts.export_family_css, family, dest_dir, "css")

    @Slot(str, str)
    def export_zip(self, family: str, dest_dir: str) -> None:
        self._export(core_fonts.export_family_zip, family, dest_dir, "zip")

    def _export(self, fn, family: str, dest_dir: str, what: str) -> None:
        if not family:
            self.exportFailed.emit("no family selected")
            return
        dest = str(Path(dest_dir).expanduser()) if dest_dir else ""
        if not dest:
            self.exportFailed.emit("choose a folder first")
            return
        try:
            out = fn(self._con, family, dest)
        except (ValueError, OSError) as e:
            self.exportFailed.emit(str(e))
            return
        settings.set(self._con, "last_export_dir", dest)
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
        self._worker = _FontScanWorker(self._db_path)
        self._worker.moveToThread(self._thread)
        self._worker.progress.connect(self._on_scan_progress)
        self._worker.done.connect(self._on_scan_done)
        self._thread.started.connect(self._worker.run)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_thread_refs)
        self._thread.start()

    # -------------------------------------------------------------- internals
    def _clear_thread_refs(self) -> None:
        self._thread = None
        self._worker = None

    def _on_scan_progress(self, n: int) -> None:
        self._scan_count = n
        self.scanCountChanged.emit()

    def _on_scan_done(self, report: dict) -> None:
        self._scanning = False
        self.scanningChanged.emit()
        self._refresh()
        self.scanFinished.emit(report)
        if report.get("aborted"):
            return  # app is quitting; stay silent
        self.message.emit(
            f"Fonts: {report['new']} new, {report['changed']} changed,"
            f" {report['pruned']} pruned ({report['total']} files)")

    def _refresh(self) -> None:
        rows = []
        for fam in core_fonts.families(self._con):
            if self._filter and self._filter not in fam["family"].lower():
                continue
            files = core_fonts.family_files(self._con, fam["family"])
            weights = sorted({f["weight"] for f in files
                              if f["weight"] is not None})
            sample = files[0]["path"] if files else ""
            rows.append({"family": fam["family"], "files": fam["n"],
                         "sample": sample,
                         "weights": ", ".join(str(w) for w in weights) or "—"})
        self._model.set_rows(rows)
        self.familiesChanged.emit()
