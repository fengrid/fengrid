"""Explorer bridge: Color palette scheme state for the Colors pane.

Owns the wheel explorer's configuration — scheme model, complementary
toggle, dist, base hue, the shared shade point (S/L) with per-color
overrides, freeform offsets, fine-tune deltas — and derives the palette
through core.color_explorer. State persists in a GLOBAL settings key
(JSON) and every user-scale mutation snapshots into the colors undo
bridge (handler "colors.explorer"), so Ctrl+Z walks wheel edits back
exactly like Harmonies-editor edits.

Drag slots (hue_drag / shade_drag) update state per mouse move WITHOUT
recording undo or persisting; end_drag() coalesces the gesture into one
undo step (the colors.py slider pattern).
"""

from __future__ import annotations

import json
import random

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ..core import color_explorer as core_ex
from ..core import colors as core_colors
from ..core import paths as core_paths
from ..core import settings

_SETTINGS_KEY = "colors_explorer"

_DEFAULTS = {
    "scheme": "mono",
    "add_comp": False,
    "dist": core_ex.DEFAULT_DIST,
    "base_h": 0.0,
    "s0": core_ex.DEFAULT_S,
    "l0": core_ex.DEFAULT_L,
    "free_offsets": [0.0],
    "free_count": 4,
    "overrides": [],
    "hue_overrides": [],
    "ft": {},
    "name": "",
}


class ColorExplorer(QObject):
    message = Signal(str)
    exportDone = Signal(str)
    exportFailed = Signal(str)
    stateChanged = Signal()
    nameChanged = Signal()

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self._con = con
        self._undo_ref = None
        state = dict(_DEFAULTS)
        try:
            stored = json.loads(settings.get(con, _SETTINGS_KEY, "") or "{}")
            if isinstance(stored, dict):
                state.update({k: v for k, v in stored.items()
                              if k in _DEFAULTS})
        except ValueError:
            pass
        if state["scheme"] not in core_ex.SCHEMES:
            state["scheme"] = "mono"
        self._scheme = state["scheme"]
        self._add_comp = bool(state["add_comp"])
        self._dist = float(state["dist"])
        self._base_h = float(state["base_h"]) % 360.0
        self._s0 = float(state["s0"])
        self._l0 = float(state["l0"])
        self._free_offsets = [float(o) for o in state["free_offsets"]] or [0.0]
        self._free_count = int(state["free_count"])
        self._overrides = [list(o) for o in state["overrides"]]
        self._hue_overrides = [float(o) for o in state["hue_overrides"]]
        self._ft = dict(state["ft"])
        self._name = str(state["name"] or "")
        self._palette_id = None

    # ------------------------------------------------------------- undo
    def bind_undo(self, undo) -> None:
        self._undo_ref = undo

    def _snapshot(self) -> dict:
        return {
            "scheme": self._scheme, "add_comp": self._add_comp,
            "dist": self._dist, "base_h": self._base_h,
            "s0": self._s0, "l0": self._l0,
            "free_offsets": list(self._free_offsets),
            "free_count": self._free_count,
            "overrides": [list(o) for o in self._overrides],
            "hue_overrides": list(self._hue_overrides),
            "ft": dict(self._ft), "name": self._name,
        }

    def restore_state(self, snap: dict) -> None:
        self._scheme = snap.get("scheme", "mono")
        self._add_comp = bool(snap.get("add_comp", False))
        self._dist = float(snap.get("dist", core_ex.DEFAULT_DIST))
        self._base_h = float(snap.get("base_h", 0.0)) % 360.0
        self._s0 = float(snap.get("s0", core_ex.DEFAULT_S))
        self._l0 = float(snap.get("l0", core_ex.DEFAULT_L))
        self._free_offsets = [float(o) for o in snap.get("free_offsets",
                                                         [0.0])] or [0.0]
        self._free_count = int(snap.get("free_count", 4))
        self._overrides = [list(o) for o in snap.get("overrides", [])]
        self._hue_overrides = [float(o)
                               for o in snap.get("hue_overrides", [])]
        self._ft = dict(snap.get("ft", {}))
        self._name = str(snap.get("name", "") or "")
        self._emit_all()

    def _begin(self):
        return self._snapshot() if self._undo_ref is not None else None

    def _end(self, pre, label: str, match: str | None = None) -> None:
        if pre is not None and self._undo_ref is not None:
            post = self._snapshot()
            if match:
                self._undo_ref.push_coalesce("colors.explorer", label, post,
                                             pre, match=match)
            else:
                self._undo_ref.push("colors.explorer", label, post, pre)
        self._persist()
        # every committed mutation re-renders the wheel/palette
        self.stateChanged.emit()

    def _persist(self) -> None:
        settings.set(self._con, _SETTINGS_KEY,
                     json.dumps(self._snapshot()))

    def _emit_all(self) -> None:
        self.stateChanged.emit()
        self.nameChanged.emit()

    # ---------------------------------------------------------- properties
    @Property(str, notify=stateChanged)
    def scheme(self) -> str:
        return self._scheme

    @Property(str, notify=stateChanged)
    def schemeLabel(self) -> str:
        if self._scheme == "freeform":
            return f"Free style - {self._free_count} colors"
        return core_ex.SCHEME_LABELS.get(self._scheme, self._scheme)

    @Property(bool, notify=stateChanged)
    def addComp(self) -> bool:
        return self._add_comp

    @Property(int, notify=stateChanged)
    def dist(self) -> int:
        return int(round(self._dist))

    @Property(int, notify=stateChanged)
    def freeCount(self) -> int:
        return self._free_count

    @Property(int, notify=stateChanged)
    def hueReadout(self) -> int:
        return int(round((self._base_h + float(self._ft.get("hue", 0) or 0))
                         % 360))

    @Property(str, notify=stateChanged)
    def baseHex(self) -> str:
        """The base color as configured — the wheel's base dot / the field."""
        cols = self._palette()
        return cols[0]["hex"] if cols else core_ex.DEFAULT_BASE_HEX

    @Property("QVariantList", notify=stateChanged)
    def colors(self) -> list:
        return self._palette()

    @Property("QVariantMap", notify=stateChanged)
    def fineTune(self) -> dict:
        return {k: float(self._ft.get(k, 0) or 0) for k in core_ex.FINE_ROWS}

    @Property(str, notify=nameChanged)
    def paletteName(self) -> str:
        return self._name

    @Property(int, notify=stateChanged)
    def paletteId(self) -> int:
        return self._palette_id if self._palette_id is not None else -1

    def _palette(self) -> list:
        return core_ex.build_palette(
            self._base_h, self._s0, self._l0, self._scheme,
            dist=self._dist, add_comp=self._add_comp,
            free_offsets=self._free_offsets, free_count=self._free_count,
            shade_overrides=self._overrides,
            hue_overrides=self._hue_overrides, ft=self._ft)

    @Slot(int, int, result="QVariant")
    def color_info(self, idx: int, ramp_idx: int = 2) -> dict:
        """Detail payload for the color info dialog — works for the main
        color (ramp_idx 2) and its ramp variants alike."""
        cols = self._palette()
        if not (0 <= idx < len(cols)):
            return {}
        c = cols[idx]
        ramp = c.get("ramp") or [c["hex"]] * 5
        hx = ramp[ramp_idx] if 0 <= ramp_idx < len(ramp) else c["hex"]
        rgb = core_colors.hex2rgb(hx)
        h, s, l = core_colors.rgb2hsl(*rgb)
        lab = core_ex.rgb2lab(rgb)
        cw = core_colors.contrast(rgb, (255, 255, 255))
        cb = core_colors.contrast(rgb, (16, 20, 24))
        return {
            "hex": hx.upper(),
            "name": core_colors.color_name(hx),
            "h": round(h), "s": round(s), "l": round(l),
            "r": rgb[0], "g": rgb[1], "b": rgb[2],
            "lab_l": round(lab[0], 1), "lab_a": round(lab[1], 1),
            "lab_b": round(lab[2], 1),
            "cw": round(cw, 1), "cb": round(cb, 1),
            "wcagW": core_colors.wcag_label(cw),
            "wcagB": core_colors.wcag_label(cb),
            "ink": core_colors.best_ink(rgb),
            "is_base": bool(c.get("is_base")) and ramp_idx == 2,
            "is_comp": bool(c.get("is_comp")) and ramp_idx == 2,
            "ramp_idx": int(ramp_idx),
        }

    @Slot(float, float, float)
    def set_base_hsl(self, h: float, s: float, l: float) -> None:
        """Promote an arbitrary final color (info dialog variants) to the
        base — its hue becomes the scheme anchor, its S/L the shared
        shade point (fine-tune deltas inverted out of the target)."""
        h, s, l = core_ex.invert_fine_tune(h, s, l, self._ft)
        pre = self._begin()
        self._base_h = h % 360.0
        self._s0 = s
        self._l0 = l
        self._overrides = []
        self._hue_overrides = []
        self._end(pre, "New base color")

    # --------------------------------------------------------------- slots
    @Slot(str)
    def set_scheme(self, scheme: str) -> None:
        if scheme not in core_ex.SCHEMES or scheme == self._scheme:
            return
        pre = self._begin()
        self._scheme = scheme
        if scheme == "freeform":
            # materialize the current offsets so dot drags edit real state
            self._free_offsets = core_ex.scheme_offsets(
                "freeform", free_offsets=self._free_offsets,
                free_count=self._free_count)
        self._overrides = []
        self._hue_overrides = []
        self._end(pre, "Scheme model")

    @Slot(bool)
    def set_add_comp(self, on: bool) -> None:
        on = bool(on)
        if on == self._add_comp:
            return
        pre = self._begin()
        self._add_comp = on
        self._overrides = []
        self._hue_overrides = []
        self._end(pre, "Complementary color")

    @Slot(int)
    def set_dist(self, dist: int) -> None:
        # triad's pair converges on the opposite point at 60° — beyond
        # that the two secondary dots would cross
        hi = 60 if self._scheme == "triad" else 90
        dist = max(0, min(hi, int(dist)))
        if dist == int(round(self._dist)):
            return
        self._dist = float(dist)
        self.stateChanged.emit()
        self._persist()

    @Slot(int)
    def set_free_count(self, n: int) -> None:
        lo, hi = core_ex.FREE_COUNT_RANGE
        n = max(lo, min(hi, int(n)))
        if n == self._free_count:
            return
        pre = self._begin()
        self._free_count = n
        self._free_offsets = core_ex.scheme_offsets(
            "freeform", free_offsets=self._free_offsets,
            free_count=self._free_count)
        self._overrides = []
        self._hue_overrides = []
        self._end(pre, "Free-style color count")

    @Slot(str)
    def set_base_hex(self, hex_str: str) -> None:
        hex_str = (hex_str or "").strip()
        if not hex_str.startswith("#"):
            hex_str = "#" + hex_str
        try:
            rgb = core_colors.hex2rgb(hex_str)
        except ValueError:
            return  # half-typed hex — ignore until valid
        h, s, l = core_colors.rgb2hsl(*rgb)
        h, s, l = core_ex.invert_fine_tune(h, s, l, self._ft)
        pre = self._begin()
        self._base_h = h % 360.0
        self._s0 = s
        self._l0 = l
        self._end(pre, "Base color")

    # ── wheel drags: per-move updates; end_drag records undo + persists ──
    # Plain drag on the base dot rotates the whole scheme so that dot
    # follows the mouse; plain drag on an outer dot adjusts its defined
    # Distance (per scheme + dot, see core.dist_for_drag); Shift+drag
    # moves ONE dot individually (its own hue offset / shade).
    @Slot(int, float, bool)
    def hue_drag(self, idx: int, angle: float, shift: bool) -> None:
        cols = self._palette()
        if not (0 <= idx < len(cols)):
            return
        dh = cols[idx]["dh"]
        if self._scheme == "freeform" and idx > 0 \
                and not cols[idx]["is_comp"]:
            # free style: every outer dot is individually placed
            self._materialize_free_offsets()
            self._free_offsets[idx] = (angle - self._base_h) % 360.0
            self.stateChanged.emit()
            return
        if shift and idx > 0:
            # Shift = this dot only: an individual hue offset off the
            # model's default position (freeform handled above)
            self._set_hue_override(idx,
                                   (angle - self._base_h - dh) % 360.0)
            self.stateChanged.emit()
            return
        if idx > 0 and not cols[idx]["is_comp"]:
            dist = core_ex.dist_for_drag(self._scheme, idx,
                                         self._base_h, angle)
            if dist is not None:
                # the dot's Distance is the dragged angle — the dot
                # re-docks to the model at the new dist
                self._dist = dist
                self._set_hue_override(idx, 0.0)
                self.stateChanged.emit()
                return
        # base dot — and dots without a dist parameter (tetrad's 180°
        # anchor, appended complementary dots) — rotate the whole scheme
        self._base_h = (angle - dh - self._hue_override_at(idx)) % 360.0
        self.stateChanged.emit()

    def _set_hue_override(self, idx: int, delta: float) -> None:
        while len(self._hue_overrides) <= idx:
            self._hue_overrides.append(0.0)
        self._hue_overrides[idx] = (delta + 180.0) % 360.0 - 180.0

    def _hue_override_at(self, idx: int) -> float:
        return self._hue_overrides[idx] if idx < len(self._hue_overrides) \
            else 0.0

    @Slot(float, float, bool, int)
    def shade_drag(self, s: float, l: float, shift: bool, idx: int) -> None:
        s = core_ex.clamp(s)
        l = core_ex.clamp(l)
        if shift and 0 <= idx < len(self._palette()):
            while len(self._overrides) <= idx:
                self._overrides.append([0.0, 0.0])
            self._overrides[idx] = [core_ex.clamp(s - self._s0, -self._s0,
                                                  100.0 - self._s0),
                                    core_ex.clamp(l - self._l0, -self._l0,
                                                  100.0 - self._l0)]
        else:
            self._s0 = s
            self._l0 = l
        self.stateChanged.emit()

    # ── drag bookkeeping: QML calls begin_drag() at press, commit_drag()
    # at release (one coalesced undo step per gesture) or cancel_drag()
    # when nothing moved ──
    @Slot()
    def begin_drag(self) -> None:
        self._drag_pre = self._snapshot() if self._undo_ref is not None \
            else None

    @Slot()
    def cancel_drag(self) -> None:
        self._drag_pre = None

    @Slot(str)
    def commit_drag(self, label: str) -> None:
        pre = getattr(self, "_drag_pre", None)
        self._drag_pre = None
        if pre is None or self._undo_ref is None or self._snapshot() == pre:
            self._persist()
            return
        post = self._snapshot()
        self._undo_ref.push_coalesce("colors.explorer", label, post, pre,
                                     match="wheel:" + label)
        self._persist()

    def _materialize_free_offsets(self) -> None:
        self._free_offsets = core_ex.scheme_offsets(
            "freeform", free_offsets=self._free_offsets,
            free_count=self._free_count)

    @Slot(int)
    def apply_preset(self, idx: int) -> None:
        if not (0 <= idx < len(core_ex.PRESETS)):
            return
        name, s, l = core_ex.PRESETS[idx]
        pre = self._begin()
        self._s0 = float(s)
        self._l0 = float(l)
        self._overrides = []
        self._hue_overrides = []
        self._end(pre, f"Preset: {name}")

    @Slot(str, int)
    def fine_tune(self, row: str, step: int) -> None:
        if row not in core_ex.FINE_ROWS or not step:
            return
        pre = self._begin()
        cur = float(self._ft.get(row, 0) or 0)
        self._ft[row] = cur + step
        self._end(pre, f"Fine tune {row}", match=f"ft:{row}")

    @Slot()
    def reset_fine_tune(self) -> None:
        if not self._ft:
            return
        pre = self._begin()
        self._ft = {}
        self._end(pre, "Reset fine tune")

    @Slot()
    def randomize(self) -> None:
        pre = self._begin()
        h, s, l = core_ex.random_base(random.Random())
        self._base_h = h
        self._s0 = s
        self._l0 = l
        self._end(pre, "Randomize palette")

    @Slot()
    def reset(self) -> None:
        pre = self._begin()
        self._scheme = "mono"
        self._add_comp = False
        self._dist = core_ex.DEFAULT_DIST
        self._base_h = 0.0
        self._s0 = core_ex.DEFAULT_S
        self._l0 = core_ex.DEFAULT_L
        self._free_offsets = [0.0]
        self._free_count = 4
        self._overrides = []
        self._hue_overrides = []
        self._ft = {}
        self._end(pre, "Reset explorer")

    @Slot(int)
    def set_as_base(self, idx: int) -> None:
        """Color info dialog: promote a palette color to the base."""
        cols = self._palette()
        if not (0 <= idx < len(cols)):
            return
        c = cols[idx]
        self.set_base_hsl(c["h"], c["s"], c["l"])

    @Slot(str)
    def set_name(self, name: str) -> None:
        self._name = name or ""
        self.nameChanged.emit()

    @Slot(str)
    def copy_value(self, text: str) -> None:
        """Copy a color value (info dialog rows) to the clipboard."""
        QGuiApplication.clipboard().setText(str(text))
        self.message.emit("Copied to clipboard")

    @Slot(str)
    def save(self, tags: str) -> None:
        cols = self._palette()
        if not cols:
            self.message.emit("Nothing to save")
            return
        hexes = [c["hex"] for c in cols]
        name = self._name or "Untitled palette"
        self._palette_id = core_colors.save_palette(
            self._con, name, hexes, tags, self._palette_id)
        if self._palette_id:
            core_db_sync(self._con, self._palette_id, tags)
        self.message.emit(f"Saved: {name}")

    @Slot(str, str)
    def export(self, kind: str, dest_dir: str) -> None:
        dest_dir = core_paths.local_path(dest_dir or "")
        if not dest_dir:
            self.exportFailed.emit("choose a folder first")
            return
        cols = self._palette()
        hexes = [c["hex"] for c in cols]
        try:
            out = core_colors.write_exports(self._name or "Untitled palette",
                                            hexes, dest_dir, kind)
        except (ValueError, OSError) as e:
            self.exportFailed.emit(f"{e} (destination: {dest_dir})")
            return
        self.exportDone.emit(str(out))


def core_db_sync(con, palette_id: int, tags: str) -> None:
    """Keep item_tag in sync with the editor's CSV tags (colors.save does
    this through core.db._sync_item_tags — same contract here)."""
    from ..core import db as core_db
    core_db._sync_item_tags(con, palette_id, "palette", tags)
