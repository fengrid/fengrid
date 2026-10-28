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
import time

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from fengrid import __version__
from fengrid.app import APP_NAME, ORG_NAME
from fengrid.buildinfo import build_commit
from fengrid.bridges.code import Code
from fengrid.bridges.presets import Presets
from fengrid.core import presets as core_presets
from fengrid.bridges.editor_highlight import EditorHighlighter
from fengrid.bridges.colors import Colors
from fengrid.bridges.data import DataIO
from fengrid.bridges.databases import Databases
from fengrid.bridges.demo import Demo
from fengrid.bridges.fonts import Fonts
from fengrid.bridges.library import Library
from fengrid.bridges.prefs import Prefs
from fengrid.bridges.projects import Projects
from fengrid.bridges.storage import Storage
from fengrid.core import projects as core_projects
from fengrid.bridges.termcolors import TermColors
from fengrid.bridges.theme import Theme
from fengrid.bridges.taxonomy import Taxonomy
from fengrid.bridges.updater import Updater
from fengrid.core import db as core_db
from fengrid.core import registry as core_registry
from fengrid.core import settings as settings_mod
from fengrid import glprobe
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


def _web_previews_pref() -> str:
    """Read the web_previews preference (auto/on/off) before Qt exists.

    Reads the app registry directly ( GLOBAL key ). A missing/unreadable
    registry — first run, --db pointing elsewhere — means "auto": the
    probe decides. Never creates the file.
    """
    registry = os.path.join(_user_data_dir(), "registry.db")
    if not os.path.isfile(registry):
        return "auto"
    try:
        import sqlite3

        from fengrid.core import settings
        con = sqlite3.connect(registry)
        try:
            value = settings.get(con, "web_previews", "auto") or "auto"
        finally:
            con.close()
        return value if value in ("auto", "on", "off") else "auto"
    except Exception:
        return "auto"


def _probe_webengine() -> None:
    """Measure whether Chromium survives this display — in a child (#32).

    Spawns a throwaway ``--webengine-probe`` process that inherits the
    mode environment (software scene graph + SwiftShader flags, or the
    EGL integration) and actually loads a page. Exit 0 → Chromium works
    here (FENGRID_WEBENGINE_OK=1); anything else — segfault, QML load
    failure, timeout — means previews must degrade to the preview-less
    shell (FENGRID_SOFTWARE_DISPLAY=1 without the OK flag), which the
    user can override in Settings (web_previews=on).
    """
    import subprocess

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--webengine-probe"]
    else:
        cmd = [sys.executable, "-m", "fengrid", "--webengine-probe"]
    print("note: probing web preview support for this display…",
          file=sys.stderr)
    try:
        result = subprocess.run(
            cmd, timeout=30,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok = result.returncode == 0
    except subprocess.TimeoutExpired:
        ok = False
    if ok:
        os.environ["FENGRID_WEBENGINE_OK"] = "1"
        print("note: web previews available (verified)", file=sys.stderr)
    else:
        print("warning: web previews are not stable on this display —"
              " running preview-less (Settings → General → Web previews"
              " can force them on)", file=sys.stderr)


def main(argv=None) -> int:
    # #61: startup phase timings land in crash.log — three freeze dumps
    # each implicated a different statement; measured phase durations
    # separate a slow database, a slow registration, and a slow QML
    # engine load instead of guessing from a sampled frame.
    _t_phase = time.perf_counter()
    # FIRST: drop the benign qt.svg "Duplicate unique style id" flood
    # (third-party icon sets ship duplicate ids; Qt re-logs per render).
    # Everything else keeps flowing; FENGRID_DEBUG_QT_SVG=1 shows it all.
    from fengrid import qtlog
    qtlog.install()

    # freeze/crash diagnostics are wired later, after data_dir is known —
    # see the faulthandler setup below (crash.log persistence, #22)

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
    parser.add_argument("--webengine-probe", action="store_true",
                        help=argparse.SUPPRESS)  # internal: #32 probe child
    args = parser.parse_args(argv)

    # crash-isolated WebEngine capability probe (#32): runs as its own
    # process so a native segfault lands in the child, not the app
    if args.webengine_probe:
        from .webengine_probe import run as _probe_run
        sys.exit(_probe_run())

    # Renderer decision (#32, tiered — previews are core, never disabled
    # by assumption):
    #   glx      — healthy default, nothing changes.
    #   egl      — GLX unusable but EGL works (GLX-less XWayland, VMs):
    #              run a REAL GL scene graph over Mesa software GL via
    #              the xcb EGL integration. The app AND Chromium render,
    #              just on the CPU (llvmpipe). Never tried before #32.
    #   none     — no GL at all: software (QPainter) scene graph, and a
    #              crash-isolated probe child decides whether Chromium
    #              survives here (SwiftShader) or previews must degrade.
    # The Settings toggle web_previews (auto/on/off) overrides the
    # measurement in both directions; FENGRID_FORCE_WEBENGINE=1 is the
    # env equivalent of "on", FENGRID_NO_WEBENGINE=1 of "off".
    mode = glprobe.display_gl_mode()
    web_pref = _web_previews_pref()
    if web_pref == "off":
        os.environ["FENGRID_NO_WEBENGINE"] = "1"
    if mode == "none":
        os.environ["QT_QUICK_BACKEND"] = "software"
        os.environ["QT_XCB_GL_INTEGRATION"] = "none"
        os.environ["FENGRID_SOFTWARE_DISPLAY"] = "1"
        # Chromium's GPU process is a known native-crash source on
        # GL-less displays; SwiftShader keeps a CPU-only GL path alive
        # for it. Whether THAT survives the software scene graph is what
        # the probe child measures — set BEFORE the child spawns (it
        # inherits the environment) and before initialize_webengine().
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
            os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
            + " --disable-gpu --use-angle=swiftshader"
              " --enable-unsafe-swiftshader").strip()
        print("warning: no usable hardware GL on this display —"
              " using the software renderer", file=sys.stderr)
    elif mode == "egl":
        os.environ["QT_XCB_GL_INTEGRATION"] = "egl"
        print("note: no GLX on this display — rendering through EGL"
              " (software GL); web previews stay available",
              file=sys.stderr)
    if mode in ("egl", "none") and web_pref == "auto":
        _probe_webengine()
    # Exposed to QML: shader-based scene-graph effects (MultiEffect blur
    # layer) must NEVER engage on the software backend — segfaults were
    # observed there (user report, ElementaryOS/GLX-less display).
    software_renderer = os.environ.get("QT_QUICK_BACKEND") == "software"

    # scheme registration must precede QGuiApplication (flags are read at
    # Chromium start), and initialize_webengine() must also run before the
    # app object exists — Chromium reads the command line during its
    # construction. Both spawn no work when WebEngine is unavailable.
    if not register_asset_scheme():
        if os.environ.get("FENGRID_SOFTWARE_DISPLAY") == "1":
            print("warning: web previews are disabled on this display"
                  " (Settings → General → Web previews can force them"
                  " on)", file=sys.stderr)
        else:
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

    # #22: crash/freeze diagnostics persist to <data_dir>/crash.log —
    # stderr dies with the terminal, and a SIGSEGV previously left
    # nothing behind. `kill -USR1 <pid>` appends a full thread dump to
    # the same file. Runs after data_dir resolution (honours --db by
    # logging next to the actual database).
    import faulthandler
    import signal
    crash_dir = (os.path.dirname(os.path.abspath(args.db))
                 if args.db else data_dir)
    _crash_log = None
    try:
        _crash_log = open(                      # noqa: SIM115 - process-lifetime
            os.path.join(crash_dir, "crash.log"), "a", encoding="utf-8")
        _crash_log.write(
            f"\n===== launch {time.strftime('%Y-%m-%d %H:%M:%S')}"
            f" — fengrid {__version__} =====\n")
        _crash_log.flush()
        faulthandler.enable(file=_crash_log)
        try:
            faulthandler.register(signal.SIGUSR1, file=_crash_log,
                                  all_threads=True, chain=False)
        except (AttributeError, ValueError, OSError):
            pass                 # not available on this platform
    except OSError:
        faulthandler.enable()    # no writable data dir — stderr as before
        try:
            faulthandler.register(signal.SIGUSR1, all_threads=True,
                                  chain=False)
        except (AttributeError, ValueError, OSError):
            pass

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
    # #61: name the storage conditions in every future report — a read
    # stall on a non-WAL (e.g. network) filesystem looks exactly like a
    # logic freeze in the dumps; the dumps name the statement, never
    # the disk.
    if _crash_log is not None:
        try:
            _crash_log.write(
                f"db {db_path} — journal "
                f"{con.execute('PRAGMA journal_mode').fetchone()[0]}"
                f" — fs {core_db.filesystem_type(db_path) or 'unknown'}\n")
            _crash_log.flush()
        except (OSError, ValueError):
            pass
    t_connect = time.perf_counter() - _t_phase
    # studio pages (Projects pane rework) — same migration discipline
    # as the guid/slug backfill: run after connect, before any bridge
    from fengrid.core import studio as core_studio
    core_studio.migrate(con)
    core_registry.seed_globals(con, reg_con)
    core_registry.set_active(reg_con, db_path)
    prefs_bridge = Prefs(con, db_path)
    t_prefs = time.perf_counter() - _t_phase
    _t_phase = time.perf_counter()
    dbs_bridge = Databases(db_path, reg_con, data_dir,
                           default_path=default_db)
    storage_bridge = Storage(con, data_dir)
    dataio_bridge = DataIO(
        con, db_path, data_dir,
        registry_path=os.path.join(data_dir, "registry.db"))
    app.aboutToQuit.connect(dataio_bridge.shutdown)

    # freeze watchdog: a silent UI freeze (the bug class that cannot be
    # reproduced on a QA host) writes every thread's stack to the data
    # dir instead of dying unexplained
    from fengrid.freeze_watchdog import FreezeWatchdog
    freeze_watchdog = FreezeWatchdog(data_dir, autostart=False)
    app.aboutToQuit.connect(freeze_watchdog.stop)
    QTimer.singleShot(0, freeze_watchdog.start)

    theme = Theme(con, _asset_dir("fonts"))
    if args.theme:
        theme.set_theme(args.theme)
    library = Library(con, db_path, no_scan=args.no_scan)
    fonts = Fonts(con, db_path)
    colors_bridge = Colors(con)
    term_bridge = TermColors(con)
    code_bridge = Code(con)
    projects_bridge = Projects(con)
    # studio workspace (Design/Templates/Docker/Docs screens)
    from fengrid.bridges.studio import Studio
    studio_bridge = Studio(con)
    studio_bridge.bind_projects(projects_bridge)
    # source control: one git repo per Project/Library under <data>/repos;
    # projects.save() commits to fengrid-main through this bridge
    from fengrid.bridges.source_control import SourceControl
    from fengrid.bridges.undo import UndoBridge
    sc_bridge = SourceControl(con, data_dir)
    projects_bridge.bind_source_control(sc_bridge)
    projects_undo = UndoBridge("projects")
    projects_undo.register(
        "projects.settings",
        lambda d: core_projects.update_project(
            con, int(d["id"]), settings=d["new"]),
        lambda d: core_projects.update_project(
            con, int(d["id"]), settings=d["old"]))
    projects_undo.register(
        "projects.meta",
        lambda d: core_projects.update_project(
            con, int(d["id"]), **d["new"]),
        lambda d: core_projects.update_project(
            con, int(d["id"]), **d["old"]))
    # colors pane edits are undoable the same way (swatch-list snapshots)
    colors_undo = UndoBridge("colors")
    colors_undo.register(
        "colors.editor",
        lambda d: colors_bridge.restore_state(d),
        lambda d: colors_bridge.restore_state(d))
    colors_bridge.bind_undo(colors_undo)
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
    # real QSyntaxHighlighter for the snippet editor — one layout for
    # glyphs, cursor and selection (the old overlay desynced them);
    # colors are pulled from the theme bridge (tokensChanged-driven)
    snip_highlighter = EditorHighlighter(theme)
    ctx.setContextProperty("snipHl", snip_highlighter)
    # a second highlighter instance for ad-hoc editors (fonts.css export
    # dialog) — attaching snipHl elsewhere would steal it from the
    # snippet editor, since EditorHighlighter owns one document at a time
    css_highlighter = EditorHighlighter(theme)
    ctx.setContextProperty("cssHl", css_highlighter)
    ctx.setContextProperty("projects", projects_bridge)
    ctx.setContextProperty("studio", studio_bridge)
    ctx.setContextProperty("sc", sc_bridge)
    ctx.setContextProperty("undoProjects", projects_undo)
    ctx.setContextProperty("undoColors", colors_undo)
    ctx.setContextProperty("demo", demo_bridge)
    ctx.setContextProperty("updater", updater_bridge)
    ctx.setContextProperty("prefs", prefs_bridge)
    ctx.setContextProperty("dbs", dbs_bridge)
    ctx.setContextProperty("storage", storage_bridge)
    ctx.setContextProperty("dataio", dataio_bridge)
    # non-empty when startup fell back (missing active database)
    ctx.setContextProperty("startupNotice", startup_notice)
    taxonomy_bridge = Taxonomy(con, data_dir)
    ctx.setContextProperty("taxonomy", taxonomy_bridge)
    # curated preset libraries (fonts / icon sets / site templates):
    # register pack rows (idempotent), never download anything
    core_presets.ensure_presets(con)
    # downloaded preset clones become scan sources (#37) — startup sync
    # covers entries downloaded by older builds or on another machine;
    # _start_initial_scans rescans exactly the kinds that registered
    preset_sources = core_presets.sync_downloaded_sources(con)
    presets_bridge = Presets(con, data_dir)
    ctx.setContextProperty("presets", presets_bridge)

    def _on_preset_source(path: str, kind: str) -> None:
        # fresh clone landed: index it right away (rescan queues while
        # a scan is already running — never dropped)
        if args.no_scan:
            return
        if kind == "fontroot":
            fonts.rescan()
        else:
            library.rescan()

    presets_bridge.sourceAdded.connect(_on_preset_source)
    preview_profile = make_preview_profile(con, app)
    # None on platforms without WebEngine — QML binds it only inside the
    # Loader, which stays inactive there
    ctx.setContextProperty("previewProfile", preview_profile)
    ctx.setContextProperty("appVersion", __version__)
    # '' when the build carried no stamp and git metadata is absent —
    # the About screen hides the row in that case (#43)
    ctx.setContextProperty("appCommit", build_commit())
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
    # #61 (user decision): system folders are NEVER scanned by default.
    # On first run, every detected path is pre-registered DISABLED so
    # the setup checkboxes start unchecked, and nothing indexes until
    # the user selects paths (each toggle triggers its own scan). A
    # skipped setup leaves an honestly-empty library.
    if prefs_bridge.firstRunNeeded and not bool(args.screenshot):
        from fengrid.core import indexer as core_indexer
        from fengrid.core import scanner as core_scanner
        from fengrid.core import fonts as core_fonts
        core_indexer.register_detected_paths(con, [
            *[(p, "system") for p in core_scanner.platform_candidates()],
            *[(p, "fontroot") for p in core_fonts.platform_font_dirs()],
        ])
        con.commit()
    t_register = time.perf_counter() - _t_phase
    _t_phase = time.perf_counter()
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
    # false on hardware-GL displays; true after the software fallback —
    # QML gates its shader effects on this (crash guard). Must precede
    # engine.load: Main.qml reads it in a root binding.
    ctx.setContextProperty("softwareRenderer", software_renderer)
    _t_load = time.perf_counter()
    engine.load(QUrl.fromLocalFile(os.path.join(_asset_dir("qml"), "Main.qml")))
    t_engine_load = time.perf_counter() - _t_load
    # #61: the phase profile — a slow read, a slow registration, and a
    # slow QML load all looked identical in the freeze dumps
    if _crash_log is not None:
        try:
            _crash_log.write(
                f"startup: connect {t_connect:.2f}s prefs {t_prefs:.2f}s"
                f" register {t_register:.2f}s"
                f" engine.load {t_engine_load:.2f}s\n")
            _crash_log.flush()
        except (OSError, ValueError):
            pass
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
        elif args.pane == 4:
            row = con.execute(
                "SELECT id FROM projects WHERE name LIKE ?",
                (f"%{args.qa_select}%",)).fetchone()
            if row:
                projects_bridge.open(row["id"])

    def _start_initial_scans():
        if args.no_scan:
            return
        # #61 (user decision): system icon/font roots are no longer
        # indexed automatically — first-run pre-registers them DISABLED
        # and the setup screen scans exactly what the user checks. Only
        # previously-downloaded preset clones (registered sources with
        # no assets yet) still auto-index.
        kinds = {s["kind"] for s in preset_sources}
        if "folder" in kinds:
            QTimer.singleShot(0, library.rescan)
        if "fontroot" in kinds:
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
