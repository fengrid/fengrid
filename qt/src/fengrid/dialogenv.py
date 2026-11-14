"""Native dialog environment probe (#81).

Fengrid's file/folder browse buttons open QtQuick.Dialogs, which on a
real desktop session goes through the platform's native dialog
machinery — on wayland/GNOME-class sessions that is xdg-desktop-portal.
A desktop where that machinery is absent or never answers produces
"clicked, nothing appeared" reports that cannot be reproduced from a
headless host, so we MEASURE it instead of guessing: at every launch
this module records what dialog backend the machine actually has, and
its result lands in crash.log next to the db/storage launch lines —
the same diagnostic file the user already sends with a report.

Stdlib-only and Qt-free (the API server imports core modules without
Qt installed). All probes are bounded: a wedged session bus must never
stall app startup, so every subprocess gets a hard timeout and the
probe answers "unknown" instead of hanging.
"""
from __future__ import annotations

import os
import shutil
import subprocess

_PORTAL_SVC = "org.freedesktop.portal.Desktop"
_PORTAL_GTK_SVC = "org.freedesktop.impl.portal.desktop.gtk"
_TIMEOUT_S = 1.5


def _sh(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=_TIMEOUT_S, check=False)
        return (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def portal_running() -> str:
    """Is the xdg-desktop-portal service reachable on the session bus?

    NameHasOwner is answered by the bus daemon itself, so it stays fast
    even when the portal helper is wedged (that wedge is exactly the
    class of machines we are diagnosing). Tries busctl, gdbus then
    dbus-send; "unknown" when none is installed.
    """
    if shutil.which("busctl"):
        out = _sh(["busctl", "--user", "--no-pager", "call",
                   "org.freedesktop.DBus", "/org/freedesktop/DBus",
                   "org.freedesktop.DBus", "NameHasOwner",
                   "s", _PORTAL_SVC])
        if "true" in out:
            return "yes"
        if "false" in out:
            return "no"
    if shutil.which("gdbus"):
        out = _sh(["gdbus", "call", "--session",
                   "--dest", "org.freedesktop.DBus",
                   "--object-path", "/org/freedesktop/DBus",
                   "--method", "org.freedesktop.DBus.NameHasOwner",
                   _PORTAL_SVC])
        if "true" in out:
            return "yes"
        if "false" in out:
            return "no"
    if shutil.which("dbus-send"):
        out = _sh(["dbus-send", "--session", "--print-reply",
                   "--dest=org.freedesktop.DBus",
                   "/org/freedesktop/DBus",
                   "org.freedesktop.DBus.NameHasOwner",
                   "string:" + _PORTAL_SVC])
        if "true" in out:
            return "yes"
        if "false" in out:
            return "no"
    return "unknown"


def dialog_environment() -> dict:
    """One dict of every fact a dialog-failure diagnosis needs."""
    e = os.environ
    return {
        "platform": e.get("QT_QPA_PLATFORM", "default"),
        "platform_theme": e.get("QT_QPA_PLATFORMTHEME", ""),
        "session_type": e.get("XDG_SESSION_TYPE", ""),
        "display": e.get("WAYLAND_DISPLAY") or e.get("DISPLAY", ""),
        "desktop": e.get("XDG_CURRENT_DESKTOP", ""),
        "portal_binary": (bool(shutil.which("xdg-desktop-portal"))
                          or bool(shutil.which("xdg-desktop-portal-gtk"))),
        "portal_running": portal_running(),
    }


def describe_environment() -> str:
    """The single crash.log line for a launch."""
    d = dialog_environment()
    return (f"dialog-env: platform={d['platform']}"
            f" theme={d['platform_theme'] or 'qt-default'}"
            f" session={d['session_type'] or 'unknown'}"
            f" display={d['display'] or 'none'}"
            f" desktop={d['desktop'] or 'unknown'}"
            f" portal-bin={'yes' if d['portal_binary'] else 'no'}"
            f" portal-serving={d['portal_running']}")
