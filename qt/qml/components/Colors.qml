import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// Colors pane (M3): harmony generator, HSL/hex editor, WCAG readouts,
// saved palettes (library SQLite), CSS/JSON/SVG/PNG board exports.
// Ported from the 0.x colors.html; the math lives in core/colors.py.
Item {
    id: colorsRoot

    // `colors !== null` guards: context properties are nulled during app
    // teardown while lingering bindings re-evaluate (same as SideRail)
    Rectangle {
        id: genBar
        height: 44
        color: theme.tokens.surface
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 10
            spacing: 10

            ComboBox {
                id: ruleBox
                Layout.preferredWidth: 150
                Layout.preferredHeight: 28
                model: [qsTr("Pleasing mix"), qsTr("Analogous"),
                        qsTr("Complementary"), qsTr("Triadic"),
                        qsTr("Monochrome")]
                currentIndex: {
                    var rules = ["pleasing", "analogous", "complementary",
                                 "triadic", "monochrome"]
                    return colors !== null
                           ? Math.max(0, rules.indexOf(colors.rule)) : 0
                }
                onActivated: function (idx) {
                    var rules = ["pleasing", "analogous", "complementary",
                                 "triadic", "monochrome"]
                    if (colors !== null)
                        colors.set_rule(rules[idx])
                }
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
                contentItem: Text {
                    text: ruleBox.displayText
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8
                }
            }

            Button {
                id: genBtn
                text: qsTr("Generate  ␣")
                onClicked: colors !== null && colors.generate()
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.accent
                }
                contentItem: Text {
                    text: genBtn.text
                    color: theme.tokens.bg
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 12; rightPadding: 12
                }
            }

            Rectangle {
                id: nameBox
                Layout.preferredWidth: 170
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: nameField.activeFocus ? theme.tokens.accent
                                                    : theme.tokens.border
                TextInput {
                    id: nameField
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                    text: colors !== null ? colors.paletteName : ""
                    onTextEdited: colors !== null && colors.set_name(text)
                }
                Text {
                    visible: nameField.text === ""
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("palette name…")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }

            Rectangle {
                Layout.preferredWidth: 150
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: tagsField.activeFocus ? theme.tokens.accent
                                                    : theme.tokens.border
                TextInput {
                    id: tagsField
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                }
                Text {
                    visible: tagsField.text === ""
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("tags (comma-separated)")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }

            component GenButton: AbstractButton {
                id: genB
                property string label
                implicitHeight: 26
                contentItem: Text {
                    text: genB.label
                    color: genB.hovered ? theme.tokens.text : theme.tokens.textMuted
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8; rightPadding: 8
                }
                background: Rectangle {
                    radius: 6
                    color: genB.pressed ? theme.tokens.surface2
                                        : (genB.hovered ? theme.tokens.surface2
                                                        : "transparent")
                    border.color: genB.hovered ? theme.tokens.accent
                                               : theme.tokens.border
                }
            }
            GenButton {
                label: qsTr("Save")
                onClicked: colors !== null && colors.save(tagsField.text)
            }
            GenButton {
                label: qsTr("CSS")
                onClicked: { exportKind = "css"; exportDialog.open() }
            }
            GenButton {
                label: qsTr("JSON")
                onClicked: { exportKind = "json"; exportDialog.open() }
            }
            GenButton {
                label: qsTr("SVG")
                onClicked: { exportKind = "svg"; exportDialog.open() }
            }
            GenButton {
                label: qsTr("PNG")
                onClicked: { exportKind = "png"; exportDialog.open() }
            }
        }
    }

    // editor sync: dragged sliders lose their `val` bindings, so values are
    // assigned imperatively; the hex field only follows selection changes —
    // rebuilding it on every swatch change would fight the user mid-typing
    // (the 0.x editor kept the field intact while typing, colors.html:429-431)
    function syncSliders() {
        if (colors === null || colors.selectedIdx < 0)
            return
        var s = colors.swatches[colors.selectedIdx]
        hSlider.val = s.h
        sSlider.val = s.s
        lSlider.val = s.l
    }
    function syncEditor() {
        syncSliders()
        if (colors !== null && colors.selectedIdx >= 0)
            hexField.text = colors.swatches[colors.selectedIdx].hex
    }
    function applyHsl() {
        if (colors === null || colors.selectedIdx < 0)
            return
        colors.set_hsl(colors.selectedIdx, hSlider.val, sSlider.val,
                       lSlider.val)
    }
    Connections {
        target: colors
        function onSelectionChanged() { syncEditor() }
        function onSwatchesChanged() {
            if (hSlider.pressed || sSlider.pressed || lSlider.pressed)
                return  // mid-drag: keep the user's values
            syncSliders()
        }
    }

    // export kind set by whichever button opened the dialog
    property string exportKind: "css"
    FolderDialog {
        id: exportDialog
        onAccepted: colors !== null && colors.export(
            colorsRoot.exportKind, Icons.toLocalPath(selectedFolder))
    }

    ListView {
        id: savedStrip
        orientation: ListView.Horizontal
        height: colors !== null && colors.palettes.length > 0 ? 92 : 0
        visible: height > 0
        anchors.bottom: editorStrip.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 8
        clip: true
        spacing: 8
        model: colors !== null ? colors.palettes : []

        delegate: Rectangle {
            id: palCard
            required property var modelData
            required property int index

            width: 150
            height: 84
            radius: 8
            color: theme.tokens.surface
            border.color: theme.tokens.border

            Row {
                id: strip
                anchors.top: parent.top
                anchors.topMargin: 8
                anchors.left: parent.left
                anchors.leftMargin: 8
                anchors.right: parent.right
                anchors.rightMargin: 8
                height: 20
                spacing: 2
                Repeater {
                    // modelData would be shadowed by this Repeater's int
                    // model inside the delegate — read it off palCard
                    model: palCard.modelData.colors.length
                    Rectangle {
                        required property int index
                        width: (strip.width - 4 * 2) / 5
                        height: parent.height
                        radius: 3
                        color: palCard.modelData.colors[index]
                    }
                }
            }
            Text {
                anchors.top: strip.bottom
                anchors.topMargin: 4
                anchors.left: parent.left
                anchors.leftMargin: 8
                anchors.right: delBtn.left
                text: modelData.name
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.text
                elide: Text.ElideRight
            }
            Text {
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 6
                anchors.left: parent.left
                anchors.leftMargin: 8
                text: modelData.colors.length + qsTr(" colors · ") +
                      (modelData.tags || "")
                font.family: theme.monoFont
                font.pixelSize: 9
                color: theme.tokens.textMuted
                elide: Text.ElideRight
                width: parent.width - 16
            }
            IconButton {
                id: delBtn
                anchors.top: parent.top
                anchors.topMargin: 6
                anchors.right: parent.right
                anchors.rightMargin: 6
                icon_name: "trash"
                icon_px: 12
                implicitWidth: 22
                implicitHeight: 22
                ToolTip.text: qsTr("Delete palette")
                onClicked: colors !== null
                           && colors.delete_palette(modelData.id)
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: colors !== null && colors.open_palette(modelData.id)
                z: -1
            }
        }
        Text {
            anchors.centerIn: parent
            visible: savedStrip.height > 0 && savedStrip.count === 0
            text: qsTr("No palettes yet")
            font.family: theme.uiFont
            font.pixelSize: 11
            color: theme.tokens.textMuted
        }
    }

    // editor strip for the selected swatch
    Rectangle {
        id: editorStrip
        height: colors !== null && colors.selectedIdx >= 0 ? 56 : 0
        visible: height > 0
        color: theme.tokens.surface
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 10
            visible: editorStrip.height > 0

            IconButton {
                icon_name: "chevron-left"
                ToolTip.text: qsTr("Move left")
                onClicked: colors !== null && colors.move_swatch(
                    colors.selectedIdx, colors.selectedIdx - 1)
            }
            IconButton {
                icon_name: "chevron-right"
                ToolTip.text: qsTr("Move right")
                onClicked: colors !== null && colors.move_swatch(
                    colors.selectedIdx, colors.selectedIdx + 1)
            }

            component EditSlider: RowLayout {
                property string label
                property real val
                property real maxVal
                signal edited(real v)
                Text {
                    text: parent.label
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.textMuted
                }
                Slider {
                    id: es
                    Layout.preferredWidth: 140
                    from: 0; to: parent.maxVal
                    value: parent.val
                    onMoved: parent.edited(value)
                }
                Text {
                    text: Math.round(parent.val)
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.text
                    Layout.preferredWidth: 26
                }
            }
            EditSlider {
                id: hSlider
                label: "H"; maxVal: 360
                onEdited: val => applyHsl()
            }
            EditSlider {
                id: sSlider
                label: "S"; maxVal: 100
                onEdited: val => applyHsl()
            }
            EditSlider {
                id: lSlider
                label: "L"; maxVal: 100
                onEdited: val => applyHsl()
            }

            Rectangle {
                Layout.preferredWidth: 90
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: hexField.activeFocus ? theme.tokens.accent
                                                   : theme.tokens.border
                TextInput {
                    id: hexField
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                    onAccepted: colors !== null && colors.selectedIdx >= 0
                                && colors.set_hex(colors.selectedIdx, text)
                }
            }
            Item { Layout.fillWidth: true }
            IconButton {
                icon_name: "x"
                ToolTip.text: qsTr("Close editor")
                onClicked: colors !== null && colors.select(colors.selectedIdx)
            }
        }
    }

    // the palette row: five swatch cards
    RowLayout {
        id: paletteRow
        spacing: 8
        anchors.top: genBar.bottom
        anchors.bottom: savedStrip.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 10

        Repeater {
            model: colors !== null ? colors.swatches : []

            Rectangle {
                id: swCard
                required property var modelData
                required property int index
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 10
                color: modelData.hex
                border.color: colors !== null && colors.selectedIdx === index
                              ? theme.tokens.litPane : "transparent"
                border.width: 2

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 12
                    spacing: 2
                    Text {
                        text: modelData.hex.toUpperCase()
                        font.family: theme.monoFont
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        color: modelData.ink
                    }
                    Text {
                        text: modelData.name
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: modelData.ink
                        opacity: 0.75
                    }
                    Text {
                        text: "C/W " + modelData.cw.toFixed(1) + " "
                              + modelData.wcagW + " · C/B "
                              + modelData.cb.toFixed(1) + " " + modelData.wcagB
                        font.family: theme.monoFont
                        font.pixelSize: 9
                        color: modelData.ink
                        opacity: 0.7
                    }
                }

                Row {
                    id: tools
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    spacing: 4
                    opacity: swMa.containsMouse ? 1 : 0

                    component SwTool: AbstractButton {
                        id: st
                        property string icon_name
                        width: 24; height: 24
                        contentItem: IconImage {
                            name: st.icon_name
                            px: 11
                            tint: "#FFFFFF"
                            anchors.centerIn: parent
                        }
                        background: Rectangle {
                            radius: 6
                            color: st.hovered ? "#40000000" : "#25000000"
                        }
                    }
                    SwTool {
                        icon_name: swCard.modelData.locked ? "lock" : "unlock"
                        onClicked: colors !== null && colors.toggle_lock(
                            swCard.index)
                    }
                    SwTool {
                        icon_name: "x"
                        onClicked: colors !== null && colors.remove_swatch(
                            swCard.index)
                    }
                }

                MouseArea {
                    id: swMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: colors !== null && colors.select(swCard.index)
                }
            }
        }
    }

    // space = reroll (only when this pane is visible and no field is in edit)
    Shortcut {
        sequence: "Space"
        enabled: colorsRoot.visible && !nameField.activeFocus
                 && !tagsField.activeFocus && !hexField.activeFocus
        onActivated: colors !== null && colors.generate()
    }
}
