"""Issue #57: the Projects pane's "No projects yet" empty state must
disappear when projects exist.

Root cause: bridges/projects.py declared `projectCount` as a `constant=True`
Property. `constant=True` tells the QML engine the value NEVER changes, so
the `visible: projects.projectCount === 0` binding in Projects.qml was never
re-evaluated after create/delete — the empty-state text stayed visible with
projects in the list.

This test drives the REAL Projects bridge through a QML binding and proves
the binding re-evaluates when the project list changes. With the pre-fix
`constant=True` declaration the text stays "0" after create() and the test
FAILS; with `notify=projectsChanged` it follows the list.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine

QML_DIR = Path(__file__).resolve().parents[1] / "qml"
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_APP = None

PROBE_QML = """
import QtQuick
Text {
    property int count: projects.projectCount
    property bool emptyVisible: projects !== null
                                && projects.projectCount === 0
    text: count
}
"""


def _qapp():
    global _APP
    if _APP is None:
        _APP = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


@pytest.fixture()
def projects_env(tmp_path):
    _qapp()
    from fengrid.bridges.projects import Projects
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    bridge = Projects(con)

    engine = QQmlEngine()
    engine.rootContext().setContextProperty("projects", bridge)
    comp = QQmlComponent(engine)
    comp.setData(PROBE_QML.encode(), QUrl("file:///probe.qml"))
    root = comp.create()
    assert root is not None, comp.errorString()
    # keep the component alive for the test body (QML lesson 17)
    yield bridge, root, comp, engine
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()
    con.close()


def test_project_count_binding_follows_create(projects_env):
    """The QML binding must re-evaluate when a project is created —
    a `constant=True` Property never notifies and the empty state
    sticks (issue #57)."""
    bridge, root, comp, engine = projects_env
    assert bridge.projectCount == 0
    assert root.property("emptyVisible") is True
    assert root.property("text") == "0"

    bridge.create("First project")
    assert bridge.projectCount == 1

    # the binding must have re-evaluated (constant=True never would)
    assert root.property("text") == "1", (
        "projectCount binding did not re-evaluate after create() — "
        "empty state would stay visible (issue #57)")
    assert root.property("emptyVisible") is False


def test_project_count_binding_follows_remove(projects_env):
    bridge, root, comp, engine = projects_env
    bridge.create("Only project")
    assert root.property("text") == "1"
    pid = bridge.currentId
    bridge.remove(pid)
    assert bridge.projectCount == 0
    assert root.property("text") == "0", (
        "projectCount binding did not re-evaluate after remove()")
    assert root.property("emptyVisible") is True