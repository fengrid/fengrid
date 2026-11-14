import QtQuick
import QtQuick.Controls

// Themed MenuItem — the Basic-style default renders menu text with the
// platform palette (near-black on dark surfaces), which made the main
// menu nearly unreadable. Every menu item goes through this component
// so text/hover/section styling follows the active theme tokens.
MenuItem {
    id: item

    contentItem: Text {
        leftPadding: item.leftPadding
        rightPadding: item.rightPadding
        text: item.text
        font: item.font
        color: item.enabled ? theme.tokens.text : theme.tokens.textMuted
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }

    // hover/keyboard highlight — token-driven, not the white Basic bar
    background: Rectangle {
        implicitHeight: 28
        radius: 5
        color: item.enabled && item.highlighted ? theme.tokens.surface2 : "transparent"
    }
}
