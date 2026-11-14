import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Explorer tab (Colors pane): Color palette scheme workspace.
//
// Left: scheme-model sprite buttons (+ add-complementary), hue/dist
// chips, the interactive wheel (or the preset grid on the PRESETS tab),
// the Base RGB field and the Fine Tune… launcher. Right: the configured
// palette — hover a swatch for its HEX, click for the detail dialog
// (HEX/HSL/RGB/LAB + set-as-base). Tables / Export… opens the shade
// tables and routes through the shared export pipeline.
//
// All state lives in the `colorex` bridge; the wheel owns the drags.
Item {
    id: explorerRoot

    readonly property bool isDark: theme.isDark

    // sprite design index per scheme (sheet row order); +complementary
    // variants sit right after mono/adjacent/triad on the same row
    readonly property var schemeDesign: ({
        "mono": 0, "adjacent": 2, "triad": 4, "tetrad": 6, "freeform": 7
    })
    readonly property var compDesign: ({
        "mono": 1, "adjacent": 3, "triad": 5, "tetrad": 6, "freeform": 7
    })
    property string leftTab: "colors"   // colors | presets

    Rectangle {
        anchors.fill: parent
        color: theme.tokens.bg
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ─────────────────────────────────────── left: scheme workspace ──
        Rectangle {
            color: theme.tokens.surface
            Layout.preferredWidth: 470
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                // scheme-model row: sprite buttons + label + comp toggle.
                // Every fixed-size element carries explicit preferred AND
                // minimum sizes: while the theme fonts are still loading
                // the text metrics are fallback-sized, and a layout row
                // driven purely by implicits lets that window squeeze the
                // sprite buttons to zero (observed as a collapsed selector
                // row on slow-startup runs).
                RowLayout {
                    spacing: 10
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    Repeater {
                        model: [
                            { key: "mono", design: 0 },
                            { key: "adjacent", design: 2 },
                            { key: "triad", design: 4 },
                            { key: "tetrad", design: 6 },
                            { key: "freeform", design: 7 }
                        ]
                        delegate: AbstractButton {
                            id: schemeBtn
                            required property var modelData
                            objectName: "explorer-scheme-btn"
                            readonly property bool active:
                                colorex !== null
                                && colorex.scheme === schemeBtn.modelData.key
                            readonly property int design:
                                (colorex !== null && colorex.addComp
                                 && (schemeBtn.modelData.key === "mono"
                                     || schemeBtn.modelData.key === "adjacent"
                                     || schemeBtn.modelData.key === "triad"))
                                ? schemeBtn.modelData.design + 1
                                : schemeBtn.modelData.design
                            Layout.preferredWidth: 38
                            Layout.preferredHeight: 38
                            Layout.minimumWidth: 38
                            Layout.minimumHeight: 38
                            HoverHandler {
                                cursorShape: Qt.PointingHandCursor
                            }
                            onClicked: colorex !== null
                                && colorex.set_scheme(schemeBtn.modelData.key)
                            // the selection ring must sit OUTSIDE the
                            // sprite: the sprite's disc fills its 38px
                            // cell and would otherwise overdraw the
                            // border (observed as a half-ring on the
                            // active scheme button)
                            background: Rectangle {
                                anchors.centerIn: schemeBtn
                                width: schemeBtn.width + 6
                                height: schemeBtn.height + 6
                                radius: width / 2
                                color: schemeBtn.hovered
                                       ? theme.tokens.scrimSoft
                                       : "transparent"
                                border.color: schemeBtn.active
                                              ? theme.tokens.accentColor
                                              : "transparent"
                                border.width: 1
                            }
                            contentItem: Image {
                                source: "image://fgscheme/scheme-"
                                        + schemeBtn.design + "-"
                                        + (schemeBtn.active ? "sel" : "idle")
                                        + "-"
                                        + (explorerRoot.isDark ? "dark"
                                                               : "light")
                                sourceSize: Qt.size(38, 38)
                                fillMode: Image.PreserveAspectFit
                            }
                            ToolTip.visible: hovered
                            ToolTip.delay: 350
                            ToolTip.text: {
                                var names = {
                                    "mono": "Monochromatic",
                                    "adjacent": "Adjacent colors",
                                    "triad": "Triad",
                                    "tetrad": "Tetrad",
                                    "freeform": "Free style"
                                }
                                return names[schemeBtn.modelData.key]
                            }
                        }
                    }
                    ColumnLayout {
                        spacing: 2
                        Layout.fillWidth: true
                        Text {
                            text: colorex !== null ? colorex.schemeLabel : ""
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: theme.tokens.text
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        RowLayout {
                            spacing: 8
                            FormCheck {
                                checkLabel: qsTr("add complementary")
                                checked: colorex !== null && colorex.addComp
                                onToggled: colorex !== null
                                    && colorex.set_add_comp(checked)
                            }
                        }
                    }
                    Item { Layout.fillWidth: true }
                }

                // hue / dist readout chips (+ the scheme-level actions)
                RowLayout {
                    spacing: 8
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    Rectangle {
                        Layout.preferredWidth: 92
                        Layout.preferredHeight: 34
                        Layout.minimumWidth: 92
                        Layout.minimumHeight: 34
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: theme.tokens.border
                        ColumnLayout {
                            anchors.centerIn: parent
                            spacing: 0
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: colorex !== null
                                      ? qsTr("Hue: %1°").arg(colorex.hueReadout)
                                      : ""
                                font.family: theme.monoFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                            }
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: qsTr("opposite")
                                font.family: theme.monoFont
                                font.pixelSize: 8
                                color: theme.tokens.textMuted
                            }
                        }
                    }
                    Rectangle {
                        id: distChip
                        objectName: "explorer-dist-chip"
                        // mono/freeform have no Distance parameter — the
                        // reference UI only shows the box for the models
                        // whose dots move apart
                        visible: colorex !== null
                                 && (colorex.scheme === "adjacent"
                                     || colorex.scheme === "triad"
                                     || colorex.scheme === "tetrad")
                        Layout.preferredWidth: 92
                        Layout.preferredHeight: 34
                        Layout.minimumWidth: 92
                        Layout.minimumHeight: 34
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: distMa.containsMouse
                                      ? theme.tokens.accentColor
                                      : theme.tokens.border
                        ColumnLayout {
                            anchors.centerIn: parent
                            spacing: 0
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: colorex !== null
                                      ? qsTr("Dist: %1°").arg(colorex.dist)
                                      : ""
                                font.family: theme.monoFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                            }
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: colorex !== null
                                      ? qsTr("default: %1°")
                                        .arg(colorex.distDefault)
                                      : ""
                                font.family: theme.monoFont
                                font.pixelSize: 8
                                color: theme.tokens.textMuted
                            }
                        }
                        MouseArea {
                            id: distMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                // scene coords (mapToItem(null)) match
                                // the popup's Overlay.overlay parent;
                                // Item has no mapToScene() in QML
                                var p = distChip.mapToItem(null, 0, 0)
                                distPopup.x = p.x
                                distPopup.y = p.y + distChip.height + 4
                                distPopup.open()
                            }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    // free-style color count — lives in the readout row
                    // (the reference puts it with the hue/dist chips);
                    // it must NOT sit in the scheme row: its width lifts
                    // that row's minimum past the panel and the wheel
                    // grows with it (observed as a free-style-only
                    // scale change that overflowed the borders)
                    ComboBox {
                        id: freeCountBox
                        visible: colorex !== null
                                 && colorex.scheme === "freeform"
                        Layout.preferredWidth: 92
                        Layout.minimumWidth: 92
                        Layout.preferredHeight: 34
                        Layout.minimumHeight: 34
                        model: ["2 colors", "3 colors", "4 colors",
                                "5 colors"]
                        currentIndex: colorex !== null
                                ? colorex.freeCount - 2 : 2
                        onActivated: function (idx) {
                            colorex !== null
                                && colorex.set_free_count(idx + 2)
                        }
                        background: Rectangle {
                            radius: 6
                            color: theme.tokens.surface2
                            border.color: theme.tokens.border
                        }
                        contentItem: Text {
                            text: freeCountBox.displayText
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.text
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 8
                        }
                    }
                    ExpTextButton {
                        label: qsTr("Randomize")
                        tip: qsTr("New random base color — the scheme stays")
                        onClicked: colorex !== null && colorex.randomize()
                    }
                    ExpTextButton {
                        label: qsTr("Reset")
                        tip: qsTr("Back to the default explorer state")
                        onClicked: colorex !== null && colorex.reset()
                    }
                }

                // wheel (COLORS tab) or preset grid (PRESETS tab)
                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: explorerRoot.leftTab === "colors" ? 0 : 1

                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 4
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: qsTr("Hold Shift to adjust dots"
                                           + " individually")
                                font.family: theme.uiFont
                                font.pixelSize: 9
                                font.italic: true
                                color: theme.tokens.textMuted
                            }
                            Item { Layout.fillHeight: true }
                        }
                        ExplorerWheel {
                            anchors.centerIn: parent
                            width: Math.min(parent.width, parent.height)
                            height: width
                        }
                    }

                    // ── presets: 3-column grid of shade styles ──
                    ScrollView {
                        id: presetScroll
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        contentWidth: availableWidth
                        ColumnLayout {
                            width: presetScroll.availableWidth
                            spacing: 10
                            Grid {
                                columns: 3
                                columnSpacing: 10
                                rowSpacing: 10
                                Repeater {
                                    model: 24
                                    delegate: AbstractButton {
                                        id: presetCell
                                        required property int index
                                        objectName: "explorer-preset-cell"
                                        // mirrors core PRESETS (name, s, l)
                                        // — keep in sync with
                                        // core/color_explorer.py
                                        readonly property var presets: [
                                            ["Lightest Pale Pastel", 18, 92],
                                            ["Bright Pastel", 60, 76],
                                            ["Shiny", 92, 64],
                                            ["Very Light Pale Pastel", 22, 86],
                                            ["Very Light Pastel", 55, 86],
                                            ["Full Colors", 88, 50],
                                            ["Lighter Pale Pastel", 26, 80],
                                            ["Lighter Pastel", 58, 70],
                                            ["Darker Colors", 82, 36],
                                            ["Pale Pastel", 30, 74],
                                            ["Pastel", 60, 62],
                                            ["Dark Neon", 100, 52],
                                            ["Darker Pale Pastel", 32, 66],
                                            ["Darker Pastel", 62, 50],
                                            ["Dark", 70, 26],
                                            ["Dark Pale Pastel", 34, 56],
                                            ["Dark Pastel", 60, 38],
                                            ["Deep Colors", 88, 30],
                                            ["Greyish darkest", 8, 26],
                                            ["Greyish dark", 10, 40],
                                            ["Greyish medium dark", 12, 52],
                                            ["Greyish medium light", 12, 64],
                                            ["Greyish lighter", 10, 76],
                                            ["Greyish lightest", 8, 88]
                                        ]
                                        readonly property var entry:
                                            presets[presetCell.index]
                                        readonly property var cols:
                                            colorex !== null
                                            ? colorex.colors : []
                                        // the current hues rendered at the
                                        // preset's shade style
                                        readonly property var stripColors: {
                                            var out = []
                                            for (var i = 0;
                                                    i < cols.length && i < 5;
                                                    i++)
                                                out.push(Qt.hsla(
                                                    cols[i].h / 360,
                                                    entry[1] / 100,
                                                    entry[2] / 100, 1))
                                            while (out.length < 5)
                                                out.push("transparent")
                                            return out
                                        }
                                        implicitWidth:
                                            (presetScroll.availableWidth
                                             - 20) / 3
                                        implicitHeight: 46
                                        HoverHandler {
                                            cursorShape: Qt.PointingHandCursor
                                        }
                                        onClicked: colorex !== null
                                            && colorex.apply_preset(
                                                presetCell.index)
                                        background: Rectangle {
                                            radius: 6
                                            color: presetCell.hovered
                                                   ? theme.tokens.scrimSoft
                                                   : "transparent"
                                            border.color: presetCell.hovered
                                                  ? theme.tokens.accentColor
                                                  : theme.tokens.border
                                        }
                                        contentItem: ColumnLayout {
                                            spacing: 3
                                            // RowLayout, not a plain Row:
                                            // a plain Row's implicitWidth
                                            // (sum of child widths) feeds
                                            // back through fillWidth and
                                            // the child widths re-bind off
                                            // the Row's own width — a
                                            // polish() loop that thrashes
                                            // the layout engine ~2000x per
                                            // run and starves real layout
                                            // passes (observed as mis-laid
                                            // -out/missing UI). Proportional
                                            // fillWidth children carry no
                                            // width→implicit cycle.
                                            RowLayout {
                                                id: presetStrip
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 16
                                                spacing: 1
                                                Repeater {
                                                    model: 5
                                                    delegate: Rectangle {
                                                        required property int index
                                                        readonly property real w: [0.6, 1.0, 1.6, 1.0, 0.6][index]
                                                        Layout.fillWidth: true
                                                        Layout.preferredWidth: w * 30
                                                        Layout.fillHeight: true
                                                        color: presetCell.stripColors[index]
                                                    }
                                                }
                                            }
                                            Text {
                                                text: presetCell.entry[0]
                                                font.family: theme.uiFont
                                                font.pixelSize: 9
                                                color: theme.tokens.textMuted
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // base RGB + fine tune
                RowLayout {
                    spacing: 10
                    Layout.fillWidth: true
                    Layout.preferredHeight: 28
                    Text {
                        text: qsTr("Base RGB:")
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.textMuted
                    }
                    Rectangle {
                        Layout.preferredWidth: 110
                        Layout.preferredHeight: 28
                        Layout.minimumWidth: 110
                        Layout.minimumHeight: 28
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: baseField.activeFocus
                                      ? theme.tokens.accent
                                      : theme.tokens.border
                        TextInput {
                            id: baseField
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: TextInput.AlignVCenter
                            font.family: theme.monoFont
                            font.pixelSize: 12
                            font.capitalization: Font.AllUppercase
                            color: theme.tokens.text
                            clip: true
                            // same gotcha as the harmonies hex field: the
                            // field follows state only while not edited
                            text: colorex !== null
                                  ? colorex.baseHex.toUpperCase().substring(1)
                                  : ""
                            onAccepted: colorex !== null
                                && colorex.set_base_hex(text)
                        }
                    }
                    Item { Layout.fillWidth: true }
                    ExpTextButton {
                        label: qsTr("Fine Tune…")
                        tip: qsTr("Step the whole palette: hue, saturation,"
                                  + " brightness, contrast")
                        onClicked: fineTuneDialog.open()
                    }
                }

                // left panel tabs
                RowLayout {
                    spacing: 2
                    Layout.preferredHeight: 24
                    Layout.fillHeight: false
                    Repeater {
                        model: [qsTr("COLORS"), qsTr("PRESETS")]
                        delegate: AbstractButton {
                            id: leftTabBtn
                            objectName: "explorer-left-tab-" + modelData
                            required property int index
                            required property string modelData
                            Layout.preferredHeight: 24
                            Layout.minimumHeight: 24
                            onClicked: explorerRoot.leftTab =
                                       (index === 0 ? "colors" : "presets")
                            background: Rectangle {
                                radius: 5
                                color: explorerRoot.leftTab
                                       === (leftTabBtn.index === 0
                                            ? "colors" : "presets")
                                       ? theme.tokens.surface2
                                       : "transparent"
                                border.color: theme.tokens.border
                            }
                            contentItem: Text {
                                text: leftTabBtn.modelData
                                color: explorerRoot.leftTab
                                       === (leftTabBtn.index === 0
                                            ? "colors" : "presets")
                                       ? theme.tokens.text
                                       : theme.tokens.textMuted
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                font.letterSpacing: 1.2
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                                rightPadding: 10
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            width: 1
            color: theme.tokens.border
            Layout.fillHeight: true
        }

        // ─────────────────────────────────────── right: palette display ──
        Rectangle {
            color: theme.tokens.bg
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Text {
                    text: qsTr("My Palette:")
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: theme.tokens.textMuted
                }

                // one ramp group per palette color, side by side: the
                // color's bar over its 4-shade strip (light → base → dark
                // taper, as in the reference). Hover shows the HEX, click
                // opens the color info dialog.
                RowLayout {
                    id: stripRow
                    Layout.fillWidth: true
                    spacing: 10
                    Repeater {
                        model: colorex !== null ? colorex.colors : []
                        delegate: ColumnLayout {
                            id: stripCol
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            spacing: 4

                            Rectangle {
                                id: mainSw
                                objectName: "explorer-main-swatch"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 40
                                Layout.minimumHeight: 40
                                radius: 6
                                color: explorerRoot.simColor(
                                            stripCol.modelData.hex)
                                border.color: stripCol.modelData.is_base
                                              ? theme.tokens.litPane
                                              : theme.tokens.border
                                border.width: stripCol.modelData.is_base
                                              ? 2 : 1
                                MouseArea {
                                    id: mainMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: explorerRoot.openInfo(
                                        stripCol.index, 2)
                                }
                                // hover shows the color's HEX (spec)
                                ToolTip.visible: mainMa.containsMouse
                                ToolTip.delay: 120
                                ToolTip.text:
                                    stripCol.modelData.hex.toUpperCase()
                            }
                            // Deliberately a plain Row (NOT the
                            // preset-strip RowLayout fix): its children
                            // bind to the strip's own width here without
                            // cycling, because the parent column's width
                            // comes from the palette RowLayout with no
                            // implicit-size feedback path — and this
                            // exact taper (width−3 over 3.2 weights)
                            // is the reference look. Verified: no
                            // polish() warnings from this item.
                            Row {
                                id: shadeStrip
                                Layout.fillWidth: true
                                height: 18
                                spacing: 1
                                Repeater {
                                    model: [0, 1, 3, 4]   // ramp sans base
                                    delegate: Rectangle {
                                        id: rampSw
                                        required property int index
                                        required property int modelData
                                        objectName: "explorer-ramp-swatch"
                                        readonly property real w:
                                            [0.6, 1.0, 1.0, 0.6][index]
                                        width: shadeStrip.width > 0
                                               ? (shadeStrip.width - 3)
                                                 * w / 3.2 : 0
                                        height: shadeStrip.height
                                        color: explorerRoot.simColor(
                                            stripCol.modelData.ramp[
                                                rampSw.modelData])
                                        MouseArea {
                                            id: rampMa
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: explorerRoot.openInfo(
                                                stripCol.index,
                                                rampSw.modelData)
                                        }
                                        ToolTip.visible: rampMa.containsMouse
                                        ToolTip.delay: 120
                                        ToolTip.text:
                                            stripCol.modelData.ramp[
                                                rampSw.modelData].toUpperCase()
                                    }
                                }
                            }
                        }
                    }
                }

                // preview: the palette laid out as a mock composition —
                // one large block per color, scattered with its ramp
                // shades (the reference PREVIEW/EXAMPLES area)
                ColumnLayout {
                    id: previewArea
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 10
                    Repeater {
                        model: {
                            var n = colorex !== null
                                    ? colorex.colors.length : 0
                            return Math.max(1, Math.ceil(n / 2))
                        }
                        delegate: RowLayout {
                            id: previewRow
                            required property int index
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 10
                            Repeater {
                                model: 2
                                delegate: Rectangle {
                                    id: blockCell
                                    required property int index
                                    readonly property int colorIdx:
                                        previewRow.index * 2 + blockCell.index
                                    readonly property bool has:
                                        colorex !== null && colorIdx >= 0
                                        && colorIdx < colorex.colors.length
                                    readonly property var col:
                                        has ? colorex.colors[colorIdx] : null
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    visible: has
                                    radius: 10
                                    clip: true
                                    color: col !== null
                                           ? explorerRoot.simColor(col.hex)
                                           : "transparent"
                                    border.color: theme.tokens.border
                                    Repeater {
                                        model: [
                                            { x: 5, y: 8, w: 24, h: 12, r: 0 },
                                            { x: 66, y: 8, w: 29, h: 18, r: 1 },
                                            { x: 5, y: 26, w: 14, h: 34, r: 3 },
                                            { x: 78, y: 40, w: 17, h: 40, r: 4 },
                                            { x: 26, y: 40, w: 30, h: 22, r: 2 },
                                            { x: 5, y: 80, w: 30, h: 12, r: 4 },
                                            { x: 42, y: 78, w: 20, h: 14, r: 1 }
                                        ]
                                        delegate: Rectangle {
                                            required property var modelData
                                            x: modelData.x / 100 * parent.width
                                            y: modelData.y / 100 * parent.height
                                            width: modelData.w / 100
                                                   * parent.width
                                            height: modelData.h / 100
                                                    * parent.height
                                            radius: 3
                                            color: blockCell.col !== null
                                                   ? explorerRoot.simColor(
                                                       blockCell.col.ramp[
                                                           modelData.r])
                                                   : "transparent"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // footer: vision simulation (eye) · tables / export
                RowLayout {
                    Layout.fillWidth: true
                    IconButton {
                        icon_name: "eye"
                        icon_px: 14
                        implicitWidth: 24
                        implicitHeight: 24
                        ToolTip.text: qsTr("Vision simulation")
                        onClicked: visionMenu.popup()
                    }
                    ExpTextButton {
                        label: visionMode === "none"
                               ? qsTr("Vision simulation")
                               : (visionMode === "protanopia"
                                  ? qsTr("Vision: protanopia")
                                  : visionMode === "deuteranopia"
                                    ? qsTr("Vision: deuteranopia")
                                    : qsTr("Vision: tritanopia"))
                        tip: qsTr("Preview the palette through common"
                                  + " color-vision deficiencies")
                        onClicked: visionMenu.popup()
                    }
                    Item { Layout.fillWidth: true }
                    ExpTextButton {
                        label: qsTr("Tables / Export…")
                        tip: qsTr("Per-color shade tables and the shared"
                                  + " export formats")
                        onClicked: tablesDialog.open()
                    }
                }
            }
        }
    }

    // ── vision simulation ──
    // Machado-style linear-RGB approximation matrices
    readonly property var simMatrices: ({
        "protanopia": [[0.567, 0.433, 0.0],
                       [0.558, 0.442, 0.0],
                       [0.0, 0.242, 0.758]],
        "deuteranopia": [[0.625, 0.375, 0.0],
                         [0.700, 0.300, 0.0],
                         [0.0, 0.300, 0.700]],
        "tritanopia": [[0.950, 0.050, 0.0],
                       [0.0, 0.433, 0.567],
                       [0.0, 0.475, 0.525]]
    })
    property string visionMode: "none"
    function simColor(hex) {
        if (visionMode === "none" || visionMode === undefined)
            return hex
        var m = simMatrices[visionMode]
        if (m === undefined)
            return hex
        var rgb = hexRgb(hex)
        var lin = []
        for (var i = 0; i < 3; i++) {
            var c = rgb[i] / 255
            lin.push(c <= 0.04045 ? c / 12.92
                                  : Math.pow((c + 0.055) / 1.055, 2.4))
        }
        var out = "#"
        for (i = 0; i < 3; i++) {
            var v = m[i][0] * lin[0] + m[i][1] * lin[1] + m[i][2] * lin[2]
            v = Math.max(0, Math.min(1, v))
            v = v <= 0.0031308 ? v * 12.92
                               : 1.055 * Math.pow(v, 1 / 2.4) - 0.055
            var s = Math.round(v * 255).toString(16)
            out += s.length < 2 ? "0" + s : s
        }
        return out
    }
    Menu {
        id: visionMenu
        MenuItem {
            text: qsTr("Normal vision")
            checkable: true
            checked: explorerRoot.visionMode === "none"
            onTriggered: explorerRoot.visionMode = "none"
        }
        MenuSeparator {}
        MenuItem {
            text: qsTr("Protanopia (no red)")
            checkable: true
            checked: explorerRoot.visionMode === "protanopia"
            onTriggered: explorerRoot.visionMode = "protanopia"
        }
        MenuItem {
            text: qsTr("Deuteranopia (no green)")
            checkable: true
            checked: explorerRoot.visionMode === "deuteranopia"
            onTriggered: explorerRoot.visionMode = "deuteranopia"
        }
        MenuItem {
            text: qsTr("Tritanopia (no blue)")
            checkable: true
            checked: explorerRoot.visionMode === "tritanopia"
            onTriggered: explorerRoot.visionMode = "tritanopia"
        }
    }

    // ── color info dialog ──
    property var infoData: null
    property int infoIdx: -1
    property int infoRamp: 2
    function openInfo(idx, rampIdx) {
        if (colorex === null)
            return
        explorerRoot.infoIdx = idx
        explorerRoot.infoRamp = rampIdx
        explorerRoot.infoData = colorex.color_info(idx, rampIdx)
        infoDialog.open()
    }
    function applyInfoBase() {
        if (colorex === null || explorerRoot.infoData === null)
            return
        if (explorerRoot.infoRamp === 2)
            colorex.set_as_base(explorerRoot.infoIdx)
        else
            colorex.set_base_hsl(explorerRoot.infoData.h,
                                 explorerRoot.infoData.s,
                                 explorerRoot.infoData.l)
    }

    FormDialog {
        id: infoDialog
        objectName: "explorer-info-dialog"
        heading: explorerRoot.infoData !== null
                 ? explorerRoot.infoData.name : ""
        acceptLabel: qsTr("Set as Base Color")
        cancelLabel: qsTr("Close")
        width: 360
        onApply: explorerRoot.applyInfoBase()

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 56
            radius: 8
            color: explorerRoot.infoData !== null
                   ? explorerRoot.infoData.hex : "transparent"
            border.color: theme.tokens.border
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: explorerRoot.infoData !== null
                      ? explorerRoot.infoData.hex : ""
                font.family: theme.monoFont
                font.pixelSize: 14
                font.weight: Font.DemiBold
                color: explorerRoot.infoData !== null
                       ? explorerRoot.infoData.ink : theme.tokens.text
            }
            // "Apply as base color" rides on the swatch itself (the
            // reference dialog's placement)
            AbstractButton {
                id: applyBaseBtn
                objectName: "explorer-info-apply-base"
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 7
                implicitWidth: applyBaseLbl.implicitWidth + 20
                implicitHeight: 24
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                onClicked: explorerRoot.applyInfoBase()
                background: Rectangle {
                    radius: 6
                    color: applyBaseBtn.hovered
                           ? Qt.rgba(0, 0, 0, 0.55)
                           : Qt.rgba(0, 0, 0, 0.4)
                    border.color: Qt.rgba(1, 1, 1, 0.25)
                }
                contentItem: Text {
                    id: applyBaseLbl
                    text: qsTr("Apply as base color")
                    font.family: theme.uiFont
                    font.pixelSize: 10
                    color: "#FFFFFF"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                ToolTip.visible: applyBaseBtn.hovered
                ToolTip.delay: 350
                ToolTip.text: qsTr("Make this color the palette's base")
            }
        }

        InfoRow { label: qsTr("HEX"); value: infoVal("hex") }
        InfoRow {
            label: qsTr("HSL")
            value: infoData !== null
                   ? infoData.h + "°, " + infoData.s + "%, " + infoData.l
                     + "%" : ""
        }
        InfoRow {
            label: qsTr("RGB")
            value: infoData !== null
                   ? infoData.r + ", " + infoData.g + ", " + infoData.b : ""
        }
        InfoRow {
            label: qsTr("LAB")
            value: infoData !== null
                   ? "L* " + infoData.lab_l + "  a* " + infoData.lab_a
                     + "  b* " + infoData.lab_b : ""
        }
        InfoRow {
            label: qsTr("Contrast")
            copyable: false
            value: infoData !== null
                   ? qsTr("on white %1 · on ink %2").arg(infoData.cw)
                     .arg(infoData.cb) : ""
        }
    }

    component InfoRow: RowLayout {
        id: infoRow
        property string label
        property string value
        property bool copyable: true
        Text {
            text: infoRow.label
            font.family: theme.uiFont
            font.pixelSize: 11
            color: theme.tokens.textMuted
            Layout.preferredWidth: 76
        }
        Text {
            text: infoRow.value
            font.family: theme.monoFont
            font.pixelSize: 12
            color: theme.tokens.text
            Layout.fillWidth: true
            elide: Text.ElideRight
        }
        IconButton {
            visible: infoRow.copyable
            objectName: "explorer-info-copy-" + infoRow.label
            icon_name: "copy"
            icon_px: 12
            implicitWidth: 22
            implicitHeight: 22
            ToolTip.text: qsTr("Copy value")
            onClicked: colorex !== null && infoRow.value !== ""
                       && colorex.copy_value(infoRow.value)
        }
    }

    function infoVal(key) {
        return infoData !== null ? String(infoData[key]).toUpperCase() : ""
    }

    // ── fine tune dialog: 4 rows × ±1/±5/±10 step buttons ──
    Dialog {
        id: fineTuneDialog
        objectName: "explorer-finetune-dialog"
        modal: true
        dim: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 320
        padding: 14
        background: Rectangle {
            radius: 12
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        contentItem: ColumnLayout {
            spacing: 10
            RowLayout {
                Text {
                    text: qsTr("Palette Fine Tune")
                    font.family: theme.headingFont
                    font.pixelSize: 13
                    font.letterSpacing: 1.2
                    font.capitalization: Font.AllUppercase
                    color: theme.tokens.text
                    Layout.fillWidth: true
                }
                IconButton {
                    icon_name: "x"
                    icon_px: 12
                    implicitWidth: 22
                    implicitHeight: 22
                    onClicked: fineTuneDialog.close()
                }
            }
            Repeater {
                model: [
                    { row: "hue", label: qsTr("Hue") },
                    { row: "saturation", label: qsTr("Saturation") },
                    { row: "brightness", label: qsTr("Brightness") },
                    { row: "contrast", label: qsTr("Contrast") }
                ]
                delegate: ColumnLayout {
                    id: ftRow
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 3
                    RowLayout {
                        spacing: 4
                        Repeater {
                            // inner Repeater shadows the outer modelData —
                            // read the row label off ftRow (gotcha 8)
                            model: [-10, -5, -1, 1, 5, 10]
                            delegate: AbstractButton {
                                id: ftBtn
                                required property int index
                                required property int modelData
                                objectName: "explorer-ft-"
                                            + ftRow.modelData.row + "-"
                                            + ftBtn.modelData
                                Layout.preferredWidth: 44
                                Layout.preferredHeight: 24
                                HoverHandler {
                                    cursorShape: Qt.PointingHandCursor
                                }
                                onClicked: colorex !== null
                                    && colorex.fine_tune(
                                        ftRow.modelData.row, ftBtn.modelData)
                                background: Rectangle {
                                    radius: 5
                                    color: ftBtn.hovered
                                           ? theme.tokens.surface2
                                           : theme.tokens.surface
                                    border.color: theme.tokens.border
                                }
                                contentItem: Text {
                                    text: (ftBtn.modelData > 0 ? "+" : "")
                                          + ftBtn.modelData
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: theme.tokens.text
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }
                    }
                    Text {
                        text: modelData.label
                        font.family: theme.uiFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                        Layout.alignment: Qt.AlignHCenter
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ExpTextButton {
                    label: qsTr("Reset tuning")
                    tip: qsTr("Clear every accumulated fine-tune delta")
                    onClicked: colorex !== null && colorex.reset_fine_tune()
                }
                Item { Layout.fillWidth: true }
                FgButton {
                    text: qsTr("Close")
                    onClicked: fineTuneDialog.close()
                }
            }
        }
    }

    // ── dist popup: slider + default reset ──
    Popup {
        id: distPopup
        objectName: "explorer-dist-popup"
        width: 210
        padding: 10
        // window-overlay parent so the chip's scene position (set at
        // open time) maps 1:1 onto the popup's x/y — Popup has NO
        // popup(parent, x, y) convenience (that's Menu's), so the chip
        // click positions it explicitly
        parent: Overlay.overlay
        background: Rectangle {
            radius: 8
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        contentItem: ColumnLayout {
            spacing: 6
            FgSlider {
                id: distSlider
                Layout.fillWidth: true
                // Distance is the arc around the wheel from the base
                // color — each model validates its own range (triad's
                // pair flanks the opposite point: 120..180)
                from: colorex !== null ? colorex.distLo : 0
                to: colorex !== null ? colorex.distHi : 90
                stepSize: 1
                value: colorex !== null ? colorex.dist : 30
                onMoved: colorex !== null && colorex.set_dist(value)
                // a drag kills the `value` binding (Qt slider gotcha) —
                // re-sync from the bridge while the user isn't dragging
                Connections {
                    target: colorex
                    function onStateChanged() {
                        if (!distSlider.pressed)
                            distSlider.value = colorex.dist
                    }
                }
            }
            RowLayout {
                Text {
                    text: distSlider.value + "°"
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                }
                Item { Layout.fillWidth: true }
                ExpTextButton {
                    label: colorex !== null
                           ? qsTr("default: %1°").arg(colorex.distDefault)
                           : qsTr("default: 30°")
                    onClicked: {
                        if (colorex !== null) {
                            distSlider.value = colorex.distDefault
                            colorex.set_dist(colorex.distDefault)
                        }
                    }
                }
            }
        }
    }

    // ── tables / export dialog: one 5-shade table per palette color ──
    Dialog {
        id: tablesDialog
        objectName: "explorer-tables-dialog"
        modal: true
        dim: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 640
        height: 520
        padding: 14
        background: Rectangle {
            radius: 12
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        contentItem: ColumnLayout {
            spacing: 10
            RowLayout {
                Text {
                    text: qsTr("Color tables & export")
                    font.family: theme.headingFont
                    font.pixelSize: 13
                    font.letterSpacing: 1.2
                    font.capitalization: Font.AllUppercase
                    color: theme.tokens.text
                    Layout.fillWidth: true
                }
                IconButton {
                    icon_name: "x"
                    icon_px: 12
                    implicitWidth: 22
                    implicitHeight: 22
                    onClicked: tablesDialog.close()
                }
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: tablesDialog.availableWidth - 28
                    spacing: 14
                    Repeater {
                        model: colorex !== null ? colorex.colors : []
                        delegate: ColumnLayout {
                            id: tableCol
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            spacing: 4
                            Text {
                                text: {
                                    var cols = colorex !== null
                                        ? colorex.colors : []
                                    if (tableCol.modelData.is_base)
                                        return qsTr("Primary color")
                                    if (tableCol.modelData.is_comp)
                                        return qsTr("Complement color")
                                    var n = 0
                                    for (var i = 1; i <= tableCol.index; i++)
                                        if (!cols[i].is_base
                                                && !cols[i].is_comp)
                                            n++
                                    return qsTr("Secondary color #%1").arg(n)
                                }
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.textMuted
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Repeater {
                                    model: 5
                                    delegate: ColumnLayout {
                                        id: segCol
                                        required property int index
                                        readonly property real w: [0.6, 1.0, 1.6, 1.0, 0.6][index]
                                        readonly property string hx: tableCol.modelData.ramp[index]
                                        readonly property var rgb: explorerRoot.hexRgb(segCol.hx)
                                        Layout.fillWidth: true
                                        spacing: 1
                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 34
                                            color: segCol.hx
                                        }
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            text: segCol.hx.toUpperCase()
                                            font.family: theme.monoFont
                                            font.pixelSize: 9
                                            color: theme.tokens.text
                                        }
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            text: qsTr("RGB: %1-%2-%3").arg(
                                                segCol.rgb[0]).arg(
                                                segCol.rgb[1]).arg(
                                                segCol.rgb[2])
                                            font.family: theme.monoFont
                                            font.pixelSize: 8
                                            color: theme.tokens.textMuted
                                        }
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            text: qsTr("RGB [%]: %1-%2-%3").arg(
                                                (segCol.rgb[0] / 255 * 100)
                                                .toFixed(1)).arg(
                                                (segCol.rgb[1] / 255 * 100)
                                                .toFixed(1)).arg(
                                                (segCol.rgb[2] / 255 * 100)
                                                .toFixed(1))
                                            font.family: theme.monoFont
                                            font.pixelSize: 8
                                            color: theme.tokens.textMuted
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                FgButton {
                    text: qsTr("Export…")
                    onClicked: {
                        tablesDialog.close()
                        explorerExport.openWith([
                            { id: "css", label: "CSS" },
                            { id: "json", label: "JSON" },
                            { id: "svg", label: "SVG board" },
                            { id: "png", label: "PNG board" }
                        ], explorerRoot.exportDest)
                        explorerExport.selectedFormats = ["css"]
                    }
                }
                Item { Layout.fillWidth: true }
                FgButton {
                    text: qsTr("Close")
                    onClicked: tablesDialog.close()
                }
            }
        }
    }

    property string exportDest: ""
    ExportDialog {
        id: explorerExport
        headline: qsTr("Export palette")
        onDoExport: function (formats, dest) {
            explorerRoot.exportDest = dest
            for (var i = 0; i < formats.length; i++)
                colorex !== null && colorex.export(formats[i], dest)
        }
    }

    function hexRgb(hx) {
        var h = String(hx).replace("#", "")
        if (h.length === 3)
            h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2]
        return [parseInt(h.substring(0, 2), 16),
                parseInt(h.substring(2, 4), 16),
                parseInt(h.substring(4, 6), 16)]
    }

    // GenButton-style quiet text button (local copy — the original lives
    // inside Colors.qml)
    component ExpTextButton: AbstractButton {
        id: expB
        property string label
        property string tip: ""
        implicitHeight: 24
        contentItem: Text {
            text: expB.label
            color: expB.hovered ? theme.tokens.text : theme.tokens.textMuted
            font.family: theme.uiFont
            font.pixelSize: 11
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            leftPadding: 8
            rightPadding: 8
        }
        background: Rectangle {
            radius: 6
            color: expB.pressed ? theme.tokens.surface2
                                : (expB.hovered ? theme.tokens.surface2
                                                : "transparent")
            border.color: expB.hovered ? theme.tokens.accentColor
                                       : theme.tokens.border
        }
        ToolTip.visible: expB.tip !== "" && expB.hovered
        ToolTip.delay: 350
        ToolTip.text: expB.tip
    }
}
