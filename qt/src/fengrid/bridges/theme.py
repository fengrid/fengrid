"""Theme bridge: brand tokens + application-font families for QML.

Fonts are registered once at startup via QFontDatabase.addApplicationFont
(see __main__.py); QML never hardcodes a family name — it reads
theme.headingFont / uiFont / monoFont. Family names are discovered
dynamically from the registered set because bundled files can register
under non-obvious names (e.g. a style-specific "Roboto Mono Medium").
"""

from __future__ import annotations

import os

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QFontDatabase

from .. import __version__
from ..core import db as core_db
from ..core import settings

from ..app import DARK, LIGHT  # noqa: F401  (re-exported for convenience)

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("module, not script")


class Theme(QObject):
    themeChanged = Signal()
    tokensChanged = Signal()

    def __init__(self, con, fonts_dir: str, parent=None):
        super().__init__(parent)
        self._con = con
        self._fonts_dir = fonts_dir
        self._dark = settings.get(con, "theme", "dark") != "light"
        self._families: set[str] = self._register_fonts(fonts_dir)

    # -- fonts ---------------------------------------------------------------
    @staticmethod
    def _register_fonts(fonts_dir: str) -> set[str]:
        fams: set[str] = set()
        if not os.path.isdir(fonts_dir):
            return fams
        for fn in sorted(os.listdir(fonts_dir)):
            if not fn.lower().endswith((".ttf", ".otf")):
                continue
            fid = QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fn))
            if fid != -1:
                fams.update(QFontDatabase.applicationFontFamilies(fid))
        return fams

    def _pick(self, preferred: list[str]) -> str:
        for name in preferred:
            if name in self._families:
                return name
        return preferred[-1]

    # -- tokens ----------------------------------------------------------------
    @staticmethod
    def _camel(key: str) -> str:
        # The QVariantMap is consumed from QML, which is camelCase; convert
        # once here at the export boundary so app.py stays idiomatic
        # snake_case Python (text_muted -> textMuted, lit_pane -> litPane;
        # keys without underscores like surface2 pass through unchanged).
        parts = key.split("_")
        return parts[0] + "".join(p.capitalize() for p in parts[1:])

    @Property("QVariantMap", notify=tokensChanged)
    def tokens(self) -> dict:
        return {self._camel(k): v
                for k, v in (DARK if self._dark else LIGHT).items()}

    @Property(bool, notify=themeChanged)
    def isDark(self) -> bool:
        return self._dark

    @Property(str, notify=themeChanged)
    def themeName(self) -> str:
        return "dark" if self._dark else "light"

    @Property(str, constant=True)
    def headingFont(self) -> str:
        # Bebas Neue: single weight, caps-only — headings only (v1 decision
        # 2026-10-19; see docs/review §4 / branding/fengrid-brand.md)
        return self._pick(["Bebas Neue", "Inter"])

    @Property(str, constant=True)
    def uiFont(self) -> str:
        return self._pick(["Inter", "DejaVu Sans"])

    @Property(str, constant=True)
    def monoFont(self) -> str:
        # Roboto Mono: wider glyphs + larger x-height than the previously
        # bundled Iosevka, which read as cramped at the UI's small pixel
        # sizes (user report 2026-10-20). "Roboto Mono Medium" is the
        # style-specific family the Medium static TTF registers.
        return self._pick(["Roboto Mono", "Roboto Mono Medium",
                           "Source Code Pro", "Noto Sans Mono",
                           "DejaVu Sans Mono"])

    @Property(str, constant=True)
    def appVersion(self) -> str:
        return __version__

    # -- slots -------------------------------------------------------------------
    @Slot()
    def toggle(self) -> None:
        self.set_theme("light" if self._dark else "dark")

    @Slot(str)
    def set_theme(self, name: str) -> None:
        dark = name != "light"
        if dark == self._dark:
            return
        self._dark = dark
        settings.set(self._con, "theme", "dark" if dark else "light")
        self.themeChanged.emit()
        self.tokensChanged.emit()
