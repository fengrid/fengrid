"""Qt-bound handlers for the hardened preview profile (ADR-0001 §8/§9).

Split out of web/__init__.py so the QtWebEngine imports happen only on
platforms that actually have the module (Windows ARM64 ships no wheels —
importing this submodule there must never happen; web/__init__.py guards
every entry into it).
"""

from __future__ import annotations

import mimetypes
import os

from PySide6.QtCore import QFile, QUrl
from PySide6.QtWebEngineCore import (QWebEngineProfile,
                                     QWebEngineUrlRequestInterceptor,
                                     QWebEngineUrlRequestJob,
                                     QWebEngineUrlSchemeHandler)

SCHEME = "fengrid-asset"
SCHEME_BYTES = SCHEME.encode()

_MIME_OVERRIDES = {".svg": "image/svg+xml", ".ico": "image/x-icon",
                   ".xpm": "image/x-xpixmap"}


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
            "SELECT 1 FROM asset WHERE path = ?",
            (path,)).fetchone() is not None
        # SEC-8: a crafted DB row (malicious import, direct DB edit) or
        # a post-scan symlink swap could otherwise serve ANY local file.
        # Defense in depth at serve time: the REAL path must resolve
        # under a registered source root, and it must be a regular file.
        if row:
            row = self._path_is_registered(path)
        if not row:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        mime = (_MIME_OVERRIDES.get(_ext(path))
                or mimetypes.guess_type(path)[0]
                or "application/octet-stream")
        job.reply(mime.encode(), _open_local(path))

    def _path_is_registered(self, path: str) -> bool:
        """True when the real (symlink-resolved) path lies under one of
        the enabled source roots."""
        try:
            real = os.path.realpath(path)
            if not os.path.isfile(real):
                return False
            roots = [r[0] for r in self._con.execute(
                "SELECT path FROM source WHERE enabled = 1")]
            for root in roots:
                if not root:
                    continue
                root_real = os.path.realpath(root)
                if (real == root_real
                        or real.startswith(root_real.rstrip(os.sep)
                                           + os.sep)):
                    return True
            # staged/temp files the importer just wrote (import of a
            # file the scanner has not indexed yet) live under the data
            # dir — accept that too
            data_dir = os.environ.get("FENGRID_DATA_DIR", "")
            if data_dir:
                data_real = os.path.realpath(data_dir)
                if real.startswith(data_real.rstrip(os.sep) + os.sep):
                    return True
        except Exception:                        # noqa: BLE001
            return False
        return False


def _ext(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot >= 0 else ""


def _open_local(path: str) -> QFile:
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


def make_preview_profile(con, parent=None) -> "QQuickWebEngineProfile":
    """Off-the-record profile wired to the allowlist scheme + interceptor.

    The interceptor and handler are parented to the profile so they live
    and die with it (Python GC must not outlive Chromium's references).

    Must be a QQuickWebEngineProfile — QML's WebEngineView.profile takes
    the QUICK profile class; assigning the core QWebEngineProfile fails
    at load ("Unable to assign QWebEngineProfile to
    QQuickWebEngineProfile") and the view silently falls back to the
    DEFAULT profile — no interceptor, no scheme handler.
    """
    from PySide6.QtWebEngineQuick import QQuickWebEngineProfile
    profile = QQuickWebEngineProfile(parent)  # default ctor = off-the-record
    profile.setHttpCacheType(QQuickWebEngineProfile.HttpCacheType.NoCache)
    profile.setPersistentCookiesPolicy(
        QQuickWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    interceptor = PreviewRequestInterceptor(profile)
    profile.setUrlRequestInterceptor(interceptor)
    handler = AssetSchemeHandler(con, profile)
    profile.installUrlSchemeHandler(SCHEME_BYTES, handler)
    return profile
