import QtQuick
import QtQuick.Controls

// Themed push button for the settings/setup surfaces — the same
// surface2 + hairline idiom the pane toolbars use (Basic style gives
// Buttons no useful default look; every button in this app is styled).
Button {
    id: btn
    implicitHeight: 30
    padding: 14
    hoverEnabled: true
    opacity: enabled ? 1 : 0.55
    background: Rectangle {
        radius: 6
        color: btn.down ? theme.tokens.accent : btn.hovered ? theme.tokens.surface2 : theme.tokens.bg
        border.color: theme.tokens.border
        Behavior on color {
            ColorAnimation {
                duration: 90
            }
        }
    }
    contentItem: Text {
        text: btn.text
        font.family: theme.uiFont
        font.pixelSize: 11
        color: btn.down ? theme.tokens.bg : btn.hovered ? theme.tokens.text : theme.tokens.textMuted
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
