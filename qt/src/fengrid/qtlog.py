"""Qt message routing: keep every diagnostic EXCEPT benign third-party
floods.

Two floods are dropped, both from files Fengrid does not ship:

1. Duplicate SVG ids — third-party icon sets routinely ship SVGs where
   several elements share the same id (badly-duplicated ids like
   ``paint0_linear`` or ``linearGradient3600`` declared twice).  Qt's
   SVG renderer logs ``qt.svg: Duplicate unique style id: "..."`` for
   EACH such element on EVERY parse — the grid re-parses on
   zoom/scroll eviction, thumbnails re-render on export/scan, so a big
   library floods the terminal with a warning the user cannot act on
   (the files are not ours; Qt renders them anyway, resolving
   url(#id) to the first declaration).

2. Unresolvable SVG property references (issue #138) — the SAME
   third-party bodies (freedesktop system icon themes like Humanity /
   elementary) ship SVGs whose url(#id) / xlink:href targets do not
   exist; Qt logs ``qt.svg: <path>:<l>:<c>: Could not resolve
   property: #id`` per reference per parse.  Suppressed ONLY when the
   cited path is not one of ours (our resource paths all carry a
   ``fengrid`` segment) — a broken Fengrid SVG still reports.

``install()`` installs a handler that drops ONLY those two classes
(text-anchored, warning-level, qt.svg category) and reproduces Qt's
default output byte-for-byte for everything else — ``<category>:
<msg>`` on stderr (no prefix for the default category).  Real SVG
failures (parse errors, missing files) still reach the terminal.

Escape hatch: ``FENGRID_DEBUG_QT_SVG=1`` passes the warnings through.
"""

from __future__ import annotations

import os
import re
import sys

from PySide6 import QtCore

# anchored to the exact reported messages — never a broad category kill
_SUPPRESS = re.compile(r"^Duplicate unique style id:")
_RESOLVE = re.compile(r":\d+:\d+: Could not resolve property:")
_installed = False


def _enabled() -> bool:
    return os.environ.get("FENGRID_DEBUG_QT_SVG", "") not in ("", "0")


def _handler(msg_type, ctx, msg: str) -> None:
    category = getattr(ctx, "category", None) or "default"
    if (msg_type == QtCore.QtMsgType.QtWarningMsg
            and category == "qt.svg"
            and not _enabled()):
        if _SUPPRESS.match(msg):
            return
        # issue #138: unresolvable url(#id) references in third-party
        # SVGs (system icon themes). Our own resource paths carry a
        # "fengrid" segment — those failures must still report.
        if _RESOLVE.search(msg) and "/fengrid/" not in msg:
            return
    _emit(category, msg)


def install() -> bool:
    """Idempotent.  Returns True when this call installed the handler."""
    global _installed
    if _installed:
        return False
    _installed = True
    QtCore.qInstallMessageHandler(_handler)
    return True


def _emit(category: str, msg: str) -> None:
    # Qt's default handler prints "<category>: <message>" (category
    # omitted for the default category) as one line on stderr.
    line = msg if category in ("", "default") else f"{category}: {msg}"
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        try:
            os.write(2, line.encode("utf-8", "replace") + b"\n")
        except OSError:
            pass
