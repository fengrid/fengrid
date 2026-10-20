import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Shared modal form shell: centered on the window overlay, fixed sane
// width (never derived from content, whose implicit sizes can collapse),
// uppercase title, right-aligned Cancel/primary footer. Instances declare
// their fields as the DEFAULT children (`fields: [...]`) — they
// land inside the content ColumnLayout — and handle `onApply` for the
// commit; the primary button closes via accept() so Enter/Escape work.
Dialog {
    id: shell

    default property alias fields: contentCol.data
    property string heading: ""
    property string acceptLabel: qsTr("Save")
    property string cancelLabel: qsTr("Cancel")
    property bool acceptEnabled: true
    signal apply()

    modal: true
    dim: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: 340
    padding: 16

    background: Rectangle {
        radius: 12
        color: theme.tokens.surface
        border.color: theme.tokens.border
    }

    contentItem: ColumnLayout {
        id: contentCol
        spacing: 10

        Text {
            text: shell.heading
            font.family: theme.headingFont
            font.pixelSize: 15
            font.letterSpacing: 1.4
            font.capitalization: Font.AllUppercase
            color: theme.tokens.text
            Layout.bottomMargin: 2
        }
    }

    footer: RowLayout {
        spacing: 8
        Item { Layout.fillWidth: true }
        Button {
            text: shell.cancelLabel
            onClicked: shell.reject()
            background: Rectangle {
                radius: 6; color: theme.tokens.surface2
                border.color: theme.tokens.border
            }
            contentItem: Text {
                text: parent.text
                color: theme.tokens.text
                font.family: theme.uiFont; font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                leftPadding: 14; rightPadding: 14
            }
        }
        Button {
            text: shell.acceptLabel
            enabled: shell.acceptEnabled
            onClicked: {
                shell.apply()
                shell.accept()      // closes + emits accepted()
            }
            background: Rectangle {
                radius: 6
                color: shell.acceptEnabled ? theme.tokens.accent
                                           : theme.tokens.border
            }
            contentItem: Text {
                text: parent.text
                color: theme.tokens.bg
                font.family: theme.uiFont; font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                leftPadding: 14; rightPadding: 14
            }
        }
    }
}
