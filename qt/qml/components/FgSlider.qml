import QtQuick
import QtQuick.Controls

// Themed slider with a small, technical handle — Qt's default knob is
// a chunky ~18px rounded rect that reads as oversized next to hairline
// icons (#87). The handle here is a 12px flat square with a hairline
// border; the track is a 3px token-driven line. Used everywhere a
// default-styled Slider would otherwise fall back to the Basic style.
Slider {
    id: ctl
    implicitWidth: 120
    implicitHeight: 24
    padding: 6
    background: Rectangle {
        x: ctl.leftPadding
        y: ctl.topPadding + (ctl.availableHeight - height) / 2
        width: ctl.availableWidth - ctl.leftPadding - ctl.rightPadding
        height: 3
        radius: 1.5
        color: theme.tokens.surface2
        Rectangle {
            width: ctl.visualPosition * parent.width
            height: parent.height
            radius: parent.radius
            color: ctl.pressed ? theme.tokens.accent : theme.tokens.border
            visible: ctl.value > ctl.from
        }
    }
    handle: Rectangle {
        x: ctl.leftPadding + (ctl.visualPosition * (ctl.availableWidth - width))
        y: ctl.topPadding + (ctl.availableHeight - height) / 2
        width: 12
        height: 12
        radius: 3
        color: ctl.pressed ? theme.tokens.accent : theme.tokens.surface2
        border.color: ctl.pressed ? theme.tokens.accent : theme.tokens.border
        Behavior on color {
            ColorAnimation {
                duration: 90
            }
        }
        Behavior on border.color {
            ColorAnimation {
                duration: 90
            }
        }
    }
    Accessible.role: Accessible.Slider
    Accessible.name: ctl.ToolTip.text
}
