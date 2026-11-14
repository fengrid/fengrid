"""QQuickImageProvider serving the scheme-selector sprites, theme-remapped.

The vendored sprite sheet (qt/resources/icons/sprites.png) carries the
eight scheme-model icons in two states (idle / selected) as dark
artwork. Raw pixels only read on the dark theme — a #323232 disc
vanishes on the light one — so this provider remaps each sprite's two
luminance bands (body < 56, details ≥ 56) onto theme-token grays per
(theme, state) and serves the result as `image://fgscheme/<id>`:

    scheme-<design 0..7>-<idle|sel>-<dark|light>

Design order on the sheet row: mono, complementary, adjacent,
adjacent+complementary, triad, triad+complementary, tetrad, freeform.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

_SHEET_Y = 71
_CELL = 38
_CELL_STEP = 40
_FIRST_X = 1

# (body, detail) per (theme, state) — Fengrid brand tokens. The light
# idle body must clearly read against the white surface (the first
# light pass used #DFE5EA and the discs vanished). The dark SELECTED
# body must also read against the pane surface (~#161B21): the first
# dark sel pass used #101418 and the active disc vanished into the
# background — only its details and a half-occluded ring survived.
_REMAPS = {
    ("dark", "idle"): ("#262C33", "#8B97A1"),
    ("dark", "sel"): ("#262C33", "#E7EDF2"),
    ("light", "idle"): ("#C6CED4", "#46505A"),
    ("light", "sel"): ("#16202B", "#F7F8F9"),
}

_LUM_SPLIT = 56


class SchemeSpriteProvider(QQuickImageProvider):
    def __init__(self, sheet_path: str):
        super().__init__(QQuickImageProvider.Image)
        self._sheet_path = sheet_path
        self._sheet: QImage | None = None
        self._cache: dict[str, QImage] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ internals
    def _sheet_image(self) -> QImage:
        if self._sheet is None:
            img = QImage(self._sheet_path)
            if img.isNull():
                # transparent stand-in keeps QML warning-free if the
                # asset ever goes missing (frozen builds ship it)
                img = QImage(_CELL, _CELL, QImage.Format.Format_ARGB32)
                img.fill(0)
            self._sheet = img
        return self._sheet

    def _sprite(self, design: int) -> QImage:
        sheet = self._sheet_image()
        x = _FIRST_X + design * _CELL_STEP
        y = _SHEET_Y
        x = max(0, min(x, sheet.width() - _CELL))
        y = max(0, min(y, sheet.height() - _CELL))
        return sheet.copy(x, y, _CELL, _CELL)

    def _remapped(self, design: int, state: str, theme_name: str) -> QImage:
        body_hex, detail_hex = _REMAPS[(theme_name, state)]
        body = _qcolor_rgba(body_hex)
        detail = _qcolor_rgba(detail_hex)
        src = self._sprite(design)
        out = QImage(src.size(), QImage.Format.Format_ARGB32)
        out.fill(0)
        for yy in range(src.height()):
            for xx in range(src.width()):
                px = src.pixel(xx, yy)
                a = (px >> 24) & 0xFF
                if a == 0:
                    continue
                r, g, b = (px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF
                lum = (r * 299 + g * 587 + b * 114) // 1000
                target = body if lum < _LUM_SPLIT else detail
                nr, ng, nb = target
                out.setPixel(xx, yy, (a << 24) | (nr << 16) | (ng << 8) | nb)
        return out

    # ------------------------------------------------------- QQuickImageProvider
    def requestImage(self, _id: str, size: QSize, requestedSize: QSize):  # noqa: N802
        try:
            parts = _id.split("-")
            design = max(0, min(7, int(parts[1])))
            state = parts[2] if len(parts) > 2 else "idle"
            theme_name = parts[3] if len(parts) > 3 else "dark"
            if state not in ("idle", "sel"):
                state = "idle"
            if theme_name not in ("dark", "light"):
                theme_name = "dark"
        except (ValueError, IndexError):
            design, state, theme_name = 0, "idle", "dark"
        key = f"{design}-{state}-{theme_name}"
        with self._lock:
            img = self._cache.get(key)
            if img is None:
                img = self._remapped(design, state, theme_name)
                self._cache[key] = img
        size.setWidth(img.width())
        size.setHeight(img.height())
        del requestedSize  # native 38px render; the UI never upscales
        return img


def _qcolor_rgba(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
