import QtQuick
import QtQuick.Controls

// Themed MenuSeparator — the Basic default line is near-invisible on
// dark surfaces; token-driven here like FgMenuItem.
MenuSeparator {
    id: sep

    contentItem: Rectangle {
        implicitHeight: 1
        color: theme.tokens.border
    }

    background: Rectangle {
        implicitWidth: sep.width
        implicitHeight: sep.padding * 2 + 1
        color: "transparent"
    }
}