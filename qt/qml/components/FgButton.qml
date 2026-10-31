import QtQuick
import QtQuick.Controls

// The canonical themed push button — the same 30px / 12px-text /
// 6px-radius metric the themed footers use, so default-styled Buttons
// never fall back to the light control palette (which put dark text on
// dark backgrounds, #87). A Button subclass: any property that works on
// Button (enabled, onClicked, ToolTip, Layout…) works here too.
Button {
    id: btn
    implicitHeight: 30
    leftPadding: 14
    rightPadding: 14
    hoverEnabled: true
    background: Rectangle {
        radius: 6
        color: btn.down ? theme.tokens.bg
               : btn.hovered ? theme.tokens.surface2
               : theme.tokens.surface2
        border.color: theme.tokens.border
        Behavior on color { ColorAnimation { duration: 90 } }
    }
    contentItem: Text {
        text: btn.text
        color: btn.enabled ? theme.tokens.text : theme.tokens.textMuted
        font.family: theme.uiFont
        font.pixelSize: 12
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
