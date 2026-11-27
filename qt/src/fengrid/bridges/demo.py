"""Demo-data bridge: load / remove the showcase suite (Projects pane).

Thin adapter over core.demo; the deletion dialog's per-kind checkboxes map
1:1 to the `kinds` list passed to core.demo.remove().
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import demo as core_demo

# dialog labels <-> core kind names
KINDS = (
    ("projects", "Projects"),
    ("icons", "Icon assets"),
    ("fonts", "Font assets"),
    ("snippets", "Code snippets"),
    ("palettes", "Palettes"),
    ("tags", "Demo tags"),
)


class Demo(QObject):
    message = Signal(str)
    changed = Signal()
    failed = Signal(str)

    def __init__(self, con, demo_dir: str, fonts_dir: str, parent=None):
        super().__init__(parent)
        self._con = con
        self._demo_dir = demo_dir
        self._fonts_dir = fonts_dir

    @Property(bool, notify=changed)
    def installed(self):
        return core_demo.is_installed(self._con)

    @Slot(result="QVariantList")
    def kinds(self) -> list:
        return [{"id": k, "label": lbl} for k, lbl in KINDS]

    @Slot()
    def install(self):
        try:
            summary = core_demo.install(self._con, self._demo_dir,
                                        self._fonts_dir)
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            self.failed.emit(str(exc)[:300])
            return
        if not summary.get("installed"):
            self.message.emit("Demo data is already loaded")
        else:
            self.message.emit(
                "Demo suite loaded — %d projects, %d snippets, %d palettes"
                % (summary["projects"], summary["snippets"],
                   summary["palettes"]))
        self.changed.emit()

    @Slot("QVariantList")
    def remove(self, kind_ids: list) -> None:
        kinds = [str(k) for k in (kind_ids or [])]
        if not kinds:
            self.message.emit("Nothing selected — demo data kept")
            return
        try:
            removed = core_demo.remove(self._con, self._demo_dir, kinds)
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            self.failed.emit(str(exc)[:300])
            return
        parts = ", ".join("%d %s" % (n, k) for k, n in sorted(removed.items())
                          if n)
        self.message.emit("Demo data removed: " + (parts or "nothing"))
        self.changed.emit()
