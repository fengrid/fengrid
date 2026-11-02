import QtQuick

// Color palette color wheel for the Colors pane Explorer tab.
//
// Two stacked canvases keep drag repaints cheap:
//   staticCanvas  — hue ring (notched teeth + segments), inner tick ring,
//                   and the shade disc (S→x, L→y field of the base hue);
//                   `cached: true`, repainted only when the base hue,
//                   theme or size actually changes.
//   markerCanvas  — the palette dots (solid disc = base, ring/outline =
//                   computed colors) on both wheels, repaints per state
//                   change.
//
// Interaction (single MouseArea, standard cursors):
//   - press/drag a hue-ring dot → the whole scheme rotates so that dot
//     follows the mouse (base + offsets preserved);
//   - Shift + drag a secondary hue dot → moves that color individually
//     (freeform: its own offset; fixed models: adjusts Dist);
//   - press/drag the shade disc → moves the shared shade point (every
//     color follows); Shift + drag a disc dot → that color only;
//   - clicking empty ring space rotates the base hue there.
import "."

Item {
    id: wheelRoot

    property var bridge: typeof colorex !== "undefined" ? colorex : null
    readonly property bool isDark: theme.isDark

    // ── geometry (all derived from the square side) ──
    readonly property real side: Math.min(width, height)
    readonly property real cx: width / 2
    readonly property real cy: height / 2
    readonly property real rTeethOut: side * 0.492
    readonly property real rRingOut: side * 0.462
    readonly property real rRingIn: side * 0.378
    readonly property real rDisc: side * 0.345
    readonly property real rMid: (rRingOut + rRingIn) / 2
    readonly property real dotBaseR: side * 0.020
    readonly property real dotSubR: side * 0.0145
    readonly property real discDotBaseR: side * 0.017
    readonly property real discDotSubR: side * 0.0125

    // hover/drag state
    property int hoverWheel: 0      // 0 none · 1 hue ring · 2 shade disc
    property int hoverIdx: -1
    property int dragWheel: 0
    property int dragIdx: -1
    readonly property bool dragging: dragWheel !== 0

    // hue h (deg, 0 = 12 o'clock, clockwise) → local point at radius r
    function ringX(h, r) { return cx + r * Math.sin(h * Math.PI / 180) }
    function ringY(h, r) { return cy - r * Math.cos(h * Math.PI / 180) }
    function angleAt(x, y) {
        var a = Math.atan2(x - cx, cy - y) * 180 / Math.PI
        return (a + 360) % 360
    }
    // shade point (s, l) → local point (S left→right, L top→bottom)
    function discX(s) { return cx - rDisc + (s / 100) * 2 * rDisc }
    function discY(l) { return cy - rDisc + (1 - l / 100) * 2 * rDisc }
    function discSAt(x) {
        return Math.max(0, Math.min(100,
            (x - (cx - rDisc)) / (2 * rDisc) * 100))
    }
    function discLAt(y) {
        return Math.max(0, Math.min(100,
            (1 - (y - (cy - rDisc)) / (2 * rDisc)) * 100))
    }

    // nearest marker hit → {wheel, idx}
    function hitTest(x, y) {
        var cols = bridge !== null ? bridge.colors : []
        var best = null
        for (var i = 0; i < cols.length; i++) {
            var dx = x - ringX(cols[i].h, rMid)
            var dy = y - ringY(cols[i].h, rMid)
            var d = Math.sqrt(dx * dx + dy * dy)
            if (d < Math.max(13, dotBaseR + 6)
                    && (best === null || d < best.d))
                best = { wheel: 1, idx: i, d: d }
        }
        if (best !== null)
            return { wheel: 1, idx: best.idx }
        var r = Math.sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy))
        if (r >= rRingIn - 4 && r <= rTeethOut + 2)
            return { wheel: 1, idx: 0 }
        best = null
        for (i = 0; i < cols.length; i++) {
            // only the base dot and individually-adjusted colors have a
            // disc marker to hit (the rest sit exactly on the base)
            if (!cols[i].is_base && !cols[i].ind)
                continue
            dx = x - discX(cols[i].s)
            dy = y - discY(cols[i].l)
            d = Math.sqrt(dx * dx + dy * dy)
            if (d < Math.max(12, discDotBaseR + 5)
                    && (best === null || d < best.d))
                best = { wheel: 2, idx: i, d: d }
        }
        if (best !== null)
            return { wheel: 2, idx: best.idx }
        if (r <= rDisc)
            return { wheel: 2, idx: -1 }
        return { wheel: 0, idx: -1 }
    }

    function updateHover(x, y) {
        var hit = hitTest(x, y)
        if (hit.wheel !== hoverWheel || hit.idx !== hoverIdx) {
            hoverWheel = hit.wheel
            hoverIdx = hit.idx
            markerCanvas.requestPaint()
        }
    }

    // one 5° ring segment: hue band + outer tooth (the reference sheet's
    // 72-block wheel). Shared by the dimmed static pass and the bright
    // scheme highlights on the marker layer.
    function paintRingSegment(ctx, i, hue, alpha) {
        var gap = 0.5
        var a0 = (hue - 90 + gap) * Math.PI / 180
        var a1 = (hue - 90 + 5 - gap) * Math.PI / 180
        var tooth = rTeethOut - (i % 2 ? side * 0.012 : side * 0.024)
        ctx.globalAlpha = alpha
        ctx.beginPath()
        ctx.arc(cx, cy, rRingOut, a0, a1)
        ctx.arc(cx, cy, rRingIn, a1, a0, true)
        ctx.closePath()
        ctx.fillStyle = Qt.hsla(hue / 360, 1, 0.5, 1)
        ctx.fill()
        ctx.beginPath()
        ctx.arc(cx, cy, tooth, a0, a1)
        ctx.arc(cx, cy, rRingOut, a1, a0, true)
        ctx.closePath()
        ctx.fillStyle = Qt.hsla(hue / 360, 1, 0.46, 1)
        ctx.fill()
        ctx.globalAlpha = 1
    }

    // ── static wheel: ring + teeth + ticks + shade disc ──
    // (repaints only on hue/theme/size changes — see the Connections below)
    Canvas {
        id: staticCanvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            if (wheelRoot.side < 40 || wheelRoot.bridge === null)
                return
            var baseH = wheelRoot.bridge.hueReadout
            var ink = String(theme.tokens.text)
            var i

            // hue ring: 72 segments with hairline gaps — drawn DIM (the
            // reference wheel mutes everything except the scheme hues,
            // which the marker layer highlights)
            var SEG = 5
            for (i = 0; i < 72; i++)
                wheelRoot.paintRingSegment(ctx, i, i * SEG, 0.38)
            // tick ring just inside the hue band (the sprites' knurl)
            ctx.strokeStyle = ink
            ctx.globalAlpha = 0.28
            ctx.lineWidth = 1
            for (i = 0; i < 48; i++) {
                var ta = (i * 7.5 - 90) * Math.PI / 180
                ctx.beginPath()
                ctx.moveTo(wheelRoot.cx + (wheelRoot.rRingIn - 1.5)
                           * Math.cos(ta),
                           wheelRoot.cy + (wheelRoot.rRingIn - 1.5)
                           * Math.sin(ta))
                ctx.lineTo(wheelRoot.cx + (wheelRoot.rRingIn
                           - wheelRoot.side * 0.014) * Math.cos(ta),
                           wheelRoot.cy + (wheelRoot.rRingIn
                           - wheelRoot.side * 0.014) * Math.sin(ta))
                ctx.stroke()
            }
            ctx.globalAlpha = 1

            // ── shade disc: S→x, L→y field of the base hue ──
            ctx.save()
            ctx.beginPath()
            ctx.arc(wheelRoot.cx, wheelRoot.cy, wheelRoot.rDisc,
                    0, 2 * Math.PI)
            ctx.clip()
            // pure hue base
            ctx.fillStyle = Qt.hsla(baseH / 360, 1, 0.5, 1)
            ctx.fillRect(wheelRoot.cx - wheelRoot.rDisc,
                         wheelRoot.cy - wheelRoot.rDisc,
                         wheelRoot.rDisc * 2, wheelRoot.rDisc * 2)
            // white overlay fading left→right desaturates the left half
            var gW = ctx.createLinearGradient(
                wheelRoot.cx - wheelRoot.rDisc, 0,
                wheelRoot.cx + wheelRoot.rDisc, 0)
            gW.addColorStop(0, Qt.rgba(1, 1, 1, 0.97))
            gW.addColorStop(0.55, Qt.rgba(1, 1, 1, 0.45))
            gW.addColorStop(1, Qt.rgba(1, 1, 1, 0))
            ctx.fillStyle = gW
            ctx.fillRect(wheelRoot.cx - wheelRoot.rDisc,
                         wheelRoot.cy - wheelRoot.rDisc,
                         wheelRoot.rDisc * 2, wheelRoot.rDisc * 2)
            // black overlay top→bottom shades the lower half
            var gB = ctx.createLinearGradient(
                0, wheelRoot.cy - wheelRoot.rDisc,
                0, wheelRoot.cy + wheelRoot.rDisc)
            gB.addColorStop(0, Qt.rgba(0, 0, 0, 0))
            gB.addColorStop(0.55, Qt.rgba(0, 0, 0, 0.38))
            gB.addColorStop(1, Qt.rgba(0, 0, 0, 0.9))
            ctx.fillStyle = gB
            ctx.fillRect(wheelRoot.cx - wheelRoot.rDisc,
                         wheelRoot.cy - wheelRoot.rDisc,
                         wheelRoot.rDisc * 2, wheelRoot.rDisc * 2)
            // polar grid: concentric circles + spokes
            ctx.strokeStyle = ink
            ctx.globalAlpha = 0.14
            ctx.lineWidth = 1
            var gi
            for (gi = 1; gi <= 2; gi++) {
                ctx.beginPath()
                ctx.arc(wheelRoot.cx, wheelRoot.cy,
                        wheelRoot.rDisc * gi / 3, 0, 2 * Math.PI)
                ctx.stroke()
            }
            for (gi = 0; gi < 12; gi++) {
                var sa = gi * 30 * Math.PI / 180
                ctx.beginPath()
                ctx.moveTo(wheelRoot.cx, wheelRoot.cy)
                ctx.lineTo(wheelRoot.cx + wheelRoot.rDisc * Math.cos(sa),
                           wheelRoot.cy + wheelRoot.rDisc * Math.sin(sa))
                ctx.stroke()
            }
            // the reference disc's shade-scale chain: small translucent
            // dots along the pale→dark diagonal (NW→SE), never move
            ctx.fillStyle = ink
            for (gi = 0; gi < 4; gi++) {
                var t = [0.25, 0.417, 0.583, 0.75][gi]
                ctx.beginPath()
                ctx.arc(wheelRoot.discX(100 * t),
                        wheelRoot.discY(100 * (1 - t)),
                        wheelRoot.side * (gi === 0 || gi === 3
                                          ? 0.009 : 0.013), 0, 2 * Math.PI)
                ctx.globalAlpha = 0.20
                ctx.fill()
            }
            ctx.globalAlpha = 1
            ctx.restore()
            // disc rim hairline
            ctx.beginPath()
            ctx.arc(wheelRoot.cx, wheelRoot.cy, wheelRoot.rDisc,
                    0, 2 * Math.PI)
            ctx.strokeStyle = String(theme.tokens.border)
            ctx.lineWidth = 1
            ctx.stroke()
        }
    }

    // ── marker layer: the palette dots ──
    Canvas {
        id: markerCanvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            if (wheelRoot.side < 40 || wheelRoot.bridge === null)
                return
            var cols = wheelRoot.bridge.colors
            var dark = String(theme.tokens.bg)
            var accent = String(theme.tokens.accent)
            var i, mx, my

            // bright highlight: every scheme hue re-lights its ring
            // segment (the dim static pass mutes the rest)
            for (i = 0; i < cols.length; i++) {
                var seg = Math.round(cols[i].h / 5) % 72
                for (var k = -2; k <= 2; k++)
                    wheelRoot.paintRingSegment(
                        ctx, (seg + k + 72) % 72, ((seg + k + 72) % 72) * 5,
                        1.0)
            }

            for (i = 0; i < cols.length; i++) {
                mx = wheelRoot.ringX(cols[i].h, wheelRoot.rMid)
                my = wheelRoot.ringY(cols[i].h, wheelRoot.rMid)
                var r = cols[i].is_base ? wheelRoot.dotBaseR
                                        : wheelRoot.dotSubR
                // backdrop halo separates the dot from the ring colors
                ctx.beginPath()
                ctx.arc(mx, my, r + 2.5, 0, 2 * Math.PI)
                ctx.strokeStyle = dark
                ctx.globalAlpha = 0.6
                ctx.lineWidth = 3
                ctx.stroke()
                ctx.globalAlpha = 1
                ctx.beginPath()
                ctx.arc(mx, my, r, 0, 2 * Math.PI)
                ctx.fillStyle = cols[i].hex
                ctx.fill()
                ctx.lineWidth = cols[i].is_base ? 2 : 1.6
                ctx.strokeStyle = "rgba(0,0,0,0.75)"
                ctx.stroke()
            }

            for (i = 0; i < cols.length; i++) {
                mx = wheelRoot.discX(cols[i].s)
                my = wheelRoot.discY(cols[i].l)
                if (cols[i].is_base) {
                    // solid white dot — the shared shade point
                    ctx.beginPath()
                    ctx.arc(mx, my, wheelRoot.discDotBaseR + 1.6, 0,
                            2 * Math.PI)
                    ctx.strokeStyle = "rgba(0,0,0,0.7)"
                    ctx.lineWidth = 2.6
                    ctx.stroke()
                    ctx.beginPath()
                    ctx.arc(mx, my, wheelRoot.discDotBaseR, 0, 2 * Math.PI)
                    ctx.fillStyle = "#FFFFFF"
                    ctx.fill()
                } else if (cols[i].ind) {
                    // hollow ring — a color Shift-dragged off the shared
                    // shade point (undragged colors sit exactly here,
                    // so no marker: the disc stays as clean as the
                    // reference screenshots)
                    ctx.beginPath()
                    ctx.arc(mx, my, wheelRoot.discDotSubR + 1.4, 0,
                            2 * Math.PI)
                    ctx.strokeStyle = "rgba(0,0,0,0.65)"
                    ctx.lineWidth = 2.6
                    ctx.stroke()
                    ctx.beginPath()
                    ctx.arc(mx, my, wheelRoot.discDotSubR, 0, 2 * Math.PI)
                    ctx.strokeStyle = "#FFFFFF"
                    ctx.lineWidth = 2
                    ctx.stroke()
                }
            }

            // hover/active highlight
            if (wheelRoot.hoverWheel !== 0 && wheelRoot.hoverIdx >= 0) {
                var c = wheelRoot.bridge.colors[wheelRoot.hoverIdx]
                if (c) {
                    mx = wheelRoot.hoverWheel === 1
                        ? wheelRoot.ringX(c.h, wheelRoot.rMid)
                        : wheelRoot.discX(c.s)
                    my = wheelRoot.hoverWheel === 1
                        ? wheelRoot.ringY(c.h, wheelRoot.rMid)
                        : wheelRoot.discY(c.l)
                    ctx.beginPath()
                    ctx.arc(mx, my, wheelRoot.dotBaseR + 5, 0, 2 * Math.PI)
                    ctx.strokeStyle = accent
                    ctx.lineWidth = 1.6
                    ctx.stroke()
                }
            }
        }
    }

    // repaint bookkeeping: static layer only when the hue/theme/size move
    property int _lastHue: -1
    property bool _lastDark: true
    property real _lastSide: 0
    Connections {
        target: wheelRoot.bridge
        function onStateChanged() {
            markerCanvas.requestPaint()
            if (wheelRoot.bridge === null)
                return
            if (wheelRoot._lastHue !== wheelRoot.bridge.hueReadout
                    || wheelRoot._lastDark !== wheelRoot.isDark
                    || wheelRoot._lastSide !== wheelRoot.side) {
                wheelRoot._lastHue = wheelRoot.bridge.hueReadout
                wheelRoot._lastDark = wheelRoot.isDark
                wheelRoot._lastSide = wheelRoot.side
                staticCanvas.requestPaint()
            }
        }
    }
    onWidthChanged: staticCanvas.requestPaint()
    onHeightChanged: staticCanvas.requestPaint()

    // ── input ──
    MouseArea {
        id: wheelInput
        anchors.fill: parent
        hoverEnabled: true
        // standard drag cursors: open hand over the wheel, closed while
        // dragging (UI interaction rule)
        cursorShape: wheelRoot.dragging ? Qt.ClosedHandCursor
                                        : Qt.OpenHandCursor
        onPressed: function (mouse) {
            if (wheelRoot.bridge === null)
                return
            wheelRoot.bridge.begin_drag()
            var hit = wheelRoot.hitTest(mouse.x, mouse.y)
            wheelRoot.dragWheel = hit.wheel
            wheelRoot.dragIdx = hit.idx
            if (hit.wheel === 1)
                wheelRoot._applyRing(mouse.x, mouse.y, hit.idx,
                                     mouse.modifiers & Qt.ShiftModifier)
            else if (hit.wheel === 2)
                wheelRoot._applyDisc(mouse.x, mouse.y, hit.idx,
                                     mouse.modifiers & Qt.ShiftModifier)
            else
                wheelRoot.bridge.cancel_drag()
        }
        onPositionChanged: function (mouse) {
            wheelRoot.updateHover(mouse.x, mouse.y)
            if (!pressed || wheelRoot.dragWheel === 0
                    || wheelRoot.bridge === null)
                return
            if (wheelRoot.dragWheel === 1)
                wheelRoot._applyRing(mouse.x, mouse.y, wheelRoot.dragIdx,
                                     mouse.modifiers & Qt.ShiftModifier)
            else
                wheelRoot._applyDisc(mouse.x, mouse.y, wheelRoot.dragIdx,
                                     mouse.modifiers & Qt.ShiftModifier)
        }
        onReleased: function (mouse) {
            if (wheelRoot.bridge !== null && wheelRoot.dragWheel === 1)
                wheelRoot.bridge.commit_drag(qsTr("Wheel hue"))
            else if (wheelRoot.bridge !== null && wheelRoot.dragWheel === 2)
                wheelRoot.bridge.commit_drag(qsTr("Wheel shade"))
            wheelRoot.dragWheel = 0
            wheelRoot.dragIdx = -1
        }
        onExited: {
            wheelRoot.hoverWheel = 0
            wheelRoot.hoverIdx = -1
            markerCanvas.requestPaint()
        }
    }

    function _applyRing(x, y, idx, shift) {
        if (bridge === null)
            return
        bridge.hue_drag(idx, angleAt(x, y), shift)
    }

    function _applyDisc(x, y, idx, shift) {
        if (bridge === null)
            return
        bridge.shade_drag(discSAt(x), discLAt(y), shift, idx)
    }
}
