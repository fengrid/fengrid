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
                            QObject, Property, Qt, QThread, QTimer, Signal,
                            Slot)
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
    failed = Signal(str)
    progress = Signal(int, str)   # throttled in _progress — see library
    total = Signal(int)

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self.cancelled = False
        self._last_emit = 0.0

    def _progress(self, n: int, path: str) -> None:
        now = time.monotonic()
        if now - self._last_emit < 0.05:
            return
        self._last_emit = now
        self.progress.emit(n, path)

    @Slot()
    def run(self):
        try:
            con = core_db.connect(self._db_path)
            try:
                roots = core_fonts.platform_font_dirs()
                sources = indexer.ensure_sources(con, roots,
                                                 kinds=("fontroot",))
                # pre-count for the launch splash's determinate bar —
                # the walk result is SHARED with scan_fonts (PERF-1:
                # the old code walked every root twice per launch)
                rows = con.execute(
                    "SELECT path FROM source WHERE enabled = 1"
                    " AND kind = 'fontroot'").fetchall()
                walk: dict[str, list] = {}
                total = 0
                for r in rows:
                    files = list(core_fonts.iter_font_files(r["path"]))
                    walk[r["path"]] = files
                    total += len(files)
                self.total.emit(total)
                report = indexer.scan_fonts(
                    con, sources,
                    progress=self._progress,
                    should_stop=lambda: self.cancelled,
                    files_by_root=walk)
            finally:
                con.close()
            self.done.emit(report)
        except Exception as exc:        # never leave `scanning` stuck true
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            # one-shot worker: leave the event loop after the slot
            # returns, or the QThread idles until aboutToQuit and a
            # mid-session bridge teardown aborts the process
            QThread.currentThread().quit()


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
    scanPathChanged = Signal()
    scanTotalChanged = Signal()

    def __init__(self, con, db_path: str, parent=None):
        super().__init__(parent)
        self._con = con
        self._db_path = db_path
        self._model = FamilyModel(self)
        self._filter = ""
        self._family_filter = ""     # rail: exact family
        self._type_filter = ""       # rail: file extension (ttf/otf/…)
        self._families: list = []
        # rail Collections row (fonts pane): None = no filter, else id
        self._collection: int | None = None
        self._smart_id = 0
        self._types: list = []
        self._selected = ""
        self._scanning = False
        self._rescan_pending = False
        self._scan_count = 0
        self._scan_total = 0
        self._scan_path = ""
        self._thread = None
        self._worker = None
        self._refresh()
        QGuiApplication.instance().aboutToQuit.connect(self._on_about_to_quit)

    def _on_about_to_quit(self) -> None:
        # cancel-then-wait: the worker checks the flag per file, so a long
        # first scan cannot wedge the exit path (see indexer.scan_fonts)
        self._rescan_pending = False  # queued drain must not restart a scan
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

    # rail-facing lists (Fonts pane's own left-panel content) + filters
    @Property("QVariantList", notify=familiesChanged)
    def families(self):
        return self._families

    @Property("QVariantList", notify=familiesChanged)
    def fontTypes(self):
        return self._types

    @Property(str, notify=familiesChanged)
    def familyFilter(self):
        return self._family_filter

    @Property(str, notify=familiesChanged)
    def typeFilter(self):
        return self._type_filter

    @Slot(str)
    def set_family_filter(self, family: str) -> None:
        """Rail filter: exact family (toggles off when re-picked)."""
        name = (family or "").strip()
        self._family_filter = "" if name == self._family_filter else name
        self._refresh()

    @Slot(str)
    def set_type_filter(self, ext: str) -> None:
        """Rail filter: only families with a file of this extension."""
        name = (ext or "").strip().lower()
        self._type_filter = "" if name == self._type_filter else name
        self._refresh()

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

    @Property(str, notify=scanPathChanged)
    def scanPath(self) -> str:
        """Latest font file under the scanner — live splash status."""
        return self._scan_path

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

    @Slot(result="QVariantList")
    def family_names(self) -> list:
        """Plain family-name strings (CSS export dialog checkboxes)."""
        return [f["family"] for f in core_fonts.families(self._con)]

    # ── rail Collections row: filter families by collection membership ──
    collectionChanged = Signal()

    @Property(str, notify=collectionChanged)
    def collectionFilter(self) -> str:
        return "" if self._collection is None else str(self._collection)

    @Slot(str)
    def set_collection(self, coll: str) -> None:
        """Toggle the collection filter (fonts pane). Same id twice
        clears it."""
        s = (coll or "").strip()
        cid = int(s) if s.isdigit() else None
        if cid is None or cid == self._collection:
            self._collection = None
        else:
            self._collection = cid
        self.collectionChanged.emit()
        self._refresh()

    @Slot(str)
    def set_smart(self, sc_id: str) -> None:
        """Toggle the smart-collection filter (fonts pane): families
        whose assets satisfy the criteria (name/tag match)."""
        sid = int(sc_id) if str(sc_id).strip().isdigit() else 0
        if sid and sid == self._smart_id:
            sid = 0
        self._smart_id = sid
        self._refresh()

    @Property(str, notify=collectionChanged)
    def smartFilter(self) -> str:
        return "" if not self._smart_id else str(self._smart_id)

    # -------------------------------------------------- specimen text
    sampleCustomChanged = Signal()

    @Property(bool, notify=sampleCustomChanged)
    def sampleCustom(self) -> bool:
        return bool(getattr(self, "_sample_custom", False))

    @Slot(bool)
    def set_sample_custom(self, on: bool) -> None:
        """User typed custom specimen text → curated passages disabled."""
        on = bool(on)
        if on != getattr(self, "_sample_custom", False):
            self._sample_custom = on
            self.sampleCustomChanged.emit()

    @Slot()
    def reshuffle_preview_text(self) -> None:
        """Pick one random passage PER size bucket — called when the
        Fonts pane opens so the specimen text rotates each session."""
        from ..core import preview_text as core_preview
        self._samples = core_preview.reshuffle()

    @Slot(int, result=str)
    def preview_text(self, px: int) -> str:
        """Default specimen text for the preview size bucket; disabled
        whenever the user has typed custom text (QML decides)."""
        if not getattr(self, "_samples", None):
            self.reshuffle_preview_text()
        from ..core import preview_text as core_preview
        return self._samples.get(core_preview.bucket_for(int(px)), "")

    @Slot(str, result="QVariantList")
    def family_row_ids(self, family: str) -> list:
        """Every asset row id of the family (starring hits them all)."""
        if not family:
            return []
        return [r[0] for r in self._con.execute(
            "SELECT id FROM asset WHERE kind = 'font' AND family = ?"
            " ORDER BY id", (family,)).fetchall()]

    @Slot(str, bool)
    def star_family(self, family: str, starred: bool) -> None:
        """Star/unstar the WHOLE family (every indexed file of it)."""
        ids = self.family_row_ids(family)
        for aid in ids:
            core_db.set_starred(self._con, int(aid), bool(starred),
                                kind="font")
        self.message.emit(
            f"{('Starred' if starred else 'Unstarred')} “{family}”"
            f" ({len(ids)} file{'s' if len(ids) != 1 else ''})")

    @Slot(str, result=bool)
    def family_starred(self, family: str) -> bool:
        ids = self.family_row_ids(family)
        return any(core_db.is_starred(self._con, int(a), kind="font")
                   for a in ids)

    def _family_matches_smart(self, family: str) -> bool:
        """Smart-criteria check for a font family: ANY asset of the
        family satisfying the criteria (name/tag match) keeps it."""
        ids = self.family_row_ids(family)
        if not ids:
            return False
        from .colors import _matches_smart
        for aid in ids:
            tags = [t["name"] for t in self._con.execute(
                "SELECT t.name FROM item_tag it JOIN tag t"
                " ON t.id = it.tag_id WHERE it.item_kind = 'font'"
                " AND it.item_id = ?", (aid,))]
            row = self._con.execute(
                "SELECT name FROM asset WHERE id = ?", (aid,)).fetchone()
            if _matches_smart(self._con, self._smart_id,
                              {"name": row["name"] if row else family,
                               "tags": ",".join(tags)}):
                return True
        return False

    @Slot(str, result="QVariantList")
    def family_files(self, family: str) -> list:
        return core_fonts.family_files(self._con, family) \
            if family else []

    @Slot(str, result=int)
    def family_primary_id(self, family: str) -> int:
        """The family's first indexed asset row id — the Properties panel
        target for tags/fields/links on the Fonts pane."""
        if not family:
            return -1
        row = self._con.execute(
            "SELECT id FROM asset WHERE kind = 'font' AND family = ?"
            " ORDER BY id LIMIT 1", (family,)).fetchone()
        return row[0] if row else -1

    @Slot(str, str)
    def export_css(self, family: str, dest_dir: str) -> None:
        self._export(core_fonts.export_family_css, family, dest_dir, "css")

    @Slot("QVariantList", str, "QVariantList", bool)
    def export_zip_pkg(self, families, dest_dir: str, fmts,
                       include_original: bool = False) -> None:
        """ZIP the webfont package (fonts.css with RELATIVE URLs at the
        root + fonts/<Name>.<flavor>) — the unified export's ZIP path."""
        from ..core import exportplus as core_exportplus
        dest = str(Path(dest_dir).expanduser()) if dest_dir else ""
        if not dest:
            self.exportFailed.emit("choose a folder first")
            return
        try:
            out = core_exportplus.export_fonts_zip(
                self._con, [str(f) for f in families], dest,
                fmts=[str(f) for f in (fmts or [])] or None,
                include_original=bool(include_original))
        except Exception as e:                    # noqa: BLE001
            self.exportFailed.emit(str(e))
            return
        settings.set(self._con, "last_export_dir", dest)
        self.exportDone.emit(str(out))

    # ------------------------------------------------- fonts.css package
    @Slot("QVariantList", "QVariantList", result=str)
    def css_preview(self, families, fmts=None) -> str:
        """The fonts.css text for the given families — relative package
        paths, nothing written (the CSS dialog shows this editable)."""
        from ..core import exportplus as core_exportplus
        try:
            return core_exportplus.css_preview(
                self._con, [str(f) for f in families],
                [str(f) for f in (fmts or [])] or None)["css"]
        except Exception as e:                    # noqa: BLE001
            self.exportFailed.emit(str(e))
            return ""

    @Slot(str, str, "QVariantList", "QVariantList")
    def export_css_package(self, dest_dir: str, css_text: str,
                           families, fmts) -> None:
        """Save fonts.css exactly as shown/edited in the dialog plus
        every referenced font file converted to the chosen flavors,
        laid out as the CSS URLs expect (fonts/<Family>/<file>)."""
        from ..core import exportplus as core_exportplus
        dest = str(Path(dest_dir).expanduser()) if dest_dir else ""
        if not dest:
            self.exportFailed.emit("choose a folder first")
            return
        try:
            out = core_exportplus.export_css_package(
                self._con, dest, css_text or "",
                [str(f) for f in families],
                [str(f) for f in (fmts or [])] or None)
        except Exception as e:                    # noqa: BLE001
            self.exportFailed.emit(str(e))
            return
        settings.set(self._con, "last_export_dir", dest)
        self.exportDone.emit(str(out))

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
            # queue instead of dropping — a font folder added during a
            # scan (first-run flow) must still get indexed afterwards
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
        wk = _FontScanWorker(self._db_path)
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

    # -------------------------------------------------------------- internals
    def _clear_thread_refs(self, t) -> None:
        # only clear OUR generation: one-shot workers emit finished even
        # after a newer rescan installed the next thread
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
        # never leave `scanning` stuck true — see library._on_scan_failed
        self._scanning = False
        self.scanningChanged.emit()
        self.scanFinished.emit({})
        self.message.emit(f"Font scan failed: {err}")

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
        if self._rescan_pending:
            self._rescan_pending = False
            QTimer.singleShot(0, self.rescan)

    @Slot()
    def refresh(self) -> None:
        """Public model refresh for QML after source mutations made
        from Settings / first-run (remove a font dir, toggle one)."""
        self._refresh()

    def _refresh(self) -> None:
        all_fams = core_fonts.families(self._con)
        # collection filter (rail Collections row, fonts pane): families
        # survive when ANY of their assets is a collection member
        coll_fams: set[str] | None = None
        if self._collection:
            coll_fams = {r["family"] for r in self._con.execute(
                "SELECT DISTINCT a.family FROM collection_ref cr"
                " JOIN asset a ON a.id = cr.item_id"
                " WHERE cr.collection_id = ? AND cr.item_kind = 'font'"
                " AND a.kind = 'font'", (self._collection,))}
        fams = all_fams
        if coll_fams is not None:
            fams = [f for f in all_fams if f["family"] in coll_fams]
        if self._smart_id:
            fams = [f for f in fams if self._family_matches_smart(
                f["family"])]
        self._families = [{"name": f["family"], "n": f["n"]}
                          for f in fams]
        self._types = [{"name": r[0], "n": r[1]} for r in self._con.execute(
            "SELECT ext, COUNT(*) FROM asset"
            " WHERE kind = 'font' AND ext IS NOT NULL"
            " GROUP BY ext ORDER BY ext")]
        # type filter: families that own at least one file with the ext
        type_fams: set[str] = set()
        if self._type_filter:
            type_fams = {r["family"] for r in self._con.execute(
                "SELECT DISTINCT family FROM asset"
                " WHERE kind = 'font' AND ext = ?",
                (self._type_filter,))}
        rows = []
        for fam in all_fams:
            if self._filter and self._filter not in fam["family"].lower():
                continue
            if self._family_filter and fam["family"] != self._family_filter:
                continue
            if self._type_filter and fam["family"] not in type_fams:
                continue
            if coll_fams is not None and fam["family"] not in coll_fams:
                continue
            if self._smart_id and not self._family_matches_smart(
                    fam["family"]):
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
