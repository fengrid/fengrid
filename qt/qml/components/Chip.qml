import QtQuick
import "."

Rectangle {
    id: chip
    property string label
    property bool on: false
    signal picked()

    width: labelText.implicitWidth + 22
    height: 24
    radius: 12
    color: on ? theme.tokens.accent : theme.tokens.surface2
    border.color: on ? theme.tokens.accent : theme.tokens.border

    Text {
        id: labelText
        anchors.centerIn: parent
        text: chip.label
        font.family: theme.monoFont
        font.pixelSize: 11
        color: chip.on ? theme.tokens.bg : theme.tokens.textMuted
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: chip.picked()
    }
}
