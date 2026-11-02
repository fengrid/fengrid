"""#141: live loading bars on the Preset Libraries dialog cards.

Drives the REAL PresetsDialog offscreen with the REAL Presets bridge:
emits the bridge's downloadProgress / downloadState signals and asserts
the per-card overlay appears, tracks the clone percent, pulses during
the ingestion scan, disappears when done, and survives both a model
rebuild and a dialog reopen (the map must never clobber live ticks and
must re-seed from the bridge snapshot).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

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
def presets_ui(tmp_path):
    _qapp()
    from fengrid.bridges.library import Library
    from fengrid.bridges.presets import Presets
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db
    from fengrid.core import presets as core_presets

    con = core_db.connect(tmp_path / "t.db")
    core_presets.ensure_presets(con)
    theme = Theme(con, str(FONTS))
    presets_bridge = Presets(con, str(tmp_path))
    library = Library(con, str(tmp_path / "t.db"), no_scan=True)

    engine = QQmlEngine()
    engine.rootContext().setContextProperty("theme", theme)
    engine.rootContext().setContextProperty("presets", presets_bridge)
    engine.rootContext().setContextProperty("library", library)
    engine.rootContext().setContextProperty("fonts", None)
    engine.rootContext().setContextProperty("previewProfile", None)
    engine.rootContext().setContextProperty("terms", None)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(
        str(QML_DIR / "components" / "PresetsDialog.qml")))
    root = comp.create(engine.rootContext())
    assert root is not None, comp.errors()

    win = QQuickWindow()
    win.setWidth(760)
    win.setHeight(640)
    root.setProperty("parent", win.contentItem())
    root.setProperty("width", 720)
    if hasattr(root, "open"):
        root.open()
    win.show()
    _qapp().processEvents()

    yield {"root": root, "win": win, "presets": presets_bridge,
           "con": con}

    if hasattr(root, "close"):
        root.close()
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()
    con.close()


def _find_by_name(item, name):
    hits = []
    stack = [item]
    while stack:
        o = stack.pop()
        try:
            if o.objectName() == name:
                hits.append(o)
        except (AttributeError, RuntimeError):
            pass
        if hasattr(o, "childItems"):
            stack.extend(o.childItems())
    return hits


def _icon_entry(ui):
    bridge = ui["presets"]
    lib = [l for l in bridge.libraries if l["kind"] == "icon"][0]
    row = bridge.entries(lib["id"])[0]
    return lib, row


def _open_icon_library(ui):
    lib, row = _icon_entry(ui)
    ui["root"].openLibrary(lib["id"], "")
    _qapp().processEvents()
    return lib, row


def _visible_overlays(ui):
    content = ui["root"].property("contentItem")
    return [o for o in _find_by_name(content, "presetProgressOverlay")
            if o.property("visible")]


def _one_visible_overlay(ui):
    overlays = _visible_overlays(ui)
    assert len(overlays) == 1, (
        f"expected exactly one visible loading bar, got {len(overlays)}")
    return overlays[0]


def _descendant(overlay, name):
    hits = _find_by_name(overlay, name)
    assert hits, f"{name} not found under the overlay"
    return hits[0]


def test_no_overlay_without_a_download(presets_ui):
    _open_icon_library(presets_ui)
    assert _visible_overlays(presets_ui) == [], (
        "loading bar visible while nothing downloads")


def test_clone_progress_tracks_percent(presets_ui):
    ui = presets_ui
    lib, row = _open_icon_library(ui)
    bridge = ui["presets"]

    bridge.downloadProgress.emit(row["id"], "clone", 45)
    ui["win"].grabWindow()          # force a render pass
    _qapp().processEvents()
    ov = _one_visible_overlay(ui)
    lbl = _descendant(ov, "presetProgressLabel")
    fill = _descendant(ov, "presetProgressFill")
    pulse = _descendant(ov, "presetProgressPulse")
    assert lbl.property("text") == "Cloning  45%", lbl.property("text")
    assert fill.property("visible") is True
    assert pulse.property("visible") is False
    track = _descendant(ov, "presetProgressTrack")
    ratio = fill.property("width") / (track.property("width") - 2)
    assert abs(ratio - 0.45) < 0.02, f"fill ratio {ratio:.3f} != 0.45"

    # ticks update in place
    bridge.downloadProgress.emit(row["id"], "clone", 80)
    _qapp().processEvents()
    ov = _one_visible_overlay(ui)
    assert _descendant(ov, "presetProgressLabel").property(
        "text") == "Cloning  80%"


def test_ingest_phase_pulses_then_clears(presets_ui):
    ui = presets_ui
    lib, row = _open_icon_library(ui)
    bridge = ui["presets"]

    bridge.downloadState.emit(row["id"], "ingest")
    _qapp().processEvents()
    ov = _one_visible_overlay(ui)
    assert _descendant(ov, "presetProgressLabel").property(
        "text") == "Indexing…"
    assert _descendant(ov, "presetProgressFill").property(
        "visible") is False
    assert _descendant(ov, "presetProgressPulse").property(
        "visible") is True

    # the scan finishes → the bar goes away
    bridge.downloadState.emit(row["id"], "done")
    _qapp().processEvents()
    assert _visible_overlays(ui) == [], "loading bar stuck after 'done'"


def test_entries_changed_never_clobbers_live_ticks(presets_ui):
    ui = presets_ui
    lib, row = _open_icon_library(ui)
    bridge = ui["presets"]

    bridge.downloadProgress.emit(row["id"], "clone", 20)
    _qapp().processEvents()
    # a model rebuild (entriesChanged → refresh) must keep the live tick
    bridge.entriesChanged.emit()
    _qapp().processEvents()
    ov = _one_visible_overlay(ui)
    lbl = _descendant(ov, "presetProgressLabel")
    assert lbl.property("text") == "Cloning  20%", lbl.property("text")


def test_reopen_seeds_progress_from_the_bridge_snapshot(presets_ui):
    """The dialog re-opened mid-download must show the true percent —
    entries() carries the snapshot, refresh() seeds the map from it."""
    ui = presets_ui
    lib, row = _open_icon_library(ui)
    bridge = ui["presets"]

    # simulate a download already in flight when the dialog opened
    bridge._busy.add(row["id"])
    bridge._progress[row["id"]] = 60
    bridge.entriesChanged.emit()
    _qapp().processEvents()
    ov = _one_visible_overlay(ui)
    lbl = _descendant(ov, "presetProgressLabel")
    assert lbl.property("text") == "Cloning  60%", lbl.property("text")

    # a REOPEN starts from an empty map — simulate one, flip the bridge
    # state to the ingestion phase, and the seed must show the pulse
    ui["root"].setProperty("progressMap", {})
    bridge._busy.discard(row["id"])
    bridge._progress.pop(row["id"], None)
    bridge._ingesting.add(row["id"])
    bridge.entriesChanged.emit()
    _qapp().processEvents()
    ov = _one_visible_overlay(ui)
    assert _descendant(ov, "presetProgressLabel").property(
        "text") == "Indexing…"
    assert _descendant(ov, "presetProgressPulse").property(
        "visible") is True
