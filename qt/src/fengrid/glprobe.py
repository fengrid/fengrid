"""Hardware-GL preflight: degrade to the software renderer instead of dying.

Qt's scene graph aborts the whole process (qFatal → SIGABRT) when its GLX
path finds no usable FBConfig — the exact failure mode of GLX-less
XWayland (Xorg deprecation era) and several NVIDIA/VM configurations:
    qglx_findConfig: Failed to finding matching FBConfig ... (×3)
    Could not initialize GLX
The abort happens inside context creation, so it cannot be caught in
Python. Instead we probe the display at the C level (ctypes, no Qt) with
the SAME minimal format Qt's qglx_findConfig fallback asks for; if the
probe fails, __main__ sets QT_QUICK_BACKEND=software before any window
exists and the app renders via QPainter instead.

Qt-free by design (no Qt imports) so it stays unit-testable headlessly.
False negatives are safe (software rendering always works); the probe is
deliberately conservative: it only reports True when GLX/EGL reports a
config on the actual display connection.
"""

from __future__ import annotations

import ctypes
import os

# GLX 1.3 enum values (glx.h) — fixed ABI, safe to hardcode
_GLX_DOUBLEBUFFER = 5
_GLX_RED_SIZE = 8
_GLX_GREEN_SIZE = 9
_GLX_BLUE_SIZE = 10
_GLX_RENDER_TYPE = 0x8011
_GLX_RGBA_BIT = 0x00000001


def _egl_display_ok(native: int) -> bool:
    """True when EGL initializes on the given native display handle."""
    try:
        egl = ctypes.CDLL("libEGL.so.1")
    except OSError:
        return False
    egl.eglGetDisplay.restype = ctypes.c_void_p
    egl.eglGetDisplay.argtypes = [ctypes.c_void_p]
    d = egl.eglGetDisplay(ctypes.c_void_p(native))
    if not d:
        return False
    egl.eglInitialize.restype = ctypes.c_uint
    egl.eglInitialize.argtypes = [ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_void_p]
    return bool(egl.eglInitialize(d, None, None))


def _x11_display() -> int:
    """Open the default X display (ctypes); 0 when unavailable."""
    try:
        x11 = ctypes.CDLL("libX11.so.6")
    except OSError:
        return 0
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    dpy = x11.XOpenDisplay(None)
    return dpy or 0


def _glx_ok() -> bool:
    """True when the X display offers at least one usable FBConfig."""
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        gl = ctypes.CDLL("libGL.so.1")
    except OSError:
        return False
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultScreen.restype = ctypes.c_int
    x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    dpy = x11.XOpenDisplay(None)
    if not dpy:
        return False
    try:
        gl.glXQueryExtension.restype = ctypes.c_int
        gl.glXQueryExtension.argtypes = [ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.c_void_p]
        if not gl.glXQueryExtension(dpy, None, None):
            return False
        gl.glXChooseFBConfig.restype = ctypes.POINTER(ctypes.c_int)
        gl.glXChooseFBConfig.argtypes = [
            ctypes.c_void_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]

        def configs_with(doublebuffer: int) -> int:
            # mirrors Qt's qglx_findConfig fallback format: rgb sizes 1,
            # single- then double-buffered, nothing else constrained
            attribs = (ctypes.c_int * 11)(
                _GLX_RENDER_TYPE, _GLX_RGBA_BIT,
                _GLX_RED_SIZE, 1, _GLX_GREEN_SIZE, 1, _GLX_BLUE_SIZE, 1,
                _GLX_DOUBLEBUFFER, doublebuffer,
                0)
            n = ctypes.c_int(0)
            ctypes.cast(gl.glXChooseFBConfig(dpy, x11.XDefaultScreen(dpy),
                                             attribs, ctypes.byref(n)),
                        ctypes.c_void_p)
            return n.value

        # single-buffer first (the exact format Qt reports failing), then
        # double-buffered — either success means GLX is usable
        return configs_with(0) > 0 or configs_with(1) > 0
    finally:
        x11.XCloseDisplay(dpy)


def _egl_ok() -> bool:
    """True when EGL initializes on the default display (Wayland path)."""
    try:
        egl = ctypes.CDLL("libEGL.so.1")
    except OSError:
        return False
    egl.eglGetDisplay.restype = ctypes.c_void_p
    egl.eglGetDisplay.argtypes = [ctypes.c_void_p]
    d = egl.eglGetDisplay(None)  # EGL_DEFAULT_DISPLAY
    if not d:
        return False
    egl.eglInitialize.restype = ctypes.c_uint
    egl.eglInitialize.argtypes = [ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_void_p]
    return bool(egl.eglInitialize(d, None, None))


def display_gl_mode() -> str:
    """How the (auto-chosen) windowing platform can render.

    Returns one of:
    - ``"override"`` — QT_QUICK_BACKEND / QSG_RHI_BACKEND / QT_QPA_PLATFORM
      already set: the caller knows what they want, we do not second-guess
      (this also keeps the offscreen QA path untouched).
    - ``"glx"`` — usable GLX on the X display: the healthy default.
    - ``"egl"`` — GLX unusable but EGL initializes on the same display
      (GLX-less XWayland, VMs): Mesa's software GL (llvmpipe) can drive a
      REAL GL scene graph through the xcb EGL integration, so the app and
      Chromium both run — slower than hardware, but nothing is disabled.
      The probe deliberately never tried EGL on the X11 path before #32,
      which forced whole machines onto the QPainter scene graph that
      cannot host WebEngine at all.
    - ``"none"`` — no usable GL at all: software (QPainter) scene graph.
    """
    if (os.environ.get("QT_QUICK_BACKEND")
            or os.environ.get("QSG_RHI_BACKEND")
            or os.environ.get("QT_QPA_PLATFORM")):
        return "override"
    if os.environ.get("FENGRID_FORCE_SOFTWARE") == "1":
        return "none"            # QA lever: exercise the #32 fallback chain
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("WAYLAND_SOCKET"):
        return "egl" if _egl_ok() else "none"
    if os.environ.get("DISPLAY"):
        if _glx_ok():
            return "glx"
        dpy = _x11_display()
        if dpy and (_egl_display_ok(dpy) or _egl_ok()):
            return "egl"
        return "none"
    return "glx"  # no display at all: Qt's own error is the honest signal


def needs_software_fallback() -> bool:
    """True when the app must run on the software (QPainter) scene graph."""
    return display_gl_mode() == "none"
