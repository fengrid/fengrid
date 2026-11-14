"""QQuickImageProvider serving the Explorer disc's shade field.

The inner saturation/lightness disc shows the S/L square mapped ONTO A
SPHERE (the same projection the wheel's dots use): the disc centre is
the sphere's apex, edge midpoints reach the equator (the rim), and
square corners beyond the equator pin onto the rim. Each pixel shows
the shade whose dot projects there — the inverse of the dot mapping —
so dots sit on their own colors and drags follow the sphere's
curvature.

Rendered here in Python because Qt's QML Canvas putImageData/ImageData
writes are unreliable (observed as silent no-ops), and per-pixel work
is cheap on this side: the geometry (S/L per pixel) is cached per size
and only the hue-dependent color pass reruns. Served as
`image://fgfield/<hue>x<px>` with a bounded cache — hue drags re-render
one texture per new degree.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

_MAX_CACHE = 48


class SphereFieldProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        self._geo: dict[int, list] = {}
        self._cache: dict[tuple[int, int], QImage] = {}
        self._order: list[tuple[int, int]] = []

    # ------------------------------------------------------------ internals
    def _geometry(self, n: int) -> list:
        """(rr, theta) per pixel, cached per texture size — rr is the
        pixel's radius normalized so the outermost in-circle pixel ring
        hits 1.0 (the equator/rim), None marks outside the disc."""
        geo = self._geo.get(n)
        if geo is None:
            half = n / 2
            reach = half - 0.5   # outermost pixel-centre radius along axes
            geo = []
            for j in range(n):
                dy = j + 0.5 - half
                for i in range(n):
                    dx = i + 0.5 - half
                    raw = math.hypot(dx, dy)
                    if raw >= half:
                        geo.append(None)
                    else:
                        geo.append((min(1.0, raw / reach),
                                    math.atan2(dy, dx)))
            self._geo[n] = geo
        return geo

    def _render(self, hue: int, n: int) -> QImage:
        geo = self._geometry(n)
        buf = bytearray(n * n * 4)
        hue %= 360
        hp = hue / 60.0
        xr = 1.0 - abs(hp % 2 - 1)
        kr = kg = kb = 0.0
        sector = int(hp) % 6
        if sector == 0:
            kr, kg = 1.0, xr
        elif sector == 1:
            kr, kg = xr, 1.0
        elif sector == 2:
            kg, kb = 1.0, xr
        elif sector == 3:
            kg, kb = xr, 1.0
        elif sector == 4:
            kr, kb = xr, 1.0
        else:
            kr, kb = 1.0, xr
        asin, cos, sin = math.asin, math.cos, math.sin
        two_over_pi = 2 / math.pi
        k = 0
        for px in geo:
            if px is None:
                k += 4
                continue
            rr, th = px
            rho = two_over_pi * asin(rr)
            s = 50 + 50 * rho * cos(th)
            l = 50 - 50 * rho * sin(th)
            if s < 0:
                s = 0
            elif s > 100:
                s = 100
            if l < 0:
                l = 0
            elif l > 100:
                l = 100
            sn = s / 100.0
            ln = l / 100.0
            c = (1 - abs(2 * ln - 1)) * sn
            m = ln - c / 2
            buf[k] = max(0, min(255, int((m + kr * c) * 255)))
            buf[k + 1] = max(0, min(255, int((m + kg * c) * 255)))
            buf[k + 2] = max(0, min(255, int((m + kb * c) * 255)))
            buf[k + 3] = 255
            k += 4
        img = QImage(n, n, QImage.Format.Format_RGBA8888)
        bits = img.bits()
        bits[:] = buf
        return img

    # ------------------------------------------------------- QQuickImageProvider
    def requestImage(self, id_: str, size: QSize,
                     requestedSize: QSize):  # noqa: N802
        hue_s, _, px_s = id_.partition("x")
        try:
            hue = int(hue_s) % 360
        except ValueError:
            hue = 0
        try:
            px = int(px_s)
        except ValueError:
            px = 224
        n = max(64, min(224, px // 2))
        key = (hue, n)
        img = self._cache.get(key)
        if img is None:
            img = self._render(hue, n)
            self._cache[key] = img
            self._order.append(key)
            while len(self._order) > _MAX_CACHE:
                self._cache.pop(self._order.pop(0), None)
        size.setWidth(img.width())
        size.setHeight(img.height())
        del requestedSize  # the Image element scales the texture
        return img