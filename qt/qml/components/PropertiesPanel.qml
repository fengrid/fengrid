import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Universal Properties panel — the right-hand configuration surface for
// EVERY asset kind (icon, font, palette, snippet). Driven entirely by
// taxonomy.item_properties(kind, id): tags, custom field values, and
// typed links, so each pane only needs to supply a kind + id.
Rectangle {
    id: panel
    color: theme.tokens.bg

    property string itemKind: "icon"
    property int itemId: -1
    property var props: null
    // re-resolve when the selection or the taxonomy layer changes
    onItemIdChanged: reload()
    onItemKindChanged: reload()
    visible: itemId >= 0

    function reload() {
        props = (taxonomy !== null && itemId >= 0)
                ? taxonomy.item_properties(itemKind, itemId) : null
    }

    Connections {
        target: taxonomy
        function onFieldsChanged() { panel.reload() }
        function onLinksChanged() { panel.reload() }
    }

    component SectionHeader: Text {
        topPadding: 12
        bottomPadding: 4
        font.family: theme.headingFont
        font.pixelSize: 12
        font.letterSpacing: 1.4
        font.capitalization: Font.AllUppercase
        color: theme.tokens.textMuted
    }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight + 24
        clip: true
        ScrollBar.vertical: ScrollBar { }

        ColumnLayout {
            id: col
            width: panel.width - 24
            x: 12
            spacing: 8

            Item { Layout.fillWidth: true; Layout.preferredHeight: 2 }

            Text {
                Layout.fillWidth: true
                text: panel.itemKind.toUpperCase()
                font.family: theme.headingFont
                font.pixelSize: 12
                font.letterSpacing: 1.6
                color: theme.tokens.accent
            }

            // ---------------------------------------------------------- TAGS
            SectionHeader { text: qsTr("Tags") }
            Flow {
                Layout.fillWidth: true
                spacing: 5
                Repeater {
                    model: panel.props ? panel.props.tags : []
                    Rectangle {
                        required property var modelData
                        radius: 9
                        height: 20
                        width: tagText.implicitWidth + 26
                        color: theme.tokens.surface2
                        Row {
                            anchors.centerIn: parent
                            spacing: 4
                            Text {
                                id: tagText
                                text: "#" + modelData
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.text
                            }
                            Text {
                                text: "✕"
                                font.pixelSize: 9
                                color: theme.tokens.textMuted
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: taxonomy !== null
                                        && taxonomy.remove_tag(
                                            panel.itemKind, panel.itemId,
                                            modelData)
                                }
                            }
                        }
                    }
                }
                Text {
                    visible: !panel.props || panel.props.tags.length === 0
                    text: qsTr("no tags yet")
                    font.family: theme.uiFont
                    font.pixelSize: 10
                    color: theme.tokens.textMuted
                }
            }
            RowLayout {
                spacing: 6
                Layout.fillWidth: true
                Rectangle {
                    Layout.fillWidth: true
                    height: 26
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: tagAddInput.activeFocus
                                  ? theme.tokens.accent : theme.tokens.border
                    TextInput {
                        id: tagAddInput
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        verticalAlignment: TextInput.AlignVCenter
                        font.family: theme.monoFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                        clip: true
                        onAccepted: {
                            if (text.trim() !== "" && taxonomy !== null) {
                                taxonomy.add_tag(panel.itemKind, panel.itemId,
                                                 text.trim())
                                text = ""
                            }
                        }
                    }
                    Text {
                        visible: tagAddInput.text === ""
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        verticalAlignment: Text.AlignVCenter
                        text: qsTr("add tag…")
                        font.family: theme.uiFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                }
                IconButton {
                    icon_name: "plus"
                    implicitWidth: 24
                    implicitHeight: 24
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (tagAddInput.text.trim() !== ""
                                    && taxonomy !== null) {
                                taxonomy.add_tag(panel.itemKind, panel.itemId,
                                                 tagAddInput.text.trim())
                                tagAddInput.text = ""
                            }
                        }
                    }
                }
            }

            // -------------------------------------------------------- FIELDS
            SectionHeader { text: qsTr("Custom fields") }
            Repeater {
                model: panel.props ? panel.props.fields : []
                RowLayout {
                    id: propRow
                    required property var modelData
                    spacing: 6
                    Layout.fillWidth: true
                    Text {
                        text: propRow.modelData.name
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                        Layout.preferredWidth: 82
                        elide: Text.ElideRight
                    }
                    Loader {
                        Layout.fillWidth: true
                        sourceComponent: propRow.modelData.type === "bool"
                                         ? boolEd
                                         : (propRow.modelData.type === "select"
                                            ? selectEd : textEd)
                    }
                    Component {
                        id: textEd
                        Rectangle {
                            implicitHeight: 24
                            radius: 5
                            color: theme.tokens.surface2
                            border.color: pvInput.activeFocus
                                          ? theme.tokens.accent
                                          : theme.tokens.border
                            TextInput {
                                id: pvInput
                                anchors.fill: parent
                                anchors.leftMargin: 6
                                anchors.rightMargin: 6
                                verticalAlignment: TextInput.AlignVCenter
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.text
                                clip: true
                                text: propRow.modelData.value
                                onEditingFinished: taxonomy !== null
                                    && taxonomy.set_field_value(
                                        panel.itemId, propRow.modelData.id,
                                        text, panel.itemKind)
                            }
                        }
                    }
                    Component {
                        id: boolEd
                        CheckBox {
                            checked: propRow.modelData.value === "1"
                            onClicked: taxonomy !== null
                                && taxonomy.set_field_value(
                                    panel.itemId, propRow.modelData.id,
                                    checked ? "1" : "0", panel.itemKind)
                        }
                    }
                    Component {
                        id: selectEd
                        ComboBox {
                            implicitHeight: 24
                            model: propRow.modelData.options.choices || []
                            currentIndex: {
                                var ch = propRow.modelData.options.choices || []
                                return Math.max(0, ch.indexOf(
                                    propRow.modelData.value))
                            }
                            onActivated: function (idx) {
                                taxonomy !== null && taxonomy.set_field_value(
                                    panel.itemId, propRow.modelData.id,
                                    model[idx], panel.itemKind)
                            }
                            background: Rectangle {
                                radius: 5; color: theme.tokens.surface2
                                border.color: theme.tokens.border
                            }
                            contentItem: Text {
                                text: parent.displayText
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.text
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 6
                            }
                        }
                    }
                    IconButton {
                        visible: propRow.modelData.type === "id"
                        icon_name: "zap"
                        icon_px: 10
                        implicitWidth: 20
                        implicitHeight: 20
                        ToolTip.text: qsTr("Generate next ID")
                        onClicked: taxonomy !== null && taxonomy.generate_id(
                            panel.itemId, propRow.modelData.id, panel.itemKind)
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: !panel.props || panel.props.fields.length === 0
                text: qsTr("No custom fields defined yet — create them from"
                           + " the icon inspector")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
                wrapMode: Text.Wrap
            }

            // --------------------------------------------------------- LINKS
            SectionHeader { text: qsTr("Links") }
            Repeater {
                model: panel.props ? panel.props.links : []
                RowLayout {
                    id: linkRow
                    required property var modelData
                    spacing: 6
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: (linkRow.modelData.direction === "out"
                               ? "→ " : "← ") + linkRow.modelData.label
                              + (linkRow.modelData.role !== ""
                                 ? "  (" + linkRow.modelData.role + ")" : "")
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                        elide: Text.ElideRight
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: taxonomy !== null
                                && taxonomy.remove_link(linkRow.modelData.id)
                        }
                        ToolTip.visible: containsMouse
                        ToolTip.text: qsTr("click to remove this link")
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: !panel.props || panel.props.links.length === 0
                text: qsTr("No links — use an asset's right-click menu to"
                           + " link collections, libraries or projects")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
                wrapMode: Text.Wrap
            }

            Item { Layout.fillHeight: true; Layout.minimumHeight: 12 }
        }
    }
}
