"""Planning bridge — the `planning` context property behind the Planning
pane (#132). Thin adapter over core.planning: Kanban stage CRUD lives in
SQLite (project_task / project_task_asset), moves are fractional-position
reorders, and the board property carries stage labels/colors so QML and
the data layer agree on them.

Slots are snake_case on purpose — PySide6 exposes @Slot methods under
their Python name only (no camelCase alias; see the #138 fix).
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import planning as core_planning


class Planning(QObject):
    message = Signal(str)
    tasksChanged = Signal()
    # deep integration: a card's project chip opens the project in the
    # Projects pane (Main.qml performs the pane switch + open())
    openProjectRequested = Signal(int)
    # QA affordance: --qa-select opens the matching task's editor. A
    # PROPERTY, not a signal: the pane's Loader is asynchronous, so a
    # signal emitted before the component finishes loading would be
    # lost — the pane reacts to the property (and its notify) instead.
    _pendingOpenChanged = Signal()

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        self._search = ""
        self._board = core_planning.board(self._con, self._search)
        self._pending_open = -1
        core_planning.migrate(self._con)

    # ------------------------------------------------------------ properties

    def _refresh(self) -> None:
        self._board = core_planning.board(self._con, self._search)
        self.tasksChanged.emit()

    @Property("QVariant", notify=tasksChanged)
    def board(self):
        return self._board

    @Property("QVariant", constant=True)
    def stages(self):
        return core_planning.stages(self._con)

    @Property(int, notify=tasksChanged)
    def totalCount(self):
        return core_planning.total(self._con)

    @Property(int, notify=_pendingOpenChanged)
    def pendingOpenTask(self):
        return self._pending_open

    # ---------------------------------------------------------------- slots

    @Slot(str)
    def toast(self, msg: str) -> None:
        """QML-side validation messages ride the same toast signal."""
        self.message.emit(str(msg))

    @Slot(str)
    def set_search(self, q: str) -> None:
        self._search = q.strip()
        self._refresh()

    @Slot(str, str, result=int)
    def create_task(self, title: str, stage: str = "triage",
                    project_id: str = "") -> int:
        pid = int(project_id) if str(project_id).lstrip("-").isdigit() \
            else None
        tid = core_planning.create_task(self._con, title, stage, pid)
        self._refresh()
        self.message.emit("Task created")
        return tid

    @Slot(int, str, str)
    def update_task(self, task_id: int, field: str, value: str) -> None:
        fields = {field: value}
        if not core_planning.update_task(self._con, int(task_id), **fields):
            self.message.emit(f"Cannot change field: {field}")
            return
        self._refresh()

    @Slot(int, str, int)
    def move_task(self, task_id: int, stage: str, index: int) -> None:
        if core_planning.move_task(self._con, int(task_id), stage,
                                   int(index)):
            self._refresh()

    @Slot(int)
    def delete_task(self, task_id: int) -> None:
        core_planning.delete_task(self._con, int(task_id))
        self._refresh()
        self.message.emit("Task deleted")

    @Slot(int, result="QVariant")
    def task(self, task_id: int):
        t = core_planning.task(self._con, int(task_id))
        if t is None:
            self.message.emit("Task not found")
            return {}
        return t

    @Slot(int, int)
    def assign_project(self, task_id: int, project_id: int) -> None:
        pid = int(project_id) if int(project_id) > 0 else None
        core_planning.update_task(self._con, int(task_id),
                                  project_id=pid)
        self._refresh()

    @Slot(int)
    def open_project(self, project_id: int) -> None:
        self.openProjectRequested.emit(int(project_id))

    @Slot(int, str, str, str, result=bool)
    def link_asset(self, task_id: int, kind: str, asset_id: str,
                   label: str = "") -> bool:
        try:
            aid = int(asset_id)
        except (TypeError, ValueError):
            return False
        ok = core_planning.link_asset(self._con, int(task_id), kind, aid,
                                      label)
        if not ok:
            self.message.emit("Asset not found in the library")
            return False
        self._refresh()
        return True

    @Slot(int, int)
    def unlink_asset(self, task_id: int, row_id: int) -> None:
        core_planning.unlink_asset(self._con, int(row_id))
        self._refresh()

    # picker sources (task dialog): projects + per-kind asset options
    @Slot(result="QVariant")
    def project_options(self):
        return core_planning.project_options(self._con)

    @Slot(str, result="QVariant")
    def asset_options(self, kind: str):
        return core_planning.asset_options(self._con, str(kind))

    # QA hook (mirrors fonts.select): --qa-select matches a task title
    # and opens its editor in the pane
    @Slot(str, result=int)
    def open_task(self, needle: str) -> int:
        tid = core_planning.open_by_title(self._con, str(needle))
        if tid > 0:
            self._pending_open = tid
            self._pendingOpenChanged.emit()
        return tid
