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
from fengrid.bridges.fonts import Fonts
from fengrid.bridges.library import Library
from fengrid.bridges.theme import Theme
from fengrid.core import db as core_db
from fengrid.web import register_asset_scheme


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
    parser.add_argument("--version", action="version",
                        version=f"fengrid {__version__}")
    args = parser.parse_args(argv)

    # scheme registration must precede QGuiApplication (flags are read at
    # Chromium start); it spawns no threads, so it is always safe. QtWebEngine
    # itself initializes lazily in the first surface that shows a view.
    if not register_asset_scheme():
        print("warning: QtWebEngineCore unavailable — preview surfaces"
              " disabled", file=sys.stderr)

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

    db_path = args.db or os.path.join(_user_data_dir(), "library.db")
    con = core_db.connect(db_path)

    theme = Theme(con, _asset_dir("fonts"))
    if args.theme:
        theme.set_theme(args.theme)
    library = Library(con, db_path, no_scan=args.no_scan)
    fonts = Fonts(con, db_path)

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("fonts", fonts)
    ctx.setContextProperty("appVersion", __version__)
    engine.load(QUrl.fromLocalFile(os.path.join(_asset_dir("qml"), "Main.qml")))
    if not engine.rootObjects():
        print("error: failed to load the QML shell", file=sys.stderr)
        return 1

    if not args.no_scan and library.totalAssets == 0:
        # first run: index the platform icon roots automatically
        QTimer.singleShot(0, library.rescan)
    if not args.no_scan and fonts.totalFonts == 0:
        # first run: index the platform font dirs automatically (own thread
        # + own connection, cancellable at quit — see bridges/fonts.py)
        QTimer.singleShot(0, fonts.rescan)

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
