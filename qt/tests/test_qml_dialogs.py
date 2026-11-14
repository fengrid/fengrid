"""#81 regression tests: Settings browse dialogs (import/export/sources).

The dead-button class: a native dialog that never maps (portal hang /
absent dialog backend — the class users hit on real desktops) leaves
its Loader active forever, so every click after the first silently
no-ops and the browse buttons look dead for the rest of the session.
The fix recycles the Loader while a previous attempt is still
unresolved (a live mapped native dialog is modal, so it keeps the
browse buttons unreachable — an unresolved active Loader at click time
can only be a dead attempt) and writes click/resolve telemetry into
crash.log so a dead-click report is discriminated (click line without
a resolution line) instead of guessed at.

The click-path test runs in a CHILD PROCESS (_qml_dialog_recycle_
child.py) on purpose: opening a QtQuick.Dialogs dialog instantiates a
platform-helper window owned by the application-global platform theme
that outlives the dialog item, its Loader and even the QQmlEngine —
inside a shared pytest QGuiApplication it poisons hover/mouse delivery
for every later window test (focusWindow() stays the hidden dialog
window after full teardown). The recycle under test is exactly the
click path a real desktop exercises, so it needs a process whose whole
lifetime is one dialog session.
"""
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))


def test_import_zip_button_recreates_dead_dialog_attempt(tmp_path):
    """Second click on ZIP… must recycle a dead attempt: the dialog
    item is destroyed and a fresh one created (distinct C++ pointer),
    the retry still opens something, and crash.log carries the click +
    retry-click telemetry. Fails on the pre-fix code, where the stuck
    active Loader reuses the same item forever and every click after
    the first is a silent no-op."""
    child = Path(__file__).parent / "_qml_dialog_recycle_child.py"
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_QUICK_BACKEND"] = "software"
    env.pop("DISPLAY", None)
    r = subprocess.run(
        [sys.executable, str(child), str(tmp_path)],
        capture_output=True, text=True, timeout=180, check=False,
        env=env)
    assert r.returncode == 0, (
        "dialog recycle child probe failed:\n" + r.stdout[-3000:]
        + "\n--- stderr tail ---\n" + r.stderr[-3000:])
    assert "RECYCLE-OK" in r.stdout, r.stdout
    # the child asserts the telemetry itself; re-assert here so the
    # failure message names the file the reporter will be asked for
    log = tmp_path / "crash.log"
    lines = log.read_text().splitlines() if log.exists() else []
    assert any("dialog click zip" in ln for ln in lines), \
        f"crash.log telemetry missing: {lines}"
    assert any("dialog retry-click zip" in ln for ln in lines), \
        f"crash.log telemetry missing: {lines}"


def test_note_dialog_event_writes_crash_log(tmp_path):
    """Telemetry sink: the prefs bridge appends parseable dialog event
    lines to crash.log next to the database."""
    from fengrid.bridges.prefs import Prefs
    from fengrid.core import db as core_db

    con = core_db.connect(tmp_path / "t.db")
    prefs = Prefs(con, str(tmp_path / "t.db"))
    prefs.noteDialogEvent("zip", "click", 0)
    prefs.noteDialogEvent("zip", "resolved-accepted", 431)
    log = (tmp_path / "crash.log").read_text().splitlines()
    dialogs = [ln for ln in log if "dialog" in ln]
    assert any("dialog click zip" in ln for ln in dialogs)
    assert any("dialog resolved-accepted zip 431ms" in ln
               for ln in dialogs)


def test_dialog_environment_describe():
    """Launch probe: the one-line environment snapshot names every fact
    a dead-dialog diagnosis needs, including the portal state."""
    from fengrid import dialogenv

    d = dialogenv.dialog_environment()
    for key in ("platform", "platform_theme", "session_type", "display",
                "desktop", "portal_binary", "portal_running"):
        assert key in d, f"dialog_environment() missing {key}"
    assert d["portal_running"] in ("yes", "no", "unknown")

    line = dialogenv.describe_environment()
    assert line.startswith("dialog-env: platform=")
    assert "portal-serving=" in line
