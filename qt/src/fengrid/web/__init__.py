"""Preview web-engine plumbing (ADR-0001 §8/§9) — the hardened scaffold.

Design, locked in the ADR:
- `fengrid-asset://` serves ONLY paths present in the scan index (path
  allowlist query, so traversal and non-indexed files 404).
- The preview profile is off-the-record (no persistent storage, no cache)
  and an interceptor blocks every request whose scheme is not ours —
  previewed components get browser-tab powers and nothing more.
- No QWebChannel bridge exists inside previewed content; privileged
  channels belong to the app's own surfaces only.

Startup ordering notes:
- `register_asset_scheme()` must run before QGuiApplication is created
  (scheme flags are read at Chromium start). It does NOT spawn threads, so
  it is safe to call unconditionally in __main__.
- QtWebEngineQuick.initialize() is intentionally NOT called here: it spins
  up Chromium infrastructure on every launch, and the qa_render gate
  hard-fails on stray QThread noise. Call it in the surface that first
  instantiates a WebEngineView (M3 playground / M4 composer), after the
  scheme registration that already happened at startup.
"""

from __future__ import annotations

import mimetypes

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import (QWebEngineProfile,
                                     QWebEngineUrlRequestInterceptor,
                                     QWebEngineUrlRequestJob,
                                     QWebEngineUrlScheme,
                                     QWebEngineUrlSchemeHandler)

SCHEME = "fengrid-asset"
_SCHEME_BYTES = SCHEME.encode()

_MIME_OVERRIDES = {".svg": "image/svg+xml", ".ico": "image/x-icon",
                   ".xpm": "image/x-xpixmap"}


def register_asset_scheme() -> bool:
    """Register the custom scheme before the app object exists.

    Returns False when QtWebEngineCore is unavailable (wheel missing on the
    platform — e.g. Windows ARM64); callers degrade to preview-less shells.
    """
    try:
        from PySide6 import QtWebEngineCore  # noqa: F401 — links the module
    except ImportError:
        return False
    scheme = QWebEngineUrlScheme(_SCHEME_BYTES)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Path)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                    | QWebEngineUrlScheme.Flag.LocalScheme
                    | QWebEngineUrlScheme.Flag.LocalAccessAllowed
                    | QWebEngineUrlScheme.Flag.NoAccessAllowed)
    QWebEngineUrlScheme.registerScheme(scheme)
    return True


def asset_url(path: str) -> QUrl:
    """Build a fengrid-asset:// URL for an absolute local path."""
    url = QUrl()
    url.setScheme(SCHEME)
    url.setPath(path)
    return url


class AssetSchemeHandler(QWebEngineUrlSchemeHandler):
    """Serves whitelisted (indexed) paths with correct MIME types."""

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        url = job.requestUrl()
        if url.scheme() != SCHEME:
            job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
            return
        path = url.path()
        # allowlist: only files the scan index knows about resolve
        row = self._con.execute(
            "SELECT 1 FROM asset WHERE path = ?", (path,)).fetchone()
        if row is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        mime = (_MIME_OVERRIDES.get(_ext(path))
                or mimetypes.guess_type(path)[0]
                or "application/octet-stream")
        job.reply(mime.encode(), _open_local(path))


def _ext(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot >= 0 else ""


def _open_local(path: str):
    from PySide6.QtCore import QFile
    f = QFile(path)
    f.open(QFile.OpenModeFlag.ReadOnly)
    return f


class PreviewRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """Blocks every request that is not the asset scheme.

    Network access from preview content is denied by construction — the
    threat model is 'user pastes a hostile snippet' (ADR §9), so preview
    panes behave like a browser tab with no special powers.
    """

    def interceptRequest(self, info) -> None:
        if info.requestUrl().scheme() != SCHEME:
            info.block(True)


def make_preview_profile(con, parent=None) -> QWebEngineProfile:
    """Off-the-record profile wired to the allowlist scheme + interceptor.

    The interceptor and handler are parented to the profile so they live
    and die with it (Python GC must not outlive Chromium's references).
    """
    profile = QWebEngineProfile(parent)  # default ctor = off-the-record
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    interceptor = PreviewRequestInterceptor(profile)
    profile.setUrlRequestInterceptor(interceptor)
    handler = AssetSchemeHandler(con, profile)
    profile.installUrlSchemeHandler(_SCHEME_BYTES, handler)
    return profile
