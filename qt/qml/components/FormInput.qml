import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Shared labeled single-line input: label ABOVE the field (clearer than
// placeholder-only), focus accent, sane implicit sizes so dialogs measure
// correctly — Rectangle-based fields without implicitWidth collapse the
// parent layout to zero-width and the dialog clips its content.
ColumnLayout {
    id: root

    property string label: ""
    property alias text: input.text
    property alias echoMode: input.echoMode
    property alias inputMethodHints: input.inputMethodHints

    function forceActiveFocus() { input.forceActiveFocus() }

    spacing: 3
    Layout.fillWidth: true

    Text {
        text: root.label
        font.family: theme.monoFont
        font.pixelSize: 10
        font.letterSpacing: 0.8
        font.capitalization: Font.AllUppercase
        color: theme.tokens.textMuted
    }
    Rectangle {
        id: box
        Layout.fillWidth: true
        implicitWidth: 240
        implicitHeight: 30
        radius: 6
        color: theme.tokens.surface2
        border.color: input.activeFocus ? theme.tokens.accent
                                        : theme.tokens.border
        TextInput {
            id: input
            anchors.fill: parent
            anchors.leftMargin: 9
            anchors.rightMargin: 9
            verticalAlignment: TextInput.AlignVCenter
            font.family: theme.monoFont
            font.pixelSize: 12
            color: theme.tokens.text
            clip: true
            selectByMouse: true
        }
    }
}
