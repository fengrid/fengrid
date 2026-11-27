"""Updater bridge: background release probe + footer notice (M5).

The network probe runs on a Python thread (a blocked socket must never
freeze the UI); results cross back through signals, which Qt delivers as
queued events to the GUI thread.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .. import __version__
from ..core import updater as core_updater


class Updater(QObject):
    checkingChanged = Signal()
    updateChanged = Signal()
    message = Signal(str)

    def __init__(self, parent=None, auto_check_delay_ms: int = 4000):
        super().__init__(parent)
        self._checking = False
        self._latest = ""
        self._available = False
        self._error = ""
        self._url = core_updater.RELEASES_URL
        if auto_check_delay_ms > 0:
            QTimer.singleShot(auto_check_delay_ms, self.check)

    # ------------------------------------------------------------ properties

    @Property(bool, notify=checkingChanged)
    def checking(self):
        return self._checking

    @Property(str, notify=updateChanged)
    def latestVersion(self):
        return self._latest

    @Property(str, constant=True)
    def currentVersion(self):
        return __version__

    @Property(bool, notify=updateChanged)
    def updateAvailable(self):
        return self._available

    @Property(str, constant=True)
    def releasesUrl(self):
        return self._url

    # ---------------------------------------------------------------- slots

    @Slot()
    def check(self):
        if self._checking:
            return
        self._checking = True
        self.checkingChanged.emit()
        thread = threading.Thread(target=self._probe, daemon=True)
        thread.start()

    def _probe(self):
        tag = core_updater.probe()
        # signal emission from a foreign thread is fine — the connection is
        # automatically queued onto the GUI thread's event loop
        self._checking = False
        self.checkingChanged.emit()
        if not tag:
            self._error = "unreachable"
            return
        self._latest = tag
        self._available = core_updater.is_newer(tag, __version__)
        self.updateChanged.emit()
