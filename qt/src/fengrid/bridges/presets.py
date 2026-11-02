"""Preset library bridge: curated remote asset libraries (fonts, icon
sets, site templates) that stay remote until the user downloads one.

Entries are catalog rows (name/URL/tags from the projects' READMEs);
downloading an entry clones its GitHub repo through Fengrid's built-in
git wrapper and derives a 1280x640 (GitHub social-image size) preview
from the repo's README/social imagery — or renders a fallback card.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QRectF
from PySide6.QtGui import (QLinearGradient, QColor, QFont, QGuiApplication,
                           QImage, QPainter)

from ..core import presets as core_presets
from ..core.projects_git import Repo, git_available

PREVIEW_W, PREVIEW_H = 1280, 640     # GitHub social-image size


def _hash_tint(seed: str) -> tuple[QColor, QColor]:
    """Deterministic pleasing gradient pair for a repo name."""
    h = hashlib.sha256(seed.encode()).digest()
    h1, h2 = int.from_bytes(h[:3], "big") % 360, \
        int.from_bytes(h[3:6], "big") % 360
    return QColor.fromHsl(h1, 150, 46), QColor.fromHsl((h1 + h2 // 8) % 360,
                                                       140, 26)


class Presets(QObject):
    message = Signal(str)
    librariesChanged = Signal()
    entriesChanged = Signal()
    # entryId, ok, detail(path or error) — emitted on the MAIN thread
    cloneDone = Signal(int, bool, str)
    # entryId, hexes — emitted when a palette-kind preset is applied
    presetApplied = Signal(int, "QVariantList")
    # path, kind — a newly registered scan source for a fresh clone;
    # the app wires this to the library/fonts rescans (#37)
    sourceAdded = Signal(str, str)
    # #141: live download progress — entryId, phase ("clone"|"update"),
    # percent 0-100 (-1 = indeterminate pulse). Emitted from the worker
    # thread; Qt queues them onto the main thread, so the dialog's bar
    # updates are safe.
    downloadProgress = Signal(int, str, int)
    # #141: entryId, phase — "ingest" when the fresh clone's scan begins
    # (the bar switches to an indeterminate "indexing" pulse), "done"
    # when the loading bar should go away.
    downloadState = Signal(int, str)

    def __init__(self, con, data_dir: str = "", parent=None):
        super().__init__(parent)
        self._con = con
        self._data_dir = str(data_dir or "")
        self._busy: set[int] = set()
        # #141: last clone percent per entry (worker-thread writes, GIL
        # safe) — lets entries() re-seed the dialog's bar after a reopen
        self._progress: dict[int, int] = {}
        # #141: entries whose clone landed and whose assets are being
        # indexed by the library/fonts scan right now
        self._ingesting: set[int] = set()
        self.cloneDone.connect(self._on_clone_done)

    # ------------------------------------------------------------- listing
    def _libraries(self) -> list:
        out = []
        for r in self._con.execute(
                "SELECT * FROM preset_library ORDER BY position, name"):
            n = self._con.execute(
                "SELECT COUNT(*) FROM preset_entry WHERE library_id = ?",
                (r["id"],)).fetchone()[0]
            dl = self._con.execute(
                "SELECT COUNT(*) FROM preset_entry WHERE library_id = ?"
                " AND downloaded = 1", (r["id"],)).fetchone()[0]
            out.append({"id": r["id"], "name": r["name"], "kind": r["kind"],
                        "summary": r["summary"], "tags": r["tags"],
                        "remote": bool(r["remote"]), "entries": n,
                        "downloaded": dl})
        return out

    @Property("QVariantList", notify=librariesChanged)
    def libraries(self):
        return self._libraries()

    @Slot(int, result="QVariantList")
    def entries(self, lib_id: int) -> list:
        out = []
        lib_kind = self._con.execute(
            "SELECT kind FROM preset_library WHERE id = ?", (int(lib_id),)
        ).fetchone()
        kind_str = (lib_kind["kind"] if lib_kind else "").lower()
        for r in self._con.execute(
                "SELECT * FROM preset_entry WHERE library_id = ?"
                " ORDER BY position, name", (int(lib_id),)):
            entry = {
                "id": r["id"], "name": r["name"], "repo": r["repo"],
                "url": r["url"], "branch": r["branch"],
                "description": r["description"], "license": r["license"],
                "homepage": r["homepage"], "tags": r["tags"],
                "downloaded": bool(r["downloaded"]),
                "localPath": r["local_path"],
                "preview": r["preview_path"],
                "busy": r["id"] in self._busy,
                # #141: progress snapshot for the dialog's loading bar —
                # percent while cloning (None before the first tick),
                # -1 pulse; "ingesting" flags the post-clone index scan
                "progressPct": self._progress.get(r["id"])
                if r["id"] in self._busy else None,
                "ingesting": r["id"] in self._ingesting,
                "libraryKind": kind_str,
                "colors": r["colors"] or "",
            }
            out.append(entry)
        return out

    @Slot(int, result="QVariantList")
    def entry_tags(self, entry_id: int) -> list:
        from ..core import db as core_db
        return core_db.tags_for(self._con, int(entry_id), "preset_entry")

    @Slot(str, int, str)
    def add_entry_tag(self, entry_id: int, name: str) -> None:
        from ..core import db as core_db
        core_db.add_tag(self._con, int(entry_id), name, kind="preset_entry")
        self.entriesChanged.emit()

    @Slot(int, str)
    def set_branch(self, entry_id: int, branch: str) -> None:
        self._con.execute("UPDATE preset_entry SET branch = ? WHERE id = ?",
                          (str(branch or "").strip(), int(entry_id)))
        self._con.commit()

    @Slot(int)
    def apply_preset(self, entry_id: int) -> None:
        """Apply a palette-kind preset entry: emit its hex colors so the
        Colors bridge (or any listener) can load them."""
        row = self._row(entry_id)
        if row is None:
            return
        import json as _json
        try:
            hexes = _json.loads(row["colors"] or "[]")
        except ValueError:
            hexes = []
        if hexes:
            self.presetApplied.emit(entry_id, hexes)

    # ------------------------------------------------------------ download
    @Slot(int)
    def download(self, entry_id: int) -> None:
        entry_id = int(entry_id)
        row = self._row(entry_id)
        if row is None:
            return
        if entry_id in self._busy:
            self.message.emit("Download already running")
            return
        if not git_available():
            self.message.emit("git is not installed — cannot download")
            return
        if row["downloaded"]:
            # refresh an existing clone instead of re-cloning
            self._busy.add(entry_id)
            threading.Thread(target=self._update_worker,
                             args=(entry_id, row["local_path"]),
                             daemon=True).start()
            self.message.emit(f"Updating {row['name']}…")
            self.entriesChanged.emit()
            return
        if not self._data_dir:
            self.message.emit("No data directory — cannot download")
            return
        dest = core_presets.entry_dir(self._data_dir, self._lib_name(row),
                                      row["repo"])
        if dest.exists():
            self.message.emit(f"{row['name']} already on disk")
            return
        self._busy.add(entry_id)
        threading.Thread(
            target=self._clone_worker,
            args=(entry_id, row["url"], row["branch"], str(dest)),
            daemon=True).start()
        self.message.emit(f"Cloning {row['name']}…")
        self.entriesChanged.emit()

    def _row(self, entry_id: int):
        return self._con.execute(
            "SELECT * FROM preset_entry WHERE id = ?", (int(entry_id),)
        ).fetchone()

    def _lib_name(self, entry_row) -> str:
        r = self._con.execute(
            "SELECT name FROM preset_library WHERE id = ?",
            (entry_row["library_id"],)).fetchone()
        return r["name"] if r else ""

    def _clone_worker(self, entry_id: int, url: str, branch: str,
                      dest: str) -> None:
        # #141: feed the dialog's loading bar — the worker thread emits
        # the signal; Qt queues it onto the main thread. The bar shows a
        # pulse until git's first progress tick arrives.
        def _pct(p: int) -> None:
            self._progress[entry_id] = int(p)
            self.downloadProgress.emit(entry_id, "clone", int(p))

        self._progress.pop(entry_id, None)
        self.downloadProgress.emit(entry_id, "clone", -1)
        try:
            Repo.clone(url, dest, branch or "", progress=_pct)
            self.cloneDone.emit(entry_id, True, dest)
        except Exception as e:                     # noqa: BLE001
            self.cloneDone.emit(entry_id, False, str(e)[:300])

    def _update_worker(self, entry_id: int, local_path: str) -> None:
        # #141: an update (git pull) reports no percent — pulse
        self.downloadProgress.emit(int(entry_id), "update", -1)
        try:
            repo = Repo(local_path)
            remotes = repo.remotes()
            if remotes:
                repo.pull(next(iter(remotes)))
                self.cloneDone.emit(entry_id, True, local_path)
            else:
                self.cloneDone.emit(entry_id, False, "no remote configured")
        except Exception as e:                     # noqa: BLE001
            self.cloneDone.emit(entry_id, False, str(e)[:300])

    def _on_clone_done(self, entry_id: int, ok: bool, detail: str) -> None:
        entry_id = int(entry_id)
        self._busy.discard(entry_id)
        self._progress.pop(entry_id, None)
        row = self._row(entry_id)
        if row is None:
            self.downloadState.emit(entry_id, "done")
            return
        if not ok:
            self.message.emit(f"Download failed: {detail}")
            self.downloadState.emit(entry_id, "done")   # clear the bar
            self.entriesChanged.emit()
            return
        branch = self._current_branch(detail)
        self._con.execute(
            "UPDATE preset_entry SET downloaded = 1, local_path = ?,"
            " branch = CASE WHEN ? != '' THEN ? ELSE branch END"
            " WHERE id = ?",
            (detail, branch, branch, entry_id))
        self._con.commit()
        preview = self._make_preview(detail, row["repo"], row["name"])
        if preview:
            self._con.execute(
                "UPDATE preset_entry SET preview_path = ? WHERE id = ?",
                (preview, entry_id))
            self._con.commit()
        self.message.emit(f"{row['name']} downloaded — preview generated")
        # register the clone as a scan source so its assets reach the
        # grid (#37): icon packs index as icons, font packs as fonts;
        # template packs are deliberately never indexed
        kind = core_presets.entry_scan_kind(self._pack_kind(row))
        ingesting = False
        if kind is not None:
            registered = core_presets.sync_downloaded_sources(self._con)
            clone = str(Path(detail).resolve())
            if any(Path(n["path"]) == Path(clone) for n in registered):
                # #141: the clone landed — its assets still need to be
                # indexed by the scan. The loading bar switches to an
                # indeterminate "indexing" pulse and stays up until that
                # scan finishes (note_scan_finished clears it).
                ingesting = True
                self._ingesting.add(entry_id)
                self.downloadState.emit(entry_id, "ingest")
                self.sourceAdded.emit(str(clone), kind)
        if not ingesting:
            # nothing to index — the loading bar is done right away
            self.downloadState.emit(entry_id, "done")
        # #141: file the download into its collections (per-type
        # 'Downloaded' + a collection named after the pack); membership
        # fills in as the clone's scan completes
        core_presets.sync_download_collections(self._con)
        core_presets.sync_default_library(self._con)
        # #141 round 2: the pack also becomes a discrete LIBRARY
        core_presets.sync_pack_libraries(self._con)
        self.entriesChanged.emit()
        self.librariesChanged.emit()

    @Slot()
    def note_scan_finished(self) -> None:
        """#141: the library/fonts scan that indexes a fresh clone's
        assets just finished — every entry still in the ingestion phase
        drops its loading bar. Called for both bridge scans; a scan of
        unrelated sources also clears the pulse (it cannot hurt — the
        entry's own assets are indexed by any completed scan)."""
        if not self._ingesting:
            return
        ids = list(self._ingesting)
        self._ingesting.clear()
        for eid in ids:
            self.downloadState.emit(eid, "done")
        self.entriesChanged.emit()

    def _pack_kind(self, entry_row) -> str:
        r = self._con.execute(
            "SELECT kind FROM preset_library WHERE id = ?",
            (entry_row["library_id"],)).fetchone()
        return r["kind"] if r else ""

    @staticmethod
    def _current_branch(path: str) -> str:
        try:
            out = Repo(path)._run("rev-parse", "--abbrev-ref", "HEAD")
            return out.strip()
        except Exception:                          # noqa: BLE001
            return ""

    # ------------------------------------------------------------- forget
    @Slot(int)
    def forget(self, entry_id: int) -> None:
        row = self._row(entry_id)
        if row is None or not row["downloaded"]:
            return
        # undo the scan-source registration BEFORE the clone disappears,
        # so no dangling source survives (#37)
        core_presets.remove_entry_source(self._con, row["local_path"])
        if row["local_path"] and os.path.isdir(row["local_path"]):
            shutil.rmtree(row["local_path"], ignore_errors=True)
        if row["preview_path"] and os.path.isfile(row["preview_path"]):
            try:
                os.remove(row["preview_path"])
            except OSError:
                pass
        self._con.execute(
            "UPDATE preset_entry SET downloaded = 0, local_path = '',"
            " preview_path = '' WHERE id = ?", (int(entry_id),))
        self._con.commit()
        self.message.emit(f"{row['name']} removed — entry is remote again")
        self.entriesChanged.emit()
        self.librariesChanged.emit()

    @Slot(int)
    def open_folder(self, entry_id: int) -> None:
        row = self._row(entry_id)
        if row is None or not row["local_path"]:
            return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(row["local_path"]))

    # ------------------------------------------------------------ previews
    def _make_preview(self, clone_path: str, repo: str, name: str) -> str:
        """1280x640 preview for a downloaded entry: crop/scale the
        repo's social/README image, or render a fallback card."""
        if not self._data_dir or not clone_path:
            return ""
        out_dir = Path(self._data_dir) / "presets" / ".previews"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / (repo.replace("/", "__") + ".png")
        src = core_presets.preview_source(Path(clone_path))
        if src is not None and src.suffix.lower() != ".svg":
            img = QImage(str(src))
            if not img.isNull():
                return self._cover_crop(img, str(out))
        if src is not None and src.suffix.lower() == ".svg":
            try:
                from PySide6.QtSvg import QSvgRenderer
                renderer = QSvgRenderer(str(src))
                img = QImage(PREVIEW_W, PREVIEW_H,
                             QImage.Format.Format_ARGB32)
                img.fill(QColor(0, 0, 0, 0))
                if renderer.isValid():
                    painter = QPainter(img)
                    renderer.render(painter)
                    painter.end()
                    return self._cover_crop(img, str(out))
            except Exception:                      # noqa: BLE001
                pass
        return self._render_fallback(str(out), name, repo)

    @staticmethod
    def _cover_crop(img: QImage, out_path: str) -> str:
        """Center-crop/scale to exactly 1280x640 (2:1 social preview)."""
        target = PREVIEW_W / PREVIEW_H
        w, h = img.width(), img.height()
        if w and h and w / h > target:
            new_w = int(h * target)
            x = (w - new_w) // 2
            img = img.copy(x, 0, new_w, h)
        elif w and h:
            new_h = int(w / target)
            y = (h - new_h) // 2
            img = img.copy(0, y, w, new_h)
        img = img.scaled(PREVIEW_W, PREVIEW_H,
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        img.save(out_path, "PNG")
        return out_path

    @staticmethod
    def _render_fallback(out_path: str, name: str, repo: str) -> str:
        c1, c2 = _hash_tint(repo)
        img = QImage(PREVIEW_W, PREVIEW_H, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        grad = QLinearGradient(0, 0, PREVIEW_W, PREVIEW_H)
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)
        painter.fillRect(img.rect(), grad)
        painter.setPen(QColor(255, 255, 255, 235))
        f = QFont()
        f.setPixelSize(96)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(QRectF(60, 200, PREVIEW_W - 120, 160),
                         Qt.AlignmentFlag.AlignHCenter
                         | Qt.AlignmentFlag.AlignVCenter, name)
        f2 = QFont()
        f2.setPixelSize(44)
        painter.setFont(f2)
        painter.setPen(QColor(255, 255, 255, 170))
        painter.drawText(QRectF(60, 380, PREVIEW_W - 120, 70),
                         Qt.AlignmentFlag.AlignHCenter
                         | Qt.AlignmentFlag.AlignVCenter, repo)
        painter.end()
        img.save(out_path, "PNG")
        return out_path
