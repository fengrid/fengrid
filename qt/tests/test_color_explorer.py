"""Explorer tab (Color palette wheel) core + bridge tests.

Covers the scheme offset math (the reference layouts), the
complementary append/dup-guard, shade ramps, fine-tune application and
its inversion, CIELAB, and the bridge's state machine: drags, presets,
undo snapshots (the same UndoBridge contract __main__ registers) and
the GLOBAL settings persistence roundtrip.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from PySide6.QtCore import QObject  # noqa: E402

from fengrid.core import color_explorer as ce  # noqa: E402
from fengrid.core import db as core_db  # noqa: E402
from fengrid.core import settings as settings_mod  # noqa: E402
from fengrid.bridges.color_explorer import ColorExplorer  # noqa: E402
from fengrid.bridges.undo import UndoBridge  # noqa: E402


# ------------------------------------------------------------------ offsets
def test_scheme_offsets_reference_layouts():
    assert ce.scheme_offsets("mono") == [0.0]
    # adjacent: base ± dist
    assert ce.scheme_offsets("adjacent", 30) == [0.0, 30.0, -30.0]
    # triad converges toward the opposite point as dist grows
    assert ce.scheme_offsets("triad", 30) == [0.0, 150.0, 210.0]
    assert ce.scheme_offsets("triad", 60) == [0.0, 180.0, 180.0]
    # tetrad: two complementary pairs offset by dist
    assert ce.scheme_offsets("tetrad", 30) == [0.0, 30.0, 180.0, 210.0]
    # freeform keeps user offsets, first pinned at 0
    assert ce.scheme_offsets("freeform", free_offsets=[10.0, 200.0],
                             free_count=2) == [0.0, 190.0]


def test_dist_for_drag_per_dot_inverse():
    # adjacent: either outer dot's angle sets |dist| (either side)
    assert ce.dist_for_drag("adjacent", 1, 0.0, 40.0) == pytest.approx(40)
    assert ce.dist_for_drag("adjacent", 2, 0.0, 330.0) == pytest.approx(30)
    # triad: dot 1 rides 120+dist, dot 2 rides 240-dist
    assert ce.dist_for_drag("triad", 1, 0.0, 150.0) == pytest.approx(30)
    assert ce.dist_for_drag("triad", 2, 0.0, 210.0) == pytest.approx(30)
    # tetrad: dot 1 rides +dist, dot 3 rides 180+dist; the 180° anchor
    # (dot 2) has no dist parameter
    assert ce.dist_for_drag("tetrad", 1, 0.0, 30.0) == pytest.approx(30)
    assert ce.dist_for_drag("tetrad", 3, 0.0, 210.0) == pytest.approx(30)
    assert ce.dist_for_drag("tetrad", 2, 0.0, 180.0) is None
    # mono has no outer dots; appended comp dots have no dist either
    assert ce.dist_for_drag("mono", 1, 0.0, 180.0) is None
    assert ce.dist_for_drag("adjacent", 3, 0.0, 180.0) is None


def test_scheme_offsets_grow_by_golden_angle():
    offs = ce.scheme_offsets("freeform", free_offsets=[0.0], free_count=3)
    assert len(offs) == 3
    assert offs[0] == 0.0
    assert offs[1] == pytest.approx(137.5)
    assert offs[2] == pytest.approx((137.5 * 2) % 360)


# ------------------------------------------------------------------ palette
def test_build_palette_mono_ramp_and_flags():
    cols = ce.build_palette(0, 50.2, 44.9, "mono")
    assert len(cols) == 1
    base = cols[0]
    assert base["is_base"] is True
    assert base["hex"] == "#ac3939"
    # ramp: light → base → dark, monotonically in L
    from fengrid.core import colors as core_colors
    ramp_l = [core_colors.rgb2hsl(*_hex2rgb(hx))[2] for hx in base["ramp"]]
    assert ramp_l[0] > ramp_l[1] > ramp_l[2] > ramp_l[3] > ramp_l[4]
    assert base["ramp"][2] == base["hex"]


def _hex2rgb(hx):
    h = hx.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def test_complementary_append_and_dup_guard():
    # adjacent gains a 4th color at the opposite hue
    cols = ce.build_palette(0, 50, 50, "adjacent", dist=30, add_comp=True)
    assert len(cols) == 4
    assert cols[-1]["is_comp"] is True
    assert cols[-1]["h"] == pytest.approx(180.0)
    # tetrad already anchors the opposite point — no duplicate
    cols = ce.build_palette(0, 50, 50, "tetrad", dist=30, add_comp=True)
    assert len(cols) == 4
    assert not any(c["is_comp"] for c in cols)
    # triad at dist 60 puts both secondaries ON the opposite point —
    # the guard skips the append (no duplicate), colors stay 3
    cols = ce.build_palette(0, 50, 50, "triad", dist=60, add_comp=True)
    assert len(cols) == 3
    assert cols[1]["h"] == pytest.approx(180.0)
    assert cols[2]["h"] == pytest.approx(180.0)


def test_shade_overrides_move_single_color():
    cols = ce.build_palette(0, 50, 50, "adjacent", dist=30,
                            shade_overrides=[[0, 0], [0, 20], [0, -20]])
    assert cols[0]["l"] == pytest.approx(50.0)
    assert cols[1]["l"] == pytest.approx(70.0)
    assert cols[2]["l"] == pytest.approx(30.0)
    # hues untouched by shade overrides
    assert cols[1]["h"] == pytest.approx(30.0)


# ---------------------------------------------------------------- fine tune
def test_fine_tune_apply_and_invert_roundtrip():
    ft = {"hue": 15, "sat": 10, "bright": -5, "contrast": 20}
    h, s, l = ce.apply_fine_tune(0, 50, 50, ft)
    assert h == pytest.approx(15)
    assert s == pytest.approx(60)
    # contrast spreads 50 around 50 → still 50, then brightness −5
    assert l == pytest.approx(45)
    rh, rs, rl = ce.invert_fine_tune(h, s, l, ft)
    assert rh == pytest.approx(0)
    assert rs == pytest.approx(50)
    assert rl == pytest.approx(50)


def test_fine_tune_contrast_spreads_light_and_dark():
    ft = {"contrast": 50}   # k = 1.5
    _, _, l_light = ce.apply_fine_tune(0, 50, 80, ft)
    _, _, l_dark = ce.apply_fine_tune(0, 50, 20, ft)
    assert l_light == pytest.approx(95)
    assert l_dark == pytest.approx(5)


# --------------------------------------------------------------------- lab
def test_rgb2lab_reference_points():
    assert ce.rgb2lab((255, 255, 255)) == pytest.approx((100, 0, 0),
                                                        abs=0.5)
    r, g, b = ce.rgb2lab((255, 0, 0))
    assert r == pytest.approx(53.2, abs=0.5)
    assert g == pytest.approx(80.1, abs=1.0)
    assert b == pytest.approx(67.2, abs=1.0)
    assert ce.rgb2lab((0, 0, 0))[0] == pytest.approx(0)


# ------------------------------------------------------------------ presets
def test_presets_grid_is_24_named_styles():
    assert len(ce.PRESETS) == 24
    names = [p[0] for p in ce.PRESETS]
    assert names[0] == "Lightest Pale Pastel"
    assert names[11] == "Dark Neon"
    assert names[-1] == "Greyish lightest"
    for _, s, l in ce.PRESETS:
        assert 0 <= s <= 100 and 0 <= l <= 100


# ------------------------------------------------------------------- bridge
@pytest.fixture()
def explorer(tmp_path):
    con = core_db.connect(tmp_path / "t.db")
    bridge = ColorExplorer(con)
    undo = UndoBridge("colors")
    undo.register("colors.explorer",
                  lambda d: bridge.restore_state(d),
                  lambda d: bridge.restore_state(d))
    bridge.bind_undo(undo)
    yield {"bridge": bridge, "con": con, "undo": undo}


def test_bridge_defaults_match_reference(explorer):
    b = explorer["bridge"]
    assert b.scheme == "mono"
    assert b.schemeLabel == "Monochromatic (1-color)"
    assert b.baseHex.lower() == "#ac3939"
    assert len(b.colors) == 1
    assert b.colors[0]["is_base"] is True


def test_bridge_scheme_switch_and_comp(explorer):
    b = explorer["bridge"]
    b.set_scheme("adjacent")
    assert len(b.colors) == 3
    b.set_add_comp(True)
    assert len(b.colors) == 4
    assert b.colors[3]["is_comp"] is True
    b.set_scheme("tetrad")
    b.set_add_comp(False)
    b.set_add_comp(True)
    assert len(b.colors) == 4   # dup guard — tetrad already spans 180°


def test_hue_drag_rotates_whole_scheme(explorer):
    b = explorer["bridge"]
    b.set_scheme("adjacent")
    b.set_dist(30)
    before = [c["h"] for c in b.colors]
    b.begin_drag()
    b.hue_drag(0, 100.0, False)
    b.commit_drag("Wheel hue")
    after = [c["h"] for c in b.colors]
    # every hue shifted by the same delta (100° from base 0)
    for bf, af in zip(before, after):
        assert (af - bf) % 360 == pytest.approx(100)
    assert b.hueReadout == 100


def test_hue_drag_shift_freeform_moves_one_color(explorer):
    b = explorer["bridge"]
    b.set_scheme("freeform")
    b.set_free_count(3)
    base_h = b.hueReadout
    offs_before = [c["dh"] for c in b.colors]
    b.begin_drag()
    b.hue_drag(1, base_h + 20.0, True)
    b.commit_drag("Wheel hue")
    offs_after = [c["dh"] for c in b.colors]
    assert offs_after[1] == pytest.approx(20.0)
    assert offs_after[0] == offs_before[0]
    assert offs_after[2] == offs_before[2]
    # base hue itself untouched
    assert b.hueReadout == base_h


def test_hue_drag_plain_outer_dot_adjusts_dist(explorer):
    b = explorer["bridge"]
    b.set_scheme("adjacent")
    b.set_dist(30)
    base_h = b.hueReadout
    b.begin_drag()
    b.hue_drag(1, base_h + 45.0, False)
    b.commit_drag("Wheel hue")
    # plain drag on an outer dot adjusts its Distance (spec) — the base
    # hue does NOT move and the model stays symmetric
    assert b.dist == 45
    assert b.hueReadout == base_h
    offs = sorted(((c["h"] - base_h) % 360 + 180) % 360 - 180
                  for c in b.colors)
    assert offs == pytest.approx([-45.0, 0.0, 45.0], abs=1)


def test_hue_drag_plain_outer_dot_per_scheme(explorer):
    b = explorer["bridge"]
    # triad dot 1 rides 120+dist; dot 2 rides 240-dist
    b.set_scheme("triad")
    b.set_dist(30)
    b.begin_drag()
    b.hue_drag(1, b.hueReadout + 150.0, False)
    assert b.dist == 30   # dragged onto the current position — no change
    b.hue_drag(1, b.hueReadout + 170.0, False)
    assert b.dist == 50
    b.hue_drag(2, b.hueReadout + 190.0, False)
    assert b.dist == 50   # 240-190 = 50
    # tetrad dot 3 rides 180+dist; dot 2 (the 180° anchor) rotates instead
    b.set_scheme("tetrad")
    b.set_dist(30)
    b.begin_drag()
    b.hue_drag(3, b.hueReadout + 210.0, False)
    assert b.dist == 30
    b.hue_drag(3, b.hueReadout + 230.0, False)
    assert b.dist == 50
    b.begin_drag()
    b.hue_drag(2, b.hueReadout + 260.0, False)
    # dist-independent anchor: whole scheme rotated to put it at 260
    assert b.hueReadout == pytest.approx(80)   # 260 - 180
    # the appended complementary dot also rotates the scheme
    b.set_scheme("adjacent")
    b.set_dist(30)
    b.set_add_comp(True)
    b.begin_drag()
    b.hue_drag(3, b.hueReadout + 90.0, False)
    # comp rides the base anchor: the whole scheme swings with it
    assert b.hueReadout == pytest.approx((80 + 90 - 180) % 360)


def test_hue_drag_shift_moves_one_dot_individually(explorer):
    b = explorer["bridge"]
    b.set_scheme("adjacent")
    b.set_dist(30)
    base_h = b.hueReadout
    b.begin_drag()
    b.hue_drag(1, base_h + 80.0, True)
    b.commit_drag("Wheel hue")
    # Shift = individual: dot 1 parked at +80°, dist untouched
    assert b.dist == 30
    assert b.colors[1]["h"] == pytest.approx((base_h + 80) % 360)
    assert b.colors[0]["h"] == pytest.approx(base_h)
    assert b.colors[2]["h"] == pytest.approx((base_h - 30) % 360)
    assert b.colors[1]["ind"] is True
    assert b.colors[0]["ind"] is False
    # a later plain drag on that dot re-docks it to the model
    b.begin_drag()
    b.hue_drag(1, base_h + 20.0, False)
    b.commit_drag("Wheel hue")
    assert b.colors[1]["ind"] is False
    assert b.colors[1]["h"] == pytest.approx((base_h + 20) % 360)


def test_shade_drag_shared_and_shift_individual(explorer):
    b = explorer["bridge"]
    b.set_scheme("adjacent")
    b.begin_drag()
    b.shade_drag(70, 30, False, -1)
    b.commit_drag("Wheel shade")
    for c in b.colors:
        assert c["s"] == pytest.approx(70)
        assert c["l"] == pytest.approx(30)
    # shift drag: only color 1 moves
    b.begin_drag()
    b.shade_drag(40, 60, True, 1)
    b.commit_drag("Wheel shade")
    assert b.colors[0]["s"] == pytest.approx(70)
    assert b.colors[1]["s"] == pytest.approx(40)
    assert b.colors[1]["l"] == pytest.approx(60)


def test_drag_commit_records_one_undo_step(explorer):
    b, undo = explorer["bridge"], explorer["undo"]
    b.set_scheme("adjacent")
    b.begin_drag()
    b.hue_drag(0, 90.0, False)
    b.commit_drag("Wheel hue")
    assert undo.canUndo
    assert undo.undoLabel == "Wheel hue"
    # a no-move gesture records nothing: cancel drops the snapshot, and
    # a commit with an unchanged state only persists
    b.begin_drag()
    b.cancel_drag()
    undo.undo()
    assert b.hueReadout == 0


def test_undo_restores_pre_drag_state(explorer):
    b, undo = explorer["bridge"], explorer["undo"]
    b.set_scheme("triad")
    b.set_base_hsl(120, 70, 40)
    before = b.baseHex
    b.begin_drag()
    b.hue_drag(0, 250.0, False)
    assert b.hueReadout == pytest.approx(250)
    b.commit_drag("Wheel hue")
    undo.undo()
    assert b.hueReadout == pytest.approx(120)
    assert b.baseHex == before
    undo.redo()
    assert b.hueReadout == pytest.approx(250)


def test_preset_sets_shade_point(explorer):
    b = explorer["bridge"]
    b.apply_preset(5)   # Full Colors (88, 50)
    assert b.colors[0]["s"] == pytest.approx(88)
    assert b.colors[0]["l"] == pytest.approx(50)


def test_fine_tune_slots_accumulate(explorer):
    b = explorer["bridge"]
    b.fine_tune("hue", 5)
    b.fine_tune("hue", 5)
    assert b.fineTune["hue"] == 10
    assert b.hueReadout == 10
    b.reset_fine_tune()
    assert b.fineTune["hue"] == 0


def test_set_as_base_promotes_color(explorer):
    b = explorer["bridge"]
    b.set_scheme("triad")
    target_hex = b.colors[1]["hex"]
    target_h = b.colors[1]["h"]
    b.set_as_base(1)
    assert b.baseHex.lower() == target_hex.lower()
    assert b.colors[0]["is_base"] is True
    # the promoted hue is now the anchor
    assert b.hueReadout == pytest.approx(target_h)


def test_color_info_payload(explorer):
    b = explorer["bridge"]
    b.set_base_hsl(210, 80, 60)
    info = b.color_info(0, 2)
    assert info["hex"].startswith("#")
    assert info["h"] == 210 and info["s"] == 80 and info["l"] == 60
    assert "lab_l" in info and "lab_a" in info and "lab_b" in info
    assert info["cw"] > 1
    # a ramp variant reports its own values
    light = b.color_info(0, 0)
    assert light["l"] > 60
    assert light["is_base"] is False


def test_set_base_hex_inverts_fine_tune(explorer):
    b = explorer["bridge"]
    b.fine_tune("hue", 10)
    b.set_base_hex("#FF0000")
    # the DISPLAYED base must be the typed red (delta backed out)
    info = b.color_info(0, 2)
    assert info["hex"] == "#FF0000"
    assert b.hueReadout == 0


def test_set_dist_clamps_to_scheme_geometry(explorer):
    b = explorer["bridge"]
    b.set_scheme("triad")
    b.set_dist(90)
    assert b.dist == 60   # the pair converges at 60 — no crossing
    b.set_scheme("adjacent")
    b.set_dist(90)
    assert b.dist == 90


def test_persistence_roundtrip(tmp_path):
    con = core_db.connect(tmp_path / "t.db")
    b = ColorExplorer(con)
    b.set_scheme("adjacent")
    b.set_base_hsl(210, 70, 55)
    b.set_add_comp(True)
    b.hue_drag(1, 210 + 75.0, True)   # individual hue offset
    b.commit_drag("Wheel hue")
    b.fine_tune("saturation", 5)
    # a fresh bridge over the same DB restores the persisted state
    b2 = ColorExplorer(con)
    assert b2.scheme == "adjacent"
    assert b2.addComp is True
    assert b2.dist == 30
    assert b2.hueReadout == pytest.approx(210)
    assert b2.fineTune["saturation"] == 5
    assert b2.colors[0]["hex"] == b.colors[0]["hex"]
    assert b2.colors[1]["h"] == pytest.approx((210 + 75) % 360)
    assert b2.colors[1]["ind"] is True


def test_freeform_count_grows_offsets(explorer):
    b = explorer["bridge"]
    b.set_scheme("freeform")
    b.set_free_count(2)
    assert len(b.colors) == 2
    b.set_free_count(5)
    assert len(b.colors) == 5
    assert b.schemeLabel == "Free style - 5 colors"


def test_save_writes_palette_rows(explorer):
    b, con = explorer["bridge"], explorer["con"]
    b.set_name("Explorer test")
    b.save("tag1, tag2")
    row = con.execute(
        "SELECT p.name, p.tags FROM palette p ORDER BY p.id DESC LIMIT 1"
    ).fetchone()
    assert row["name"] == "Explorer test"
    assert "tag1" in row["tags"]
    hexes = [r[0] for r in con.execute(
        "SELECT hex FROM palette_color WHERE palette_id = ("
        "SELECT MAX(id) FROM palette) ORDER BY position")]
    assert len(hexes) == len(b.colors)


def test_settings_key_is_global(explorer):
    # the explorer state must survive a database switch — it lives in
    # the registry-backed GLOBAL key set
    assert "colors_explorer" in settings_mod.GLOBAL_KEYS
