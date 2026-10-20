import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Font details screen: opens for the selected family — per-variant
// specimen rows with custom sizing, sample text, and a dark/light preview
// background so designers can judge a face in context.
Popup {
    id: detail

    property string family: ""
    property real previewPx: 30
    property bool darkBg: true
    property string sample: "The quick brown fox jumps over the lazy dog"
    readonly property var variants: fonts !== null && family !== ""
                                    ? fonts.family_files(family) : []

    // 100..900 CSS weights → Qt font weights
    function weightEnum(w) {
        var map = {}
        map[100] = Font.Thin; map[200] = Font.ExtraLight
        map[300] = Font.Light; map[400] = Font.Normal
        map[500] = Font.Medium; map[600] = Font.DemiBold
        map[700] = Font.Bold; map[800] = Font.ExtraBold
        map[900] = Font.Black
        return map[w] !== undefined ? map[w] : Font.Normal
    }

    width: Math.min(860, parent ? parent.width - 60 : 800)
    height: Math.min(640, parent ? parent.height - 60 : 600)
    modal: true
    anchors.centerIn: parent
    padding: 16
    background: Rectangle {
        radius: 12
        color: theme.tokens.surface
        border.color: theme.tokens.border
    }

    contentItem: ColumnLayout {
        spacing: 10

        // header
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: detail.family
                font.family: detail.family
                font.pixelSize: 22
                color: theme.tokens.text
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            IconButton {
                icon_name: "x"
                ToolTip.text: qsTr("Close")
                onClicked: detail.close()
            }
        }

        // controls: size, sample, background
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Text {
                text: qsTr("size")
                font.family: theme.monoFont; font.pixelSize: 10
                color: theme.tokens.textMuted
            }
            Slider {
                id: sizeSlider
                Layout.preferredWidth: 170
                from: 10; to: 96; stepSize: 1
                value: detail.previewPx
                onMoved: detail.previewPx = value
            }
            Text {
                text: Math.round(detail.previewPx) + "px"
                font.family: theme.monoFont; font.pixelSize: 10
                color: theme.tokens.text
                Layout.preferredWidth: 34
            }
            TextField {
                id: sampleField
                Layout.fillWidth: true
                text: detail.sample
                onTextEdited: detail.sample = text
                placeholderText: qsTr("type your own sample…")
                font.family: theme.monoFont; font.pixelSize: 11
                color: theme.tokens.text
                background: Rectangle {
                    radius: 6; color: theme.tokens.surface2
                    border.color: sampleField.activeFocus
                                  ? theme.tokens.accent : theme.tokens.border
                }
            }
            Button {
                checkable: true
                checked: detail.darkBg
                text: checked ? qsTr("Dark bg") : qsTr("Light bg")
                onClicked: detail.darkBg = !detail.darkBg
                background: Rectangle {
                    radius: 6
                    color: parent.checked ? "#101418" : "#FFFFFF"
                    border.color: theme.tokens.border
                }
                contentItem: Text {
                    text: parent.text
                    color: parent.checked ? "#F5C25C" : "#16202B"
                    font.family: theme.monoFont; font.pixelSize: 10
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8; rightPadding: 8
                }
            }
        }

        // variant specimens
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentHeight: varCol.implicitHeight + 16
            ScrollBar.vertical: ScrollBar { }

            ColumnLayout {
                id: varCol
                width: detail.availableWidth - 4
                spacing: 14

                Text {
                    text: detail.variants.length + " variant"
                          + (detail.variants.length === 1 ? "" : "s")
                          + " · alphabetical preview at "
                          + Math.round(detail.previewPx) + "px"
                    font.family: theme.monoFont; font.pixelSize: 10
                    color: theme.tokens.textMuted
                }

                // glyph sentence
                Rectangle {
                    Layout.fillWidth: true
                    height: glRow.implicitHeight + 20
                    radius: 8
                    color: detail.darkBg ? "#101418" : "#FFFFFF"
                    border.color: theme.tokens.border
                    ColumnLayout {
                        id: glRow
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 2
                        Text {
                            text: detail.sample
                            font.family: detail.family
                            font.pixelSize: Math.min(detail.previewPx, 46)
                            color: detail.darkBg ? "#E7EDF2" : "#16202B"
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        Text {
                            text: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 &!?%()[]{}@#*"
                            font.family: detail.family
                            font.pixelSize: Math.min(detail.previewPx * 0.6, 22)
                            color: detail.darkBg ? "#8DA0AF" : "#6B7A88"
                            wrapMode: Text.WrapAnywhere
                            Layout.fillWidth: true
                        }
                    }
                }

                // every indexed variant, rendered in its own style
                Repeater {
                    model: detail.variants
                    Rectangle {
                        id: varRow
                        required property var modelData
                        Layout.fillWidth: true
                        height: specCol.implicitHeight + 18
                        radius: 8
                        color: detail.darkBg ? "#101418" : "#FFFFFF"
                        border.color: theme.tokens.border
                        ColumnLayout {
                            id: specCol
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: varRow.modelData.style || "Regular"
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: detail.darkBg ? "#F5C25C" : "#A16207"
                                }
                                Text {
                                    text: "weight " + (varRow.modelData.weight || 400)
                                          + (varRow.modelData.italic ? " · italic" : "")
                                          + " · " + varRow.modelData.name
                                          + "." + (varRow.modelData.ext || "ttf")
                                    font.family: theme.monoFont
                                    font.pixelSize: 9
                                    color: detail.darkBg ? "#8DA0AF" : "#6B7A88"
                                }
                                Item { Layout.fillWidth: true }
                            }
                            Text {
                                text: detail.sample
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                font.family: detail.family
                                font.pixelSize: detail.previewPx
                                font.weight: detail.weightEnum(
                                                 varRow.modelData.weight || 400)
                                font.italic: !!varRow.modelData.italic
                                color: detail.darkBg ? "#E7EDF2" : "#16202B"
                            }
                        }
                    }
                }

                Text {
                    visible: detail.variants.length === 0
                    text: qsTr("No indexed files for this family")
                    font.family: theme.uiFont; font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }
        }
    }
}
