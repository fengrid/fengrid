"""QML tests for the Planning pane (#132): the Kanban board creates
against the real Planning bridge, the accordion expands/collapses
stages, task creation through the dialog lands in the board, and the
drag glue computes drop targets correctly (data-layer moves drive the
assertions — real mouse drags are covered by the bridge move tests).

House pattern (see test_qml_colors): the QQmlComponent stays a local of
the yielding fixture frame — created objects DIE with their component,
so a helper function that returns would destroy the scene.
"""
import os
import sys
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest                                    # noqa: E402
from PySide6.QtCore import QPointF as _QPointF    # noqa: E402
from PySide6.QtCore import Qt as _Qt              # noqa: E402
from PySide6.QtCore import QUrl                  # noqa: E402
from PySide6.QtGui import QGuiApplication        # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PySide6.QtTest import QTest                   # noqa: E402

QML_DIR = Path(__file__).resolve().parents[1] / "qml"
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        _APP = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


def _by_class(root, prefix):
    out, stack = [], [root]
    while stack:
        o = stack.pop()
        try:
            cn = o.metaObject().className()
        except RuntimeError:
            continue
        if cn.startswith(prefix):
            out.append(o)
        try:
            stack.extend(o.childItems())
        except RuntimeError:
            continue
    return out


@pytest.fixture()
def planning_ui(tmp_path):
    _qapp()
    from fengrid.bridges.planning import Planning
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    theme = Theme(con, "")
    bridge = Planning(con)

    engine = QQmlEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("planning", bridge)

    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(str(QML_DIR / "components" /
                                        "Planning.qml")))
    root = cast(QQuickItem, comp.create(engine.rootContext()))
    assert root is not None, [str(e) for e in comp.errors()]
    root.setWidth(1280)
    root.setHeight(800)
    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    _qapp().processEvents()

    yield {"root": root, "win": win, "engine": engine,
           "bridge": bridge, "con": con}
    # let the accordion's width Behavior animations (140ms) settle before
    # teardown — tearing a window down mid-animation poisons the next
    # fixture in the same process
    QTest.qWait(220)
    win.close()
    try:
        root.setParentItem(None)
    except RuntimeError:
        pass
    engine.collectGarbage()
    del engine


def _stage_cols(root):
    # inline components report their QML type name (StageColumn), not the
    # C++ base class
    return [o for o in _by_class(root, "StageColumn")
            if o.property("stageData") is not None]


def test_board_creates_with_eight_stage_columns(planning_ui):
    root = planning_ui["root"]
    cols = _stage_cols(root)
    assert len(cols) == 8
    # default expanded stage is todo; one expanded, seven bars
    expanded = [c for c in cols if c.property("expanded")]
    assert len(expanded) == 1
    assert expanded[0].property("stageData")["key"] == "todo"


def test_accordion_expands_clicked_stage(planning_ui):
    root = planning_ui["root"]
    cols = _stage_cols(root)
    target = [c for c in cols
              if c.property("stageData")["key"] == "review"][0]
    # the header TapHandler is what a click hits — drive the same state
    # change the handler makes (item-level interaction in offscreen rigs
    # is fragile; the state contract is what matters)
    root.setProperty("expandedStage", "review")
    _qapp().processEvents()
    expanded = [c for c in cols if c.property("expanded")]
    assert len(expanded) == 1
    assert expanded[0].property("stageData")["key"] == "review"
    # collapsing all is allowed ("" = all bars)
    root.setProperty("expandedStage", "")
    _qapp().processEvents()
    assert not [c for c in cols if c.property("expanded")]


def test_task_creation_flows_to_board(planning_ui):
    ui = planning_ui
    root, bridge = ui["root"], ui["bridge"]
    before = bridge.totalCount
    tid = bridge.create_task("Design the badge", "todo")
    assert tid > 0 and bridge.totalCount == before + 1
    _qapp().processEvents()
    cols = _stage_cols(root)
    todo = [c for c in cols
            if c.property("stageData")["key"] == "todo"][0]
    cards = todo.property("stageData")["cards"]
    assert any(c["title"] == "Design the badge" for c in cards)

    # the card component rendered in the expanded column
    cards_ui = [o for o in _by_class(todo, "TaskCard")
                if o.property("task") is not None]
    assert any(o.property("task")["id"] == tid for o in cards_ui)


def test_move_task_via_bridge_updates_board(planning_ui):
    ui = planning_ui
    root, bridge = ui["root"], ui["bridge"]
    tid = bridge.create_task("Move me", "todo")
    _qapp().processEvents()
    root.setProperty("expandedStage", "running")
    _qapp().processEvents()
    bridge.move_task(tid, "running", 0)
    _qapp().processEvents()
    cols = _stage_cols(root)
    running = [c for c in cols
               if c.property("stageData")["key"] == "running"][0]
    cards = running.property("stageData")["cards"]
    assert any(c["id"] == tid for c in cards)
    todo = [c for c in cols if c.property("stageData")["key"] == "todo"][0]
    assert not any(c["id"] == tid for c in todo.property("stageData")["cards"])


def test_drag_glue_targets(planning_ui):
    """stageAtPoint resolves planningRoot coordinates to a stage key and
    indexAtY resolves them to an insertion slot — the two halves of
    drag & drop. Coordinates go through mapToItem so Flickable scroll
    offsets can never skew the hit test."""
    root = planning_ui["root"]
    cols = _stage_cols(root)
    expanded = [c for c in cols if c.property("expanded")][0]
    w = expanded.property("width")
    # the column's center, mapped into planningRoot coordinates (the
    # space the drag proxy and the card MouseArea report)
    center = expanded.mapToItem(root, w / 2, 100)
    key = root.stageAtPoint(center.x(), center.y())
    assert key == expanded.property("stageData")["key"]
    assert root.stageAtPoint(-50, -50) == ""
    # insertion slot beyond the last card appends
    assert expanded.indexAtY(center.x(), 10_000) == \
        len(expanded.property("stageData")["cards"])
    # slot before every card is 0 (top of the column, planningRoot coords)
    top = expanded.mapToItem(root, w / 2, 60)
    assert expanded.indexAtY(top.x(), top.y()) == 0


def test_dialog_opens_with_task_data(planning_ui):
    ui = planning_ui
    bridge = ui["bridge"]
    tid = bridge.create_task("Dialog probe", "blocked")
    bridge.update_task(tid, "status_note", "needs input")
    _qapp().processEvents()
    # open the detail view through the pane's own entry point
    ui["root"].openTask(tid)
    _qapp().processEvents()
    d = ui["root"].property("taskDialogRef")
    assert d is not None and d.property("creating") is not None, \
        "task dialog must be reachable through the QA handle"
    assert d.property("creating") is False
    assert d.property("task")["title"] == "Dialog probe"
    d.close()


def test_card_drag_gesture_moves_task(planning_ui):
    """Full gesture path: press a card, drag it over a collapsed bar,
    release — the proxy follows the pointer, the drop files the task in
    that stage and expands it (the #132 retest bug: the Flickables ate
    the gesture and drags did nothing)."""
    ui = planning_ui
    root, bridge, win = ui["root"], ui["bridge"], ui["win"]
    root.setProperty("expandedStage", "todo")
    tid = bridge.create_task("Drag Target", "todo")
    _qapp().processEvents()

    cols = _stage_cols(root)
    todo = [c for c in cols
            if c.property("stageData")["key"] == "todo"][0]
    triage = [c for c in cols
              if c.property("stageData")["key"] == "triage"][0]

    card = [o for o in _by_class(todo, "TaskCard")
            if o.property("task")["id"] == tid][0]
    ma = [c for c in card.childItems()
          if c.metaObject().className().startswith("QQuickMouseArea")][0]

    start = card.mapToItem(win.contentItem(), card.width() / 2,
                           card.height() / 2)
    QTest.mousePress(win, _Qt.MouseButton.LeftButton,
                     pos=start.toPoint())
    _qapp().processEvents()
    # move past the 6px drag threshold
    QTest.mouseMove(win, (start + _QPointF(0, 40)).toPoint())
    _qapp().processEvents()
    assert root.property("dragTaskId") == tid, "drag never started"

    hover = triage.mapToItem(win.contentItem(), 17, 300)
    QTest.mouseMove(win, hover.toPoint())
    _qapp().processEvents()
    assert root.property("dragHoverStage") == "triage"

    QTest.mouseRelease(win, _Qt.MouseButton.LeftButton,
                       pos=hover.toPoint())
    _qapp().processEvents()
    assert root.property("dragTaskId") == -1
    assert root.property("expandedStage") == "triage", \
        "dropping on a collapsed bar must expand it"
    # the drop triggered a board rebuild — the pre-drop column wrappers
    # are dead; re-fetch from the fresh delegate tree
    fresh = _stage_cols(root)
    triage2 = [c for c in fresh
               if c.property("stageData")["key"] == "triage"][0]
    triage_cards = triage2.property("stageData")["cards"]
    assert any(c["id"] == tid for c in triage_cards)
