"""glprobe.display_gl_mode() tier selection (#32).

The renderer decision hierarchy: explicit QT_* overrides win (QA paths
untouched), then GLX on X11, then EGL on the SAME X display (the tier
that keeps web previews alive on GLX-less XWayland/VM machines), then
the software (QPainter) scene graph. The ctypes probes themselves are
display-bound, so the tests inject fake probe results and pin the
DECISION LOGIC only.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fengrid import glprobe                      # noqa: E402


@pytest.fixture
def _no_override_env(monkeypatch):
    for var in ("QT_QUICK_BACKEND", "QSG_RHI_BACKEND", "QT_QPA_PLATFORM",
                "FENGRID_FORCE_SOFTWARE", "WAYLAND_DISPLAY",
                "WAYLAND_SOCKET", "DISPLAY"):
        monkeypatch.delenv(var, raising=False)


def test_qt_overrides_win(_no_override_env, monkeypatch):
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    assert glprobe.display_gl_mode() == "override"


def test_qa_software_lever(_no_override_env, monkeypatch):
    monkeypatch.setenv("FENGRID_FORCE_SOFTWARE", "1")
    monkeypatch.setenv("DISPLAY", ":99")
    assert glprobe.display_gl_mode() == "none"


def test_x11_glx_healthy(_no_override_env, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(glprobe, "_glx_ok", lambda: True)
    assert glprobe.display_gl_mode() == "glx"


def test_x11_falls_back_to_egl(_no_override_env, monkeypatch):
    # THE #32 case: GLX offers nothing, but EGL (Mesa software GL) works
    # on the same display — a real GL scene graph, previews stay alive.
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(glprobe, "_x11_display", lambda: 0xDEADBEEF)
    monkeypatch.setattr(glprobe, "_glx_ok", lambda: False)
    monkeypatch.setattr(glprobe, "_egl_display_ok", lambda dpy: True)
    assert glprobe.display_gl_mode() == "egl"


def test_x11_no_gl_at_all(_no_override_env, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(glprobe, "_x11_display", lambda: 0xDEADBEEF)
    monkeypatch.setattr(glprobe, "_glx_ok", lambda: False)
    monkeypatch.setattr(glprobe, "_egl_display_ok", lambda dpy: False)
    monkeypatch.setattr(glprobe, "_egl_ok", lambda: False)
    assert glprobe.display_gl_mode() == "none"


def test_wayland_egl(_no_override_env, monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(glprobe, "_egl_ok", lambda: True)
    assert glprobe.display_gl_mode() == "egl"
    monkeypatch.setattr(glprobe, "_egl_ok", lambda: False)
    assert glprobe.display_gl_mode() == "none"


def test_needs_software_fallback_only_for_none(_no_override_env, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(glprobe, "_x11_display", lambda: 0xDEADBEEF)
    monkeypatch.setattr(glprobe, "_glx_ok", lambda: False)
    monkeypatch.setattr(glprobe, "_egl_display_ok", lambda dpy: True)
    assert glprobe.needs_software_fallback() is False   # egl != software
