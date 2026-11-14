"""Gating tests for the launch splash (SplashOverlay).

Regression for #34: the splash used to be driven by a startup-time
snapshot (`initialScans` computed before engine.load) — whenever the
initial scans were scheduled after that point (mounts remount, setup
flow) the session was stale and the splash never showed, leaving a
multi-minute first scan with no feedback at all.

SplashOverlay now owns the session: it opens whenever a scan starts on
a still-empty database and closes when the scans go quiet. A rescan of
a populated library never opens it.

The tests drive the real Library/Fonts bridges (no_scan=True) and flip
`scanning` through the bridge's internal flag + scanningChanged signal —
exactly the state and signal the QML gating reads — so no real
filesystem scan (or its timing races) is involved.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest                                    # noqa: E402
from PySide6.QtCore import QUrl                  # noqa: E402
from PySide6.QtGui import QGuiApplication        # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow         # noqa: E402
from PySide6.QtTest import QTest                 # noqa: E402

QML_DIR = Path(__file__).resolve().parents[1] / "qml"
SRC = Path(__file__).resolve().parents[1] / "src"
FONTS = Path(__file__).resolve().parents[2] / "fonts"
sys.path.insert(0, str(SRC))

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        _APP = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


@pytest.fixture()
def splash_ui(tmp_path):
    _qapp()
    from fengrid.bridges.fonts import Fonts
    from fengrid.bridges.library import Library
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    db_path = str(tmp_path / "t.db")
    theme = Theme(con, str(FONTS))
    library = Library(con, db_path, no_scan=True)
    fonts = Fonts(con, db_path)

    engine = QQmlEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("fonts", fonts)
    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(
            str(QML_DIR / "components" / "SplashOverlay.qml")))
    root = comp.create(engine.rootContext())
    assert root is not None, [str(e) for e in comp.errors()]
    root.setWidth(1280)
    root.setHeight(800)
    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    _qapp().processEvents()
    QTest.qWait(50)

    yield {"root": root, "win": win, "engine": engine,
           "library": library, "fonts": fonts, "con": con}

    win.close()
    try:
        root.setParentItem(None)
    except RuntimeError:
        pass
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()


def _set_scanning(bridge, on: bool):
    """Flip a bridge's `scanning` the way its own scan lifecycle does."""
    bridge._scanning = on
    bridge.scanningChanged.emit()


def _finish(library, fonts):
    """Both scans go quiet: scanFinished on each, other not scanning."""
    _set_scanning(library, False)
    library.scanFinished.emit({})
    _set_scanning(fonts, False)
    fonts.scanFinished.emit({})


def test_splash_hidden_initially(splash_ui):
    root = splash_ui["root"]
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is False


def test_splash_opens_on_scan_of_empty_library(splash_ui):
    """THE #34 regression: scan starts on an empty DB → splash opens."""
    root, library = splash_ui["root"], splash_ui["library"]
    _set_scanning(library, True)
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is True
    _finish(splash_ui["library"], splash_ui["fonts"])
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is False


def test_splash_opens_on_scan_of_empty_fonts(splash_ui):
    root, fonts = splash_ui["root"], splash_ui["fonts"]
    _set_scanning(fonts, True)
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is True
    _finish(splash_ui["library"], splash_ui["fonts"])
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is False


def test_splash_stays_hidden_for_rescan_of_populated_library(splash_ui):
    """Manual rescans of a populated library never reshow the splash."""
    root, con, library = (splash_ui["root"], splash_ui["con"],
                          splash_ui["library"])
    # one real asset row (through the real source FK) → totalAssets > 0
    src = con.execute(
        "INSERT INTO source (kind, path, label, enabled) VALUES"
        " ('local', '/tmp', 'test', 1)").lastrowid
    con.execute(
        "INSERT INTO asset (source_id, kind, name, path, mtime) VALUES"
        " (?, 'icon', 'test-icon', '/tmp/test-icon.svg', 0)", (src,))
    con.commit()
    assert library.totalAssets > 0
    _set_scanning(library, True)
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is False
    _finish(splash_ui["library"], splash_ui["fonts"])
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is False


def test_splash_survives_until_both_scans_quiet(splash_ui):
    """Library scan finishing alone must NOT close a fonts-only session."""
    root, fonts = splash_ui["root"], splash_ui["fonts"]
    _set_scanning(fonts, True)
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is True
    _finish(splash_ui["library"], splash_ui["fonts"])
    # library quiet, fonts still scanning → splash stays
    _set_scanning(fonts, False)   # override the _finish above's fonts part
    fonts.scanFinished.emit({})
    _set_scanning(fonts, True)
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is True
    _finish(splash_ui["library"], splash_ui["fonts"])
    QTest.qWait(50)
    _qapp().processEvents()
    assert root.property("shown") is False
