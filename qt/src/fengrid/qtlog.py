"""Qt message routing: keep every diagnostic EXCEPT one benign flood.

Third-party icon sets routinely ship SVGs where several elements share
the same id (badly-duplicated ids like ``paint0_linear`` or
``linearGradient3600`` declared twice).  Qt's SVG renderer logs
``qt.svg: Duplicate unique style id: "..."`` for EACH such element on
EVERY parse — the grid re-parses on zoom/scroll eviction, thumbnails
re-render on export/scan, so a big library floods the terminal with a
warning the user cannot act on (the files are not ours; Qt renders them
anyway, resolving url(#id) to the first declaration).

``install()`` installs a handler that drops ONLY that exact warning
(text-anchored, warning-level, qt.svg category) and reproduces Qt's
default output byte-for-byte for everything else — ``<category>: <msg>``
on stderr (no prefix for the default category).  Real SVG failures
(parse errors, missing files) still reach the terminal.

Escape hatch: ``FENGRID_DEBUG_QT_SVG=1`` passes the warnings through.

Installed first thing in ``main()`` so every render path (QML Image's
svg imageformat plugin, library._render_svg, exportplus.render_svg,
ingest conversion) is covered.
"""

from __future__ import annotations

import os
import re
import sys

from PySide6 import QtCore

# anchored to the exact reported message — never a broad category kill
_SUPPRESS = re.compile(r"^Duplicate unique style id:")
_installed = False


def install() -> bool:
    """Idempotent.  Returns True when this call installed the handler."""
    global _installed
    if _installed:
        return False
    _installed = True
    QtCore.qInstallMessageHandler(_handler)
    return True


def _enabled() -> bool:
    return os.environ.get("FENGRID_DEBUG_QT_SVG", "") not in ("", "0")


def _handler(msg_type, ctx, msg: str) -> None:
    category = getattr(ctx, "category", None) or "default"
    if (msg_type == QtCore.QtMsgType.QtWarningMsg
            and category == "qt.svg"
            and not _enabled()
            and _SUPPRESS.match(msg)):
        return
    _emit(category, msg)


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
