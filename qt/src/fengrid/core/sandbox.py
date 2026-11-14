"""Sandbox exclusion — Flatpak, Snap, and other sandbox asset trees.

Sandboxes bundle their own copies of theme icons, fonts, and media under
per-app trees (every installed flatpak/snap app carries a full
``files/share/icons`` copy). Walking those trees yields thousands of
redundant or stale duplicates that pollute the library, slow scans, and
frequently produce unreadable/permission-denied entries. Every traversal
in the core (scanner, fonts, watch) prunes sandbox directories; explicit
imports of a sandbox path are rejected with a clear error.

Opt-out: FENGRID_ALLOW_SANDBOX=1 restores inclusion everywhere (for
diagnosis; documented in QUICKSTART.md "Importing assets").
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Directory names pruned from ANY traversal (os.walk dirnames). Hidden
# variants (.snap, .flatpak, .var) are already covered by the walkers'
# hidden-dir filter; these are the visible ones. A tree named exactly
# like one of these under a user root is a sandbox payload — theme icon
# copies inside it are redundant with the system theme sources.
SANDBOX_DIR_NAMES = frozenset({
    "snap", ".snap",
    "flatpak", ".flatpak",
    "squashfs-root",          # unsquashed snap payloads
    "appdir",                 # appimage build trees
})

# Absolute prefixes treated as sandbox roots: indexing them directly is
# refused for source registration and explicit imports.
_SANDBOX_PREFIXES = (
    "/snap/",
    "/var/lib/flatpak/",
    "/var/lib/snapd/",
    "/var/lib/snap/",
    "/app/",                  # the flatpak runtime mount inside a sandbox
    "/opt/hostedtoolcache/",  # CI sandboxes (GitHub runners) — huge trees
)

# Per-user trees; computed once (Path.home() is stable for a session)
_HOME_SANDBOX_PREFIXES = (
    Path.home() / ".local/share/flatpak",
    Path.home() / ".cache/flatpak",
    Path.home() / ".var/app",
    Path.home() / "snap",
    Path.home() / ".snap",
)

# Path segments that mark a per-app sandbox payload regardless of which
# root the walk started at (e.g. ~/dev/flatpak-builds/app/com.foo/current/active/files/...)
_APP_PAYLOAD_RE = re.compile(
    r"(^|/)(flatpak|snapd?)(/|$).*/(app|revision|current|active|files)/",
    re.IGNORECASE)


def allow_sandbox() -> bool:
    """True when FENGRID_ALLOW_SANDBOX=1 — every exclusion is skipped."""
    return os.environ.get("FENGRID_ALLOW_SANDBOX") == "1"


def is_sandbox_path(path: str | Path) -> bool:
    """True when the path sits inside a sandbox tree (flatpak/snap/...).

    Used for whole-root decisions: source registration, explicit
    imports, watch-folder setup. Traversal-level pruning uses
    prune_sandbox_dirs() instead (cheap per-directory name check).
    """
    if allow_sandbox():
        return False
    p = os.path.realpath(os.fspath(path))
    home = os.path.realpath(str(Path.home()))
    for pref in _SANDBOX_PREFIXES:
        if p.startswith(pref):
            return True
    for pref in _HOME_SANDBOX_PREFIXES:
        if p.startswith(os.path.realpath(str(pref)) + os.sep) or p == \
                os.path.realpath(str(pref)):
            return True
    return bool(_APP_PAYLOAD_RE.search(p))


def sandbox_reason(path: str | Path) -> str | None:
    """A human-readable reason string when path is a sandbox path."""
    if not is_sandbox_path(path):
        return None
    if os.path.realpath(os.fspath(path)).startswith("/snap/"):
        return "snap package tree"
    if "flatpak" in os.path.realpath(os.fspath(path)):
        return "flatpak per-app tree"
    if "/snap" in os.path.realpath(os.fspath(path)):
        return "snap payload"
    return "sandbox tree"


def prune_sandbox_dirs(dirnames: list[str]) -> list[str]:
    """Filter an os.walk dirnames list IN PLACE; returns it for chaining.

    Call this in every walker right after the hidden-dir filter so a
    user-added root never descends into a nested sandbox payload.
    """
    if allow_sandbox():
        return dirnames
    dirnames[:] = [d for d in dirnames if d not in SANDBOX_DIR_NAMES]
    return dirnames
