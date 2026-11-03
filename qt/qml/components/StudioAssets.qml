import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// ASSETS screen — the project's attached artifacts, with library
// pickers filtered the same way the side rail filters collections.
Item {
    id: assetsRoot
    component SectionLabel: Text {
        font.family: theme.monoFont
        font.pixelSize: 9
        font.letterSpacing: 1.4
        color: theme.tokens.accent
    }

    property var prj: null              // Projects bridge

    function refreshPickers() {
        if (prj === null)
            return;
        iconOpts = prj.icon_options();
        fontOpts = prj.font_options();
        snipOpts = prj.snippet_options();
        palOpts = prj.palette_options();
    }
    property var iconOpts: []
    property var fontOpts: []
    property var snipOpts: []
    property var palOpts: []
    Component.onCompleted: refreshPickers()
    Connections {
        target: prj
        function onProjectsChanged() {
            assetsRoot.refreshPickers();
        }
        function onCurrentChanged() {
            assetsRoot.refreshPickers();
        }
    }

    component PickerRow: RowLayout {
        id: pickRow
        property string kindLabel
        property var opts: []
        property string kind
        Layout.fillWidth: true
        spacing: 6
        Text {
            text: pickRow.kindLabel
            font.family: theme.uiFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
            Layout.preferredWidth: 64
        }
        ComboBox {
            id: pickBox
            Layout.fillWidth: true
            model: pickRow.opts
            textRole: "name"
            background: Rectangle {
                radius: 4
                color: theme.tokens.surface2
                border.color: theme.tokens.border
            }
            contentItem: Text {
                text: pickBox.displayText
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.text
                verticalAlignment: Text.AlignVCenter
                leftPadding: 6
            }
        }
        FgButton {
            text: qsTr("Attach")
            enabled: pickBox.currentIndex >= 0
            onClicked: {
                var o = pickRow.opts[pickBox.currentIndex];
                prj.add_asset(pickRow.kind, o.id, o.name);
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 10

        SectionLabel {
            text: qsTr("Attach from the library")
        }
        PickerRow {
            kindLabel: qsTr("Icon")
            kind: "icon"
            opts: assetsRoot.iconOpts
        }
        PickerRow {
            kindLabel: qsTr("Font")
            kind: "font"
            opts: assetsRoot.fontOpts
        }
        PickerRow {
            kindLabel: qsTr("Snippet")
            kind: "snippet"
            opts: assetsRoot.snipOpts
        }
        PickerRow {
            kindLabel: qsTr("Palette")
            kind: "palette"
            opts: assetsRoot.palOpts
        }

        SectionLabel {
            text: qsTr("Attached to this project")
        }
        ListView {
            id: attachedList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: prj !== null ? prj.assets : []
            spacing: 3
            ScrollBar.vertical: ScrollBar {}
            delegate: RowLayout {
                width: attachedList.width
                spacing: 6
                Rectangle {
                    width: 8
                    height: 8
                    radius: 4
                    color: modelData.asset_kind === "icon" ? theme.tokens.accentIcon : modelData.asset_kind === "font" ? theme.tokens.accentFont : modelData.asset_kind === "palette" ? theme.tokens.accentColor : theme.tokens.accentCode
                }
                Text {
                    Layout.fillWidth: true
                    text: modelData.label || modelData.asset_kind + " #" + modelData.asset_id
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.text
                    elide: Text.ElideRight
                }
                Text {
                    text: modelData.asset_kind
                    font.family: theme.monoFont
                    font.pixelSize: 9
                    color: theme.tokens.textMuted
                }
                IconButton {
                    icon_name: "trash"
                    icon_px: 10
                    implicitWidth: 20
                    implicitHeight: 20
                    ToolTip.text: qsTr("Remove from project")
                    onClicked: prj.remove_asset(modelData.id)
                }
            }
            Text {
                anchors.centerIn: parent
                visible: attachedList.count === 0
                text: qsTr("No assets attached yet — pick from the " + "library above, or attach a whole " + "collection from the project list's " + "context menu")
                wrapMode: Text.Wrap
                width: parent.width - 40
                horizontalAlignment: Text.AlignHCenter
                color: theme.tokens.textMuted
                font.family: theme.uiFont
                font.pixelSize: 10
            }
        }
    }
}
