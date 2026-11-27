"""Storage bridge: attach/detach/remount storage backends from QML.

Mount operations run on a worker thread (a network mount can hang for
its full timeout — the UI must never block), one op at a time. The
source table stays Library's territory: `attached`/`detached` are
signals the shell answers with library.add_folder / remove_folder_path.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QObject, QThread, Signal, Slot

from ..core import storage as core_storage
from ..core import db as core_db


class _OpWorker(QObject):
    done = Signal(dict)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            self.done.emit({"ok": True, **self._fn()})
        except core_storage.StorageError as e:
            self.done.emit({"ok": False, "err": str(e)})
        except Exception as e:            # noqa: BLE001 — surface, don't crash
            self.done.emit({"ok": False, "err": str(e)})
        finally:
            # one-shot worker: leave the event loop after the slot
            # returns, or the QThread idles forever and destroying the
            # bridge aborts the process (tests + rapid attach churn)
            QThread.currentThread().quit()


class Storage(QObject):
    message = Signal(str)
    attached = Signal(str, str)     # local_path, source kind
    detached = Signal(str)          # local_path
    mountsChanged = Signal()
    ready = Signal(int, int)        # remount: ok, failed

    def __init__(self, con, data_dir: str, parent=None):
        super().__init__(parent)
        self._con = con
        self._data_dir = data_dir
        self._thread: QThread | None = None
        self._worker: _OpWorker | None = None
        self._busy = False
        self._mounts = self._load()
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_about_to_quit)

    # ------------------------------------------------------------ state
    def _load(self) -> list[dict]:
        rows = self._con.execute(
            "SELECT id, backend, uri, local_path, kind FROM storage_mount"
            " ORDER BY backend, uri").fetchall()
        out = []
        for r in rows:
            row = dict(r)
            meta = core_storage.BACKENDS.get(row["backend"])
            row["backendLabel"] = meta.label if meta else row["backend"]
            row["healthy"] = core_storage.healthy(row["local_path"],
                                                  row["backend"])
            out.append(row)
        return out

    @Property("QVariantList", notify=mountsChanged)
    def mounts(self):
        return self._mounts

    @Property(int, notify=mountsChanged)
    def mountCount(self) -> int:
        return len(self._mounts)

    @Property("QVariantList", constant=True)
    def backends(self):
        """All backends for the Settings storage rows (local included —
        its 'attach' is the folder picker)."""
        out = []
        for key, b in core_storage.BACKENDS.items():
            avail, status = core_storage.availability(key)
            out.append({"key": key, "label": b.label, "hint": b.hint,
                        "available": avail, "status": status})
        return out

    @Property(bool, notify=mountsChanged)
    def busy(self) -> bool:
        return self._busy

    # -------------------------------------------------------------- slots
    @Slot(str, str, str)
    def attach(self, backend: str, uri: str, kind: str = "folder") -> None:
        """Mount + register a backend; emits attached(local, kind)."""
        uri = (uri or "").strip()
        if not uri:
            self.message.emit("Enter a location first")
            return
        if kind not in ("folder", "fontroot"):
            kind = "folder"
        if self._busy:
            self.message.emit("A storage operation is already running")
            return
        self._start("attach", {
            "backend": backend, "uri": uri, "kind": kind,
        })

    @Slot(int)
    def detach(self, mount_id: int) -> None:
        row = next((m for m in self._mounts if m["id"] == mount_id), None)
        if row is None:
            return
        if self._busy:
            self.message.emit("A storage operation is already running")
            return
        self._start("detach", dict(row))

    @Slot()
    def remountAll(self) -> None:
        """Startup: bring registered mounts back (skip healthy ones).
        Emits ready(ok, failed) — the shell starts its first scan after."""
        stale = [m for m in self._mounts if not m["healthy"]]
        if not stale:
            self.ready.emit(len(self._mounts), 0)
            return
        if self._busy:
            self.ready.emit(len(self._mounts) - len(stale), len(stale))
            return
        self._start("remount", {"rows": stale})

    # ----------------------------------------------------------- internals
    def _start(self, op: str, payload: dict) -> None:
        self._busy = True
        self.mountsChanged.emit()

        if op == "attach":
            b, uri = payload["backend"], payload["uri"]

            def fn():
                # the worker only mounts — DB writes stay on the main
                # thread (sqlite objects are thread-affine)
                path = core_storage.attach(b, uri, self._data_dir)
                return {"op": op, "path": str(path),
                        "kind": payload["kind"], "backend": b, "uri": uri}
        elif op == "detach":
            b, uri, path = (payload["backend"], payload["uri"],
                            payload["local_path"])

            def fn():
                core_storage.detach(b, uri, path)
                return {"op": op, "path": path, "id": payload["id"]}
        else:  # remount
            rows = payload["rows"]

            def fn():
                failed = []
                for m in rows:
                    try:
                        core_storage.attach(m["backend"], m["uri"],
                                            self._data_dir)
                    except core_storage.StorageError as e:
                        failed.append(f"{m['uri']}: {e}")
                return {"op": "remount", "failed": failed,
                        "ok": len(rows) - len(failed)}

        th = QThread(self)
        wk = _OpWorker(fn)
        self._thread, self._worker = th, wk
        wk.moveToThread(th)
        wk.done.connect(self._on_done)
        th.started.connect(wk.run)
        th.finished.connect(wk.deleteLater)
        th.finished.connect(th.deleteLater)
        th.finished.connect(lambda t=th: self._clear_refs(t))
        th.start()

    def _on_done(self, result: dict) -> None:
        op = result.get("op", "")
        self._busy = False
        if op == "remount":
            failed = result.get("failed", [])
            for line in failed:
                self.message.emit(f"Remount failed — {line}")
            self.ready.emit(int(result.get("ok", 0)), len(failed))
        elif not result.get("ok"):
            self.message.emit(f"Storage: {result.get('err', 'failed')}")
        elif op == "attach":
            # main thread owns the connection — register now that the
            # mount actually exists
            self._register(result["backend"], result["uri"],
                           result["path"], result["kind"])
            self.message.emit(f"Attached: {result['path']}")
            self.attached.emit(result["path"], result["kind"])
        elif op == "detach":
            self._forget(result["id"], result["path"])
            self.message.emit(f"Detached: {result['path']}")
            self.detached.emit(result["path"])
        self._mounts = self._load()
        self.mountsChanged.emit()

    def _clear_refs(self, t=None) -> None:
        # only clear OUR generation — a newer op may own the refs now
        if t is None or self._thread is t:
            self._thread = None
            self._worker = None

    def _on_about_to_quit(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(10000)

    # registry helpers — the source row itself belongs to Library
    def _register(self, backend: str, uri: str, local_path: str,
                  kind: str) -> None:
        self._con.execute(
            "INSERT INTO storage_mount(backend, uri, local_path, kind)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(local_path) DO UPDATE SET uri = excluded.uri,"
            " backend = excluded.backend, kind = excluded.kind",
            (backend, uri, local_path, kind))
        self._con.commit()

    def _forget(self, mount_id: int, local_path: str) -> None:
        self._con.execute("DELETE FROM storage_mount WHERE id = ?",
                          (mount_id,))
        self._con.commit()