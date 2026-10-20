import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

Rectangle {
    id: rail
    color: theme.tokens.surface

    // pane switching: 0 = icons, 1 = fonts (Main owns the state)
    property int pane: 0
    signal panePicked(int idx)

    // `library !== null` guards: context properties are nulled during app
    // teardown while lingering bindings re-evaluate — without the guard the
    // exit path spams TypeErrors (seen in the first offscreen QA run).
    component RailItem: Rectangle {
        id: itemRoot
        property string label
        property string sub: ""           // secondary line (collection tags)
        property string count: ""
        property bool active: false
        property color accent: theme.tokens.accent   // per-category accent
        property bool indent: false       // sub-collection nesting
        signal picked()

        Layout.fillWidth: true
        Layout.leftMargin: indent ? 24 : 8
        Layout.rightMargin: 8
        height: sub === "" ? 26 : 36
        radius: 6
        color: active ? theme.tokens.surface2
                      : (itemMa.containsMouse ? theme.tokens.surface2 : "transparent")

        Rectangle {
            width: 3
            height: parent.height - 8
            radius: 1.5
            anchors.left: parent.left
            anchors.leftMargin: itemRoot.indent ? 8 : 0
            anchors.verticalCenter: parent.verticalCenter
            color: itemRoot.accent
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

            // pane items carry their category accent (Icons teal, Fonts
            // violet, Colors rose, Code coral, Projects green)
            SectionLabel { text: qsTr("Panes") }
            RailItem {
                label: qsTr("Icons")
                accent: theme.tokens.accentIcon
                active: rail.pane === 0
                onPicked: rail.panePicked(0)
            }
            RailItem {
                label: qsTr("Fonts")
                accent: theme.tokens.accentFont
                active: rail.pane === 1
                onPicked: rail.panePicked(1)
            }
            RailItem {
                label: qsTr("Colors")
                accent: theme.tokens.accentColor
                active: rail.pane === 2
                onPicked: rail.panePicked(2)
            }
            RailItem {
                label: qsTr("Code")
                accent: theme.tokens.accentCode
                active: rail.pane === 3
                onPicked: rail.panePicked(3)
            }
            RailItem {
                label: qsTr("Projects")
                accent: theme.tokens.accentProject
                active: rail.pane === 4
                onPicked: rail.panePicked(4)
            }

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
                    id: collRow
                    required property var modelData
                    label: collRow.modelData.name
                    sub: collRow.modelData.tags
                    count: String(collRow.modelData.n)
                    indent: collRow.modelData.parentId > 0
                    active: library !== null
                            && library.collectionFilter === String(collRow.modelData.id)
                    onPicked: library.set_collection(
                        library.collectionFilter === String(collRow.modelData.id)
                            ? "" : String(collRow.modelData.id))
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            collMenu.target = collRow.modelData
                            collMenu.popup()
                        }
                    }
                }
            }
            // contextual menu for a collection row
            Menu {
                id: collMenu
                property var target: null
                width: 190
                padding: 4
                background: Rectangle {
                    radius: 8; color: theme.tokens.surface
                    border.color: theme.tokens.border
                }
                MenuItem {
                    text: qsTr("New sub-collection…")
                    height: 28
                    enabled: collMenu.target !== null
                    onTriggered: {
                        subDialog.parentId = collMenu.target.id
                        subDialog.open()
                    }
                }
                MenuItem {
                    text: qsTr("Edit tags…")
                    height: 28
                    enabled: collMenu.target !== null
                    onTriggered: {
                        subDialog.parentId = collMenu.target.id
                        subDialog.tagMode = true
                        subDialog.open()
                    }
                }
                MenuItem {
                    text: qsTr("Delete collection")
                    height: 28
                    enabled: collMenu.target !== null
                    onTriggered: library.delete_collection(collMenu.target.id)
                }
            }
            // shared name/tags input for new sub-collections + tag edits
            Popup {
                id: subDialog
                property int parentId: 0
                property bool tagMode: false
                width: rail.width - 24
                padding: 10
                background: Rectangle {
                    radius: 8; color: theme.tokens.surface
                    border.color: theme.tokens.border
                }
                contentItem: ColumnLayout {
                    spacing: 6
                    Text {
                        text: subDialog.tagMode ? qsTr("Collection tags (comma-separated)")
                                                : qsTr("New sub-collection")
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 26
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: subInput.activeFocus ? theme.tokens.accent
                                                           : theme.tokens.border
                        TextInput {
                            id: subInput
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: TextInput.AlignVCenter
                            font.family: theme.monoFont
                            font.pixelSize: 11
                            color: theme.tokens.text
                            clip: true
                            onAccepted: subDialog.commit()
                        }
                    }
                }
                function commit() {
                    if (subInput.text.trim() === "")
                        return
                    if (tagMode)
                        library.set_collection_tags(parentId, subInput.text)
                    else
                        library.create_sub_collection(subInput.text.trim(),
                                                      parentId)
                    subInput.text = ""
                    close()
                }
                onOpened: {
                    subInput.text = tagMode && collMenu.target
                        ? (collMenu.target.tags || "") : ""
                    subInput.forceActiveFocus()
                }
                onClosed: tagMode = false
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
