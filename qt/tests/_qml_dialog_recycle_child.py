"""#81 child probe: drive the real SettingsScreen offscreen, click the
ZIP… browse button TWICE, and verify the dead-attempt recycle guard.

Runs as its own PROCESS (spawned by test_qml_dialogs.py) on purpose:
opening a QtQuick.Dialogs file dialog instantiates a platform-helper
window owned by the application-global platform theme, which outlives
the dialog item, its Loader and even the QQmlEngine — inside a shared
pytest QGuiApplication it poisons mouse/hover delivery for every
later window test (proven: focusWindow() stays the hidden
"Import ZIP archive" Dialog window after full teardown). The recycle
under test is exactly the click-path a real desktop exercises, so it
must live in a process whose whole lifetime is one dialog session.

Usage: python _qml_dialog_recycle_child.py <tmpdir>
Exits 0 and prints RECYCLE-OK on success; prints diagnostics and
exits 1 on any broken expectation (fails the parent test).
"""
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "qt/src"))


def children(item):
    out, stack = [], [item]
    while stack:
        o = stack.pop()
        out.append(o)
        try:
            stack.extend(o.childItems())
        except RuntimeError:
            continue
    return out


def click_at(win, item):
    from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    c = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    for etype in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        ev = QMouseEvent(etype, QPointF(c.x(), c.y()), QPointF(c.x(), c.y()),
                         Qt.LeftButton, Qt.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(win, ev)
    from PySide6.QtTest import QTest
    QTest.qWait(120)


def main():
    try:
        _run()
    except BaseException:               # noqa: BLE001 — probe contract:
        traceback.print_exc()           # report ANY failure as a clean
        sys.stdout.flush()              # exit-1 result, never a crash
        sys.stderr.flush()              # loop or a lost assertion
        os._exit(1)   # hard exit: Qt teardown after a dialog session
        # segfaults on interpreter shutdown (platform-theme helper
        # refs outlive the Python wrappers) — report, don't crash
    sys.stdout.flush()
    os._exit(0)


def _run():
    import shiboken6
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest

    tmp = Path(sys.argv[1])

    # the app instance MUST exist before any bridge: Theme/Fonts use
    # QFontDatabase, which segfaults without a QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)

    from fengrid.bridges.code import Code
    from fengrid.bridges.colors import Colors
    from fengrid.bridges.data import DataIO
    from fengrid.bridges.fonts import Fonts
    from fengrid.bridges.library import Library
    from fengrid.bridges.prefs import Prefs
    from fengrid.bridges.storage import Storage
    from fengrid.bridges.theme import Theme
    from fengrid.bridges.updater import Updater
    from fengrid.core import db as core_db

    con = core_db.connect(tmp / "t.db")
    db_path = str(tmp / "t.db")
    theme = Theme(con, str(REPO / "fonts"))
    library = Library(con, db_path, no_scan=True)
    fonts = Fonts(con, db_path)
    colors = Colors(con)
    code = Code(con)
    prefs = Prefs(con, db_path)
    updater = Updater(auto_check_delay_ms=0)
    storage = Storage(con, str(tmp))
    dataio = DataIO(con, db_path, str(tmp))

    engine = QQmlEngine()
    ctx = engine.rootContext()
    for name, obj in (("theme", theme), ("library", library),
                      ("fonts", fonts), ("colors", colors), ("code", code),
                      ("prefs", prefs), ("updater", updater),
                      ("storage", storage), ("dataio", dataio)):
        ctx.setContextProperty(name, obj)
    ctx.setContextProperty("appVersion", "0.0-test")
    ctx.setContextProperty("appCommit", "0" * 40)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(
        str(REPO / "qt/qml/components/SettingsScreen.qml")))
    root = comp.create(ctx)
    assert root is not None, [str(e) for e in comp.errors()]
    root.setWidth(1280)
    root.setHeight(800)
    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    app.processEvents()
    QTest.qWait(200)
    root.showCategory("import")
    app.processEvents()
    QTest.qWait(100)

    def zip_loader_and_item():
        for o in children(root):
            if not o.metaObject().className().startswith("QQuickLoader"):
                continue
            it = o.property("item")
            if it is not None and it.property("title") == "Import ZIP archive":
                return o, it
        return None, None

    buttons = [o for o in children(root) if o.property("text") == "ZIP…"]
    assert buttons, "ZIP… button not found"

    # click 1: opens (offscreen "opens" = helper window exists)
    click_at(win, buttons[0])
    loader1, item1 = zip_loader_and_item()
    assert loader1 is not None and item1 is not None, \
        "click 1: no dialog item — button click dead"
    assert loader1.property("active") is True
    p1 = shiboken6.getCppPointer(item1)[0]

    # click 2: the dead-attempt case (dialog never resolved) — the
    # guard must recycle the Loader and produce a FRESH item
    click_at(win, buttons[0])
    loader2, item2 = zip_loader_and_item()
    assert loader2 is not None and item2 is not None, \
        "click 2: no dialog item — the retry was a silent no-op"
    p2 = shiboken6.getCppPointer(item2)[0]
    assert p2 != p1, (
        f"retry reused the same dialog item ({p1:#x}) — dead attempt "
        "was never recycled; buttons would look dead for the session")

    # telemetry: both the click and the retry-click must be recorded
    # in crash.log beside the DB (the prefs bridge sink)
    log = (tmp / "crash.log")
    assert log.exists(), "no crash.log written beside the test DB"
    lines = log.read_text().splitlines()
    assert any("dialog click zip" in ln for ln in lines), \
        f"missing 'dialog click zip' in {lines}"
    assert any("dialog retry-click zip" in ln for ln in lines), \
        f"missing 'dialog retry-click zip' in {lines}"

    print("RECYCLE-OK")


if __name__ == "__main__":
    main()
