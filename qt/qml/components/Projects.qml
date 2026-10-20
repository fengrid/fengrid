import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// Projects pane (M4): the design-token coordinator + component composer.
// Port of the 0.x projects.html configurator — four parameter areas
// (Colors / Type / Icons / Preview), the attached-assets strip, a live
// boilerplate preview rendered from the SAME generator the exporter uses,
// and a zip/tar.gz export. Settings persist per project as JSON.
Item {
    id: projectsRoot

    // local editable mirror of the current project's settings; written
    // through on every edit via projects.set_setting()
    property var st: ({})
    property var fontsModel: []
    property var iconOpts: []
    property var fontOpts: []
    property var snippetOpts: []
    property var paletteOpts: []

    function syncSettings() {
        if (projects !== null && projects.settings !== undefined
                && projects.settings !== null)
            st = projects.settings
        else
            st = {}
    }

    function refreshPickers() {
        if (projects === null)
            return
        iconOpts = projects.icon_options()
        fontOpts = projects.font_options()
        snippetOpts = projects.snippet_options()
        paletteOpts = projects.palette_options()
        fontsModel = projects.family_options()
    }

    Connections {
        target: projects
        function onCurrentChanged() { projectsRoot.syncSettings() }
        function onProjectsChanged() { projectsRoot.refreshPickers() }
    }
    Component.onCompleted: { syncSettings(); refreshPickers() }

    Toast { id: toast }

    // section heading inside the params column — instances set `text` on
    // the base Text directly; no custom property needed
    component SectionLabel: Text {
        font.family: theme.monoFont
        font.pixelSize: 9
        font.letterSpacing: 1.4
        color: theme.tokens.accent
    }

    // one "add <kind>" row: combo + add button
    component AddAssetRow: RowLayout {
        id: addRow
        property string label
        property var opts: []
        signal picked(int id, string label)
        Text {
            text: addRow.label
            font.family: theme.monoFont; font.pixelSize: 10
            color: theme.tokens.textMuted
            Layout.preferredWidth: 70
        }
        ComboBox {
            id: pick
            Layout.fillWidth: true
            model: addRow.opts
            textRole: "name"
            background: Rectangle {
                radius: 4; color: theme.tokens.surface2
                border.color: theme.tokens.border
            }
            contentItem: Text {
                text: pick.displayText
                font.family: theme.monoFont; font.pixelSize: 10
                color: theme.tokens.text
                verticalAlignment: Text.AlignVCenter; leftPadding: 6
            }
        }
        Button {
            text: qsTr("+")
            onClicked: {
                if (pick.currentIndex >= 0) {
                    var o = addRow.opts[pick.currentIndex]
                    addRow.picked(o.id, o.name)
                }
            }
        }
    }

    // ------------------------------------------------------------- sidebar
    Rectangle {
        id: sidebar
        width: 250
        color: theme.tokens.surface
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 6

            Button {
                Layout.fillWidth: true
                text: qsTr("+ New project")
                onClicked: projects !== null && projects.new_project()
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.accentProject
                }
                contentItem: Text {
                    text: parent.text
                    color: theme.tokens.bg
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: projSearch.activeFocus ? theme.tokens.accent
                                                     : theme.tokens.border
                TextInput {
                    id: projSearch
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                    onTextChanged: projDebounce.restart()
                }
                Text {
                    visible: projSearch.text === ""
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("search projects…")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
                Timer {
                    id: projDebounce
                    interval: 200
                    onTriggered: projects !== null && projects.set_search(projSearch.text)
                }
            }

            ListView {
                id: projList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 4
                model: projects !== null ? projects.projects : []
                ScrollBar.vertical: ScrollBar { }

                delegate: Rectangle {
                    id: projItem
                    required property var modelData
                    readonly property var row: modelData
                    width: projList.width
                    height: projRow.implicitHeight + 12
                    radius: 7
                    color: projects !== null
                           && projects.currentId === projItem.modelData.id
                           ? theme.tokens.surface2 : "transparent"
                    border.color: projects !== null
                                  && projects.currentId === projItem.modelData.id
                                  ? theme.tokens.accentProject : "transparent"

                    ColumnLayout {
                        id: projRow
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 2
                        Text {
                            text: projItem.modelData.name
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: theme.tokens.text
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Text {
                            text: projItem.modelData.asset_count + " assets · "
                                  + String(projItem.modelData.updated).slice(0, 10)
                            font.family: theme.monoFont
                            font.pixelSize: 9
                            color: theme.tokens.textMuted
                            Layout.fillWidth: true
                        }
                    }
                    MouseArea {
                        id: projMa
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            projects !== null
                                && projects.open(projItem.modelData.id)
                            if (mouse.button === Qt.RightButton)
                                projMenu.popup()
                        }
                    }
                }

                // project context menu
                Menu {
                    id: projMenu
                    width: 190
                    padding: 4
                    background: Rectangle {
                        radius: 8; color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    MenuItem {
                        text: qsTr("Open")
                        height: 28
                        onTriggered: projects !== null && projects.open(
                            projList.currentItem ? projList.currentItem.row.id : -1)
                    }
                    MenuItem {
                        text: qsTr("Export…")
                        height: 28
                        onTriggered: {
                            if (projList.currentItem)
                                projects.open(projList.currentItem.row.id)
                            exportDialog.open()
                        }
                    }
                    // a project can collect an ENTIRE collection — its refs
                    // follow live (project_asset kind 'collection')
                    MenuItem {
                        id: attachCollItem
                        text: qsTr("Attach collection…")
                        height: 28
                        enabled: library !== null
                                 && library.collections.length > 0
                        onHoveredChanged: if (hovered) attachCollSub.popup(
                                              attachCollItem,
                                              attachCollItem.width, 0)
                        onClicked: attachCollSub.popup(
                                       attachCollItem, attachCollItem.width, 0)
                        Menu {
                            id: attachCollSub
                            width: 200
                            padding: 4
                            background: Rectangle {
                                radius: 8; color: theme.tokens.surface
                                border.color: theme.tokens.border
                            }
                            Repeater {
                                model: library !== null
                                       ? library.collections : []
                                MenuItem {
                                    id: attachCollTarget
                                    required property var modelData
                                    height: 28
                                    onTriggered: {
                                        if (projList.currentItem
                                                && projects !== null)
                                            projects.add_asset(
                                                "collection",
                                                attachCollTarget.modelData.id,
                                                attachCollTarget.modelData.name)
                                    }
                                    contentItem: Text {
                                        text: attachCollTarget.modelData.name
                                        font.family: theme.uiFont
                                        font.pixelSize: 11
                                        color: theme.tokens.text
                                        elide: Text.ElideRight
                                        verticalAlignment: Text.AlignVCenter
                                        leftPadding: 10
                                    }
                                    background: Rectangle {
                                        color: attachCollTarget.hovered
                                               ? theme.tokens.surface2
                                               : "transparent"
                                        radius: 5
                                    }
                                }
                            }
                        }
                    }
                    MenuSeparator {
                        topPadding: 3; bottomPadding: 3
                        contentItem: Rectangle {
                            implicitHeight: 1; color: theme.tokens.border
                        }
                    }
                    MenuItem {
                        text: qsTr("Delete project")
                        height: 28
                        onTriggered: {
                            if (projList.currentItem && projects !== null)
                                projects.remove(projList.currentItem.row.id)
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: projects !== null && projects.projectCount === 0
                    text: qsTr("No projects yet — create one!")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }
        }
    }
    Rectangle { width: 1; anchors.top: parent.top; anchors.bottom: parent.bottom
                anchors.left: sidebar.right; color: theme.tokens.border }

    // ----------------------------------------------------------- main area
    ColumnLayout {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: sidebar.right
        anchors.right: parent.right
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 40
            color: theme.tokens.surface
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 8
                spacing: 6

                TextField {
                    id: nameField
                    Layout.preferredWidth: 220
                    text: projects !== null && projects.current.name !== undefined
                          ? projects.current.name : ""
                    onEditingFinished: projects !== null
                                       && projects.update_meta("name", text)
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: theme.tokens.text
                    placeholderText: qsTr("project name")
                    background: Rectangle {
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: nameField.activeFocus
                                      ? theme.tokens.accent : theme.tokens.border
                    }
                }
                Item { Layout.fillWidth: true }
                ComboBox {
                    id: exportFmt
                    model: [qsTr(".zip"), qsTr(".tar.gz")]
                    Layout.preferredWidth: 92
                    background: Rectangle {
                        radius: 6; color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: exportFmt.displayText
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: theme.tokens.text
                        verticalAlignment: Text.AlignVCenter; leftPadding: 6
                    }
                }
                Button {
                    id: exportBtn
                    text: qsTr("Export")
                    enabled: projects !== null && projects.currentId >= 0
                    onClicked: exportDialog.open()
                    ToolTip.visible: hovered
                    ToolTip.text: qsTr("Tokens, fonts, icons, boilerplate site + manifest")
                    background: Rectangle {
                        radius: 6
                        color: exportBtn.enabled ? theme.tokens.accent
                                                 : theme.tokens.border
                    }
                    contentItem: Text {
                        text: exportBtn.text
                        color: theme.tokens.bg
                        font.family: theme.uiFont; font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 10; rightPadding: 10
                    }
                }
                Button {
                    id: runBtn
                    text: qsTr("Run ▸")
                    enabled: projects !== null && projects.currentId >= 0
                             && previewProfile !== null
                    onClicked: {
                        previewDoc = projects !== null ? projects.preview_html() : ""
                        previewActive = true
                    }
                    background: Rectangle {
                        radius: 6
                        color: runBtn.enabled ? theme.tokens.accent
                                              : theme.tokens.border
                    }
                    contentItem: Text {
                        text: runBtn.text
                        color: runBtn.enabled ? theme.tokens.bg
                                              : theme.tokens.textMuted
                        font.family: theme.uiFont; font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 10; rightPadding: 10
                    }
                }
                IconButton {
                    icon_name: "help"
                    ToolTip.text: qsTr("Help & guide")
                    onClicked: helpPopup.open()
                }
                Button {
                    id: demoBtn
                    text: demo !== null && demo.installed
                          ? qsTr("Remove demo…") : qsTr("Load demo suite")
                    Layout.preferredHeight: 26
                    onClicked: {
                        if (demo !== null && demo.installed)
                            demoDialog.open()
                        else
                            demo.install()
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: demo !== null && demo.installed
                        ? qsTr("Delete demo data — choose which kinds to keep")
                        : qsTr("Load the showcase suite: 14 projects with example icons, fonts, snippets and palettes")
                    background: Rectangle {
                        radius: 6
                        color: demoBtn.hovered ? theme.tokens.surface2
                                               : "transparent"
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: demoBtn.text
                        color: theme.tokens.text
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                    }
                }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            handle: Rectangle { color: theme.tokens.border; width: 1 }

            // ---- parameters column
            Flickable {
                SplitView.preferredWidth: 360
                SplitView.minimumWidth: 300
                clip: true
                contentHeight: paramsCol.implicitHeight + 20
                ScrollBar.vertical: ScrollBar { }

                ColumnLayout {
                    id: paramsCol
                    width: parent.width - 8
                    x: 4
                    spacing: 10

                    // COLORS -------------------------------------------------
                    SectionLabel { text: qsTr("Colors") }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 8
                        rowSpacing: 4
                        Repeater {
                            model: projects !== null ? projects.roles : []
                            RowLayout {
                                id: roleRow
                                required property string modelData
                                Layout.fillWidth: true
                                Text {
                                    text: roleRow.modelData
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: theme.tokens.textMuted
                                    Layout.preferredWidth: 44
                                }
                                Rectangle {
                                    width: 14; height: 14; radius: 3
                                    color: {
                                        var c = projectsRoot.st.colors
                                                ? projectsRoot.st.colors[roleRow.modelData]
                                                : ""
                                        return c && c !== "" ? c : "transparent"
                                    }
                                    border.color: theme.tokens.border
                                }
                                TextField {
                                    id: roleField
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 40
                                    Layout.preferredWidth: 60
                                    text: {
                                        var c = projectsRoot.st.colors
                                                ? projectsRoot.st.colors[roleRow.modelData]
                                                : ""
                                        return c || ""
                                    }
                                    placeholderText: qsTr("auto")
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: theme.tokens.text
                                    onEditingFinished: projects !== null
                                        && projects.set_setting(
                                            "colors." + roleRow.modelData, text)
                                    background: Rectangle {
                                        radius: 4; color: theme.tokens.surface2
                                        border.color: roleField.activeFocus
                                                      ? theme.tokens.accent
                                                      : theme.tokens.border
                                    }
                                }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("radius")
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }
                        Slider {
                            id: radiusSlider
                            Layout.fillWidth: true
                            from: 0; to: 32; stepSize: 1
                            value: projectsRoot.st.colors
                                   ? (projectsRoot.st.colors.radius || 10) : 10
                            onMoved: projects !== null
                                     && projects.set_setting("colors.radius", value)
                        }
                        Text {
                            text: (projectsRoot.st.colors
                                   ? (projectsRoot.st.colors.radius || 10) : 10) + "px"
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.text
                            Layout.preferredWidth: 36
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("prefix")
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }
                        TextField {
                            id: prefixField
                            Layout.preferredWidth: 70
                            text: projectsRoot.st.prefix || "fg"
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.text
                            onEditingFinished: projects !== null
                                               && projects.set_setting("prefix", text)
                            background: Rectangle {
                                radius: 4; color: theme.tokens.surface2
                                border.color: prefixField.activeFocus
                                              ? theme.tokens.accent
                                              : theme.tokens.border
                            }
                        }
                        Item { Layout.fillWidth: true }
                        ComboBox {
                            id: palApply
                            Layout.preferredWidth: 108
                            model: projectsRoot.paletteOpts
                            textRole: "name"
                            background: Rectangle {
                                radius: 4; color: theme.tokens.surface2
                                border.color: theme.tokens.border
                            }
                            contentItem: Text {
                                text: palApply.displayText
                                font.family: theme.monoFont; font.pixelSize: 10
                                color: theme.tokens.text
                                verticalAlignment: Text.AlignVCenter; leftPadding: 6
                            }
                        }
                        Button {
                            text: qsTr("apply")
                            onClicked: {
                                if (palApply.currentIndex < 0) return
                                projects.apply_palette(
                                    projectsRoot.paletteOpts[palApply.currentIndex].id)
                            }
                        }
                    }

                    // TYPE ---------------------------------------------------
                    SectionLabel { text: qsTr("Type") }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("body")
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.textMuted
                            Layout.preferredWidth: 56
                        }
                        ComboBox {
                            id: bodyFam
                            Layout.fillWidth: true
                            model: projectsRoot.fontsModel
                            editable: true
                            editText: projectsRoot.st.type ? (projectsRoot.st.type.body || "") : ""
                            onActivated: function (idx) {
                                projects.set_setting("type.body", projectsRoot.fontsModel[idx])
                            }
                            background: Rectangle {
                                radius: 4; color: theme.tokens.surface2
                                border.color: theme.tokens.border
                            }
                            contentItem: TextInput {
                                text: bodyFam.editText
                                font.family: theme.monoFont; font.pixelSize: 10
                                color: theme.tokens.text
                                verticalAlignment: TextInput.AlignVCenter
                                leftPadding: 6
                                onEditingFinished: projects !== null
                                                   && projects.set_setting("type.body", text)
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("heading")
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.textMuted
                            Layout.preferredWidth: 56
                        }
                        ComboBox {
                            id: headFam
                            Layout.fillWidth: true
                            model: projectsRoot.fontsModel
                            editable: true
                            editText: projectsRoot.st.type ? (projectsRoot.st.type.heading || "") : ""
                            onActivated: function (idx) {
                                projects.set_setting("type.heading", projectsRoot.fontsModel[idx])
                            }
                            background: Rectangle {
                                radius: 4; color: theme.tokens.surface2
                                border.color: theme.tokens.border
                            }
                            contentItem: TextInput {
                                text: headFam.editText
                                font.family: theme.monoFont; font.pixelSize: 10
                                color: theme.tokens.text
                                verticalAlignment: TextInput.AlignVCenter
                                leftPadding: 6
                                onEditingFinished: projects !== null
                                                   && projects.set_setting("type.heading", text)
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("base / scale")
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }
                        TextField {
                            id: baseField
                            Layout.preferredWidth: 56
                            text: projectsRoot.st.type
                                  ? String(projectsRoot.st.type.baseSize || 16) : "16"
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.text
                            onEditingFinished: projects !== null
                                               && projects.set_setting("type.baseSize", text)
                            background: Rectangle {
                                radius: 4; color: theme.tokens.surface2
                                border.color: baseField.activeFocus
                                              ? theme.tokens.accent : theme.tokens.border
                            }
                        }
                        TextField {
                            id: scaleField
                            Layout.preferredWidth: 56
                            text: projectsRoot.st.type
                                  ? String(projectsRoot.st.type.scale || 1.25) : "1.25"
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.text
                            onEditingFinished: projects !== null
                                               && projects.set_setting("type.scale", text)
                            background: Rectangle {
                                radius: 4; color: theme.tokens.surface2
                                border.color: scaleField.activeFocus
                                              ? theme.tokens.accent : theme.tokens.border
                            }
                        }
                    }

                    // ICONS --------------------------------------------------
                    SectionLabel { text: qsTr("Icons") }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("size")
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }
                        Slider {
                            id: iconSizeSlider
                            Layout.fillWidth: true
                            from: 12; to: 128; stepSize: 2
                            value: projectsRoot.st.iconSize || 32
                            onMoved: projects !== null
                                     && projects.set_setting("iconSize", value)
                        }
                        Text {
                            text: (projectsRoot.st.iconSize || 32) + "px"
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.text
                            Layout.preferredWidth: 36
                        }
                    }
                    AddAssetRow {
                        label: qsTr("add icon")
                        opts: projectsRoot.iconOpts
                        onPicked: function (id, label) {
                            projects.add_asset("icon", id, label)
                        }
                    }

                    // FONTS / SNIPPETS / PALETTES ----------------------------
                    SectionLabel { text: qsTr("Assets") }
                    AddAssetRow {
                        label: qsTr("add font")
                        opts: projectsRoot.fontOpts
                        onPicked: function (id, label) {
                            projects.add_asset("font", id, label)
                        }
                    }
                    AddAssetRow {
                        label: qsTr("add snippet")
                        opts: projectsRoot.snippetOpts
                        onPicked: function (id, label) {
                            projects.add_asset("snippet", id, label)
                        }
                    }
                    AddAssetRow {
                        label: qsTr("add palette")
                        opts: projectsRoot.paletteOpts
                        onPicked: function (id, label) {
                            projects.add_asset("palette", id, label)
                        }
                    }

                    // attached assets list
                    ListView {
                        id: assetList
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(
                            (projects !== null && projects.assets !== null
                             ? projects.assets.length : 0) * 26 + 6, 160)
                        model: projects !== null && projects.assets !== null
                               ? projects.assets : []
                        clip: true
                        ScrollBar.vertical: ScrollBar { }
                        delegate: RowLayout {
                            id: assetRow
                            required property var modelData
                            width: assetList.width
                            height: 24
                            Text {
                                text: assetRow.modelData.asset_kind + " · "
                                      + assetRow.modelData.label
                                font.family: theme.monoFont; font.pixelSize: 10
                                color: theme.tokens.text
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            IconButton {
                                icon_name: "trash"
                                onClicked: projects.remove_asset(
                                    assetRow.modelData.id)
                            }
                        }
                    }

                    // PREVIEW ------------------------------------------------
                    SectionLabel { text: qsTr("Preview") }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("source")
                            font.family: theme.monoFont; font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }
                        ComboBox {
                            id: pvMode
                            Layout.preferredWidth: 110
                            model: [qsTr("Site"), qsTr("Snippet")]
                            currentIndex: projectsRoot.st.preview
                                          && projectsRoot.st.preview.mode === "snippet" ? 1 : 0
                            onActivated: function (idx) {
                                projects.set_setting(
                                    "preview.mode", idx === 1 ? "snippet" : "site")
                            }
                            background: Rectangle {
                                radius: 4; color: theme.tokens.surface2
                                border.color: theme.tokens.border
                            }
                            contentItem: Text {
                                text: pvMode.displayText
                                font.family: theme.monoFont; font.pixelSize: 10
                                color: theme.tokens.text
                                verticalAlignment: Text.AlignVCenter; leftPadding: 6
                            }
                        }
                        ComboBox {
                            id: pvSnippet
                            Layout.fillWidth: true
                            model: projectsRoot.snippetOpts
                            textRole: "name"
                            enabled: pvMode.currentIndex === 1
                            onActivated: function (idx) {
                                projects.set_setting(
                                    "preview.snippetId",
                                    String(projectsRoot.snippetOpts[idx].id))
                            }
                            background: Rectangle {
                                radius: 4; color: theme.tokens.surface2
                                border.color: theme.tokens.border
                            }
                            contentItem: Text {
                                text: pvSnippet.displayText
                                font.family: theme.monoFont; font.pixelSize: 10
                                color: theme.tokens.text
                                verticalAlignment: Text.AlignVCenter; leftPadding: 6
                            }
                        }
                    }
                    Item { Layout.preferredHeight: 8 }
                }
            }

            // ---- live preview
            Rectangle {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 200
                color: theme.tokens.surface
                Item {
                    anchors.fill: parent
                    Loader {
                        id: pvLoader
                        anchors.fill: parent
                        anchors.margins: 1
                        active: projectsRoot.previewActive
                        sourceComponent: PreviewPane {
                            profile: previewProfile
                            document: projectsRoot.previewDoc
                        }
                    }
                    Column {
                        anchors.centerIn: parent
                        visible: !projectsRoot.previewActive
                        spacing: 10
                        IconImage {
                            anchors.horizontalCenter: parent.horizontalCenter
                            name: "play"
                            px: 28
                            tint: theme.tokens.textMuted
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: qsTr("Press Run ▸ to render the boilerplate")
                            font.family: theme.uiFont; font.pixelSize: 12
                            color: theme.tokens.textMuted
                        }
                    }
                }
            }
        }
    }

    // shared preview state
    property string previewDoc: ""
    property bool previewActive: false

    Connections {
        target: demo
        function onMessage(msg) { toast.show(msg); refreshPickers() }
        function onFailed(err) {
            toast.show(qsTr("Demo data error: %1").arg(err))
        }
        function onChanged() {
            refreshPickers()
            // refresh the project list through the existing search slot
            projects.set_search(projSearch.text)
        }
    }

    // demo removal dialog — per-kind checkboxes (keep tags, drop the rest…)
    Popup {
        id: demoDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(380, projectsRoot.width - 40)
        padding: 16
        background: Rectangle {
            radius: 12
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }

        property var checkedKinds: []

        onOpened: checkedKinds = demo.kinds().map(function (k) { return k.id })

        contentItem: ColumnLayout {
            spacing: 10
            Text {
                text: qsTr("Delete demo data")
                font.family: theme.headingFont
                font.pixelSize: 14
                color: theme.tokens.accent
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                font.family: theme.uiFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
                text: qsTr("Only demo-created rows are touched — anything "
                           + "you added yourself stays. Projects that lose "
                           + "their assets still work; exports skip the "
                           + "missing files.")
            }
            Repeater {
                model: demo !== null ? demo.kinds() : []
                CheckBox {
                    id: kindBox
                    required property var modelData
                    text: modelData.label
                    checked: demoDialog.checkedKinds.indexOf(modelData.id) >= 0
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    onToggled: {
                        var set = demoDialog.checkedKinds.slice()
                        var i = set.indexOf(kindBox.modelData.id)
                        if (checked && i < 0)
                            set.push(kindBox.modelData.id)
                        else if (!checked && i >= 0)
                            set.splice(i, 1)
                        demoDialog.checkedKinds = set
                    }
                    contentItem: Text {
                        text: kindBox.text
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        color: theme.tokens.text
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 4
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: qsTr("Select all")
                    onClicked: {
                        demoDialog.checkedKinds =
                            demo.kinds().map(function (k) { return k.id })
                    }
                    background: Rectangle {
                        radius: 6; color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: parent.text
                        color: theme.tokens.text
                        font.family: theme.uiFont; font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    text: qsTr("Keep all")
                    onClicked: demoDialog.checkedKinds = []
                    background: Rectangle {
                        radius: 6; color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: parent.text
                        color: theme.tokens.text
                        font.family: theme.uiFont; font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Item { Layout.fillWidth: true }
                Button {
                    id: demoDeleteBtn
                    text: qsTr("Delete")
                    enabled: demoDialog.checkedKinds.length > 0
                    onClicked: {
                        demo.remove(demoDialog.checkedKinds)
                        demoDialog.close()
                    }
                    background: Rectangle {
                        radius: 6
                        color: demoDeleteBtn.enabled
                               ? theme.tokens.accent : theme.tokens.border
                    }
                    contentItem: Text {
                        text: parent.text
                        color: theme.tokens.bg
                        font.family: theme.uiFont; font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    text: qsTr("Cancel")
                    onClicked: demoDialog.close()
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
                    }
                }
            }
        }
    }

    FileDialog {
        id: exportDialog
        fileMode: FileDialog.SaveFile
        nameFilters: exportFmt.currentIndex === 1
                     ? [qsTr("Archives (*.tar.gz)")]
                     : [qsTr("Archives (*.zip)")]
        onAccepted: projects !== null && projects.export(
            Icons.toLocalPath(selectedFile),
            exportFmt.currentIndex === 1 ? "targz" : "zip")
    }

    Popup {
        id: helpPopup
        modal: true
        anchors.centerIn: parent
        width: Math.min(460, projectsRoot.width - 40)
        height: Math.min(400, projectsRoot.height - 40)
        background: Rectangle {
            radius: 12
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        contentItem: Flickable {
            clip: true
            contentHeight: phCol.implicitHeight
            ScrollBar.vertical: ScrollBar { }
            ColumnLayout {
                id: phCol
                width: helpPopup.width - 32
                spacing: 6
                Text {
                    text: qsTr("Projects guide")
                    font.family: theme.headingFont
                    font.pixelSize: 14
                    color: theme.tokens.accent
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                    text: qsTr(
                        "A project is a named set of design tokens plus the "
                        + "library assets (icons, fonts, snippets, palettes) it "
                        + "ships with.\n\nColors: set the six roles explicitly "
                        + "or leave them on 'auto' — auto roles fall back to "
                        + "the first attached palette positionally, then to "
                        + "sane defaults. 'apply' fills the roles from a saved "
                        + "palette.\n\nType: pick body/heading families from "
                        + "the scanned fonts and set the base size and modular "
                        + "scale — the export emits @font-face rules and font "
                        + "stacks.\n\nExport: a zip (or tar.gz) with "
                        + "css/tokens.css, css/fonts.css, css/icons.css, "
                        + "js/icons.js, a boilerplate index.html driven "
                        + "entirely by the tokens, the attached files under "
                        + "assets/, snippet pages, palettes.json and a "
                        + "manifest.json. Run ▸ renders the same boilerplate "
                        + "live in the sandboxed preview.")
                }
            }
        }
    }

    Connections {
        target: projects
        function onMessage(msg) { toast.show(msg) }
        function onExportDone(path) {
            toast.show(qsTr("Exported: %1").arg(path))
        }
        function onExportFailed(err) {
            toast.show(qsTr("Export failed: %1").arg(err))
        }
    }
}

