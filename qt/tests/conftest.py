"""Session Qt application for the fengrid test suite (#168).

ONE QGuiApplication for the entire pytest run, created before any
bridge or QML object exists.

The bug class: a core test file constructing a bare QCoreApplication
(`QCoreApplication.instance() or QCoreApplication([])` — formerly in
test_planning.py, test_data_management.py, test_entity_inspector.py,
test_fonts_samples.py, test_freeze_watchdog.py) leaves that instance
alive for the rest of the process. `QGuiApplication.instance()` then
RETURNS it, so the QML fixtures' `instance() or QGuiApplication(...)`
guard never builds a real GUI application, and the first
QQmlComponent.create() segfaults inside populateInstance/
setPropertyBinding (exit 139). The full suite only ever passed by
alphabetical luck — test_command_bar.py happens to create the
QGuiApplication first — while any ad-hoc core-then-QML file pair died.

Rules this installs:
- never construct QCoreApplication/QGuiApplication directly in a test;
  the session app already exists and every `instance() or ...` guard is
  a no-op returning it;
- on a displayless host with no QT_QPA_PLATFORM, offscreen is forced at
  IMPORT time (before test modules are collected) so GUI-stack tests
  are hermetic instead of aborting at the first QGuiApplication();
- every app-creating test site asserts the instance really is a
  QGuiApplication, so a future regression fails loudly instead of
  segfaulting inside Quick.

Regression pin: test_qt_app_session.py drives the reported
core-then-QML file pair in a child process (red pre-fix: rc -11).
"""
import os
import sys

# Force a working platform before any test module is imported: fixture-
# time (and import-time) QGuiApplication constructions abort on hosts
# with no display and no QT_QPA_PLATFORM.
if (not os.environ.get("QT_QPA_PLATFORM")
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest  # noqa: E402  (env must be set before Qt is imported)
from PySide6.QtGui import QGuiApplication  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _session_qt_app():
    """The single application instance for the whole pytest run."""
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)
    yield app
