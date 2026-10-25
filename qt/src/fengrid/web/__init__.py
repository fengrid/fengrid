"""Preview web-engine plumbing (ADR-0001 §8/§9) — the hardened scaffold.

Design, locked in the ADR:
- `fengrid-asset://` serves ONLY paths present in the scan index (path
  allowlist query, so traversal and non-indexed files 404).
- The preview profile is off-the-record (no persistent storage, no cache)
  and an interceptor blocks every request whose scheme is not ours —
  previewed components get browser-tab powers and nothing more.
- No QWebChannel bridge exists inside previewed content; privileged
  channels belong to the app's own surfaces only.

Startup ordering (all enforced in __main__):
1. `register_asset_scheme()` — before QGuiApplication; scheme flags are
   read at Chromium start. Spawns no threads.
2. `initialize_webengine()` — before QGuiApplication. A Qt 6 requirement:
   Chromium reads the command line while the application object is being
   constructed, and a later initialize() is rejected ("must be called
   before constructing the application object"). Skipped under
   QT_QPA_PLATFORM=offscreen, where QA renders never show a preview — the
   gate hard-fails on the stray QThread teardown noise that Chromium
   infrastructure produces at exit.
3. `make_preview_profile()` — after the app exists, before the first
   WebEngineView is instantiated; exposed to QML as a context property.

Import safety: QtWebEngineCore has no wheels on some platforms (Windows
ARM64). Every Qt-bound class lives in `web/handlers.py`, imported here
only after `webengine_available()` succeeds — the source tree itself
never crashes at import time on a preview-less platform.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QUrl

SCHEME = "fengrid-asset"
SCHEME_BYTES = SCHEME.encode()


def webengine_available() -> bool:
    # FENGRID_NO_WEBENGINE=1: user-level bisect lever — a preview-less
    # shell is fully functional, so a crash suspect can be excluded
    # without rebuilding (used while chasing the software-renderer
    # segfaults, #27/#32)
    if os.environ.get("FENGRID_NO_WEBENGINE", "") == "1":
        return False
    try:
        from PySide6 import QtWebEngineCore  # noqa: F401 — links the module
    except ImportError:
        return False
    return True


def register_asset_scheme() -> bool:
    """Register the custom scheme before the app object exists.

    Returns False when QtWebEngineCore is unavailable; callers degrade to
    preview-less shells.
    """
    if not webengine_available():
        return False
    from PySide6.QtWebEngineCore import QWebEngineUrlScheme

    scheme = QWebEngineUrlScheme(SCHEME_BYTES)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Path)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                    | QWebEngineUrlScheme.Flag.LocalScheme
                    | QWebEngineUrlScheme.Flag.LocalAccessAllowed
                    | QWebEngineUrlScheme.Flag.NoAccessAllowed)
    QWebEngineUrlScheme.registerScheme(scheme)
    return True


def initialize_webengine() -> bool:
    """Call QtWebEngineQuick.initialize() — MUST run before QGuiApplication."""
    if not webengine_available():
        return False
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False
    from PySide6.QtWebEngineQuick import QtWebEngineQuick
    QtWebEngineQuick.initialize()
    return True


def asset_url(path: str) -> QUrl:
    """Build a fengrid-asset:// URL for an absolute local path."""
    url = QUrl()
    url.setScheme(SCHEME)
    url.setPath(path)
    return url


def make_preview_profile(con, parent=None):
    """Off-the-record profile wired to the allowlist scheme + interceptor.

    Returns None when QtWebEngineCore is unavailable (preview-less shell).
    The interceptor and handler are parented to the profile so they live
    and die with it (Python GC must not outlive Chromium's references).
    """
    if not webengine_available():
        return None
    from .handlers import make_preview_profile as _make
    return _make(con, parent)
