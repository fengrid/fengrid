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
from ..core import paths as core_paths
from ..core import settings


_MAX_SWATCHES = 7


class Colors(QObject):
    message = Signal(str)
    exportDone = Signal(str)
    exportFailed = Signal(str)
    swatchesChanged = Signal()
    palettesChanged = Signal()
    selectionChanged = Signal()
    nameChanged = Signal()
    ruleChanged = Signal()
    presetCountChanged = Signal()

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        self._swatches: list[dict] = []
        self._rule = settings.get(con, "colors_rule", "pleasing")
        if self._rule not in core_colors.GENERATION_MODES:
            self._rule = "pleasing"
        self._selected = -1
        self._name = ""
        self._palette_id: int | None = None
        # increments on every Generate press — feeds core generate()'s
        # variation seed so repeated presses always yield fresh unlocked
        # colors (anchor rotation + seeded jitter), even with locks present
        self._variation = 0
        # optional collection filter for the side rail (palette kind)
        self._collection: int | None = None
        self._starred_only = False
        # saved-library tag filter (rail Libraries row on this pane):
        # comma tag list + match_all, filtered in Python over row["tags"]
        self._lib_tags: list[str] = []
        self._lib_match_all = True
        # #141: palettes filed from applied Preset Libraries presets
        self._preset_count = 0
        # active smart collection (sidebar) — criteria filtered in Python
        self._smart_id = 0
        # optional undo bridge (projects.bind_source_control pattern):
        # every editor-scale mutation snapshots the swatch list so
        # Ctrl+Z can walk it back (spec: undo for fields/options)
        self._undo_ref = None
        self._refresh_palettes()
        # seed the pane with one roll so it never opens empty
        self._swatches = core_colors.generate(self._rule, [], mode="dark")

    # ---------------------------------------------------------------- undo
    def bind_undo(self, undo) -> None:
        self._undo_ref = undo

    def _snapshot(self) -> dict:
        return {
            "swatches": [dict(s) for s in self._swatches],
            "name": self._name,
            "pid": self._palette_id,
        }

    def restore_state(self, snap: dict) -> None:
        self._swatches = [dict(s) for s in snap.get("swatches", [])]
        self._name = snap.get("name", "") or ""
        self._palette_id = snap.get("pid")
        self._selected = -1
        self.swatchesChanged.emit()
        self.nameChanged.emit()
        self.selectionChanged.emit()

    def _begin(self):
        return self._snapshot() if self._undo_ref is not None else None

    def _end(self, pre, label: str, match: str | None = None) -> None:
        if pre is None or self._undo_ref is None:
            return
        post = self._snapshot()
        if match:
            self._undo_ref.push_coalesce("colors.editor", label, post,
                                         pre, match=match)
        else:
            self._undo_ref.push("colors.editor", label, post, pre)

    # ---------------------------------------------------------------- state
    @Property("QVariantList", notify=swatchesChanged)
    def swatches(self) -> list:
        out = []
        for s in self._swatches:
            rgb = core_colors.hex2rgb(s["hex"])
            h, sat, li = core_colors.rgb2hsl(*rgb)
            cw = core_colors.contrast(rgb, (255, 255, 255))
            cb = core_colors.contrast(rgb, (16, 20, 24))
            # #25: the lock glyph is tinted amber on locked swatches —
            # amber on a pale swatch (Wheat ~1.1:1) is invisible, so the
            # lock tint falls back to the swatch's best ink when amber
            # cannot read
            amber = core_colors.contrast(rgb, (245, 194, 92))
            out.append({
                "hex": s["hex"], "locked": s["locked"],
                "cw": round(cw, 1), "cb": round(cb, 1),
                "wcagW": core_colors.wcag_label(cw),
                "wcagB": core_colors.wcag_label(cb),
                "name": core_colors.color_name(s["hex"]),
                "ink": core_colors.best_ink(rgb),
                "lock_ink": "#F5C25C" if amber >= 3.0
                else core_colors.best_ink(rgb),
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

    @Property(int, notify=palettesChanged)
    def paletteId(self) -> int:
        """The working palette's saved row id (-1 when unsaved) — the
        Properties panel targets this for tags/fields/links."""
        return self._palette_id if self._palette_id is not None else -1

    @Property(str, notify=palettesChanged)
    def collectionFilter(self) -> str:
        return "" if self._collection is None else str(self._collection)

    @Property(str, notify=palettesChanged)
    def smartFilter(self) -> str:
        return "" if not self._smart_id else str(self._smart_id)

    @Slot(str)
    def set_smart(self, sc_id: str) -> None:
        """Toggle the sidebar smart-collection filter (palette kind)."""
        sid = int(sc_id) if str(sc_id).strip().isdigit() else 0
        if sid and sid == self._smart_id:
            sid = 0
        self._smart_id = sid
        self._refresh_palettes()

    # ---------------------------------------------------------------- slots
    @Slot(str)
    def set_rule(self, rule: str) -> None:
        if rule not in core_colors.GENERATION_MODES or rule == self._rule:
            return
        self._rule = rule
        settings.set(self._con, "colors_rule", rule)
        self.ruleChanged.emit()

    @Slot(str)
    def set_collection(self, coll: str) -> None:
        """Toggle the side-rail collection filter (palette kind)."""
        s = (coll or "").strip()
        cid = int(s) if s.isdigit() else None
        if cid is None or cid == self._collection:
            self._collection = None
        else:
            self._collection = cid
        self._starred_only = False
        self.starredOnlyChanged.emit()
        self._refresh_palettes()

    # ── starred rail row: filter the pane to starred palettes ──
    starredOnlyChanged = Signal()

    @Property(bool, notify=starredOnlyChanged)
    def starredOnly(self) -> bool:
        return self._starred_only

    # ── saved-library tag filter (rail Libraries row, palette pane) ──
    libTagsChanged = Signal()

    @Property(str, notify=libTagsChanged)
    def libraryTagFilter(self) -> str:
        return ",".join(self._lib_tags)

    # #141: palettes filed by applying a Preset Libraries palette
    # preset (tagged 'preset') — the rail's Saved Presets row counts
    # and browses them on the Colors pane
    @Property(int, notify=presetCountChanged)
    def presetPaletteCount(self) -> int:
        return self._preset_count

    @Slot(str, bool)
    def set_library_tags(self, tags_csv: str, match_all: bool = True) -> None:
        """Toggle the library-view tag filter on this pane (second call
        with the same list clears it)."""
        wanted = [t.strip() for t in str(tags_csv or "").split(",")
                  if t.strip()]
        if wanted and wanted == self._lib_tags:
            wanted = []
        self._lib_tags = wanted
        self._lib_match_all = bool(match_all)
        self.libTagsChanged.emit()
        self._refresh_palettes()

    @Slot(bool)
    def set_starred_only(self, on: bool) -> None:
        on = bool(on)
        if on == self._starred_only:
            return
        self._starred_only = on
        if on:
            self._collection = None
        self.starredOnlyChanged.emit()
        self._refresh_palettes()

    @Slot()
    def generate(self) -> None:
        pre = self._begin()
        self._variation += 1
        self._swatches = core_colors.generate(
            self._rule, self._swatches, variation=self._variation)
        self._end(pre, "Re-roll colors")
        self.swatchesChanged.emit()

    @Slot(int)
    def toggle_lock(self, i: int) -> None:
        if 0 <= i < len(self._swatches):
            self._swatches[i]["locked"] = not self._swatches[i]["locked"]
            self.swatchesChanged.emit()

    @Slot()
    def add_swatch(self) -> None:
        """Append one unlocked swatch — hue rotates by the golden angle
        off the last color so additions harmonize. Schemes default to 5
        colors and accept up to 7."""
        if len(self._swatches) >= _MAX_SWATCHES:
            self.message.emit("A color scheme holds at most"
                              f" {_MAX_SWATCHES} colors")
            return
        pre = self._begin()
        base = (self._swatches[-1]["hex"] if self._swatches
                else "#3388cc")
        h, s, l = core_colors.rgb2hsl(*core_colors.hex2rgb(base))
        nh = (h + 137.5 * (len(self._swatches) + 1)) % 360
        self._swatches.append({
            "hex": core_colors.rgb2hex(
                *core_colors.hsl2rgb(nh, s or 62, l or 50)),
            "locked": False})
        self._selected = len(self._swatches) - 1
        self._end(pre, "Add swatch")
        self.selectionChanged.emit()
        self.swatchesChanged.emit()

    @Slot(int)
    def remove_swatch(self, i: int) -> None:
        if 0 <= i < len(self._swatches) and len(self._swatches) > 2:
            pre = self._begin()
            del self._swatches[i]
            if self._selected >= len(self._swatches):
                self._selected = -1
                self.selectionChanged.emit()
            self._end(pre, "Remove swatch")
            self.swatchesChanged.emit()

    @Slot(int, int)
    def move_swatch(self, frm: int, to: int) -> None:
        if (0 <= frm < len(self._swatches) and 0 <= to < len(self._swatches)
                and frm != to):
            pre = self._begin()
            moved = self._swatches.pop(frm)
            self._swatches.insert(to, moved)
            self._end(pre, "Reorder swatches")
            self.swatchesChanged.emit()

    @Slot(int, float, float, float)
    def set_hsl(self, i: int, h: float, s: float, l: float) -> None:
        if 0 <= i < len(self._swatches):
            pre = self._begin()
            rgb = core_colors.hsl2rgb(h, s, l)
            self._swatches[i]["hex"] = core_colors.rgb2hex(*rgb)
            # coalesced: a slider drag is ONE undo step, not 60
            self._end(pre, f"Adjust swatch {i + 1}", match=f"hsl:{i}")
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
            pre = self._begin()
            self._swatches[i]["hex"] = hex_str
            self._end(pre, f"Set swatch {i + 1}", match=f"hex:{i}")
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
        # keep item_tag in sync with the editor's CSV tags (single
        # source of truth going forward)
        if self._palette_id:
            core_db._sync_item_tags(self._con, self._palette_id,
                                    "palette", tags)
        self._refresh_palettes()
        self.message.emit(f"Saved: {name}")

    @Slot(str)
    def save_as_preset(self, name: str) -> None:
        """#141: file an applied palette preset — save (or update, when
        a palette of that preset name already exists) the working
        swatches as a palette tagged 'preset', so it lands in the
        Colors pane's list and the rail's Saved Presets row can count
        and browse it. Automatic: applying a preset from the Preset
        Libraries dialog needs no further user action."""
        name = (name or "").strip() or "Preset palette"
        hexes = [s["hex"] for s in self._swatches]
        if not hexes:
            return
        existing = self._con.execute(
            "SELECT id FROM palette WHERE name = ?", (name,)).fetchone()
        pid = existing["id"] if existing else None
        self._palette_id = core_colors.save_palette(
            self._con, name, hexes, "preset", pid)
        core_db._sync_item_tags(self._con, self._palette_id,
                                "palette", "preset")
        self._name = name
        self.nameChanged.emit()
        self._refresh_palettes()
        self.message.emit(
            f"Applied {name} — saved to the Colors pane")

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
        # paletteId is the Properties panel's item target — its QML binding
        # re-evaluates on palettesChanged, which open_palette never fired
        # (save_palette did), so the panel stayed hidden for opened palettes
        self.palettesChanged.emit()

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

    @Slot("QVariantList")
    def load_hexes(self, hexes: list) -> None:
        """Load a list of hex strings into the working swatches (used by
        the preset bridge when a palette-kind preset entry is applied)."""
        clean = []
        for h in hexes:
            h = (h or "").strip()
            if not h.startswith("#"):
                h = "#" + h
            try:
                core_colors.hex2rgb(h)
                clean.append({"hex": h, "locked": False})
            except ValueError:
                continue
        if clean:
            self._swatches = clean
            self._palette_id = None
            self.swatchesChanged.emit()
            self.selectionChanged.emit()
            self.nameChanged.emit()
            self.palettesChanged.emit()

    @Slot(str, str)
    def export(self, kind: str, dest_dir: str) -> None:
        # #54: normalize any stray file:// URL to a plain local path
        # (same contract as the other folder-accepting bridges).
        dest_dir = core_paths.local_path(dest_dir or "")
        if not dest_dir:
            self.exportFailed.emit("choose a folder first")
            return
        hexes = [s["hex"] for s in self._swatches]
        try:
            out = core_colors.write_exports(self._name or "Untitled palette",
                                            hexes, dest_dir, kind)
        except (ValueError, OSError) as e:
            self.exportFailed.emit(f"{e} (destination: {dest_dir})")
            return
        self.exportDone.emit(str(out))

    # ------------------------------------------------------------ internals
    def _refresh_palettes(self) -> None:
        self._palettes = core_colors.list_palettes(
            self._con, collection_id=self._collection,
            starred_only=self._starred_only)
        if self._smart_id:
            self._palettes = [p for p in self._palettes
                              if _matches_smart(self._con, self._smart_id, p)]
        if self._lib_tags:
            self._palettes = [p for p in self._palettes
                              if _tags_match(p.get("tags"), self._lib_tags,
                                             self._lib_match_all)]
        # #141: palettes filed by applying a palette preset (tagged
        # 'preset') — feeds the rail's Saved Presets row
        n = self._con.execute(
            "SELECT COUNT(*) FROM palette p"
            " JOIN item_tag it ON it.item_id = p.id"
            " AND it.item_kind = 'palette'"
            " JOIN tag t ON t.id = it.tag_id"
            " WHERE t.name = 'preset'").fetchone()[0]
        if n != self._preset_count:
            self._preset_count = n
            self.presetCountChanged.emit()
        self.palettesChanged.emit()


def _tags_match(row_tags, wanted: list[str], match_all: bool) -> bool:
    """Comma-tag-string row vs library-view tag list (all/any)."""
    have = {t.strip().lower() for t in str(row_tags or "").split(",")
            if t.strip()}
    hits = [t.lower() in have for t in wanted]
    return all(hits) if match_all else any(hits)


def _matches_smart(con, smart_id: int, row: dict) -> bool:
    """Tag/q criteria match for a palette/snippet-style row (tags column)."""
    import json as _json
    r = con.execute("SELECT criteria FROM smart_collection WHERE id = ?",
                    (smart_id,)).fetchone()
    if r is None:
        return True
    try:
        crit = _json.loads(r["criteria"] or "{}")
    except ValueError:
        return True
    tags = [t.strip().lower() for t in crit.get("tags", []) if t.strip()]
    row_tags = [t.strip().lower() for t in (row.get("tags") or "").split(",")
                if t.strip()]
    if tags:
        hit = [t in row_tags for t in tags]
        if not (all(hit) if crit.get("tag_match_all") else any(hit)):
            return False
    if crit.get("q") and str(crit["q"]).lower() not in str(
            row.get("name") or row.get("title") or "").lower():
        return False
    return True
