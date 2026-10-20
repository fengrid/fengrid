import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

Rectangle {
    id: panel
    color: theme.tokens.surface

    property int index: -1
    property Item gridView
    property string exportDir: ""
    property string exportFormat: "png"
    property string exportSize: "64"
    property var d: null
    // QA modal registry (--dialog <name>)
    readonly property var qaModals: ({ "fieldDialog": fieldDialog })
    // taxonomy rows for the selected asset, snapshotted at reload time
    property var fieldsModel: []
    property var linksModel: []

    onIndexChanged: reload()
    onVisibleChanged: if (visible) reload()

    function reload() {
        d = (index >= 0 && library !== null) ? library.get_details(index) : null
        fieldsModel = taxonomy !== null ? taxonomy.fields : []
        linksModel = (taxonomy !== null && d) ? taxonomy.links_for("icon", d.id)
                                              : []
    }

    function fmtBytes(n) {
        if (n === null || n === undefined)
            return "—"
        if (n < 1024)
            return n + " B"
        if (n < 1024 * 1024)
            return (n / 1024).toFixed(1) + " KB"
        return (n / 1048576).toFixed(1) + " MB"
    }

    function toLocalPath(u) {
        var s = u.toString()
        if (s.indexOf("file://") === 0)
            return decodeURIComponent(s.substring(7))
        return s
    }

    Connections {
        target: library
        function onTagsRevision() { panel.reload() }
        function onListsChanged() { panel.reload() }
    }
    Connections {
        target: taxonomy
        function onFieldsChanged() { panel.reload() }
        function onLinksChanged() { panel.reload() }
        function onViewsChanged() { panel.reload() }
        function onSmartsChanged() { panel.reload() }
    }

    component SectionHeader: Text {
        topPadding: 10
        bottomPadding: 2
        font.family: theme.headingFont
        font.pixelSize: 12
        font.letterSpacing: 1.4
        font.capitalization: Font.AllUppercase
        color: theme.tokens.textMuted
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 112
            Rectangle {
                anchors.centerIn: parent
                width: 108
                height: 108
                radius: 8
                color: theme.tokens.bg
                border.color: theme.tokens.border
                Image {
                    anchors.centerIn: parent
                    width: 88
                    height: 88
                    source: d ? Icons.fileUrl(d.path) : ""
                    asynchronous: true
                    sourceSize.width: 256
                    sourceSize.height: 256
                    fillMode: Image.PreserveAspectFit
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: d ? d.name : ""
            font.family: theme.headingFont
            font.pixelSize: 22
            font.letterSpacing: 1
            color: theme.tokens.text
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            text: d ? ((d.theme || "—") + (d.context ? " · " + d.context : "")) : ""
            font.family: theme.monoFont
            font.pixelSize: 11
            color: theme.tokens.accent
        }

        GridLayout {
            columns: 2
            columnSpacing: 10
            rowSpacing: 4
            Layout.fillWidth: true
            Repeater {
                model: d ? [
                    { l: qsTr("size"),   v: d.sizePx ? d.sizePx + "px" : "—" },
                    { l: qsTr("pixels"), v: (d.width && d.height) ? d.width + "×" + d.height : "—" },
                    { l: qsTr("type"),   v: d.ext ? d.ext.toUpperCase() : "—" },
                    { l: qsTr("file"),   v: panel.fmtBytes(d.bytes) },
                    { l: qsTr("mode"),   v: d.colorspace || "—" },
                    { l: qsTr("colors"), v: (d.colorCount !== null && d.colorCount !== undefined) ? String(d.colorCount) : "—" },
                    { l: qsTr("tone"),   v: d.mono === 1 ? qsTr("mono") : (d.mono === 0 ? qsTr("color") : "—") }
                ] : []
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Text {
                        text: modelData.l
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.textMuted
                        Layout.preferredWidth: 56
                    }
                    Text {
                        text: modelData.v
                        font.family: theme.monoFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }
        }

        SectionHeader {
            text: qsTr("Variants")
            visible: d && d.variants.length > 0
            Layout.fillWidth: true
        }
        Flow {
            visible: d && d.variants.length > 0
            spacing: 6
            Layout.fillWidth: true
            Repeater {
                model: d ? d.variants : []
                Chip {
                    required property var modelData
                    label: modelData.size_px + "px"
                    onPicked: {
                        var row = library.row_of_asset(modelData.id)
                        if (row >= 0 && panel.gridView)
                            panel.gridView.currentIndex = row
                    }
                }
            }
        }

        SectionHeader { text: qsTr("Tags"); Layout.fillWidth: true }
        Flow {
            spacing: 6
            Layout.fillWidth: true
            Repeater {
                model: d ? d.tags : []
                Rectangle {
                    required property var modelData
                    width: tagText.implicitWidth + removeText.implicitWidth + 26
                    height: 22
                    radius: 11
                    color: theme.tokens.surface2
                    border.color: theme.tokens.border
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
                            id: removeText
                            text: "×"
                            font.pixelSize: 11
                            color: theme.tokens.textMuted
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: library.remove_tag(panel.index, modelData)
                        }
                    }
                }
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
                border.color: tagInput.activeFocus ? theme.tokens.accent : theme.tokens.border
                TextInput {
                    id: tagInput
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                    onAccepted: {
                        if (text.trim() !== "" && panel.index >= 0)
                            library.add_tag(panel.index, text.trim())
                        text = ""
                    }
                }
            }
            IconImage {
                name: "plus"
                px: 14
                tint: theme.tokens.textMuted
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (tagInput.text.trim() !== "" && panel.index >= 0)
                            library.add_tag(panel.index, tagInput.text.trim())
                        tagInput.text = ""
                    }
                }
            }
        }

        // CUSTOM FIELDS (taxonomy layer): every defined field with this
        // asset's value, edited in place — text/number/date/id as text
        // inputs, bool as a checkbox, select as a choice combo; id fields
        // gain a Generate button. "+ Field" defines a new global field.
        SectionHeader { text: qsTr("FIELDS") }
        Repeater {
            model: fieldsModel
            RowLayout {
                id: fieldRow
                required property var modelData
                required property int index
                spacing: 6
                Layout.fillWidth: true
                Text {
                    text: fieldRow.modelData.name
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.textMuted
                    Layout.preferredWidth: 86
                    elide: Text.ElideRight
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        onClicked: fieldDeleteMenu.openFor(fieldRow.index,
                                                           fieldRow.modelData)
                    }
                }
                // type-appropriate editor
                Loader {
                    Layout.fillWidth: true
                    sourceComponent: fieldRow.modelData.type === "bool"
                                     ? boolEditor
                                     : (fieldRow.modelData.type === "select"
                                        ? selectEditor : textEditor)
                }
                Component {
                    id: textEditor
                    Rectangle {
                        height: 24
                        radius: 5
                        color: theme.tokens.surface2
                        border.color: fieldEdit.activeFocus
                                      ? theme.tokens.accent : theme.tokens.border
                        TextInput {
                            id: fieldEdit
                            anchors.fill: parent
                            anchors.leftMargin: 6
                            anchors.rightMargin: 6
                            verticalAlignment: TextInput.AlignVCenter
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.text
                            clip: true
                            text: fieldRow.modelData.value
                            onEditingFinished: taxonomy !== null
                                && taxonomy.set_field_value(
                                    d.id, fieldRow.modelData.id, text)
                        }
                    }
                }
                Component {
                    id: boolEditor
                    CheckBox {
                        checked: fieldRow.modelData.value === "1"
                        onClicked: taxonomy !== null && taxonomy.set_field_value(
                            d.id, fieldRow.modelData.id, checked ? "1" : "0")
                        contentItem: Text {
                            text: qsTr("yes")
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.textMuted
                            leftPadding: parent.indicator.width + 6
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
                Component {
                    id: selectEditor
                    ComboBox {
                        width: 140
                        model: fieldRow.modelData.options.choices || []
                        currentIndex: {
                            var ch = fieldRow.modelData.options.choices || []
                            return ch.indexOf(fieldRow.modelData.value)
                        }
                        onActivated: function (idx) {
                            taxonomy !== null && taxonomy.set_field_value(
                                d.id, fieldRow.modelData.id,
                                model[idx])
                        }
                        background: Rectangle {
                            radius: 5; color: theme.tokens.surface2
                            border.color: theme.tokens.border
                        }
                        contentItem: Text {
                            text: parent.displayText
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.text
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 6
                        }
                    }
                }
                IconButton {
                    visible: fieldRow.modelData.type === "id"
                    icon_name: "zap"
                    icon_px: 11
                    implicitWidth: 22
                    implicitHeight: 22
                    ToolTip.text: qsTr("Generate next ID")
                    onClicked: taxonomy !== null && taxonomy.generate_id(
                        d.id, fieldRow.modelData.id)
                }
            }
        }
        RowLayout {
            spacing: 6
            Layout.fillWidth: true
            IconImage {
                name: "plus"; px: 12; tint: theme.tokens.textMuted
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: fieldDialog.open()
                }
            }
            Text {
                Layout.fillWidth: true
                text: qsTr("Add field…  (right-click a field label to delete)")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
            }
        }

        // LINKS (taxonomy layer): typed links in and out of this asset
        SectionHeader { text: qsTr("LINKS") }
        Repeater {
            model: linksModel
            RowLayout {
                id: linkRow
                required property var modelData
                required property int index
                spacing: 6
                Layout.fillWidth: true
                Text {
                    text: (linkRow.modelData.direction === "out"
                           ? "→ " : "← ") + linkRow.modelData.label
                          + (linkRow.modelData.role !== ""
                             ? "  (" + linkRow.modelData.role + ")" : "")
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.textMuted
                    elide: Text.ElideRight
                    Layout.fillWidth: true
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
            visible: taxonomy !== null && taxonomy.links_for(
                         "icon", d ? d.id : -1).length === 0
            text: qsTr("Link to collections, libraries or projects from the"
                       + " asset's right-click menu")
            font.family: theme.uiFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
            wrapMode: Text.Wrap
        }

        // delete-field menu (right-click a field label)
        Menu {
            id: fieldDeleteMenu
            property int targetFieldId: 0
            function openFor(idx, field) {
                targetFieldId = field.id
                popup()
            }
            width: 160
            padding: 4
            background: Rectangle {
                radius: 8; color: theme.tokens.surface
                border.color: theme.tokens.border
            }
            MenuItem {
                text: qsTr("Delete field")
                height: 28
                onTriggered: taxonomy !== null
                             && taxonomy.delete_field(
                                 fieldDeleteMenu.targetFieldId)
                contentItem: Text {
                    text: parent.text
                    font.family: theme.uiFont; font.pixelSize: 11
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 10
                }
                background: Rectangle {
                    color: parent.hovered ? theme.tokens.surface2
                                          : "transparent"
                    radius: 5
                }
            }
        }

        // new-field dialog: name + type + per-type options
        Dialog {
            id: fieldDialog
            objectName: "fieldDialog"
            width: 320
            padding: 16
            modal: true
            dim: true
            parent: Overlay.overlay
            anchors.centerIn: parent
            background: Rectangle {
                radius: 12; color: theme.tokens.surface
                border.color: theme.tokens.border
            }
            contentItem: ColumnLayout {
                spacing: 10
                Text {
                    text: qsTr("New field")
                    font.family: theme.headingFont; font.pixelSize: 15
                    font.letterSpacing: 1.4
                    font.capitalization: Font.AllUppercase
                    color: theme.tokens.text
                    Layout.bottomMargin: 2
                }
                Text {
                    text: qsTr("field")
                    font.family: theme.monoFont; font.pixelSize: 10
                    font.letterSpacing: 0.8
                    font.capitalization: Font.AllUppercase
                    color: theme.tokens.textMuted
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitWidth: 240
                    implicitHeight: 30
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: fName.activeFocus ? theme.tokens.accent
                                                    : theme.tokens.border
                    TextInput {
                        id: fName
                        anchors.fill: parent
                        anchors.leftMargin: 9; anchors.rightMargin: 9
                        verticalAlignment: TextInput.AlignVCenter
                        font.family: theme.monoFont; font.pixelSize: 12
                        color: theme.tokens.text
                        clip: true
                        selectByMouse: true
                    }
                }
                Text {
                    text: qsTr("type")
                    font.family: theme.monoFont; font.pixelSize: 10
                    font.letterSpacing: 0.8
                    font.capitalization: Font.AllUppercase
                    color: theme.tokens.textMuted
                }
                ComboBox {
                    id: fType
                    Layout.fillWidth: true
                    implicitHeight: 30
                    model: ["text", "number", "bool", "date", "select", "id"]
                    background: Rectangle {
                        radius: 6; color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: fType.displayText
                        font.family: theme.monoFont; font.pixelSize: 12
                        color: theme.tokens.text
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 9
                    }
                }
                Text {
                    visible: fType.currentIndex === 4
                    text: qsTr("choices (comma-separated)")
                    font.family: theme.monoFont; font.pixelSize: 10
                    font.letterSpacing: 0.8
                    font.capitalization: Font.AllUppercase
                    color: theme.tokens.textMuted
                }
                Rectangle {
                    visible: fType.currentIndex === 4
                    Layout.fillWidth: true
                    implicitWidth: 240
                    implicitHeight: 30
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: fChoices.activeFocus ? theme.tokens.accent
                                                       : theme.tokens.border
                    TextInput {
                        id: fChoices
                        anchors.fill: parent
                        anchors.leftMargin: 9; anchors.rightMargin: 9
                        verticalAlignment: TextInput.AlignVCenter
                        font.family: theme.monoFont; font.pixelSize: 12
                        color: theme.tokens.text
                        clip: true
                        selectByMouse: true
                    }
                }
                RowLayout {
                    visible: fType.currentIndex === 5
                    spacing: 8
                    ColumnLayout {
                        spacing: 3
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("id prefix")
                            font.family: theme.monoFont; font.pixelSize: 10
                            font.letterSpacing: 0.8
                            font.capitalization: Font.AllUppercase
                            color: theme.tokens.textMuted
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 30
                            radius: 6
                            color: theme.tokens.surface2
                            border.color: fPrefix.activeFocus
                                          ? theme.tokens.accent
                                          : theme.tokens.border
                            TextInput {
                                id: fPrefix
                                anchors.fill: parent
                                anchors.leftMargin: 9; anchors.rightMargin: 9
                                verticalAlignment: TextInput.AlignVCenter
                                font.family: theme.monoFont; font.pixelSize: 12
                                color: theme.tokens.text
                                clip: true
                                selectByMouse: true
                            }
                        }
                    }
                    ColumnLayout {
                        spacing: 3
                        Layout.preferredWidth: 76
                        Text {
                            text: qsTr("padding")
                            font.family: theme.monoFont; font.pixelSize: 10
                            font.letterSpacing: 0.8
                            font.capitalization: Font.AllUppercase
                            color: theme.tokens.textMuted
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 30
                            radius: 6
                            color: theme.tokens.surface2
                            border.color: fPad.activeFocus
                                          ? theme.tokens.accent
                                          : theme.tokens.border
                            TextInput {
                                id: fPad
                                anchors.fill: parent
                                anchors.leftMargin: 9; anchors.rightMargin: 9
                                verticalAlignment: TextInput.AlignVCenter
                                font.family: theme.monoFont; font.pixelSize: 12
                                color: theme.tokens.text
                                clip: true
                                selectByMouse: true
                                text: "4"
                            }
                        }
                    }
                }
            }
            footer: RowLayout {
                spacing: 8
                Item { Layout.fillWidth: true }
                Button {
                    text: qsTr("Cancel")
                    onClicked: fieldDialog.reject()
                    background: Rectangle {
                        radius: 6; color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: parent.text; color: theme.tokens.text
                        font.family: theme.uiFont; font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 14; rightPadding: 14
                    }
                }
                Button {
                    text: qsTr("Create")
                    enabled: fName.text.trim() !== ""
                    onClicked: {
                        var opts = {}
                        if (fType.currentIndex === 4)
                            opts.choices = fChoices.text.split(",").map(
                                function (s) { return s.trim() }).filter(
                                function (s) { return s !== "" })
                        if (fType.currentIndex === 5) {
                            opts.prefix = fPrefix.text.trim()
                            opts.pad = parseInt(fPad.text) || 4
                        }
                        taxonomy.create_field(fName.text, fType.currentText,
                                              JSON.stringify(opts))
                        fName.text = ""
                        fChoices.text = ""
                        fieldDialog.accept()
                    }
                    background: Rectangle {
                        radius: 6
                        color: fName.text.trim() !== ""
                               ? theme.tokens.accent : theme.tokens.border
                    }
                    contentItem: Text {
                        text: parent.text; color: theme.tokens.bg
                        font.family: theme.uiFont; font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 14; rightPadding: 14
                    }
                }
            }
        }


        Item { Layout.fillHeight: true }

        Text {
            Layout.fillWidth: true
            text: d ? d.path : ""
            font.family: theme.monoFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
            wrapMode: Text.WrapAnywhere
            maximumLineCount: 3
            elide: Text.ElideMiddle
        }

        RowLayout {
            spacing: 8
            Layout.fillWidth: true
            Button {
                id: starBtn
                implicitWidth: 36
                implicitHeight: 30
                enabled: panel.index >= 0
                onClicked: library.set_starred(
                    panel.index, !(d && d.starred))
                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: (d && d.starred)
                    ? qsTr("Unstar — removes the 'starred' tag and pulls the asset out of Starred Assets")
                    : qsTr("Star — tags the asset and adds it to Starred Assets")
                background: Rectangle {
                    radius: 6
                    color: starBtn.hovered ? theme.tokens.surface2
                                           : "transparent"
                    border.color: theme.tokens.border
                }
                contentItem: Item {
                    Image {
                        anchors.centerIn: parent
                        width: 16
                        height: 16
                        sourceSize.width: 32
                        sourceSize.height: 32
                        source: Icons.url(
                            "star",
                            d && d.starred ? theme.tokens.litPane
                                           : theme.tokens.textMuted,
                            d && d.starred ? theme.tokens.litPane : "none")
                    }
                }
            }
            Button {
                id: copyBtn
                Layout.fillWidth: true
                implicitHeight: 30
                text: qsTr("Copy name")
                onClicked: library.copy_name(panel.index)
                background: Rectangle {
                    radius: 6
                    color: copyBtn.hovered ? Qt.lighter(theme.tokens.accent, 1.08)
                                           : theme.tokens.accent
                }
                contentItem: Text {
                    text: copyBtn.text
                    color: theme.tokens.bg
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
            Button {
                id: collBtn
                Layout.fillWidth: true
                implicitHeight: 30
                text: qsTr("To collection")
                onClicked: collMenu.popup()
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: collBtn.hovered ? theme.tokens.accent : theme.tokens.border
                }
                contentItem: Text {
                    text: collBtn.text
                    color: theme.tokens.text
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
        Button {
            id: exportBtn
            Layout.fillWidth: true
            implicitHeight: 30
            enabled: index >= 0
            text: qsTr("Export…")
            onClicked: exportPopup.open()
            background: Rectangle {
                radius: 6
                color: theme.tokens.surface2
                border.color: exportBtn.hovered ? theme.tokens.accent : theme.tokens.border
            }
            contentItem: Text {
                text: exportBtn.text
                color: theme.tokens.text
                font.family: theme.uiFont
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    Menu {
        id: collMenu
        width: 200
        Repeater {
            model: library.collections
            MenuItem {
                required property var modelData
                text: modelData.name
                onTriggered: library.add_to_collection(panel.index, modelData.id)
            }
        }
        MenuSeparator { }
        MenuItem {
            text: qsTr("New collection…")
            onTriggered: newCollDialog.open()
        }
    }

    Dialog {
        id: newCollDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("New collection")
        modal: true
        width: 280
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: {
            var id = library.create_collection(collNameInput.text.trim())
            if (id > 0 && panel.index >= 0)
                library.add_to_collection(panel.index, id)
            collNameInput.text = ""
        }
        ColumnLayout {
            width: parent.width
            TextField {
                id: collNameInput
                Layout.fillWidth: true
                placeholderText: qsTr("collection name")
            }
        }
    }

    Popup {
        id: exportPopup
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 300
        padding: 14
        modal: true
        background: Rectangle {
            color: theme.tokens.surface
            border.color: theme.tokens.border
            border.width: 1
            radius: 8
        }
        ColumnLayout {
            spacing: 8
            Text {
                text: qsTr("Export")
                font.family: theme.headingFont
                font.pixelSize: 16
                font.letterSpacing: 1.2
                font.capitalization: Font.AllUppercase
                color: theme.tokens.text
            }
            Text {
                text: qsTr("Format")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
            }
            Flow {
                spacing: 6
                Layout.fillWidth: true
                Repeater {
                    model: ["png", "jpeg", "webp", "ico", "pdf", "gif", "tiff", "bmp"]
                    Chip {
                        required property var modelData
                        label: modelData
                        on: panel.exportFormat === modelData
                        onPicked: panel.exportFormat = modelData
                    }
                }
            }
            Text {
                text: qsTr("Size")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
            }
            Flow {
                spacing: 6
                Layout.fillWidth: true
                Repeater {
                    model: ["16", "32", "64", "128", "256", "orig"]
                    Chip {
                        required property var modelData
                        label: modelData === "orig" ? qsTr("orig") : modelData + "px"
                        on: panel.exportSize === modelData
                        onPicked: panel.exportSize = modelData
                    }
                }
            }
            Button {
                id: exportFolderBtn
                Layout.fillWidth: true
                text: panel.exportDir === "" ? qsTr("Choose folder…") : panel.exportDir
                onClicked: folderDialog.open()
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
                contentItem: Text {
                    text: exportFolderBtn.text
                    color: theme.tokens.textMuted
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    elide: Text.ElideMiddle
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
            Button {
                id: doExportBtn
                Layout.fillWidth: true
                implicitHeight: 30
                enabled: panel.exportDir !== "" && panel.index >= 0
                text: qsTr("Export")
                onClicked: {
                    library.export_asset(panel.index, panel.exportFormat,
                                         panel.exportSize, panel.exportDir)
                    exportPopup.close()
                }
                background: Rectangle {
                    radius: 6
                    color: doExportBtn.enabled ? theme.tokens.accent : theme.tokens.border
                }
                contentItem: Text {
                    text: doExportBtn.text
                    color: theme.tokens.bg
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }

    FolderDialog {
        id: folderDialog
        onAccepted: panel.exportDir = panel.toLocalPath(selectedFolder)
    }
}
