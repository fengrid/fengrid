import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

Rectangle {
    id: rail
    color: theme.tokens.surface

    // `library !== null` guards: context properties are nulled during app
    // teardown while lingering bindings re-evaluate — without the guard the
    // exit path spams TypeErrors (seen in the first offscreen QA run).
    component RailItem: Rectangle {
        id: itemRoot
        property string label
        property string count: ""
        property bool active: false
        signal picked()

        Layout.fillWidth: true
        Layout.leftMargin: 8
        Layout.rightMargin: 8
        height: 26
        radius: 6
        color: active ? theme.tokens.surface2
                      : (itemMa.containsMouse ? theme.tokens.surface2 : "transparent")

        Rectangle {
            width: 3
            height: parent.height - 8
            radius: 1.5
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            color: theme.tokens.accent
            visible: itemRoot.active
        }
        Text {
            id: labelText
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - countText.implicitWidth - 46
            text: itemRoot.label
            font.family: theme.uiFont
            font.pixelSize: 12
            color: itemRoot.active ? theme.tokens.text : theme.tokens.textMuted
            elide: Text.ElideRight
        }
        Text {
            id: countText
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            text: itemRoot.count
            font.family: theme.monoFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
        }
        MouseArea {
            id: itemMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: itemRoot.picked()
        }
    }

    component SectionLabel: Text {
        Layout.fillWidth: true
        Layout.leftMargin: 14
        topPadding: 14
        bottomPadding: 4
        font.family: theme.headingFont
        font.pixelSize: 12
        font.letterSpacing: 1.4
        font.capitalization: Font.AllUppercase
        color: theme.tokens.textMuted
    }

    Flickable {
        id: flick
        anchors.fill: parent
        contentHeight: railCol.implicitHeight + 20
        clip: true
        ScrollBar.vertical: ScrollBar { }

        ColumnLayout {
            id: railCol
            width: rail.width
            spacing: 2

            SectionLabel { text: qsTr("Library") }
            RailItem {
                label: qsTr("All assets")
                count: library !== null ? String(library.totalAssets) : ""
                active: library !== null && library.themeFilter === ""
                        && library.contextFilter === "" && library.extFilter === ""
                onPicked: {
                    library.set_theme("")
                    library.set_context("")
                    library.set_ext("")
                }
            }

            SectionLabel { text: qsTr("Themes") }
            Repeater {
                model: library.themes
                RailItem {
                    required property var modelData
                    label: modelData.name
                    count: String(modelData.n)
                    active: library !== null && library.themeFilter === modelData.name
                    onPicked: library.set_theme(
                        library.themeFilter === modelData.name ? "" : modelData.name)
                }
            }

            SectionLabel { text: qsTr("Contexts") }
            Repeater {
                model: library.contexts
                RailItem {
                    required property var modelData
                    label: modelData.name
                    count: String(modelData.n)
                    active: library !== null && library.contextFilter === modelData.name
                    onPicked: library.set_context(
                        library.contextFilter === modelData.name ? "" : modelData.name)
                }
            }

            SectionLabel { text: qsTr("Types") }
            Repeater {
                model: library.exts
                RailItem {
                    required property var modelData
                    label: modelData.name.toUpperCase()
                    count: String(modelData.n)
                    active: library !== null && library.extFilter === modelData.name
                    onPicked: library.set_ext(
                        library.extFilter === modelData.name ? "" : modelData.name)
                }
            }

            SectionLabel { text: qsTr("Collections") }
            Repeater {
                model: library.collections
                RailItem {
                    required property var modelData
                    label: modelData.name
                    count: String(modelData.n)
                    active: library !== null
                            && library.collectionFilter === String(modelData.id)
                    onPicked: library.set_collection(
                        library.collectionFilter === String(modelData.id)
                            ? "" : String(modelData.id))
                }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                height: 26
                radius: 6
                color: theme.tokens.surface2
                border.color: collInput.activeFocus ? theme.tokens.accent : theme.tokens.border

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 6
                    spacing: 4
                    TextInput {
                        id: collInput
                        Layout.fillWidth: true
                        font.family: theme.monoFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                        clip: true
                        onAccepted: {
                            if (text.trim() !== "")
                                library.create_collection(text.trim())
                            text = ""
                        }
                    }
                    IconImage {
                        name: "plus"
                        px: 12
                        tint: theme.tokens.textMuted
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (collInput.text.trim() !== "")
                                    library.create_collection(collInput.text.trim())
                                collInput.text = ""
                            }
                        }
                    }
                }
            }

            SectionLabel { text: qsTr("Tags") }
            Repeater {
                model: library.tags
                RailItem {
                    required property var modelData
                    label: "#" + modelData.name
                    count: String(modelData.n)
                    active: library !== null && library.tagFilter === modelData.name
                    onPicked: library.set_tag(
                        library.tagFilter === modelData.name ? "" : modelData.name)
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 14
                topPadding: 6
                text: qsTr("Select an asset to tag it")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
                wrapMode: Text.Wrap
            }

            Item { Layout.fillHeight: true; Layout.minimumHeight: 8 }

            // add-folder source (native FolderDialog — no server involved)
            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                Layout.bottomMargin: 10
                height: 26
                radius: 6
                color: addMa.containsMouse ? theme.tokens.surface2 : "transparent"
                border.color: theme.tokens.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    spacing: 6
                    IconImage { name: "folder-plus"; px: 13; tint: theme.tokens.textMuted }
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("Add folder…")
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        color: theme.tokens.textMuted
                    }
                }
                MouseArea {
                    id: addMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: folderDialog.open()
                }
                FolderDialog {
                    id: folderDialog
                    onAccepted: library.add_folder(Icons.toLocalPath(selectedFolder))
                }
            }
        }
    }
}
