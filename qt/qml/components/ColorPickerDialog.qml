import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// Visual color picker: preset swatch grid + synced HEX entry.
// Follows the app's dialog idiom (surface, border, FgDialogFooter).
Dialog {
    id: colorPickerRoot

    property string currentHex: "#3388cc"
    signal acceptedHex(string hex)

    width: 380
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    padding: 16
    background: Rectangle {
        radius: 12
        color: theme.tokens.surface
        border.color: theme.tokens.border
    }

    function openWith(initialHex) {
        currentHex = initialHex || "#3388cc"
        hexInput.text = currentHex.toUpperCase()
        open()
    }

    contentItem: ColumnLayout {
        spacing: 12

        Text {
            text: qsTr("Select Color")
            font.family: theme.headingFont
            font.pixelSize: 14
            font.letterSpacing: 1.2
            font.capitalization: Font.AllUppercase
            color: theme.tokens.text
        }

        // preset swatches: 32 curated colors across the hue wheel
        GridLayout {
            Layout.fillWidth: true
            columns: 8
            rowSpacing: 6
            columnSpacing: 6
            Repeater {
                model: [
                    "#FF0000", "#FF4500", "#FF8C00", "#FFD700",
                    "#FFFF00", "#ADFF2F", "#00FF00", "#00FF7F",
                    "#00FFFF", "#1E90FF", "#0000FF", "#8A2BE2",
                    "#FF00FF", "#FF69B4", "#FFFFFF", "#C0C0C0",
                    "#808080", "#404040", "#000000", "#8B4513",
                    "#F5F5DC", "#FFE4C4", "#FFC0CB", "#E6E6FA",
                    "#90EE90", "#87CEEB", "#FFA07A", "#20B2AA",
                    "#FA8072", "#B0C4DE", "#D2691E", "#483D8B"
                ]
                delegate: Rectangle {
                    required property string modelData
                    Layout.preferredWidth: 28
                    Layout.preferredHeight: 28
                    radius: 6
                    color: modelData
                    border.color: colorPickerRoot.currentHex.toUpperCase() === modelData.toUpperCase()
                        ? theme.tokens.accent : "transparent"
                    border.width: 2
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            colorPickerRoot.currentHex = modelData
                            hexInput.text = modelData.toUpperCase()
                        }
                    }
                }
            }
        }

        // HEX entry row
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: qsTr("HEX")
                font.family: theme.monoFont
                font.pixelSize: 9
                font.letterSpacing: 1.2
                font.capitalization: Font.AllUppercase
                color: theme.tokens.textMuted
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: hexInput.activeFocus ? theme.tokens.accent : theme.tokens.border
                TextInput {
                    id: hexInput
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                    onTextEdited: {
                        var t = text.trim()
                        if (t.length > 0 && t[0] !== "#")
                            t = "#" + t
                        colorPickerRoot.currentHex = t
                    }
                }
            }
        }
    }

    footer: FgDialogFooter {
        cancelLabel: qsTr("Cancel")
        acceptLabel: qsTr("Apply")
        onCancelClicked: colorPickerRoot.reject()
        onAcceptClicked: {
            var hex = (hexInput.text || "").trim()
            if (hex.length > 0 && hex[0] !== "#")
                hex = "#" + hex
            if (hex.length === 7) {
                colorPickerRoot.acceptedHex(hex.toUpperCase())
                colorPickerRoot.accept()
            }
        }
    }
}
