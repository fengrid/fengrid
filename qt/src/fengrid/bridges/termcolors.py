"""Terminal-theme designer bridge: in-memory working theme + exports.

The working theme lives in memory (QVariant-friendly dict); presets from
the Gogh collection load with one call, per-slot edits persist to the
working theme only, and the persistence path is "Save to snippets" (the
theme becomes a live-preview snippet that can be collected and attached
to projects like any other snippet).
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import termcolors as core_tc


class TermColors(QObject):
    message = Signal(str)
    themeChanged = Signal()
    exportDone = Signal(str)
    exportFailed = Signal(str)

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        self._theme = core_tc.normalize({"name": "My terminal theme"})

    # ------------------------------------------------------------ properties

    @Property("QVariant", notify=themeChanged)
    def theme(self):
        return self._theme

    @Slot(result="QVariant")
    def presets(self) -> list:
        return [{"name": n} for n in core_tc.preset_names()]

    @Slot(str, result="QVariant")
    def preset(self, name: str):
        p = core_tc.get_preset(name)
        return p or {}

    @Slot(result="QVariantList")
    def formats(self) -> list:
        return list(core_tc.FORMATS)

    # ---------------------------------------------------------------- slots

    @Slot(str, str)
    def set_value(self, key: str, value: str) -> None:
        """key: 'bg' | 'fg' | 'cursor' | 'selection' | 'normal.<slot>'
        | 'bright.<slot>'"""
        value = str(value or "").strip()
        if key in ("bg", "fg", "cursor", "selection"):
            if value:
                self._theme[key] = value
            self.themeChanged.emit()
            return
        pool, _, slot = key.partition(".")
        if pool in ("normal", "bright") and slot:
            if value:
                self._theme.setdefault(pool, {})[slot] = value
            self.themeChanged.emit()

    @Slot(str)
    def set_name(self, name: str) -> None:
        self._theme["name"] = str(name or "Untitled terminal theme")
        self.themeChanged.emit()

    @Slot(str)
    def load_preset(self, name: str) -> None:
        p = core_tc.get_preset(name)
        if p is None:
            self.message.emit("No such preset: " + name)
            return
        self._theme = p
        self.themeChanged.emit()
        self.message.emit("Loaded preset: " + name)

    @Slot(str, str, str)
    def derive(self, bg: str, fg: str, accent: str) -> None:
        bg, fg, accent = (str(bg or "").strip(), str(fg or "").strip(),
                          str(accent or "").strip())
        if not bg or not fg or not accent:
            self.message.emit("Derive needs bg, fg and accent colors")
            return
        self._theme = core_tc.derive(bg, fg, accent,
                                     name=self._theme.get("name") or "")
        self.themeChanged.emit()
        self.message.emit("Theme derived from bg/fg/accent")

    @Slot(str, str)
    def export(self, dest: str, fmt: str) -> None:
        try:
            path = core_tc.export(self._theme, str(fmt), str(dest))
            self.exportDone.emit(path)
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI
            self.exportFailed.emit(str(exc)[:300])

    @Slot()
    def save_as_snippet(self):
        sid = core_tc.save_as_snippet(self._con, self._theme)
        self.message.emit("Saved to snippets: "
                          "Terminal theme — %s" % self._theme.get("name"))
        return sid
