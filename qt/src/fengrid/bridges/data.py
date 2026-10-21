"""DataIO bridge — the single context property (`dataio`) behind the
Settings data-management surface: import/ingest, extended export,
backup/restore, SQLite administration and watch folders.

Threading: every long job runs on a one-shot QThread worker with its
OWN database connection (the house pattern — WAL + BEGIN IMMEDIATE make
this safe alongside scans). Jobs are serialized: one at a time, a second
request while busy fails fast with a toast-able signal. Progress and
completion arrive as queued signals; QML binds `busy`.

Options flow ONE WAY from Settings UI → properties (persisted as JSON
settings blobs `import_opts`/`export_opts`) → job functions, so the
screen is always showing what the next job will actually do.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import (QObject, QThread, QTimer, QCoreApplication,
                            Signal, Slot, Property)

from ..core import backup as core_backup
from ..core import db as core_db
from ..core import exportplus as xp
from ..core import indexer, ingest, settings as core_settings
from ..core import watch as core_watch


class _Worker(QObject):
    """One-shot job runner: fn(*args) → done(payload) | failed(err)."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, args=(), parent=None):
        super().__init__(parent)
        self._fn = fn
        self._args = args

    def run(self):
        try:
            self.done.emit(self._fn(*self._args))
        except Exception as e:            # noqa: BLE001 — job boundary
            self.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            QThread.currentThread().quit()


def _default_import_opts() -> dict:
    return {"mode": "copy", "convert": "none", "template": "",
            "prefix": "", "suffix": "", "find": "", "repl": "",
            "style": "none", "start": 1, "pad": 2, "random_len": 6}


def _default_export_opts() -> dict:
    return {"icon_fmts": ["png"], "icon_size": "orig", "tint": "",
            "script": "", "script_enabled": False,
            "font_fmts": ["woff2"], "color_codes": "txt",
            "snippet_kind": "bundle"}


class DataIO(QObject):
    jobStarted = Signal(str)                     # import|export|backup
    jobProgress = Signal(str, int, int)          # kind, done, total
    jobDone = Signal(str, str)                   # kind, summary
    jobFailed = Signal(str, str)                 # kind, error
    message = Signal(str)                        # → toast
    importFinished = Signal(dict)                # report → library rescan
    backupsChanged = Signal()
    watchesChanged = Signal()
    statsChanged = Signal()
    adminDone = Signal(str, str)                 # op, summary
    transportsChanged = Signal()

    def __init__(self, con, db_path: str, data_dir: str,
                 registry_path: str = "", parent=None):
        super().__init__(parent)
        self._con = con
        self._db_path = str(db_path)
        self._data_dir = str(data_dir)
        self._registry = registry_path
        self._thread = None
        self._worker = None
        self._import_opts = self._load_json("import_opts",
                                            _default_import_opts())
        self._export_opts = self._load_json("export_opts",
                                            _default_export_opts())
        self._stats: dict = {}
        self._restore_pending = False
        # watcher heartbeat: cheap 5s tick; jobs run in their own thread
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._watch_tick)
        self._timer.start()
        # safety auto-backup at quit (synchronous by design: the process
        # is ending, threads would never finish)
        QCoreApplication.instance().aboutToQuit.connect(
            self._auto_backup_on_quit)

    # ── options (persisted JSON blobs) ───────────────────────────────
    def _load_json(self, key: str, default: dict) -> dict:
        try:
            raw = core_settings.get(self._con, key, "")
            if raw:
                merged = dict(default)
                merged.update(json.loads(raw))
                return merged
        except (ValueError, TypeError):
            pass
        return dict(default)

    def _save_json(self, key: str, value: dict) -> None:
        core_settings.set(self._con, key, json.dumps(value))

    importOptsChanged = Signal()
    exportOptsChanged = Signal()

    @Property("QVariantMap", notify=importOptsChanged)
    def importOpts(self) -> dict:
        return self._import_opts

    @Slot("QVariantMap")
    def setImportOpts(self, opts: dict) -> None:
        merged = _default_import_opts()
        merged.update({k: v for k, v in (opts or {}).items()
                       if k in merged})
        if merged == self._import_opts:
            return
        self._import_opts = merged
        self._save_json("import_opts", merged)
        self.importOptsChanged.emit()

    @Property("QVariantMap", notify=exportOptsChanged)
    def exportOpts(self) -> dict:
        return self._export_opts

    @Slot("QVariantMap")
    def setExportOpts(self, opts: dict) -> None:
        merged = _default_export_opts()
        merged.update({k: v for k, v in (opts or {}).items()
                       if k in merged})
        if merged == self._export_opts:
            return
        self._export_opts = merged
        self._save_json("export_opts", merged)
        self.exportOptsChanged.emit()

    # ── job plumbing ─────────────────────────────────────────────────
    busyChanged = Signal()

    @Property(bool, notify=busyChanged)
    def jobRunning(self) -> bool:
        """True while any import/export/backup/admin/watch job runs —
        QML disables the section buttons off this."""
        return self._worker is not None

    def _start(self, kind: str, fn, args=()) -> bool:
        if self._worker is not None:
            self.jobFailed.emit(kind, "another data job is still running")
            return False
        th = QThread(self)
        wk = _Worker(fn, args)
        self._thread, self._worker = th, wk
        wk.moveToThread(th)
        th.started.connect(wk.run)

        def _finish(payload):
            self._clear(th)
            if kind == "backup":
                self.backupsChanged.emit()
            if kind == "restore" and getattr(self, "_restore_pending",
                                             False):
                self._restore_pending = False
                self.backupsChanged.emit()
                from PySide6.QtCore import QTimer as _T
                _T.singleShot(400, self._relaunch)
            if kind == "import":
                self.importFinished.emit(payload if isinstance(payload, dict)
                                         else {})
            self.jobDone.emit(kind, _summary(kind, payload))
            self.message.emit(_summary(kind, payload))

        def _fail(err):
            self._clear(th)
            self.jobFailed.emit(kind, err)
            self.message.emit(f"{kind} failed: {err}")

        wk.done.connect(_finish)
        wk.failed.connect(_fail)
        wk.done.connect(wk.deleteLater)
        wk.failed.connect(wk.deleteLater)
        th.finished.connect(th.deleteLater)
        self.jobStarted.emit(kind)
        self.busyChanged.emit()
        th.start()
        return True

    def _clear(self, t) -> None:
        if self._thread is t:
            self._thread = None
            self._worker = None
            self.busyChanged.emit()

    def _progress(self, kind: str):
        def emit(done, total):
            self.jobProgress.emit(kind, int(done), int(total))
        return emit

    # ── import ───────────────────────────────────────────────────────
    @Slot("QStringList")
    def importStart(self, paths) -> None:
        """Materialise files, then index them (scan runs inside the job
        on its own connection — chunked, memory-bounded)."""
        opts = dict(self._import_opts)
        data_dir = self._data_dir

        def job():
            csv_names = None
            if opts.get("csv_path"):
                from .patterns import read_csv_names   # local import ok
                try:
                    csv_names = read_csv_names(opts["csv_path"],
                                               opts.get("csv_column", "0"))
                except Exception:
                    csv_names = None
            rep = ingest.import_files(
                list(paths), data_dir, mode=opts["mode"],
                convert=opts["convert"], template=opts["template"],
                prefix=opts["prefix"], suffix=opts["suffix"],
                find=opts["find"], repl=opts["repl"],
                style=opts["style"], enum_start=int(opts["start"]),
                enum_pad=int(opts["pad"]),
                random_len=int(opts["random_len"]),
                csv_names=csv_names,
                slug=_slug_for(list(paths), opts),
                progress=self._progress("import"))
            rep.update(_index_materialised(self._db_path, rep, opts))
            return rep

        self._start("import", job)

    @Slot(str)
    def importZip(self, path: str) -> None:
        opts = dict(self._import_opts)
        data_dir = self._data_dir

        def job():
            rep = ingest.import_zip(
                path, data_dir, mode=opts["mode"],
                convert=opts["convert"], slug="zip-import",
                template=opts["template"], prefix=opts["prefix"],
                suffix=opts["suffix"], find=opts["find"],
                repl=opts["repl"], style=opts["style"],
                enum_start=int(opts["start"]), enum_pad=int(opts["pad"]),
                random_len=int(opts["random_len"]),
                progress=self._progress("import"))
            rep.update(_index_materialised(self._db_path, rep, opts))
            return rep

        self._start("import", job)

    @Slot(str)
    def importFolder(self, path: str) -> None:
        """Folders become SOURCES (linked, not copied) — the scanner
        indexes them; identical to the first-run folder flow."""
        def job():
            desc = ingest.import_folder(path)
            con = core_db.connect(self._db_path)
            try:
                row = con.execute("SELECT id FROM source WHERE path = ?",
                                  (desc["path"],)).fetchone()
                if row is None:
                    con.execute(
                        "INSERT INTO source(kind, path, label, enabled)"
                        " VALUES(?, ?, ?, 1)",
                        (desc["kind"], desc["path"],
                         Path(desc["path"]).name))
                    con.commit()
                sources = [(row[0] if row else
                            con.execute("SELECT id FROM source"
                                        " WHERE path = ?",
                                        (desc["path"],)).fetchone()[0],
                            desc["path"])]
                if desc["kind"] == "fontroot":
                    rep = ingest.scan_fonts_into(con, sources)
                else:
                    rep = ingest.scan_into(
                        con, sources,
                        progress=self._progress("import"))
            finally:
                con.close()
            return {"placed": rep.get("total", 0), "failed": 0,
                    "skipped": 0, "errors": [], "dest": desc["path"],
                    "indexed": rep.get("total", 0), "rescan": True}

        if not self._start("import", job):
            return
        # rescan the OTHER bridge too (its cached model must see this)
        # handled by importFinished → Main

    @Slot(result=str)
    def importMode(self) -> str:
        return str(self._import_opts.get("mode", "copy"))

    # ── export ───────────────────────────────────────────────────────
    @Slot("QStringList", str, str)
    def exportIcons(self, paths, dest: str, opts_json: str) -> None:
        opts = self._export_opts if not opts_json else {
            **_default_export_opts(),
            **json.loads(opts_json or "{}")}

        def job():
            rows = [{"name": Path(p).stem, "path": p} for p in paths]
            rep = xp.export_icons(
                rows, dest,
                fmts=list(opts.get("icon_fmts") or ["png"]),
                size=(int(opts["icon_size"])
                      if str(opts.get("icon_size", "orig")) not in
                      ("orig", "", "None") else None),
                tint=str(opts.get("tint", "")),
                script=str(opts.get("script", "")),
                script_enabled=bool(opts.get("script_enabled")),
                progress=self._progress("export"))
            core_settings.set(self._con, "last_export_dir", str(dest))
            return rep

        self._start("export", job)

    @Slot(str, str, str)
    def exportFontsWeb(self, family: str, dest: str, opts_json: str) -> None:
        opts = json.loads(opts_json or "{}")

        def job():
            return xp.export_fonts_web(
                self._con, family, dest,
                fmts=list(opts.get("font_fmts") or ["woff2"]),
                weights=opts.get("weights") or None,
                progress=self._progress("export"))

        self._start("export", job)

    @Slot(str, "QStringList", str, str)
    def exportPalette(self, name: str, hexes, dest: str,
                      kinds_json: str) -> None:
        """Multi-format palette export + optional HEX/HSL/RGB/CMYK code
        list (the conversion-site killer)."""
        kinds = json.loads(kinds_json or '["css","json"]')

        def job():
            from ..core import colors as core_colors
            written = []
            for k in kinds:
                if k in ("txt", "csv", "md"):
                    text = xp.color_code_lines(
                        list(hexes),
                        json.loads(opts_names()) if False else None, k)
                    out = Path(dest) / f"{_slug(name)}.{k}"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(text, encoding="utf-8")
                    written.append(str(out))
                else:
                    out = core_colors.write_exports(name, list(hexes),
                                                    dest, k)
                    written.append(str(out))
            core_settings.set(self._con, "last_export_dir", str(dest))
            return {"written": len(written), "outputs": written,
                    "files": len(hexes)}

        def opts_names():
            return "null"

        self._start("export", job)

    @Slot(str, str, str)
    def exportSnippets(self, dest: str, kind: str, ids_json: str) -> None:
        ids = json.loads(ids_json or "[]")

        def job():
            cols = ("id, title, language, description, tags,"
                    " html, css, js")
            if ids:
                q = ",".join("?" * len(ids))
                rows = [dict(r) for r in self._con.execute(
                    f"SELECT {cols} FROM snippet WHERE id IN ({q})",
                    list(ids))]
            else:
                rows = [dict(r) for r in self._con.execute(
                    f"SELECT {cols} FROM snippet ORDER BY title")]
            rep = xp.export_snippets(rows, dest, kind=kind)
            core_settings.set(self._con, "last_export_dir", str(dest))
            return rep

        self._start("export", job)

    @Slot(str, str, bool)
    def exportBundle(self, scope: str, dest: str,
                     with_files: bool = True) -> None:
        def job():
            rep = xp.export_bundle(self._con, dest, scope=scope,
                                   with_files=with_files,
                                   progress=self._progress("export"))
            core_settings.set(self._con, "last_export_dir", str(dest))
            return rep

        self._start("export", job)

    @Slot(str, str)
    def importBundle(self, path: str, mode: str) -> None:
        data_dir = self._data_dir

        def job():
            return _import_bundle_job(self._db_path, data_dir, path, mode,
                                      self._progress("import"))

        self._start("import", job)

    autoBackupChanged = Signal()

    @Property(bool, notify=autoBackupChanged)
    def autoBackup(self) -> bool:
        return core_settings.get_bool(self._con, "auto_backup", False)

    @Slot(bool)
    def setAutoBackup(self, on: bool) -> None:
        core_settings.set_bool(self._con, "auto_backup", bool(on))
        self.autoBackupChanged.emit()

    # ── backup / restore ─────────────────────────────────────────────
    @Slot(str)
    def backupNow(self, dest_dir: str = "") -> None:
        dest = dest_dir or os.path.join(self._data_dir, "backups")

        def job():
            return core_backup.backup(self._db_path, dest,
                                      registry_path=self._registry,
                                      data_dir=self._data_dir,
                                      logs_dir=self._data_dir)

        self._start("backup", job)

    @Slot(result="QVariantList")
    def backups(self) -> list:
        return core_backup.list_backups(
            os.path.join(self._data_dir, "backups"))

    @Slot(str)
    def restoreBackup(self, path: str) -> None:
        """Swap the live database and relaunch — every bridge holds the
        old connection, so a hot-swap is impossible (same rule as
        database switching). FENGRID_NO_RELAUNCH=1 keeps tests in-process."""
        def job():
            res = core_backup.restore(path, self._db_path)
            return {"restored": res["restored"], "files": 1,
                    "previous": res.get("previous") or "",
                    "name": Path(path).name}

        if self._start("restore", job):
            self._restore_pending = True

    @Slot(str)
    def deleteBackup(self, path: str) -> None:
        try:
            core_backup.remove_backup(
                path, os.path.join(self._data_dir, "backups"))
            self.backupsChanged.emit()
            self.message.emit("Backup removed")
        except Exception as e:               # noqa: BLE001 — user input
            self.message.emit(f"Remove failed: {e}")

    @Slot()
    def restoreNeedsRestartNote(self) -> None:
        self.message.emit("Database restored — restart Fengrid to load it")

    def _auto_backup_on_quit(self) -> None:
        try:
            if not core_settings.get_bool(self._con, "auto_backup", False):
                return
            if self._worker is not None:     # a job is mid-flight
                return
            core_backup.backup(
                self._db_path,
                os.path.join(self._data_dir, "backups"),
                registry_path=self._registry, label="auto")
        except Exception:                    # never block quitting
            pass

    # ── database administration ──────────────────────────────────────
    @Slot()
    def refreshStats(self) -> None:
        def job():
            return {"kind": "stats",
                    "data": core_backup.stats(self._con, self._db_path)}

        def got(payload):
            self._stats = payload.get("data", {})
            self.statsChanged.emit()

        self._run_admin("stats", job, got)

    @Property("QVariantMap", notify=statsChanged)
    def stats(self) -> dict:
        return self._stats

    @Slot(str)
    def adminRun(self, op: str) -> None:
        ops = {
            "check": core_backup.quick_check,
            "vacuum": core_backup.vacuum,
            "checkpoint": core_backup.checkpoint,
            "optimize": core_backup.optimize,
            "rebuild_fts": core_backup.rebuild_fts,
            "sweep": core_backup.sweep_orphans,
        }
        if op not in ops:
            self.adminDone.emit(op, f"unknown operation: {op}")
            return
        fn = ops[op]

        def job():
            return {"kind": op, "data": fn(self._con)}

        def got(payload):
            data = payload.get("data", {})
            self.adminDone.emit(op, _admin_summary(op, data))
            if op == "sweep":
                self.importFinished.emit({"rescan": True})

        self._run_admin(op, job, got)

    def _run_admin(self, op, job, on_done) -> None:
        if self._worker is not None:
            self.adminDone.emit(op, "another data job is still running")
            return
        th = QThread(self)
        wk = _Worker(job)
        self._thread, self._worker = th, wk
        wk.moveToThread(th)
        th.started.connect(wk.run)

        def _done(payload):
            self._clear(th)
            on_done(payload)

        def _fail(err):
            self._clear(th)
            self.adminDone.emit(op, err)
            self.message.emit(f"{op}: {err}")

        wk.done.connect(_done)
        wk.failed.connect(_fail)
        wk.done.connect(wk.deleteLater)
        wk.failed.connect(wk.deleteLater)
        th.finished.connect(th.deleteLater)
        self.busyChanged.emit()
        th.start()

    # ── watch folders ────────────────────────────────────────────────
    @Slot(result="QVariantList")
    def transports(self) -> list:
        return core_watch.availability()

    @Slot(result="QVariantList")
    def watches(self) -> list:
        out = []
        for r in self._con.execute(
                "SELECT w.id, w.path, w.label, w.transport, w.interval,"
                " w.enabled, s.last_run, s.last_hits FROM watch_source w"
                " LEFT JOIN watch_state s ON s.watch_id = w.id"
                " ORDER BY w.id"):
            row = dict(r)
            row["enabled"] = bool(row["enabled"])
            row["lastRun"] = row.pop("last_run") or 0
            row["lastHits"] = row.pop("last_hits") or 0
            out.append(row)
        return out

    @Slot(str, str, int)
    def watchAdd(self, path: str, transport: str, interval: int) -> None:
        path = (path or "").strip()
        if not path:
            self.message.emit("Watch folder needs a path")
            return
        try:
            self._con.execute(
                "INSERT INTO watch_source(path, label, transport, interval)"
                " VALUES(?, ?, ?, ?)",
                (path, Path(path).name or path, transport,
                 max(15, int(interval))))
            self._con.commit()
            self.watchesChanged.emit()
            self.message.emit(f"Watching {path}")
        except Exception as e:               # noqa: BLE001
            self.message.emit(f"Cannot add watch: {e}")

    @Slot(int)
    def watchRemove(self, watch_id: int) -> None:
        self._con.execute("DELETE FROM watch_source WHERE id = ?",
                          (int(watch_id),))
        self._con.execute("DELETE FROM watch_state WHERE watch_id = ?",
                          (int(watch_id),))
        self._con.commit()
        self.watchesChanged.emit()

    @Slot(int, bool)
    def watchToggle(self, watch_id: int, enabled: bool) -> None:
        self._con.execute("UPDATE watch_source SET enabled = ? WHERE id = ?",
                          (1 if enabled else 0, int(watch_id)))
        self._con.commit()
        self.watchesChanged.emit()

    @Slot(int)
    def watchRunNow(self, watch_id: int) -> None:
        self._run_watch(int(watch_id), force=True)

    def _watch_tick(self) -> None:
        if self._worker is not None:
            return                          # serialized: one job at a time
        try:
            rows = [dict(r) for r in self._con.execute(
                "SELECT w.id, w.interval, w.enabled, s.last_run"
                " FROM watch_source w LEFT JOIN watch_state s"
                " ON s.watch_id = w.id WHERE w.enabled = 1")]
        except Exception:                    # db closed during quit
            return
        for r in rows:
            if core_watch.due({"interval": r["interval"]},
                              last_run=r["last_run"] or 0):
                self._run_watch(int(r["id"]), force=False)
                break

    def _run_watch(self, watch_id: int, force: bool) -> None:
        row = self._con.execute(
            "SELECT * FROM watch_source WHERE id = ?", (watch_id,)
        ).fetchone()
        if row is None:
            return
        w = dict(row)
        data_dir = self._data_dir
        db_path = self._db_path

        def job():
            staging_root = Path(data_dir) / "watch-staging"
            local = core_watch.resolve_local(w, staging_root)
            sig = core_watch.signature(local)
            state = _watch_state(db_path, watch_id)
            if not force and sig == state.get("last_sig"):
                _touch_watch(db_path, watch_id, sig,
                             state.get("last_hits", 0))
                return {"files": 0, "errors": [], "skipped": 0,
                        "placed": 0, "rescan": False, "quiet": True}
            # changed (or forced): make it a source and scan it
            con = core_db.connect(db_path)
            try:
                src_row = con.execute(
                    "SELECT id FROM source WHERE path = ?",
                    (str(local),)).fetchone()
                if src_row is None:
                    kind = "fontroot" if local.suffix == "" and \
                        w["transport"] != "local" else "folder"
                    con.execute(
                        "INSERT INTO source(kind, path, label, enabled)"
                        " VALUES(?, ?, ?, 1)",
                        (kind, str(local), w["label"] or local.name))
                    con.commit()
                    src_row = con.execute(
                        "SELECT id FROM source WHERE path = ?",
                        (str(local),)).fetchone()
                rep = indexer.scan(con, [(src_row[0], str(local))],
                                   progress=self._progress("watch"))
            finally:
                con.close()
            hits = int(rep.get("new", 0)) + int(rep.get("changed", 0))
            _touch_watch(db_path, watch_id, sig, hits)
            return {"files": hits, "errors": [], "skipped": 0,
                    "placed": hits, "rescan": hits > 0,
                    "watch": w["label"] or str(local)}

        def done(payload):
            self._clear(self._thread)
            if payload.get("quiet"):
                return
            self.watchesChanged.emit()
            if payload.get("rescan"):
                self.message.emit(
                    f"Watch {payload.get('watch', '')}: "
                    f"{payload.get('files', 0)} new/changed")
                self.importFinished.emit(payload)
            self.jobDone.emit("watch", f"{payload.get('files', 0)} files")

        def fail(err):
            self._clear(self._thread)
            self.jobFailed.emit("watch", err)
            self.message.emit(f"watch failed: {err}")
            self.watchesChanged.emit()

        th = QThread(self)
        wk = _Worker(job)
        self._thread, self._worker = th, wk
        wk.moveToThread(th)
        th.started.connect(wk.run)
        wk.done.connect(done)
        wk.failed.connect(fail)
        wk.done.connect(wk.deleteLater)
        wk.failed.connect(wk.deleteLater)
        th.finished.connect(th.deleteLater)
        self.busyChanged.emit()
        th.start()

    def _relaunch(self) -> None:
        """Restart into the restored database (argv preserved minus the
        QA dialog flags, so we don't reopen the restore screen)."""
        if os.environ.get("FENGRID_NO_RELAUNCH"):
            self.message.emit("Database restored (relaunch suppressed)")
            return
        args, skip = [], False
        drop_with_value = {"--dialog", "--qa-select", "--db"}
        for a in sys.argv[1:]:
            if skip:
                skip = False
                continue
            if a in drop_with_value:
                skip = True
                continue
            if any(a.startswith(f"{f}=") for f in drop_with_value):
                continue
            args.append(a)
        exe = sys.executable
        try:
            if getattr(sys, "frozen", False):
                os.execv(exe, [exe, *args])
            else:
                os.execv(exe, [exe, "-m", "fengrid", *args])
        except OSError:
            self.message.emit("Restart failed — please restart manually")

    # lifecycle: quit must not destroy running threads
    def shutdown(self) -> None:
        try:
            self._timer.stop()
        except Exception:                   # noqa: BLE001
            pass


# ── helpers (module level — testable) ───────────────────────────────
def _slug_for(paths, opts) -> str:
    if len(paths) == 1:
        return _slug(Path(str(paths[0])).stem)[:40] or "import"
    return "import"


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(s)).strip("-")


def _summary(kind: str, payload) -> str:
    if not isinstance(payload, dict):
        return f"{kind}: done"
    if kind == "import":
        placed = payload.get("placed", 0)
        failed = payload.get("failed", 0)
        indexed = payload.get("indexed", 0)
        msg = f"Imported {placed} file(s)"
        if indexed:
            msg += f" · indexed {indexed}"
        if failed:
            msg += f" · {failed} failed"
        errs = payload.get("errors") or []
        if errs:
            msg += f" — {errs[0]}"
        return msg
    if kind == "export":
        return (f"Exported {payload.get('written', 0)} file(s)"
                + (f" · {payload['failed']} failed"
                   if payload.get("failed") else ""))
    if kind == "backup":
        return f"Backup saved: {payload.get('name', '')}"
    if kind == "restore":
        prev = payload.get("previous") or ""
        note = f" (previous saved as {Path(prev).name})" if prev else ""
        return f"Database restored{note} — restarting…"
    return f"{kind}: done"


def _admin_summary(op: str, data) -> str:
    if op == "check":
        return ("Integrity: OK" if data.get("ok")
                else "Integrity problems: " +
                "; ".join(data.get("lines", [])[:3]))
    if op == "vacuum":
        return (f"VACUUM complete "
                f"({data.get('pages_before')} → "
                f"{data.get('pages_after')} pages)")
    if op == "checkpoint":
        return (f"WAL checkpointed ({data.get('checkpointed', 0)} pages)"
                if "checkpointed" in data
                else f"Checkpoint: {data.get('note', 'done')}")
    if op == "optimize":
        return "Optimizer run complete"
    if op == "rebuild_fts":
        return f"Search index rebuilt ({data.get('assets', 0)} assets)"
    if op == "sweep":
        total = sum(int(v) for v in data.values())
        detail = ", ".join(f"{k}:{v}" for k, v in data.items() if v)
        return (f"Repaired {total} orphaned row(s)"
                + (f" ({detail})" if detail else ""))
    return f"{op}: done"


def _index_materialised(db_path: str, rep: dict, opts: dict) -> dict:
    """Scan every directory we just wrote into (icons + fonts)."""
    dest = rep.get("dest")
    if not dest or not rep.get("placed"):
        return {"indexed": 0}
    con = core_db.connect(db_path)
    total = 0
    try:
        row = con.execute("SELECT id FROM source WHERE path = ?",
                          (dest,)).fetchone()
        if row is None:
            # sniff: any font files in there?
            has_font = any(Path(dest).rglob("*.ttf")) or \
                any(Path(dest).rglob("*.otf"))
            con.execute(
                "INSERT INTO source(kind, path, label, enabled)"
                " VALUES(?, ?, ?, 1)",
                ("fontroot" if has_font and opts.get("mode") != "copy"
                 else ("fontroot" if has_font else "folder"),
                 dest, Path(dest).parent.name + "/" + Path(dest).name))
            con.commit()
            row = con.execute("SELECT id FROM source WHERE path = ?",
                              (dest,)).fetchone()
        has_font = any(Path(dest).rglob(ext)
                       for ext in ("*.ttf", "*.otf", "*.ttc"))
        if has_font:
            fr = ingest.scan_fonts_into(con, [(row[0], dest)])
            total += int(fr.get("total", 0))
        ir = ingest.scan_into(con, [(row[0], dest)])
        total += int(ir.get("total", 0))
    finally:
        con.close()
    return {"indexed": total, "rescan": True}


def _watch_state(db_path: str, watch_id: int) -> dict:
    con = core_db.connect(db_path)
    try:
        r = con.execute("SELECT last_run, last_sig, last_hits"
                        " FROM watch_state WHERE watch_id = ?",
                        (watch_id,)).fetchone()
        return {"last_run": r[0] if r else 0,
                "last_sig": r[1] if r else "",
                "last_hits": r[2] if r else 0} if r else \
            {"last_run": 0, "last_sig": "", "last_hits": 0}
    finally:
        con.close()


def _touch_watch(db_path: str, watch_id: int, sig: str, hits: int) -> None:
    con = core_db.connect(db_path)
    try:
        con.execute(
            "INSERT INTO watch_state(watch_id, last_run, last_sig,"
            " last_hits) VALUES(?, ?, ?, ?)"
            " ON CONFLICT(watch_id) DO UPDATE SET last_run=excluded.last_run,"
            " last_sig=excluded.last_sig, last_hits=excluded.last_hits",
            (watch_id, time.time(), sig, int(hits)))
        con.commit()
    finally:
        con.close()


def _import_bundle_job(db_path: str, data_dir: str, path: str, mode: str,
                       progress) -> dict:
    """Bundle import: materialise files → scan → re-apply tags and
    collection membership by resolved path (round-trip of export_bundle)."""
    data = xp.read_bundle(path)
    assets = list(data.get("assets", []))
    dest = Path(data_dir) / "imported" / "bundle-import"
    dest.mkdir(parents=True, exist_ok=True)
    placed_paths: dict[int, str] = {}
    placed = failed = 0
    errors: list = []
    with __import__("zipfile").ZipFile(path) as zf:
        names = set(zf.namelist())
        for i, a in enumerate(assets):
            member = f"files/{a['id']}_{Path(a['path']).name}"
            if member not in names:
                continue
            try:
                target = dest / Path(a["path"]).name
                target = dest / patterns_uniquify(dest, target.name)
                with zf.open(member) as fi, open(target, "wb") as fo:
                    import shutil
                    shutil.copyfileobj(fi, fo, 64 * 1024)
                placed_paths[a["id"]] = str(target)
                placed += 1
            except Exception as e:           # noqa: BLE001
                failed += 1
                if len(errors) < 20:
                    errors.append(f"{a.get('name')}: {e}")
            if progress is not None:
                progress(i + 1, len(assets))

    rep = {"placed": placed, "failed": failed, "skipped": 0,
           "errors": errors, "dest": str(dest)}
    rep.update(_index_materialised(db_path, rep,
                                   {"mode": "copy"}))
    # re-link tags + collections against the NEW ids (path-matched)
    con = core_db.connect(db_path)
    applied_tags = applied_coll = 0
    try:
        id_map: dict[int, int] = {}
        for old_id, p in placed_paths.items():
            r = con.execute("SELECT id FROM asset WHERE path = ?",
                            (p,)).fetchone()
            if r:
                id_map[old_id] = r[0]
        tag_ids = {t["name"]: t["id"] for t in
                   con.execute("SELECT id, name FROM tag")}
        for link in data.get("tag_links", []):
            new_id = id_map.get(link["id"])
            if not new_id:
                continue
            tid = tag_ids.get(link["tag"])
            if tid is None:
                cur = con.execute("INSERT INTO tag(name) VALUES (?)",
                                  (link["tag"],))
                tid = cur.lastrowid
                tag_ids[link["tag"]] = tid
            con.execute(
                "INSERT OR IGNORE INTO item_tag(item_id, item_kind, tag_id)"
                " VALUES(?, 'icon', ?)", (new_id, tid))
            applied_tags += 1
        coll_ids = {c["name"]: c["id"] for c in
                    con.execute("SELECT id, name FROM collection")}
        for link in data.get("collection_links", []):
            new_id = id_map.get(link["id"])
            if not new_id:
                continue
            cid = coll_ids.get(link["collection"])
            if cid is None:
                cur = con.execute("INSERT INTO collection(name) VALUES (?)",
                                  (link["collection"],))
                cid = cur.lastrowid
                coll_ids[link["collection"]] = cid
            con.execute(
                "INSERT OR IGNORE INTO collection_ref(collection_id,"
                " item_kind, item_id) VALUES(?, 'icon', ?)",
                (cid, new_id))
            applied_coll += 1
        # project round-trip: recreate the project + its asset refs
        applied_project = None
        proj = data.get("project")
        if proj:
            existing = con.execute(
                "SELECT id FROM projects WHERE name = ?",
                (proj["name"],)).fetchone()
            if existing:
                pid = existing[0]
            else:
                pid = con.execute(
                    "INSERT INTO projects(name, description, settings)"
                    " VALUES(?, ?, ?)",
                    (proj["name"], proj.get("description", ""),
                     proj.get("settings", "{}"))).lastrowid
            for old_id, new_id in id_map.items():
                con.execute(
                    "INSERT OR IGNORE INTO project_asset(project_id,"
                    " asset_kind, asset_id) VALUES(?, 'icon', ?)",
                    (pid, new_id))
            applied_project = proj["name"]
        con.commit()
    finally:
        con.close()
    rep["tag_links"] = applied_tags
    rep["project"] = applied_project
    rep["collection_links"] = applied_coll
    rep["rescan"] = True
    return rep


def patterns_uniquify(dest, name):
    from fengrid.core.patterns import uniquify
    return uniquify(dest, name)
