"""file-URL <-> plain-path helpers (Windows-safe).

QML FolderDialog/FileDialog hand over file:// URLs; hand-rolled
substring conversion breaks on Windows drive letters — file:///D:/…
sliced after "file://" leaves "/D:/…", which os.path.isdir can never
match — and on UNC shares. QUrl is the battle-tested converter: it
percent-decodes spaces (%20) and non-ASCII, strips the leading slash on
Windows drive-letter URLs, and resolves UNC hosts. Anything that does
not look like a URL passes through untouched.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QUrl


def local_path(value: str) -> str:
    """Accept a file:// URL or a plain path; return a plain local path.

    - file:///home/x/My%20Icons   → /home/x/My Icons
    - file:///D:/Library/Icons    → D:/Library/Icons   (Windows drive)
    - file://server/share/icons   → //server/share/icons (UNC)
    - D:/Library/Icons           → unchanged (already plain)

    QUrl.toLocalFile strips the leading slash on Windows drive-letter
    URLs only when running ON Windows; to behave identically on every
    host (and in tests), the drive-letter form is normalized here.
    """
    s = str(value)
    if not s.startswith("file://"):
        return s
    local = QUrl(s).toLocalFile() or s
    if re.match(r"^/[A-Za-z]:($|[/?#])", local):
        return local[1:]      # Windows drive URL: /D:/… → D:/…
    return local


def file_url(path: str) -> str:
    """Inverse: a plain local path → a well-formed file:// URL (the
    start directory dialogs receive)."""
    return QUrl.fromLocalFile(str(path)).toString()
