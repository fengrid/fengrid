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

from ..app import DARK, LIGHT, ACCENTS  # noqa: F401  (re-exported for convenience)

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("module, not script")


class Theme(QObject):
    themeChanged = Signal()
    tokensChanged = Signal()
    accentChanged = Signal()

    def __init__(self, con, fonts_dir: str, parent=None):
        super().__init__(parent)
        self._con = con
        self._fonts_dir = fonts_dir
        self._dark = settings.get(con, "theme", "dark") != "light"
        self._families: set[str] = self._register_fonts(fonts_dir)
        # the user-chosen accent preset id (ACCENTS in app.py). "teal" is
        # the brand default; the stored value is validated on read so a
        # hand-edited row can never break the theme.
        self._accent = str(settings.get(con, "accent", "teal") or "teal")  # type: ignore[arg-type]
        if self._accent not in ACCENTS:
            self._accent = "teal"

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
        toks = {self._camel(k): v
                for k, v in (DARK if self._dark else LIGHT).items()}
        # the user-chosen accent overrides the brand token — both themes
        # (the preset carries a light-surface variant that keeps ≥4.5:1
        # on #F7F8F9; the dark value is the brand 0.x pane color)
        pair = ACCENTS.get(self._accent)
        if pair:
            toks["accent"] = pair[1] if self._dark else pair[2]
        return toks

    @Property(str, notify=accentChanged)
    def accent(self) -> str:
        return self._accent

    @Property("QVariantList", constant=True)
    def accentOptions(self) -> list:
        # [{id, name, dark, light}] — the Settings swatch row and the
        # first-run picker render these; the id is what set_accent stores
        return [{"id": k, "name": v[0], "dark": v[1], "light": v[2]}
                for k, v in ACCENTS.items()]

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
    @Slot(str)
    def set_accent(self, name: str) -> None:
        name = str(name or "").strip()
        if name not in ACCENTS or name == self._accent:
            return
        self._accent = name
        settings.set(self._con, "accent", name)
        self.accentChanged.emit()
        self.tokensChanged.emit()

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
