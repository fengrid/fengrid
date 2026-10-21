import QtQuick
import QtQuick.Controls

Popup {
    id: toast
    property string body: ""
    function show(msg) {
        toast.body = msg
        open()
        hideTimer.restart()
    }

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: bodyText.implicitWidth + 36
    height: 38
    padding: 0
    background: Rectangle {
        // translucent panel: dark glass look with an accent hairline
        color: Qt.rgba(theme.tokens.surface2.r, theme.tokens.surface2.g,
                       theme.tokens.surface2.b, 0.88)
        border.color: theme.tokens.accent
        border.width: 1
        radius: 8
    }
    contentItem: Text {
        id: bodyText
        text: toast.body
        color: theme.tokens.text
        font.family: theme.uiFont
        font.pixelSize: 12
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 120 } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 160 } }
    Timer { id: hideTimer; interval: 2600; onTriggered: toast.close() }
}
