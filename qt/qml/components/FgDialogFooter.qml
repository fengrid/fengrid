import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Right-aligned Cancel/primary footer used by every themed dialog.
// Dialog `padding` insets the contentItem only — an unwrapped footer
// sits FLUSH against the dialog's bottom-right corner (buttons touched
// the edge). This Item restores the same 16px insets the content column
// carries, so every dialog reads with identical margins.
Item {
    id: footerRoot

    property string cancelLabel: qsTr("Cancel")
    property string acceptLabel: qsTr("Save")
    property bool acceptEnabled: true
    signal cancelClicked
    signal acceptClicked

    implicitWidth: row.implicitWidth + 32
    implicitHeight: row.implicitHeight + 16

    RowLayout {
        id: row
        spacing: 8
        anchors {
            left: parent.left
            leftMargin: 16
            right: parent.right
            rightMargin: 16
            bottom: parent.bottom
            bottomMargin: 16
        }

        Item {
            Layout.fillWidth: true
        }

        Button {
            text: footerRoot.cancelLabel
            onClicked: footerRoot.cancelClicked()
            background: Rectangle {
                radius: 6
                color: theme.tokens.surface2
                border.color: theme.tokens.border
            }
            contentItem: Text {
                text: parent.text
                color: theme.tokens.text
                font.family: theme.uiFont
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                leftPadding: 14
                rightPadding: 14
            }
        }

        Button {
            text: footerRoot.acceptLabel
            enabled: footerRoot.acceptEnabled
            onClicked: footerRoot.acceptClicked()
            background: Rectangle {
                radius: 6
                color: footerRoot.acceptEnabled ? theme.tokens.accent : theme.tokens.border
            }
            contentItem: Text {
                text: parent.text
                color: theme.tokens.bg
                font.family: theme.uiFont
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                leftPadding: 14
                rightPadding: 14
            }
        }
    }
}
