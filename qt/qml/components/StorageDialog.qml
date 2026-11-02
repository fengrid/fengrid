import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Attach-backend dialog: the backend is fixed by the row that opened
// it; only location + target kind are entered. Credentials never pass
// through Fengrid — the hint line carries the backend's status, which
// says where each tool finds auth (agent, keyring, passwd file).
FormDialog {
    id: dlg
    property string backend: "sshfs"
    property string backendLabel: ""
    property string hint: ""

    heading: qsTr("Attach storage")
    acceptLabel: qsTr("Attach")
    acceptEnabled: uriField.text.trim().length > 0

    function openFor(key, label, hintLine) {
        backend = key;
        backendLabel = label;
        hint = hintLine;
        uriField.text = "";
        open();
        uriField.forceActiveFocus();
    }

    Text {
        Layout.fillWidth: true
        text: dlg.backendLabel
        font.family: theme.uiFont
        font.pixelSize: 12
        font.weight: Font.DemiBold
        color: theme.tokens.text
    }
    FormInput {
        id: uriField
        label: qsTr("Location")
        text: ""
    }
    Text {
        Layout.fillWidth: true
        text: dlg.hint
        wrapMode: Text.Wrap
        font.family: theme.uiFont
        font.pixelSize: 10
        color: theme.tokens.textMuted
    }
    ComboBox {
        id: kindBox
        Layout.fillWidth: true
        Layout.preferredHeight: 30
        model: [qsTr("Attach as icon folder"), qsTr("Attach as font folder")]
        background: Rectangle {
            radius: 6
            color: theme.tokens.surface2
            border.color: theme.tokens.border
        }
        contentItem: Text {
            text: kindBox.displayText
            font.family: theme.monoFont
            font.pixelSize: 11
            color: theme.tokens.text
            verticalAlignment: Text.AlignVCenter
            leftPadding: 8
        }
    }
    onApply: storage.attach(dlg.backend, uriField.text, kindBox.currentIndex === 1 ? "fontroot" : "folder")
}
