"""Colors bridge: palette state over the SQLite core (colors pane, M3).

Thin adapter like bridges/fonts.py: the 5-swatch working palette lives in
memory (hex + locked), generation/edit math is core.colors, and saved
palettes persist in the library DB (palette / palette_color tables — the
0.x pane used per-pane server endpoints; same data, no server).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..core import colors as core_colors
from ..core import db as core_db
from ..core import settings


class Colors(QObject):
    message = Signal(str)
    exportDone = Signal(str)
    exportFailed = Signal(str)
    swatchesChanged = Signal()
    palettesChanged = Signal()
    selectionChanged = Signal()
    nameChanged = Signal()
    ruleChanged = Signal()

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        self._swatches: list[dict] = []
        self._rule = settings.get(con, "colors_rule", "pleasing")
        if self._rule not in core_colors.HARMONIES:
            self._rule = "pleasing"
        self._selected = -1
        self._name = ""
        self._palette_id: int | None = None
        self._refresh_palettes()
        # seed the pane with one roll so it never opens empty
        self._swatches = core_colors.generate(self._rule, [], mode="dark")

    # ---------------------------------------------------------------- state
    @Property("QVariantList", notify=swatchesChanged)
    def swatches(self) -> list:
        out = []
        for s in self._swatches:
            rgb = core_colors.hex2rgb(s["hex"])
            h, sat, li = core_colors.rgb2hsl(*rgb)
            cw = core_colors.contrast(rgb, (255, 255, 255))
            cb = core_colors.contrast(rgb, (16, 20, 24))
            out.append({
                "hex": s["hex"], "locked": s["locked"],
                "cw": round(cw, 1), "cb": round(cb, 1),
                "wcagW": core_colors.wcag_label(cw),
                "wcagB": core_colors.wcag_label(cb),
                "name": core_colors.color_name(s["hex"]),
                "ink": core_colors.best_ink(rgb),
                # editor sliders read these; set_hsl converts back
                "h": round(h), "s": round(sat), "l": round(li),
            })
        return out

    @Property(int, notify=selectionChanged)
    def selectedIdx(self) -> int:
        return self._selected

    @Property(str, notify=nameChanged)
    def paletteName(self) -> str:
        return self._name

    @Property(str, notify=ruleChanged)
    def rule(self) -> str:
        return self._rule

    @Property("QVariantList", notify=palettesChanged)
    def palettes(self) -> list:
        return self._palettes

    # ---------------------------------------------------------------- slots
    @Slot(str)
    def set_rule(self, rule: str) -> None:
        if rule not in core_colors.HARMONIES or rule == self._rule:
            return
        self._rule = rule
        settings.set(self._con, "colors_rule", rule)
        self.ruleChanged.emit()

    @Slot()
    def generate(self) -> None:
        self._swatches = core_colors.generate(self._rule, self._swatches)
        self.swatchesChanged.emit()

    @Slot(int)
    def toggle_lock(self, i: int) -> None:
        if 0 <= i < len(self._swatches):
            self._swatches[i]["locked"] = not self._swatches[i]["locked"]
            self.swatchesChanged.emit()

    @Slot(int)
    def remove_swatch(self, i: int) -> None:
        if 0 <= i < len(self._swatches) and len(self._swatches) > 2:
            del self._swatches[i]
            if self._selected >= len(self._swatches):
                self._selected = -1
                self.selectionChanged.emit()
            self.swatchesChanged.emit()

    @Slot(int, int)
    def move_swatch(self, frm: int, to: int) -> None:
        if (0 <= frm < len(self._swatches) and 0 <= to < len(self._swatches)
                and frm != to):
            moved = self._swatches.pop(frm)
            self._swatches.insert(to, moved)
            self.swatchesChanged.emit()

    @Slot(int, float, float, float)
    def set_hsl(self, i: int, h: float, s: float, l: float) -> None:
        if 0 <= i < len(self._swatches):
            rgb = core_colors.hsl2rgb(h, s, l)
            self._swatches[i]["hex"] = core_colors.rgb2hex(*rgb)
            self.swatchesChanged.emit()

    @Slot(int, str)
    def set_hex(self, i: int, hex_str: str) -> None:
        hex_str = (hex_str or "").strip()
        if not hex_str.startswith("#"):
            hex_str = "#" + hex_str
        if 0 <= i < len(self._swatches):
            try:
                core_colors.hex2rgb(hex_str)
            except ValueError:
                return  # half-typed hex — ignore until valid
            self._swatches[i]["hex"] = hex_str
            self.swatchesChanged.emit()

    @Slot(int)
    def select(self, i: int) -> None:
        i = -1 if i == self._selected else i
        self._selected = i
        self.selectionChanged.emit()

    @Slot(str)
    def set_name(self, name: str) -> None:
        self._name = name or ""
        self.nameChanged.emit()

    @Slot(str)
    def save(self, tags: str) -> None:
        hexes = [s["hex"] for s in self._swatches]
        if not hexes:
            self.message.emit("Nothing to save")
            return
        locks = [bool(s["locked"]) for s in self._swatches]
        name = self._name or "Untitled palette"
        self._palette_id = core_colors.save_palette(
            self._con, name, hexes, tags, self._palette_id, locked=locks)
        self._refresh_palettes()
        self.message.emit(f"Saved: {name}")

    @Slot(int)
    def open_palette(self, palette_id: int) -> None:
        rows = self._con.execute(
            "SELECT name FROM palette WHERE id = ?", (palette_id,)).fetchone()
        if rows is None:
            return
        self._swatches = core_colors.palette_colors(self._con, palette_id)
        self._selected = -1
        self._name = rows["name"]
        self._palette_id = palette_id
        self.swatchesChanged.emit()
        self.selectionChanged.emit()
        self.nameChanged.emit()

    @Slot(int)
    def delete_palette(self, palette_id: int) -> None:
        core_colors.delete_palette(self._con, palette_id)
        if self._palette_id == palette_id:
            self._palette_id = None
        self._refresh_palettes()
        self.message.emit("Palette deleted")

    @Slot(int)
    def new_from_palette(self, palette_id: int) -> None:
        # load as a copy: clears the id so Save creates a new row
        self.open_palette(palette_id)
        self._palette_id = None

    @Slot(str, str)
    def export(self, kind: str, dest_dir: str) -> None:
        if not dest_dir:
            self.exportFailed.emit("choose a folder first")
            return
        hexes = [s["hex"] for s in self._swatches]
        try:
            out = core_colors.write_exports(self._name or "Untitled palette",
                                            hexes, dest_dir, kind)
        except (ValueError, OSError) as e:
            self.exportFailed.emit(str(e))
            return
        self.exportDone.emit(str(out))

    # ------------------------------------------------------------ internals
    def _refresh_palettes(self) -> None:
        self._palettes = core_colors.list_palettes(self._con)
        self.palettesChanged.emit()
