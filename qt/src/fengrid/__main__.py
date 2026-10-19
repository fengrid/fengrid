"""Entry point for the Fengrid Qt workbench (skeleton).

Skeleton status: starts a QGuiApplication, loads the placeholder QML shell,
exits cleanly. The workbench (library grid, providers, composer) lands in
M0/M1 per docs/architecture/0001-qt6-rewrite.md. PyInstaller bundles this
file as the entry point (see build/scripts and docker/).
"""

import os
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from fengrid import __version__
from fengrid.app import APP_NAME, ORG_NAME


def _qml_main_url() -> QUrl:
    """Locate qml/Main.qml across the source tree and PyInstaller bundles."""
    here = os.path.dirname(os.path.abspath(__file__))
    # source layout: qt/src/fengrid/__main__.py -> qt/qml/Main.qml
    candidate = os.path.abspath(os.path.join(here, "..", "..", "qml", "Main.qml"))
    # PyInstaller (--add-data "qml:qml") puts it under sys._MEIPASS/qml
    bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "qml", "Main.qml")
    path = candidate if os.path.isfile(candidate) else bundled
    return QUrl.fromLocalFile(path)


def main() -> int:
    QGuiApplication.setApplicationName(APP_NAME)
    QGuiApplication.setOrganizationName(ORG_NAME)
    QGuiApplication.setApplicationVersion(__version__)
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.load(_qml_main_url())
    if not engine.rootObjects():
        print("error: failed to load the QML shell", file=sys.stderr)
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
