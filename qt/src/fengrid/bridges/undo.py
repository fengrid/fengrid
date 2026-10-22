"""Qt-facing undo/redo facade — a thin QObject over core.history.History.

Each editable bridge owns one UndoBridge; QML (and the global Ctrl+Z /
Ctrl+Shift+Z shortcuts in Main.qml) bind its canUndo/redoLabels. The
bridge registers apply/undo callables per entry; undo() replays the
stored payload through them. Bulk operations wrap their work in
core.history.bulk_guard so nothing is recorded and the stack resets.
"""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core.history import History, bulk_guard


class UndoBridge(QObject):
    message = Signal(str)
    changed = Signal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._history = History()
        # per-entry handlers: {handler_id: (apply_fn, undo_fn)}
        self._handlers: dict[str, tuple] = {}

    # ------------------------------------------------------------ register
    def register(self, handler_id: str, apply_fn, undo_fn) -> None:
        """Bind an apply/undo pair identified by `handler_id` (e.g.
        'projects.settings'). Entries reference the id."""
        self._handlers[handler_id] = (apply_fn, undo_fn)

    def push(self, handler_id: str, label: str, apply_data, undo_data) -> None:
        """Record one user-scale change (the bridge ALREADY applied the
        change; apply_data re-applies it, undo_data reverts it)."""
        if handler_id not in self._handlers:
            return
        self._history.push(label, {"h": handler_id, "d": apply_data},
                           {"h": handler_id, "d": undo_data})
        self.changed.emit()

    def bulk(self):
        """Context manager: `with bridge.bulk(): <bulk mutation>` — no
        entries recorded, stack cleared after (bulk actions are not
        undoable, per spec)."""
        return bulk_guard(self._history)

    # ------------------------------------------------------------ QML API
    def _emit(self) -> None:
        self.changed.emit()

    @Property(bool, notify=changed)
    def canUndo(self) -> bool:
        return self._history.can_undo()

    @Property(bool, notify=changed)
    def canRedo(self) -> bool:
        return self._history.can_redo()

    @Property(str, notify=changed)
    def undoLabel(self) -> str:
        return self._history.peek_undo_label()

    @Property(str, notify=changed)
    def redoLabel(self) -> str:
        return self._history.peek_redo_label()

    @Property(int, notify=changed)
    def depth(self) -> int:
        return self._history.depth

    @Slot()
    def undo(self) -> None:
        entry = self._history.pop_undo()
        if entry is None:
            return
        payload = entry.undo_data
        pair = self._handlers.get(payload.get("h"))
        if pair is None:
            self.message.emit("Undo unavailable for this action")
            return
        try:
            pair[1](payload.get("d"))
            self.message.emit(f"Undid: {entry.label}")
        except Exception as exc:                  # noqa: BLE001
            self.message.emit(f"Undo failed: {exc}")
        self.changed.emit()

    @Slot()
    def redo(self) -> None:
        entry = self._history.pop_redo()
        if entry is None:
            return
        payload = entry.apply_data
        pair = self._handlers.get(payload.get("h"))
        if pair is None:
            self.message.emit("Redo unavailable for this action")
            return
        try:
            pair[0](payload.get("d"))
            self.message.emit(f"Redid: {entry.label}")
        except Exception as exc:                  # noqa: BLE001
            self.message.emit(f"Redo failed: {exc}")
        self.changed.emit()

    @Slot()
    def clear(self) -> None:
        self._history.clear()
        self.changed.emit()
