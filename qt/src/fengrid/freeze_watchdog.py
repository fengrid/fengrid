"""Main-thread liveness watchdog: turns a silent UI freeze into evidence.

When the Qt main thread stops servicing the event loop, the app looks
dead to the user, logs nothing, and the only diagnostic is a force-kill
— exactly the class of bug that cannot be reproduced on a QA host. This
watchdog makes that state self-reporting: a daemon thread pings the main
thread through a queued slot every couple of seconds; if the slot has
not run for a sustained window, it writes every thread's Python stack to
``<data_dir>/freeze-<timestamp>.log`` (keeping the newest few) and prints
one terminal line pointing at the file.

Deliberately low-tech: the watcher thread touches no Qt object beyond
the queued invoke (so it cannot deadlock against Qt's own locks), dumps
are rare and cheap, the threshold is generous enough that heavy scans or
large exports on a slow machine never trigger it, and the thread is a
daemon so it can never block quit.
"""

from __future__ import annotations

import faulthandler
import glob
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QMetaObject, Qt, Slot

PING_INTERVAL_S = 2.0
THRESHOLD_S = 15.0
REARM_S = 60.0          # one dump per sustained stall, not per interval
KEEP_DUMPS = 5


class _Liveness(QObject):
    """Lives on the main thread; its ping slot only runs when the event
    loop is actually processing events."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.last = time.monotonic()

    @Slot()
    def ping(self):
        self.last = time.monotonic()


class FreezeWatchdog:
    def __init__(self, data_dir: str, parent=None, autostart: bool = True):
        self._data_dir = str(data_dir)
        self._live = _Liveness(parent)
        self._running = False
        self._thread: threading.Thread | None = None
        if autostart:
            self.start()

    def start(self) -> None:
        """Arm and start the watchdog thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._live.last = time.monotonic()
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="fengrid-freeze-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Idempotent; called from aboutToQuit so the daemon never races
        process teardown."""
        self._running = False

    # ----------------------------------------------------------- internals
    def _loop(self) -> None:
        while self._running:
            QMetaObject.invokeMethod(self._live, "ping",
                                     Qt.ConnectionType.QueuedConnection)
            time.sleep(PING_INTERVAL_S)
            if not self._running:
                break
            stalled = time.monotonic() - self._live.last
            if stalled < THRESHOLD_S:
                continue
            try:
                path = self._dump(stalled)
            except Exception:                # noqa: BLE001 — never crash
                path = "<dump failed>"
            print(f"warning: fengrid UI freeze detected "
                  f"(main thread unresponsive {int(stalled)}s) — "
                  f"thread stacks written to {path}", file=sys.stderr)
            time.sleep(REARM_S)              # one dump per sustained stall

    def _dump(self, stalled: float) -> str:
        d = Path(self._data_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"freeze-{time.strftime('%Y%m%d-%H%M%S')}.log"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"fengrid freeze dump — {time.ctime()}\n"
                    f"main thread unresponsive >= {int(stalled)}s\n"
                    f"(the Qt event loop stopped servicing queued events)\n\n")
            faulthandler.dump_traceback(file=f)
        old = sorted(glob.glob(str(d / "freeze-*.log")))
        for stale in old[:-KEEP_DUMPS]:
            try:
                os.unlink(stale)
            except OSError:
                pass
        return str(path)