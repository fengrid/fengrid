"""Entry point for the Fengrid Qt workbench.

- QQuickStyle "Basic" is set before the app object exists — controls are
  token-driven from QML, not from a desktop style.
- Fonts are registered from the bundled fonts/ directory before the QML
  engine loads; QML reads family names only via the Theme bridge.
- --screenshot renders the shell, saves a PNG and exits — the headless QA
  loop (QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software).
"""

import argparse
import gc
import os
import sys

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from fengrid import __version__
from fengrid.app import APP_NAME, ORG_NAME
from fengrid.bridges.code import Code
from fengrid.bridges.colors import Colors
from fengrid.bridges.data import DataIO
from fengrid.bridges.databases import Databases
from fengrid.bridges.demo import Demo
from fengrid.bridges.fonts import Fonts
from fengrid.bridges.library import Library
from fengrid.bridges.prefs import Prefs
from fengrid.bridges.projects import Projects
from fengrid.bridges.storage import Storage
from fengrid.bridges.termcolors import TermColors
from fengrid.bridges.theme import Theme
from fengrid.bridges.taxonomy import Taxonomy
from fengrid.bridges.updater import Updater
from fengrid.core import db as core_db
from fengrid.core import registry as core_registry
from fengrid.core import settings as settings_mod
from fengrid.glprobe import needs_software_fallback
from fengrid.web import initialize_webengine, make_preview_profile, \
    register_asset_scheme


def _asset_dir(*parts: str) -> str:
    """Locate a repo/bundle directory: source tree first, then _MEIPASS."""
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.abspath(os.path.join(here, "..", "..", *parts))
    if os.path.isdir(cand):
        return cand
    return os.path.join(getattr(sys, "_MEIPASS", ""), *parts)


def _user_data_dir() -> str:
    try:
        from platformdirs import user_data_dir
        d = user_data_dir("fengrid", appauthor=False)
    except ImportError:  # pragma: no cover - platformdirs is a build dep
        base = os.environ.get("XDG_DATA_HOME",
                              os.path.expanduser("~/.local/share"))
        d = os.path.join(base, "fengrid")
    os.makedirs(d, exist_ok=True)
    return d


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fengrid")
    parser.add_argument("--screenshot", metavar="PATH",
                        help="render the shell, save a PNG and exit (headless QA)")
    parser.add_argument("--shot-delay", type=int, default=1800,
                        help="ms to wait before capturing (default 1800)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--theme", choices=("dark", "light"), default=None)
    parser.add_argument("--db", default=None,
                        help="override the library database path")
    parser.add_argument("--no-scan", action="store_true",
                        help="skip the first-run auto scan")
    parser.add_argument("--pane", type=int, default=None,
                        help="initial pane: 0 icons, 1 fonts, 2 colors, 3 code,"
                             " 4 projects (default: the startup_pane setting;"
                             " QA screenshots pass this explicitly)")
    parser.add_argument("--qa-select", default="",
                        help="pre-select an item for QA screenshots"
                             " (font family / palette / snippet name)")
    parser.add_argument("--dialog", default="",
                        help="open a named modal for QA screenshots"
                             " (libDialog, smartDialog, renameDialog,"
                             " subDialog, fieldDialog, settings, firstRun,"
                             " menu, storage, commandBar, paletteSettings,"
                             " splash)")
    parser.add_argument("--term", action="store_true",
                        help="open the Colors pane on the Terminal designer"
                             " (QA screenshots)")
    parser.add_argument("--version", action="version",
                        version=f"fengrid {__version__}")
    args = parser.parse_args(argv)

    # Degrade to the software renderer instead of letting Qt abort the
    # process when the display has no usable hardware GL (GLX-less XWayland,
    # NVIDIA/VM edge cases — SIGABRT "Could not initialize GLX"). The probe
    # respects explicit QT_* overrides, so the QA offscreen path is untouched.
    if needs_software_fallback():
        os.environ["QT_QUICK_BACKEND"] = "software"
        os.environ["QT_XCB_GL_INTEGRATION"] = "none"
        print("warning: no usable hardware GL on this display —"
              " using the software renderer", file=sys.stderr)

    # scheme registration must precede QGuiApplication (flags are read at
    # Chromium start), and initialize_webengine() must also run before the
    # app object exists — Chromium reads the command line during its
    # construction. Both spawn no work when WebEngine is unavailable.
    if not register_asset_scheme():
        print("warning: QtWebEngineCore unavailable — preview surfaces"
              " disabled", file=sys.stderr)
    initialize_webengine()

    # must precede QGuiApplication — controls are token-driven from QML
    QQuickStyle.setStyle("Basic")

    QGuiApplication.setApplicationName(APP_NAME)
    QGuiApplication.setOrganizationName(ORG_NAME)
    QGuiApplication.setApplicationVersion(__version__)
    app = QGuiApplication(sys.argv)

    # the shipped mark lives in qt/resources (tracked); the legacy
    # branding/assets tree is a gitignored design source — try both, and
    # degrade silently to no icon if neither exists
    for icon_rel in (("resources", "branding"), ("branding", "assets")):
        icon_path = os.path.join(_asset_dir(*icon_rel), "fengrid-mark.svg")
        if os.path.isfile(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break

    data_dir = _user_data_dir()
    default_db = os.path.join(data_dir, "library.db")

    # App registry: known/starred/active databases + GLOBAL user prefs
    # (theme, icon size, …) — bound BEFORE any bridge reads settings so
    # a database switch never repaints the app.
    reg_con = core_registry.open_registry(data_dir)
    settings_mod.bind_registry(reg_con)

    startup_notice = ""
    if args.db:
        db_path = args.db                    # per-run override (QA too)
    else:
        active = core_registry.active_path(reg_con)
        if active and os.path.isfile(active):
            db_path = active
        elif active:
            db_path = default_db
            startup_notice = (f"Database missing: {active} —"
                              " opened the default instead")
        else:
            db_path = default_db
    con = core_db.connect(db_path)
    core_registry.seed_globals(con, reg_con)
    core_registry.set_active(reg_con, db_path)
    prefs_bridge = Prefs(con, db_path)
    dbs_bridge = Databases(db_path, reg_con, data_dir,
                           default_path=default_db)
    storage_bridge = Storage(con, data_dir)
    dataio_bridge = DataIO(
        con, db_path, data_dir,
        registry_path=os.path.join(data_dir, "registry.db"))
    app.aboutToQuit.connect(dataio_bridge.shutdown)

    theme = Theme(con, _asset_dir("fonts"))
    if args.theme:
        theme.set_theme(args.theme)
    library = Library(con, db_path, no_scan=args.no_scan)
    fonts = Fonts(con, db_path)
    colors_bridge = Colors(con)
    term_bridge = TermColors(con)
    code_bridge = Code(con)
    projects_bridge = Projects(con)
    # demo suite: files under the data dir so removal never touches user folders
    demo_bridge = Demo(con, os.path.join(data_dir, "demo-assets"),
                       _asset_dir("fonts"))
    # the release probe must never fire in QA/offscreen runs — and only
    # when the user left "check at startup" enabled in Settings
    _offline_qa = bool(args.screenshot) \
        or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    updater_bridge = Updater(
        app, auto_check_delay_ms=0
        if _offline_qa or not prefs_bridge.updateCheck else 4000)

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("fonts", fonts)
    ctx.setContextProperty("colors", colors_bridge)
    ctx.setContextProperty("terms", term_bridge)
    ctx.setContextProperty("code", code_bridge)
    ctx.setContextProperty("projects", projects_bridge)
    ctx.setContextProperty("demo", demo_bridge)
    ctx.setContextProperty("updater", updater_bridge)
    ctx.setContextProperty("prefs", prefs_bridge)
    ctx.setContextProperty("dbs", dbs_bridge)
    ctx.setContextProperty("storage", storage_bridge)
    ctx.setContextProperty("dataio", dataio_bridge)
    # non-empty when startup fell back (missing active database)
    ctx.setContextProperty("startupNotice", startup_notice)
    taxonomy_bridge = Taxonomy(con)
    ctx.setContextProperty("taxonomy", taxonomy_bridge)
    preview_profile = make_preview_profile(con, app)
    # None on platforms without WebEngine — QML binds it only inside the
    # Loader, which stays inactive there
    ctx.setContextProperty("previewProfile", preview_profile)
    ctx.setContextProperty("appVersion", __version__)
    ctx.setContextProperty(
        "initialPane",
        args.pane if args.pane is not None else prefs_bridge.startupPane)
    ctx.setContextProperty("initialTerm", args.term)
    # first-run setup shows when the flag is unset — but never in
    # --screenshot runs (pane shots must stay clean on a fresh DB;
    # QA forces the screen with --dialog firstRun)
    ctx.setContextProperty(
        "initialFirstRun",
        prefs_bridge.firstRunNeeded and not bool(args.screenshot))
    # startup scan session: drives the launch splash (shown only while
    # these initial scans actually run — manual rescans never reshow it)
    ctx.setContextProperty(
        "initialScans",
        (not args.no_scan)
        and (library.totalAssets == 0 or fonts.totalFonts == 0))
    # QA affordances (icons pane): pre-select an icon so the inspector
    # panel is present in screenshots, and optionally scroll its body so
    # the pinned action footer is captured mid-overflow
    _qa_icon_path = ""
    if args.qa_select and args.pane in (None, 0):
        _row = con.execute(
            "SELECT path FROM asset WHERE kind = 'icon' AND name LIKE ?"
            " ORDER BY name LIMIT 1", (f"{args.qa_select}%",)).fetchone()
        _qa_icon_path = _row["path"] if _row else ""
    ctx.setContextProperty("qaIconPath", _qa_icon_path)
    ctx.setContextProperty(
        "qaInspectorScroll",
        int(os.environ.get("FENGRID_QA_INSPECTOR_SCROLL", "0") or 0))
    engine.load(QUrl.fromLocalFile(os.path.join(_asset_dir("qml"), "Main.qml")))
    if not engine.rootObjects():
        print("error: failed to load the QML shell", file=sys.stderr)
        return 1

    # QA affordance: --dialog names a modal; Main.qml opens it after load
    # (popups are not reachable from the QObject tree, so the registry is
    # QML-side — see Main.openQaModal)
    ctx.setContextProperty("qaOpenModal", args.dialog)

    # QA affordance: --qa-select <name> pre-selects an item so the
    # Properties panel has a target in screenshots
    if args.qa_select:
        if args.pane == 1:
            fonts.select(args.qa_select)
        elif args.pane == 2:
            row = con.execute(
                "SELECT id FROM palette WHERE name LIKE ?",
                (f"%{args.qa_select}%",)).fetchone()
            if row:
                colors_bridge.open_palette(row["id"])
        elif args.pane == 3:
            row = con.execute(
                "SELECT id FROM snippet WHERE title LIKE ?",
                (f"%{args.qa_select}%",)).fetchone()
            if row:
                code_bridge.open_snippet(row["id"])

    def _start_initial_scans():
        if args.no_scan:
            return
        # first run: index the platform icon roots automatically
        if library.totalAssets == 0:
            QTimer.singleShot(0, library.rescan)
        # first run: index the platform font dirs automatically (own thread
        # + own connection, cancellable at quit — see bridges/fonts.py)
        if fonts.totalFonts == 0:
            QTimer.singleShot(0, fonts.rescan)

    if storage_bridge.mountCount != 0:
        # bring registered mounts back BEFORE the first scan, so their
        # sources resolve to live paths (failures toast + degrade to
        # the missing-root behaviour the scanner already handles)
        storage_bridge.ready.connect(
            lambda ok, fail: _start_initial_scans())
        storage_bridge.remountAll()
    else:
        _start_initial_scans()

    if args.screenshot:
        def _grab():
            wins = [o for o in engine.rootObjects() if hasattr(o, "grabWindow")]
            if wins:
                img = wins[0].grabWindow()
                if img.save(args.screenshot):
                    print(f"screenshot: {args.screenshot}")
                else:
                    print(f"error: could not save {args.screenshot}", file=sys.stderr)
            else:
                print("error: no root window", file=sys.stderr)
            app.quit()
        QTimer.singleShot(max(200, args.shot_delay), _grab)

    code = app.exec()
    # Destroy the QML scene while the bridges are still alive: after exec()
    # returns, engine teardown nulls the context properties while delegate
    # bindings are still live, and every touched binding logged a TypeError
    # at exit. The engine has no parent, so dropping the last reference runs
    # its C++ destructor now, while `theme`/`library` are still valid.
    del engine
    gc.collect()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
