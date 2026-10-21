"""Prefs bridge: the Settings/Preferences store + first-run state.

Owns the config keys that don't belong to a single pane — icon grid
size, startup pane, update-check, first-run completion — plus the
detected system paths the setup screen reviews. Theme, keymap, colors
rule and search mode stay on their own bridges (their notify signals
already drive the rest of the UI); the Settings screen binds to those
bridges directly for those rows, so there is exactly one writer per
key.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import fonts as core_fonts
from ..core import scanner, settings


class Prefs(QObject):
    iconSizeChanged = Signal()
    startupPaneChanged = Signal()
    updateCheckChanged = Signal()
    firstRunNeededChanged = Signal()
    commandShortcutChanged = Signal()
    message = Signal(str)

    # Alt+` (Option+` on macs — Qt maps Alt to Option in sequences)
    DEFAULT_COMMAND_SHORTCUT = "Alt+`"

    def __init__(self, con: sqlite3.Connection, db_path: str, parent=None):
        super().__init__(parent)
        self._con = con
        self._db_path = db_path
        self._icon_size = int(settings.get(con, "icon_size", 32) or 32)
        self._startup_pane = int(settings.get(con, "startup_pane", 0) or 0)
        # ships enabled: a missing row means "check for releases at start"
        self._update_check = settings.get_bool(con, "update_check", True)
        self._first_run_needed = not settings.get_bool(
            con, "first_run_done", False)
        self._command_shortcut = (
            settings.get(con, "command_shortcut", "")
            or self.DEFAULT_COMMAND_SHORTCUT)
        # detected at construction, resolved so they string-match the
        # source rows the scanner registers (which are stored resolved)
        self._system_icon_paths = [
            str(Path(p).resolve()) for p in scanner.platform_candidates()]
        self._system_font_dirs = [
            str(Path(p).resolve()) for p in core_fonts.platform_font_dirs()]

    # ------------------------------------------------------------- icon grid
    @Property(int, notify=iconSizeChanged)
    def iconSize(self) -> int:
        return self._icon_size

    @Slot(int)
    def set_icon_size(self, size: int) -> None:
        size = max(16, min(256, int(size)))
        if size == self._icon_size:
            return
        self._icon_size = size
        settings.set(self._con, "icon_size", size)
        self.iconSizeChanged.emit()

    # ---------------------------------------------------------- startup pane
    @Property(int, notify=startupPaneChanged)
    def startupPane(self) -> int:
        return self._startup_pane

    @Slot(int)
    def set_startup_pane(self, pane: int) -> None:
        pane = max(0, min(4, int(pane)))
        if pane == self._startup_pane:
            return
        self._startup_pane = pane
        settings.set(self._con, "startup_pane", pane)
        self.startupPaneChanged.emit()

    # ------------------------------------------------------------ update check
    @Property(bool, notify=updateCheckChanged)
    def updateCheck(self) -> bool:
        return self._update_check

    @Slot(bool)
    def set_update_check(self, on: bool) -> None:
        on = bool(on)
        if on == self._update_check:
            return
        self._update_check = on
        settings.set_bool(self._con, "update_check", on)
        self.updateCheckChanged.emit()

    # --------------------------------------------------------------- first run
    @Property(bool, notify=firstRunNeededChanged)
    def firstRunNeeded(self) -> bool:
        return self._first_run_needed

    @Slot()
    def complete_first_run(self) -> None:
        """Persist that setup was shown; the QML overlay binds to
        firstRunNeeded and closes itself when this flips."""
        if not self._first_run_needed:
            return
        self._first_run_needed = False
        settings.set_bool(self._con, "first_run_done", True)
        self.firstRunNeededChanged.emit()

    @Slot()
    def start_first_run(self) -> None:
        """Re-run setup from Settings (shows the overlay again; the
        flag only flips back on the next complete)."""
        if self._first_run_needed:
            return
        self._first_run_needed = True
        settings.set_bool(self._con, "first_run_done", False)
        self.firstRunNeededChanged.emit()

    # ------------------------------------------------------------- command bar
    @Property(str, notify=commandShortcutChanged)
    def commandShortcut(self) -> str:
        """Raw QKeySequence text ('Alt+`') — QML Shortcut binds this,
        so rebinding is live on every change."""
        return self._command_shortcut

    @Property(str, notify=commandShortcutChanged)
    def formattedShortcut(self) -> str:
        """Human-readable tip for placeholders: 'Alt + `'."""
        return " + ".join(self._command_shortcut.split("+"))

    @Slot(str)
    def set_command_shortcut(self, seq: str) -> None:
        seq = (seq or "").strip()
        if not seq:
            # never allow empty — the placeholder tip would lie and the
            # Shortcut would silently stop firing
            seq = self.DEFAULT_COMMAND_SHORTCUT
        if seq == self._command_shortcut:
            return
        self._command_shortcut = seq
        settings.set(self._con, "command_shortcut", seq)
        self.commandShortcutChanged.emit()

    # ------------------------------------------------------------ system paths
    @Property("QVariantList", constant=True)
    def systemIconPaths(self):
        """Detected platform icon roots, resolved — the setup screen
        lists these with per-path enable checkboxes."""
        return self._system_icon_paths

    @Property("QVariantList", constant=True)
    def systemFontDirs(self):
        """Detected platform font directories, resolved."""
        return self._system_font_dirs

    # ------------------------------------------------------------------ about
    @Property(str, constant=True)
    def dbPath(self) -> str:
        return self._db_path