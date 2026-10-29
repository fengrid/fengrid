import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

Rectangle {
    id: panel
    color: theme.tokens.surface

    // QA hook: the scrolling body (Main scrolls it for overflow shots)
    property alias bodyFlick: bodyFlick

    property int index: -1
    property Item gridView
    property string exportDir: ""
    property string exportFormat: "png"   // kept: legacy single-format users
    property string exportSize: "64"
    property var exportFormats: []
    property string exportTint: ""
    property var d: null
    // multi-selection (grid checkboxes): aggregate summary instead of the
    // single-asset detail — Main binds this to the grid's selectedIds
    property var selectedIds: []
    property var sel: null                 // library.selection_details map
    readonly property bool multi: sel !== null
    // QA modal registry (--dialog <name>)
    readonly property var qaModals: ({ "fieldDialog": fieldDialog })
    // taxonomy rows for the selected asset, snapshotted at reload time
    property var fieldsModel: []
    property var linksModel: []

    onIndexChanged: reload()
    onSelectedIdsChanged: reload()
    onVisibleChanged: if (visible) reload()

    function reload() {
        d = (index >= 0 && library !== null) ? library.get_details(index) : null
        // ≥2 checked boxes → aggregate view; the bridge clamps unknown
        // ids away, so a stale selection (rescan purged a row) falls
        // back to the single view instead of an empty panel
        sel = (selectedIds.length > 1 && library !== null)
              ? library.selection_details(selectedIds) : null
        fieldsModel = taxonomy !== null ? taxonomy.fields : []
        linksModel = (taxonomy !== null && d && !multi)
                     ? taxonomy.links_for("icon", d.id) : []
    }

    // multi-select helpers
    function fmtFormats(fmts) {
        if (!fmts || fmts.length === 0)
            return "—"
        var out = []
        for (var i = 0; i < fmts.length && i < 3; i++)
            out.push(fmts[i].ext + " ×" + fmts[i].n)
        var rest = fmts.length - out.length
        if (rest > 0)
            out.push("+" + rest)
        return out.join(" · ")
    }
    function fmtPixels(s) {
        if (!s || s.minW === undefined)
            return "—"
        if (s.minH !== undefined && (s.minW !== s.minH || s.maxW !== s.maxH))
            return s.minW + "×" + s.minH + " – " + s.maxW + "×" + s.maxH
        return s.minW === s.maxW ? s.minW + " px" : s.minW + "–" + s.maxW + " px"
    }
    function fmtMode(s) {
        if (!s)
            return "—"
        var out = []
        if (s.mono > 0)
            out.push(s.mono + " mono")
        if (s.color > 0)
            out.push(s.color + " color")
        return out.length ? out.join(" · ") : "—"
    }
    function fmtJoined(list, max) {
        if (!list || list.length === 0)
            return "—"
        var out = list.slice(0, max || 2).join(", ")
        var rest = list.length - Math.min(list.length, max || 2)
        return rest > 0 ? out + " (+" + rest + ")" : out
    }
    function fmtColors(s) {
        if (!s || s.avgColors === undefined)
            return "—"
        return qsTr("avg %1").arg(s.avgColors)
    }

    // aggregate property rows for the multi-selection summary
    readonly property var selRows: sel ? [
        { l: qsTr("items"),   v: String(sel.count) },
        { l: qsTr("size"),    v: fmtBytes(sel.bytes) },
        { l: qsTr("formats"), v: fmtFormats(sel.formats) },
        { l: qsTr("pixels"),  v: fmtPixels(sel) },
        { l: qsTr("mode"),    v: fmtMode(sel) },
        { l: qsTr("colors"),  v: fmtColors(sel) },
        { l: qsTr("themes"),  v: fmtJoined(sel.themes, 2) },
        { l: qsTr("starred"), v: sel.starred > 0
                                ? qsTr("%1 of %2").arg(sel.starred)
                                  .arg(sel.count) : qsTr("none") }
    ] : []

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
        return Icons.toLocalPath(u)   // single source of truth (#41)
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

    // scrolling body — spans the FULL panel height so overflowing
    // section content passes BEHIND the pinned action footer below
    Flickable {
        id: bodyFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: body.implicitHeight + 28 + footerRect.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            width: 6
            contentItem: Rectangle {
                implicitWidth: 6
                radius: 3
                color: theme.tokens.textMuted
            }
            background: Item { }
        }
        ColumnLayout {
            id: body
            x: 14
            y: 14
            width: bodyFlick.width - 28
            spacing: 10

        // preview: single asset = large tile; multi-selection = a flow
        // of small thumbnails (first 12, "+N" chip beyond)
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 112
            visible: !panel.multi
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
        Flow {
            visible: panel.multi
            spacing: 6
            Layout.fillWidth: true
            Repeater {
                model: panel.sel ? panel.sel.paths.slice(0, 12) : []
                Rectangle {
                    required property var modelData
                    width: 34
                    height: 34
                    radius: 6
                    color: theme.tokens.bg
                    border.color: theme.tokens.border
                    Image {
                        anchors.centerIn: parent
                        width: 26
                        height: 26
                        source: Icons.fileUrl(modelData)
                        asynchronous: true
                        sourceSize.width: 64
                        sourceSize.height: 64
                        fillMode: Image.PreserveAspectFit
                    }
                }
            }
            Rectangle {
                visible: panel.sel && panel.sel.paths.length > 12
                width: 34
                height: 34
                radius: 6
                color: theme.tokens.surface2
                border.color: theme.tokens.border
                Text {
                    anchors.centerIn: parent
                    text: "+" + (panel.sel ? panel.sel.paths.length - 12 : 0)
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.textMuted
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: panel.multi ? qsTr("%1 selected").arg(panel.sel.count)
                              : (d ? d.name : "")
            font.family: theme.headingFont
            font.pixelSize: panel.multi ? 18 : 22
            font.letterSpacing: 1
            color: theme.tokens.text
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            visible: panel.multi || d !== null
            text: panel.multi
                  ? panel.fmtFormats(panel.sel.formats)
                  : (d ? ((d.theme || "—") + (d.context ? " · " + d.context : "")) : "")
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
                model: panel.multi ? panel.selRows : (d ? [
                    { l: qsTr("size"),   v: d.sizePx ? d.sizePx + "px" : "—" },
                    { l: qsTr("pixels"), v: (d.width && d.height) ? d.width + "×" + d.height : "—" },
                    { l: qsTr("type"),   v: d.ext ? d.ext.toUpperCase() : "—" },
                    { l: qsTr("file"),   v: panel.fmtBytes(d.bytes) },
                    { l: qsTr("mode"),   v: d.colorspace || "—" },
                    { l: qsTr("colors"), v: (d.colorCount !== null && d.colorCount !== undefined) ? String(d.colorCount) : "—" },
                    { l: qsTr("tone"),   v: d.mono === 1 ? qsTr("mono") : (d.mono === 0 ? qsTr("color") : "—") }
                ] : [])
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

        // ── IDENTITY: the generated GUID + the user slug ([[ … ]] links) ──
        SectionHeader {
            text: qsTr("Identity")
            visible: !panel.multi
            Layout.fillWidth: true
        }
        ColumnLayout {
            visible: d !== null && !panel.multi
            spacing: 4
            Layout.fillWidth: true
            RowLayout {
                spacing: 6
                Layout.fillWidth: true
                Text {
                    text: qsTr("GUID")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                    Layout.preferredWidth: 56
                }
                Text {
                    id: guidText
                    text: d ? (d.guid || "") : ""
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.text
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
                IconButton {
                    icon_name: "copy"
                    icon_px: 11
                    implicitWidth: 22
                    implicitHeight: 22
                    ToolTip.text: qsTr("Copy GUID")
                    onClicked: {
                        if (guidText.text !== "" && library !== null)
                            library.copy_text(guidText.text)
                    }
                }
            }
            RowLayout {
                spacing: 6
                Layout.fillWidth: true
                Text {
                    text: qsTr("Slug")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                    Layout.preferredWidth: 56
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: 24
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: slugField.activeFocus
                                  ? theme.tokens.accent : theme.tokens.border
                    TextInput {
                        id: slugField
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        verticalAlignment: TextInput.AlignVCenter
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.text
                        clip: true
                        text: d ? (d.slug || "") : ""
                        onAccepted: commitSlug()
                        onEditingFinished: commitSlug()
                        function commitSlug() {
                            if (d === null || taxonomy === null)
                                return
                            if (text === (d.slug || ""))
                                return
                            taxonomy.set_slug("icon", d.id, text)
                            panel.reload()
                        }
                    }
                }
            }
            Text {
                visible: slugField.text !== ""
                text: qsTr("link with [[ %1 ]]").arg(slugField.text)
                font.family: theme.monoFont
                font.pixelSize: 9
                color: theme.tokens.textMuted
            }
        }

        SectionHeader {
            text: qsTr("Variants")
            visible: !panel.multi && d && d.variants.length > 0
            Layout.fillWidth: true
        }
        Flow {
            visible: !panel.multi && d && d.variants.length > 0
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

        SectionHeader {
            text: qsTr("Tags")
            visible: !panel.multi
            Layout.fillWidth: true
        }
        Flow {
            visible: !panel.multi
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
            visible: !panel.multi
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

        // multi-selection: tags applied to EVERY selected asset
        // (read-only summary — bulk tag edits stay in the context menu)
        SectionHeader {
            text: qsTr("Shared tags")
            visible: panel.multi
            Layout.fillWidth: true
        }
        Flow {
            visible: panel.multi
            spacing: 6
            Layout.fillWidth: true
            Repeater {
                model: panel.sel ? panel.sel.sharedTags : []
                Rectangle {
                    required property var modelData
                    width: sharedTagText.implicitWidth + 18
                    height: 22
                    radius: 11
                    color: theme.tokens.surface2
                    border.color: theme.tokens.border
                    Text {
                        id: sharedTagText
                        anchors.centerIn: parent
                        text: "#" + modelData
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.text
                    }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: panel.multi && panel.sel
                     && panel.sel.sharedTags.length === 0
            text: qsTr("No tag is applied to every selected asset")
            font.family: theme.uiFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
            wrapMode: Text.Wrap
        }

        // CUSTOM FIELDS (taxonomy layer): every defined field with this
        // asset's value, edited in place — text/number/date/id as text
        // inputs, bool as a checkbox, select as a choice combo; id fields
        // gain a Generate button. "+ Field" defines a new global field.
        SectionHeader {
            text: qsTr("FIELDS")
            visible: !panel.multi
        }
        Repeater {
            model: fieldsModel
            visible: !panel.multi
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
            visible: !panel.multi
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
        SectionHeader {
            text: qsTr("LINKS")
            visible: !panel.multi
        }
        Repeater {
            model: linksModel
            visible: !panel.multi
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
            visible: !panel.multi && taxonomy !== null && taxonomy.links_for(
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
            FgMenuItem {
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
            footer: FgDialogFooter {
                acceptLabel: qsTr("Create")
                acceptEnabled: fName.text.trim() !== ""
                onCancelClicked: fieldDialog.reject()
                onAcceptClicked: {
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
            }
        }



        Text {
            Layout.fillWidth: true
            visible: !panel.multi
            text: d ? d.path : ""
            font.family: theme.monoFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
            wrapMode: Text.WrapAnywhere
            maximumLineCount: 3
            elide: Text.ElideMiddle
        }

    }
    }

    Rectangle {                 // pinned action footer — opaque, so the
        id: footerRect           // sections above scroll behind it
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        implicitHeight: footerCol.implicitHeight + 24
        color: theme.tokens.surface

        Rectangle {              // hairline top edge
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 1
            color: theme.tokens.border
        }
        ColumnLayout {
            id: footerCol
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: 12
            spacing: 10
            RowLayout {
                spacing: 8
                Layout.fillWidth: true
                Button {
                    id: starBtn
                    implicitWidth: 36
                    implicitHeight: 30
                    visible: !panel.multi
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
                            sourceSize.width: 16
                            sourceSize.height: 16
                            source: Icons.url(
                                "star",
                                d && d.starred ? theme.tokens.litPane
                                               : theme.tokens.textMuted,
                                d && d.starred ? theme.tokens.litPane : "none",
                                16)
                        }
                    }
                }
                Button {
                    id: copyBtn
                    Layout.fillWidth: true
                    implicitHeight: 30
                    text: panel.multi ? qsTr("Copy names") : qsTr("Copy name")
                    onClicked: panel.multi
                               ? library.copy_names(panel.selectedIds)
                               : library.copy_name(panel.index)
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
                    visible: !panel.multi
                    text: qsTr("To collection")
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
                enabled: panel.multi || index >= 0
                text: panel.multi
                      ? qsTr("Export %1 selected…").arg(panel.sel.count)
                      : qsTr("Export…")
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
    }

    Menu {
        id: collMenu
        width: 200
        Repeater {
            model: library.collections
            FgMenuItem {
                required property var modelData
                text: modelData.name
                onTriggered: library.add_to_collection(panel.index, modelData.id)
            }
        }
        FgMenuSeparator { }
        FgMenuItem {
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
        onAboutToShow: {
            if (panel.exportFormats.length === 0 && dataio !== null)
                panel.exportFormats = dataio.exportOpts.icon_fmts.slice()
            if (dataio !== null)
                panel.exportTint = dataio.exportOpts.tint || ""
        }
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
                text: panel.multi
                      ? qsTr("Export %1 selected").arg(
                            panel.sel ? panel.sel.count : 0)
                      : qsTr("Export")
                font.family: theme.headingFont
                font.pixelSize: 16
                font.letterSpacing: 1.2
                font.capitalization: Font.AllUppercase
                color: theme.tokens.text
            }
            Text {
                visible: panel.multi
                text: qsTr("every selected asset, one folder")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
            }
            Text {
                text: qsTr("Formats (multi-select)")
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
                        on: panel.exportFormats.indexOf(modelData) >= 0
                        onPicked: {
                            var out = []
                            for (var i = 0; i < panel.exportFormats.length; i++)
                                if (panel.exportFormats[i] !== modelData)
                                    out.push(panel.exportFormats[i])
                            if (out.length === panel.exportFormats.length)
                                out.push(modelData)
                            if (out.length)
                                panel.exportFormats = out
                        }
                    }
                }
            }
            Text {
                text: qsTr("Tint (optional, e.g. #39B8C4)")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
            }
            TextField {
                id: tintField
                Layout.fillWidth: true
                text: panel.exportTint
                onTextEdited: panel.exportTint = text
                placeholderText: qsTr("recolor through alpha…")
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.text
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: tintField.activeFocus
                                  ? theme.tokens.accent : theme.tokens.border
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
                enabled: panel.exportDir !== ""
                         && (panel.multi ? panel.sel !== null
                                         : panel.index >= 0)
                text: qsTr("Export")
                onClicked: {
                    if (panel.exportFormats.length === 0)
                        panel.exportFormats = [panel.exportFormat]
                    var opts = {
                        icon_fmts: panel.exportFormats,
                        icon_size: panel.exportSize,
                        tint: panel.exportTint,
                        script: "",
                        script_enabled: false
                    }
                    // multi-selection: export the package (all selected
                    // assets into one folder) in a single dataio job
                    var paths = panel.multi
                                ? (panel.sel ? panel.sel.paths : [])
                                : (panel.d ? [panel.d.path] : [])
                    if (paths.length)
                        dataio.exportIcons(paths, panel.exportDir,
                                           JSON.stringify(opts))
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
