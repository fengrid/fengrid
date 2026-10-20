import QtQuick
import QtQuick.Controls
import "."

// Tinted Feather-style icon button (content is token-driven, no emoji).
// Shared by the shell header and the pane toolbars.
ToolButton {
    id: btn
    property string icon_name: ""
    property int icon_px: 16
    // active = a persistent on-state (e.g. the star toggle) — renders in the
    // lit-pane amber, which the palette reserves for selection states
    property bool active: false
    icon.width: 0
    icon.height: 0
    implicitWidth: 30
    implicitHeight: 30
    contentItem: IconImage {
        name: btn.icon_name
        tint: btn.active ? theme.tokens.litPane
                         : (btn.hovered || btn.pressed ? theme.tokens.text
                                                       : theme.tokens.textMuted)
        px: btn.icon_px
        anchors.centerIn: parent
    }
    background: Rectangle {
        radius: 6
        color: btn.pressed ? theme.tokens.surface2
                           : (btn.hovered ? theme.tokens.surface2 : "transparent")
    }
    ToolTip.visible: hovered && ToolTip.text.length > 0
    ToolTip.delay: 400
}
