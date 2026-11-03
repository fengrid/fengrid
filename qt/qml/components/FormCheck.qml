import QtQuick
import QtQuick.Controls

// Shared themed checkbox (used by the form dialogs).
CheckBox {
    id: root

    property string checkLabel: ""

    font.family: theme.uiFont
    font.pixelSize: 11
    spacing: 0

    indicator: Rectangle {
        implicitWidth: 15
        implicitHeight: 15
        radius: 4
        color: root.checked ? theme.tokens.accent : theme.tokens.surface2
        border.color: root.checked ? theme.tokens.accent : theme.tokens.border
        anchors.verticalCenter: parent.verticalCenter
        Text {
            anchors.centerIn: parent
            text: root.checked ? "✓" : ""
            font.pixelSize: 10
            font.weight: Font.Bold
            color: theme.tokens.bg
        }
    }
    contentItem: Text {
        text: root.checkLabel
        font: root.font
        color: theme.tokens.text
        leftPadding: root.indicator.width + 8
        verticalAlignment: Text.AlignVCenter
    }
}
