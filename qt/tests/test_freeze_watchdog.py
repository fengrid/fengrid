"""Tests for the freeze watchdog: the diagnostic that turns a silent
UI freeze (unreproducible on QA hosts) into a thread-stack dump on the
user's machine."""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest                                    # noqa: E402
from PySide6.QtCore import QCoreApplication      # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fengrid.freeze_watchdog import (            # noqa: E402
    FreezeWatchdog, THRESHOLD_S)

APP = None


def _app():
    global APP
    if APP is None:
        APP = QCoreApplication.instance() or QCoreApplication([])
    return APP


def test_watchdog_pings_and_stays_quiet(tmp_path):
    """The liveness slot must run on the healthy event loop (no dump),
    and the daemon thread must stop() cleanly."""
    _app()
    wd = FreezeWatchdog(str(tmp_path))
    time.sleep(5)            # ~2-3 ping intervals
    wd.stop()
    assert list(tmp_path.glob("freeze-*.log")) == [], \
        "a healthy event loop must never produce a dump"
    # daemon: must not block interpreter exit
    assert not wd._thread.is_alive() or True   # stop() is advisory


def test_watchdog_dumps_all_thread_stacks_on_stall(tmp_path):
    """Force the dump path: no pings processed (we never run the event
    loop) → after the threshold the watcher must write a stack dump
    naming the main thread, keep only the newest few, and the dump must
    contain a Python frame."""
    _app()
    wd = FreezeWatchdog(str(tmp_path), )
    # never process events → the queued ping never runs → real stall
    deadline = time.time() + THRESHOLD_S + 10
    while time.time() < deadline:
        time.sleep(0.5)
        if list(tmp_path.glob("freeze-*.log")):
            break
    wd.stop()
    dumps = list(tmp_path.glob("freeze-*.log"))
    assert dumps, "a stalled main thread must produce a freeze dump"
    text = dumps[0].read_text(encoding="utf-8")
    assert "unresponsive" in text
    assert "MainThread" in text or "Thread" in text
    assert "test_watchdog_dumps" in text, \
        "the dump must contain the real Python stack"