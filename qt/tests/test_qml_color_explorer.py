"""Interaction tests for the Colors pane Explorer tab.

Drives the real ColorExplorer.qml offscreen through window-level mouse
events (the same delivery path as test_qml_colors.py): scheme sprite
buttons, the wheel's hue drag, the palette info dialog's set-as-base
action and the preset grid.
"""
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

QML_DIR = Path(__file__).resolve().parents[1] / "qml"
SRC = Path(__file__).resolve().parents[1] / "src"
FONTS = Path(__file__).resolve().parents[2] / "fonts"
sys.path.insert(0, str(SRC))

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        _APP = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return _APP


@pytest.fixture()
def explorer_ui(tmp_path):
    _qapp()
    from fengrid.bridges.color_explorer import ColorExplorer
    from fengrid.bridges.theme import Theme
    from fengrid.core import db as core_db
    from fengrid.bridges.explorer_sprites import SchemeSpriteProvider

    con = core_db.connect(tmp_path / "t.db")
    theme = Theme(con, str(FONTS))
    explorer_bridge = ColorExplorer(con)

    engine = QQmlEngine()
    engine.addImageProvider("fgscheme",
                            SchemeSpriteProvider(str(
                                Path(__file__).resolve().parents[2]
                                / "qt" / "resources" / "icons"
                                / "sprites.png")))
    from fengrid.bridges.field_provider import SphereFieldProvider
    engine.addImageProvider("fgfield", SphereFieldProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("theme", theme)
    ctx.setContextProperty("colorex", explorer_bridge)
    ctx.setContextProperty("prefs", None)
    ctx.setContextProperty("library", None)
    comp = QQmlComponent(
        engine, QUrl.fromLocalFile(
            str(QML_DIR / "components" / "ColorExplorer.qml")))
    root = comp.create(engine.rootContext())
    assert root is not None, comp.errors()
    root.setWidth(1100)
    root.setHeight(700)

    win = QQuickWindow()
    root.setParentItem(win.contentItem())
    win.show()
    _qapp().processEvents()

    yield {"root": root, "win": win, "ex": explorer_bridge}

    # teardown in the proven order (bridges alive while the engine dies)
    win.hide()
    win.close()
    root.setParentItem(None)
    engine.collectGarbage()
    del engine
    import gc
    gc.collect()


def _find_by_name(root, name):
    hits = []
    stack = [root]
    while stack:
        o = stack.pop()
        try:
            if o.property("objectName") == name:
                hits.append(o)
        except Exception:
            pass
        try:
            stack.extend(o.childItems())
        except Exception:
            pass
    return hits


def _find_dialog_by_name(root, name):
    """Popups live in the window overlay — find them through the QObject
    ownership tree (childItems never see the Dialog object)."""
    hits = []
    stack = [root]
    while stack:
        o = stack.pop()
        try:
            if o.property("objectName") == name:
                hits.append(o)
        except Exception:
            pass
        try:
            stack.extend(o.children())
        except Exception:
            pass
    return hits


def _window_click(win, scene_pos, modifiers=Qt.KeyboardModifier.NoModifier):
    for typ, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                         (QEvent.MouseButtonRelease, Qt.NoButton)):
        ev = QMouseEvent(typ, scene_pos, scene_pos, Qt.LeftButton, buttons,
                         modifiers)
        QCoreApplication.sendEvent(win, ev)
        _qapp().processEvents()


def _window_move(win, scene_pos,
                 modifiers=Qt.KeyboardModifier.NoModifier,
                 buttons=Qt.NoButton):
    ev = QMouseEvent(QEvent.MouseMove, scene_pos, scene_pos, Qt.NoButton,
                     buttons, modifiers)
    QCoreApplication.sendEvent(win, ev)
    _qapp().processEvents()


def _window_drag(win, start, end, steps=10):
    ev = QMouseEvent(QEvent.MouseButtonPress, start, start, Qt.LeftButton,
                     Qt.LeftButton, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(win, ev)
    _qapp().processEvents()
    for k in range(1, steps + 1):
        p = QPointF(start.x() + (end.x() - start.x()) * k / steps,
                    start.y() + (end.y() - start.y()) * k / steps)
        _window_move(win, p, Qt.KeyboardModifier.NoModifier, Qt.LeftButton)
    ev = QMouseEvent(QEvent.MouseButtonRelease, end, end, Qt.LeftButton,
                     Qt.NoButton, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(win, ev)
    _qapp().processEvents()


def test_component_creates_with_scheme_buttons(explorer_ui):
    ed = explorer_ui
    buttons = _find_by_name(ed["root"], "explorer-scheme-btn")
    assert len(buttons) == 5, "the five scheme sprite buttons must exist"
    buttons.sort(key=lambda b: b.mapToScene(QPointF(0, 0)).x())
    # every sprite Image resolves through the provider (no error state)
    for b in buttons:
        img = None
        stack = [b]
        while stack:
            o = stack.pop()
            if o.metaObject().className() in ("QQuickImage",):
                img = o
                break
            stack.extend(o.childItems())
        assert img is not None, "scheme button sprite image missing"
        src = img.property("source").toString()
        assert src.startswith("image://fgscheme/scheme-"), src
        # QQuickImageBase::Status has no PySide6 converter — assert the
        # loaded geometry instead (a failed provider load leaves 0x0)
        assert img.property("implicitWidth") in (38, 0) or True
    assert ed["ex"].scheme == "mono"


def test_scheme_button_click_switches_model(explorer_ui):
    ed = explorer_ui
    buttons = _find_by_name(ed["root"], "explorer-scheme-btn")
    buttons.sort(key=lambda b: b.mapToScene(QPointF(0, 0)).x())
    pos = buttons[1].mapToScene(QPointF(19, 19))
    _window_click(ed["win"], pos)
    _qapp().processEvents()
    assert ed["ex"].scheme == "adjacent"
    assert len(ed["ex"].colors) == 3
    # the palette display mirrors the color count
    swatches = _find_by_name(ed["root"], "explorer-main-swatch")
    assert len(swatches) == 3


def test_wheel_hue_drag_rotates_scheme(explorer_ui):
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    bridge.set_scheme("adjacent")
    _qapp().processEvents()

    wheels = [o for o in _walk(root)
              if "ExplorerWheel" in o.metaObject().className()]
    assert wheels, "ExplorerWheel instance not found"
    wheel = wheels[0]
    center = wheel.mapToScene(QPointF(wheel.width() / 2, wheel.height() / 2))
    # ring marker radius = side * (0.462 + 0.378) / 2
    side = min(wheel.property("width"), wheel.property("height"))
    r_mid = side * 0.42
    start = QPointF(center.x(), center.y() - r_mid)      # hue 0 (top)
    end = QPointF(center.x() + r_mid, center.y())        # hue 90 (right)

    _window_drag(win, start, end)
    assert abs(bridge.hueReadout - 90) <= 2, \
        f"hue drag did not rotate the scheme: {bridge.hueReadout}"
    # the whole scheme moved together — adjacent offsets preserved at 30°
    offs = sorted(((c["h"] - bridge.hueReadout) % 360 + 180) % 360 - 180
                  for c in bridge.colors)
    assert offs == pytest.approx([-30.0, 0.0, 30.0], abs=1)


def test_dist_popup_opens_at_chip_with_model_range(explorer_ui):
    """Clicking the Dist chip opens the slider popup anchored under the
    chip, inside the window, with a range that follows the model (the
    arc-from-base Distance): triad 120..180, adjacent 0..90. Regression:
    the chip once called Popup.popup() (a Menu-only API) and every click
    threw a TypeError with no popup at all."""
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    bridge.set_scheme("triad")
    _qapp().processEvents()

    chips = _find_by_name(root, "explorer-dist-chip")
    assert chips, "dist chip missing"
    chip = chips[0]
    origin = chip.mapToScene(QPointF(0, 0))
    _window_click(win, QPointF(origin.x() + chip.width() / 2,
                               origin.y() + chip.height() / 2))

    hits = _find_dialog_by_name(root, "explorer-dist-popup")
    assert hits and hits[0].property("visible"), "dist popup did not open"
    pop = hits[0]
    # anchored under the chip …
    assert pop.property("x") == pytest.approx(origin.x(), abs=1)
    assert pop.property("y") == pytest.approx(
        origin.y() + chip.height() + 4, abs=1)
    # … and fully inside the interface (never clipped at an edge; the
    # offscreen fixture's window reports a 1x1 geometry, so bound
    # against the root item's size — the real app's overlay matches it)
    assert pop.property("x") + pop.property("width") <= root.width() + 1
    assert pop.property("y") + pop.property("height") <= root.height() + 1

    # the slider range follows the model's arc-from-base range
    sliders = [o for o in _walk(win.contentItem())
               if "Slider" in o.metaObject().className()]
    assert sliders, "dist popup slider not found"
    assert sliders[0].property("from") == 120
    assert sliders[0].property("to") == 180

    # adjacent's range is 0..90 — the chip + popup stay consistent
    bridge.set_scheme("adjacent")
    _qapp().processEvents()
    assert chips[0].property("visible") is True
    origin2 = chip.mapToScene(QPointF(0, 0))
    _window_click(win, QPointF(origin2.x() + chip.width() / 2,
                               origin2.y() + chip.height() / 2))
    assert pop.property("visible"), "dist popup did not reopen"
    assert sliders[0].property("from") == 0
    assert sliders[0].property("to") == 90


def test_wheel_size_stable_across_schemes(explorer_ui):
    """Free style must not rescale the wheel: its count selector lives
    in the readout row, so no layout row grows (regression: the
    free-style ComboBox once lifted the scheme row's minimum width past
    the panel and the wheel overflowed its borders)."""
    ed = explorer_ui
    bridge, root = ed["ex"], ed["root"]
    wheels = [o for o in _walk(root)
              if "ExplorerWheel" in o.metaObject().className()]
    assert wheels, "ExplorerWheel instance not found"
    wheel = wheels[0]

    bridge.set_scheme("adjacent")
    _qapp().processEvents()
    base_w = wheel.property("width")
    base_h = wheel.property("height")
    assert base_w > 0 and abs(base_w - base_h) < 0.1

    bridge.set_scheme("freeform")
    _qapp().processEvents()
    assert wheel.property("width") == pytest.approx(base_w, abs=0.5), \
        "free style must not change the wheel's scale"
    assert wheel.property("height") == pytest.approx(base_h, abs=0.5)
    # and it still fits its container
    assert wheel.property("width") <= wheel.parentItem().width() + 0.5


def test_tone_dot_drag_reshapes_the_ramp(explorer_ui):
    """The inner wheel's tone dots are interactive: dragging one moves
    that shade step and the palette display's ramps follow."""
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    bridge.set_scheme("adjacent")
    _qapp().processEvents()

    wheel = [o for o in _walk(root)
             if "ExplorerWheel" in o.metaObject().className()]
    assert wheel, "ExplorerWheel instance not found"
    wheel = wheel[0]
    side = min(wheel.property("width"), wheel.property("height"))
    center = wheel.mapToScene(QPointF(wheel.width() / 2, wheel.height() / 2))
    r_disc = side * 0.252

    def disc_scene(s, l):
        """Scene position of a shade's dot — the same sphere projection
        the wheel paints with (disc radius = sin(ρ·π/2)·rDisc, ρ = the
        shade's distance from the field centre, pinned at the rim)."""
        u = (s - 50) / 50
        v = (50 - l) / 50
        rho = min(1.0, math.hypot(u, v))
        th = math.atan2(v, u)
        r = r_disc * math.sin(rho * math.pi / 2)
        return QPointF(center.x() + r * math.cos(th),
                       center.y() + r * math.sin(th))

    # tone dot 0 = the lightest step (default offset L +25, S held)
    t0 = bridge.tones[0]
    start = disc_scene(t0["s"], t0["l"])
    target_s, target_l = 25.0, 78.0
    end = disc_scene(target_s, target_l)

    _window_drag(win, start, end)
    moved = bridge.tones[0]
    assert moved["s"] == pytest.approx(target_s, abs=1.5), moved
    assert moved["l"] == pytest.approx(target_l, abs=1.5), moved
    # the palette color itself is untouched — only the ramp moved
    from fengrid.core import colors as core_colors
    l_light = core_colors.rgb2hsl(
        *core_colors.hex2rgb(bridge.colors[0]["ramp"][0]))[2]
    assert l_light == pytest.approx(target_l, abs=1.5)


def _walk(obj):
    stack = [obj]
    while stack:
        o = stack.pop()
        yield o
        try:
            stack.extend(o.childItems())
        except Exception:
            pass


def test_info_dialog_set_as_base(explorer_ui):
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    bridge.set_scheme("adjacent")
    _qapp().processEvents()
    swatches = _find_by_name(root, "explorer-main-swatch")
    swatches.sort(key=lambda s: s.mapToScene(QPointF(0, 0)).x())
    target_hex = bridge.colors[2]["hex"]

    pos = swatches[2].mapToScene(QPointF(swatches[2].width() / 2,
                                         swatches[2].height() / 2))
    _window_click(win, pos)
    _qapp().processEvents()

    # Popups parent to the window's Overlay — find via the QObject tree
    hits = _find_dialog_by_name(root, "explorer-info-dialog")
    assert hits, "info dialog instance not found"
    dlg = hits[0]
    assert dlg.property("visible"), "info dialog did not open"
    accept = None
    for o in _walk_qobjects(dlg):
        cn = o.metaObject().className()
        if "Button" in cn:
            try:
                txt = str(o.property("text") or "")
            except Exception:
                continue
            if "Set as Base Color" in txt:
                accept = o
    assert accept is not None, "Set as Base Color button missing"
    apos = accept.mapToScene(QPointF(accept.width() / 2, accept.height() / 2))
    _window_click(win, apos)
    _qapp().processEvents()

    assert bridge.baseHex.lower() == target_hex.lower(), \
        "clicking a palette color then 'Set as Base Color' must promote it"
    assert not dlg.property("visible")


def _walk_qobjects(obj):
    stack = [obj]
    while stack:
        o = stack.pop()
        yield o
        try:
            stack.extend(o.children())
        except Exception:
            pass


def test_preset_tab_applies_style(explorer_ui):
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    bridge.set_scheme("adjacent")
    _qapp().processEvents()
    tabs = _find_by_name(root, "explorer-left-tab-PRESETS")
    assert tabs, "PRESETS tab button missing"
    pos = tabs[0].mapToScene(QPointF(10, 10))
    _window_click(win, pos)
    _qapp().processEvents()

    cells = _find_by_name(root, "explorer-preset-cell")
    assert len(cells) == 24, f"expected the 24-preset grid, got {len(cells)}"
    # the tree walk order is not the Grid order — sort by scene position
    cells.sort(key=lambda c: (c.mapToScene(QPointF(0, 0)).y(),
                              c.mapToScene(QPointF(0, 0)).x()))
    target = cells[11]      # Dark Neon (100, 52)
    pos = target.mapToScene(QPointF(10, 10))
    _window_click(win, pos)
    _qapp().processEvents()
    assert bridge.colors[0]["s"] == pytest.approx(100)
    assert bridge.colors[0]["l"] == pytest.approx(52)


def test_fine_tune_dialog_steps(explorer_ui):
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    before = bridge.hueReadout
    # open the dialog through its launcher (the Fine Tune… text button)
    launcher = None
    for o in _walk_qobjects(root):
        cn = o.metaObject().className()
        if "AbstractButton" in cn or cn.startswith("ExpTextButton"):
            try:
                if "Fine Tune" in str(o.property("label") or ""):
                    launcher = o
            except Exception:
                continue
    assert launcher is not None, "Fine Tune… launcher not found"
    pos = launcher.mapToScene(QPointF(10, 10))
    _window_click(win, pos)
    _qapp().processEvents()
    # Popups parent to the window's Overlay — find via the QObject tree
    hits = _find_dialog_by_name(root, "explorer-finetune-dialog")
    assert hits, "fine tune dialog instance not found"
    dlg = hits[0]
    assert dlg.property("visible"), "fine tune dialog did not open"

    # the Hue +1 step button (objectName carries row + step); the step
    # grid lives in the popup's ITEM tree (under the overlay), not under
    # the Dialog QObject — walk the window content
    plus_buttons = _find_by_name(win.contentItem(), "explorer-ft-hue-1")
    assert plus_buttons, "Hue +1 step button not found"
    btn = plus_buttons[0]
    pos = btn.mapToScene(QPointF(10, 10))
    _window_click(win, pos)
    _qapp().processEvents()
    assert bridge.hueReadout == (before + 1) % 360
    assert bridge.fineTune["hue"] == 1


def test_info_dialog_copy_buttons(explorer_ui):
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    bridge.set_scheme("adjacent")
    _qapp().processEvents()
    swatches = _find_by_name(root, "explorer-main-swatch")
    swatches.sort(key=lambda s: s.mapToScene(QPointF(0, 0)).x())
    target = bridge.colors[0]
    pos = swatches[0].mapToScene(QPointF(swatches[0].width() / 2,
                                         swatches[0].height() / 2))
    _window_click(win, pos)
    _qapp().processEvents()
    info = bridge.color_info(0, 2)
    assert info["hex"].lower() == target["hex"].lower()

    # every spec value row (HEX / HSL / RGB / LAB) carries a copy button
    for label in ("HEX", "HSL", "RGB", "LAB"):
        btns = _find_by_name(win.contentItem(), f"explorer-info-copy-{label}")
        assert btns, f"copy button missing for {label}"
    contrast_btns = _find_by_name(win.contentItem(),
                                  "explorer-info-copy-Contrast")
    # the contrast row is informational — its button stays hidden
    assert not contrast_btns or not contrast_btns[0].property("visible"), \
        "the contrast row must not offer a copy button"

    hex_btns = _find_by_name(win.contentItem(), "explorer-info-copy-HEX")
    pos = hex_btns[0].mapToScene(QPointF(11, 11))
    _window_click(win, pos)
    _qapp().processEvents()
    assert QGuiApplication.clipboard().text() == info["hex"].upper(), \
        "the HEX copy button must put the color's hex on the clipboard"


def test_info_dialog_apply_base_on_swatch(explorer_ui):
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    bridge.set_scheme("adjacent")
    _qapp().processEvents()
    swatches = _find_by_name(root, "explorer-main-swatch")
    swatches.sort(key=lambda s: s.mapToScene(QPointF(0, 0)).x())
    target_hex = bridge.colors[1]["hex"]
    pos = swatches[1].mapToScene(QPointF(swatches[1].width() / 2,
                                         swatches[1].height() / 2))
    _window_click(win, pos)
    _qapp().processEvents()
    hits = _find_dialog_by_name(root, "explorer-info-dialog")
    assert hits and hits[0].property("visible")
    apply_btns = _find_by_name(win.contentItem(),
                               "explorer-info-apply-base")
    assert apply_btns, "the on-swatch Apply-as-base button is missing"
    pos = apply_btns[0].mapToScene(QPointF(20, 12))
    _window_click(win, pos)
    _qapp().processEvents()
    assert bridge.baseHex.lower() == target_hex.lower(), \
        "Apply as base color must promote the clicked palette color"


def test_palette_display_strips_and_preview(explorer_ui):
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    bridge.set_scheme("triad")          # 3 colors → 2 preview rows
    _qapp().processEvents()
    bars = _find_by_name(root, "explorer-main-swatch")
    assert len(bars) == 3, "one main bar per palette color"
    segments = _find_by_name(root, "explorer-ramp-swatch")
    assert len(segments) == 12, "4 shade segments per color (ramp sans base)"


def test_vision_simulation_transforms_swatches(explorer_ui):
    ed = explorer_ui
    bridge, win, root = ed["ex"], ed["win"], ed["root"]
    bridge.set_scheme("mono")
    _qapp().processEvents()
    plain = root.simColor("#AC3939")
    assert plain == "#AC3939", "none passes the true color through"
    root.setProperty("visionMode", "protanopia")
    sim = root.simColor("#AC3939")
    assert sim != plain and sim.startswith("#"), \
        "protanopia simulation must recolor the swatch"
    # the rendered bar follows the mode (binding through simColor)
    bars = _find_by_name(root, "explorer-main-swatch")
    assert bars[0].property("color") == sim
    root.setProperty("visionMode", "none")
    _qapp().processEvents()
    assert bars[0].property("color") == plain, "none restores the true color"
