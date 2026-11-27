"""#168 regression: a core test file must not poison a later QML test
file in the same pytest process.

Pre-fix, `pytest tests/test_planning.py tests/test_qml_colors.py`
segfaulted (exit 139) at the first QQmlComponent.create(): a bridge test
in test_planning.py constructed a bare QCoreApplication whose instance
lingered for the rest of the process, so the QML fixture's
`QGuiApplication.instance() or QGuiApplication(...)` guard never built a
real GUI application and Quick ran component creation under the wrong
application type.

The full suite never saw this (alphabetical luck: test_command_bar.py
creates the QGuiApplication first); any ad-hoc core-then-QML pair died.
qt/tests/conftest.py now installs ONE session QGuiApplication before any
test, which makes every `instance() or ...` guard a no-op.
"""
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication

QT_DIR = Path(__file__).resolve().parents[1]


def _run_pair(files, tmp_path):
    """Run a core-then-QML file pair in a fresh child process, exactly
    the ad-hoc workflow the reporter hit."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_QUICK_BACKEND"] = "software"
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *files],
        cwd=str(QT_DIR), env=env, capture_output=True, text=True,
        timeout=600, check=False)


def test_core_then_qml_file_pair_does_not_segfault(tmp_path):
    r = _run_pair(
        ["tests/test_planning.py", "tests/test_qml_colors.py"], tmp_path)
    tail = (r.stdout + r.stderr)[-3000:]
    assert r.returncode == 0, (
        f"core-then-QML pair exited rc={r.returncode} (139/-11 = the "
        "reported segfault)\n--- child output tail ---\n" + tail)


def test_session_app_is_a_real_qguiapplication():
    """The conftest session app must exist and be a QGuiApplication —
    a bare QCoreApplication instance here is exactly the poison that
    segfaulted the first QML component creation (#168)."""
    app = QGuiApplication.instance()
    assert app is not None, "conftest session app must exist"
    assert isinstance(app, QGuiApplication), (
        f"QGuiApplication.instance() returned {type(app).__name__}: a "
        "bare QCoreApplication is lingering and poisons QML component "
        "creation (#168)")
