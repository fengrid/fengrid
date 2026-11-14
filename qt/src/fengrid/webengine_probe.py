"""Crash-isolated WebEngine capability probe (#32).

On displays without usable hardware GL, whether Chromium survives is an
EMPIRICAL question — it depends on the exact driver/driverless stack —
and a wrong guess either crashes the app or needlessly disables a core
feature. So we measure: this module runs as a THROWAWAY child process
(``fengrid --webengine-probe``) that inherits the parent's display and
mode environment (software scene graph + SwiftShader flags, or the EGL
integration), initializes QtWebEngine, loads a real page in a
WebEngineView, pumps the event loop briefly, and exits 0.

Any native crash (the #32 segfault class) kills only the child; the
parent sees a non-zero exit and degrades to the preview-less shell.
Never import this module into the app process — it exists to be the
process that may die.
"""

from __future__ import annotations

import os

# How long the child lets the view render before declaring success.
_DWELL_MS = 4000

_PROBE_QML = """
import QtQuick
import QtQuick.Controls
import QtWebEngine

ApplicationWindow {
    width: 320; height: 240; visible: true
    WebEngineView {
        anchors.fill: parent
        Component.onCompleted:
            url = "data:text/html,<h1 style='color:teal'>probe</h1>"
    }
}
"""


def run() -> int:
    """Probe body — returns a process exit code, never raises."""
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        # Offscreen QA/CI never engages a real display; the parent only
        # probes real-display modes. A direct offscreen invocation has
        # nothing to measure — report OK without starting Chromium.
        return 0
    from fengrid.web import initialize_webengine, webengine_available
    if not webengine_available():
        return 3
    try:
        from PySide6.QtCore import QUrl, QTimer
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine

        initialize_webengine()          # MUST precede QGuiApplication
        app = QGuiApplication([])
        engine = QQmlApplicationEngine()
        import tempfile

        with tempfile.NamedTemporaryFile(
                "w", suffix=".qml", delete=False) as f:
            f.write(_PROBE_QML)
            qml_path = f.name
        engine.load(QUrl.fromLocalFile(qml_path))
        if not engine.rootObjects:
            return 4                    # QML failed to load — treat as fail
        QTimer.singleShot(_DWELL_MS, app.quit)
        app.exec()
        return 0
    except Exception:
        return 5
