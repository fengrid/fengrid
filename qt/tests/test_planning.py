"""Planning board core + bridge (#132): stage model, task CRUD, Kanban
moves with fractional positions, project assignment (FK behavior), and
per-task asset links."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fengrid.core import db as core_db          # noqa: E402
from fengrid.core import planning as core_planning  # noqa: E402


@pytest.fixture()
def lib(tmp_path):
    con = core_db.connect(tmp_path / "library.db")
    con.execute("INSERT INTO projects(name, description) VALUES"
                " ('Aurora', 'rebrand')")
    con.commit()
    yield con
    con.close()


# ------------------------------------------------------------------ stages

def test_stage_model_matches_reference_board():
    keys = core_planning.STAGE_KEYS
    assert keys == ("triage", "todo", "scheduled", "ready", "running",
                    "blocked", "review", "done")
    labels = [core_planning.STAGE_LABELS[k] for k in keys]
    assert labels == ["Triage", "ToDo", "Scheduled", "Ready", "Running",
                      "Blocked", "Review", "Done"]
    # dark + light variants differ (light needs darkened hues for contrast)
    for _key, _label, dark, light in core_planning.STAGES:
        assert dark and light and dark != light


# ------------------------------------------------------------------- crud

def test_create_task_defaults_and_positions(lib):
    a = core_planning.create_task(lib, "First", "todo")
    b = core_planning.create_task(lib, "Second", "todo")
    c = core_planning.create_task(lib, "Other", "running")
    board = {s["key"]: s["cards"] for s in core_planning.board(lib)}
    assert [t["title"] for t in board["todo"]] == ["First", "Second"]
    assert board["todo"][0]["position"] < board["todo"][1]["position"]
    assert board["running"][0]["id"] == c
    assert a in [t["id"] for t in board["todo"]]
    # unknown stage falls back to triage, empty title gets a sane default
    d = core_planning.create_task(lib, "  ", "nonsense")
    board = {s["key"]: s["cards"] for s in core_planning.board(lib)}
    assert d in [t["id"] for t in board["triage"]]
    assert board["triage"][0]["title"] == "Untitled task"


def test_move_task_reorders_within_stage(lib):
    a = core_planning.create_task(lib, "A", "todo")
    b = core_planning.create_task(lib, "B", "todo")
    c = core_planning.create_task(lib, "C", "todo")
    assert core_planning.move_task(lib, c, "todo", 0)
    board = {s["key"]: s["cards"] for s in core_planning.board(lib)}
    assert [t["id"] for t in board["todo"]] == [c, a, b]
    # clamp: index past the end appends
    assert core_planning.move_task(lib, c, "todo", 99)
    board = {s["key"]: s["cards"] for s in core_planning.board(lib)}
    assert [t["id"] for t in board["todo"]] == [a, b, c]


def test_move_task_across_stages(lib):
    tid = core_planning.create_task(lib, "Flow", "triage")
    assert core_planning.move_task(lib, tid, "review", 0)
    board = {s["key"]: s["cards"] for s in core_planning.board(lib)}
    assert [t["id"] for t in board["review"]] == [tid]
    assert board["triage"] == []
    # bad stage / unknown id are no-ops
    assert not core_planning.move_task(lib, tid, "garbage", 0)
    assert not core_planning.move_task(lib, 4242, "todo", 0)


def test_update_task_whitelist_and_priority(lib):
    tid = core_planning.create_task(lib, "T")
    assert core_planning.update_task(lib, tid, title="Renamed",
                                     description="body",
                                     status_note="needs input",
                                     due_date="2026-11-15",
                                     priority="high")
    t = core_planning.task(lib, tid)
    assert t["title"] == "Renamed" and t["priority"] == "high"
    assert t["status_note"] == "needs input"
    assert t["due_date"] == "2026-11-15"
    # priority outside the vocabulary is rejected, unknown field ignored
    assert not core_planning.update_task(lib, tid, priority="urgent")
    assert not core_planning.update_task(lib, tid, evil="x")
    assert core_planning.task(lib, tid)["priority"] == "high"


def test_project_assignment_and_fk_behavior(lib):
    pid = lib.execute("SELECT id FROM projects").fetchone()["id"]
    tid = core_planning.create_task(lib, "Assigned", project_id=pid)
    t = core_planning.task(lib, tid)
    assert t["project_id"] == pid and t["projectName"] == "Aurora"
    # deleting the project NULLs the assignment (ON DELETE SET NULL),
    # the task survives
    lib.execute("DELETE FROM projects WHERE id = ?", (pid,))
    lib.commit()
    t = core_planning.task(lib, tid)
    assert t["project_id"] is None and t["projectName"] == ""


def test_task_asset_links(lib):
    lib.execute("INSERT INTO source(kind, path, label) VALUES ('folder', '/tmp', 'Probe')")
    sid = lib.execute("SELECT id FROM source").fetchone()["id"]
    lib.execute("INSERT INTO asset(source_id, kind, name, path) VALUES"
                f" ({sid}, 'icon', 'Spark', '/tmp/spark.svg')")
    lib.commit()
    aid = lib.execute("SELECT id FROM asset").fetchone()["id"]
    tid = core_planning.create_task(lib, "With assets")
    assert core_planning.link_asset(lib, tid, "icon", aid)
    # idempotent re-link
    assert core_planning.link_asset(lib, tid, "icon", aid)
    t = core_planning.task(lib, tid)
    assert t["assetCount"] == 1 and t["assets"][0]["name"] == "Spark"
    row_id = t["assets"][0]["id"]
    core_planning.unlink_asset(lib, row_id)
    assert core_planning.task(lib, tid)["assetCount"] == 0
    # unknown asset refused
    assert not core_planning.link_asset(lib, tid, "icon", 987654)
    assert not core_planning.link_asset(lib, tid, "kind", 1)


def test_search_filters_by_title_and_project(lib):
    pid = lib.execute("SELECT id FROM projects").fetchone()["id"]
    core_planning.create_task(lib, "Wire the footer")
    core_planning.create_task(lib, "Misc", "todo", pid)
    b = core_planning.board(lib, "footer")
    total = sum(len(s["cards"]) for s in b)
    assert total == 1
    b = core_planning.board(lib, "aurora")
    total = sum(len(s["cards"]) for s in b)
    todo = [s for s in b if s["key"] == "todo"][0]
    assert total == 1 and todo["cards"][0]["projectName"] == "Aurora"


def test_counts_and_total(lib):
    core_planning.create_task(lib, "One", "todo")
    core_planning.create_task(lib, "Two", "todo")
    core_planning.create_task(lib, "Three", "done")
    counts = core_planning.counts(lib)
    assert counts == {"todo": 2, "done": 1}
    assert core_planning.total(lib) == 3


# ------------------------------------------------------------------ bridge

def test_bridge_board_property_and_slots(lib, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from fengrid.bridges.planning import Planning

    QCoreApplication.instance() or QCoreApplication([])
    bridge = Planning(lib)
    seen = []
    bridge.tasksChanged.connect(lambda: seen.append(1))

    tid = bridge.create_task("Bridge task", "todo", "")
    assert seen, "tasksChanged must fire on create"
    assert bridge.totalCount == 1
    rows = [c for s in bridge.board if s["key"] == "todo"
            for c in s["cards"]]
    assert rows and rows[0]["title"] == "Bridge task"

    bridge.move_task(tid, "review", 0)
    rows = [c for s in bridge.board if s["key"] == "review"
            for c in s["cards"]]
    assert rows and rows[0]["id"] == tid

    bridge.update_task(tid, "status_note", "needs input")
    detail = bridge.task(tid)
    assert detail["status_note"] == "needs input"
    assert detail["shortId"] and len(detail["shortId"]) == 6

    bridge.assign_project(tid, 0)     # 0 → unassigned, not a crash
    assert bridge.task(tid)["project_id"] is None

    # options + stages + search
    assert bridge.project_options() and bridge.project_options()[0]["name"]
    assert len(bridge.asset_options("snippet")) == 0  # empty library
    assert len(bridge.stages) == 8
    bridge.set_search("nomatch-xyz")
    filtered = [c for st in bridge.board for c in st["cards"]]
    assert filtered == []             # board respects the filter
    assert bridge.totalCount == 1     # badge stays the unfiltered total
    bridge.set_search("")
    assert bridge.totalCount == 1

    bridge.delete_task(tid)
    assert bridge.totalCount == 0

    # toast slot routes validation strings through the message signal
    got = []
    bridge.message.connect(got.append)
    bridge.toast("Bad value")
    assert got == ["Bad value"]
