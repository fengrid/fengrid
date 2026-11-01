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

    // a project row asked for its inspector (Main hosts the overlay)
    signal entityProperties(string kind, int id)

    // local editable mirror of the current project's settings; written
    // through on every edit via projects.set_setting()
    property var st: ({})
    property var fontsModel: []
    property var iconOpts: []
    property var fontOpts: []
    property var snippetOpts: []
    property var paletteOpts: []

    function syncSettings() {
        if (projects !== null && projects.settings !== undefined && projects.settings !== null)
            st = projects.settings;
        else
            st = {};
    }

    function refreshPickers() {
        if (projects === null)
            return;
        iconOpts = projects.icon_options();
        fontOpts = projects.font_options();
        snippetOpts = projects.snippet_options();
        paletteOpts = projects.palette_options();
        fontsModel = projects.family_options();
    }

    // git spec: batch operations auto-branch before changing anything,
    // then prompt to commit or discard. No repo → run unprotected.
    property string batchLabel: ""
    function runBatch(label, op) {
        var guarded = projects !== null && projects.batch_begin(label);
        op();
        if (guarded) {
            batchLabel = label;
            batchReview.open();
        }
    }

    Connections {
        target: projects
        function onMessage(msg) {
            projectsRoot.logText = (projectsRoot.logText + msg + "\n").slice(-20000);
        }
        function onExportDone(path) {
            projectsRoot.logText = (projectsRoot.logText + "exported: " + path + "\n").slice(-20000);
        }
        function onExportFailed(err) {
            projectsRoot.logText = (projectsRoot.logText + "export FAILED: " + err + "\n").slice(-20000);
        }
        function onAskDone(reply) {
            projectsRoot.askText = (projectsRoot.askText + reply + "\n\n").slice(-40000);
        }
        function onAskFailed(err) {
            projectsRoot.askText = (projectsRoot.askText + "✗ " + err + "\n\n").slice(-40000);
        }
        function onCurrentChanged() {
            projectsRoot.syncSettings();
        }
        function onProjectsChanged() {
            projectsRoot.refreshPickers();
        }
    }
    Component.onCompleted: {
        syncSettings();
        refreshPickers();
        if (projects !== null && projects.currentId >= 0 && sc !== null)
            sc.attach(projects.current().name || "", "project");
    }

    Toast {
        id: toast
    }

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
            font.family: theme.monoFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
            Layout.preferredWidth: 70
        }
        ComboBox {
            id: pick
            Layout.fillWidth: true
            model: addRow.opts
            textRole: "name"
            background: Rectangle {
                radius: 4
                color: theme.tokens.surface2
                border.color: theme.tokens.border
            }
            contentItem: Text {
                text: pick.displayText
                font.family: theme.monoFont
                font.pixelSize: 10
                color: theme.tokens.text
                // elide inside the combo — long labels (file names like
                // "Bebas Neue-Regular.ttf") clipped mid-glyph at the edge
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
                leftPadding: 6
            }
        }
        FgButton {
            text: qsTr("+")
            onClicked: {
                if (pick.currentIndex >= 0) {
                    var o = addRow.opts[pick.currentIndex];
                    addRow.picked(o.id, o.name);
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
            anchors.margins: 12
            spacing: 6

            Button {
                Layout.fillWidth: true
                text: qsTr("+ New Project")
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
                border.color: projSearch.activeFocus ? theme.tokens.accent : theme.tokens.border
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
                    text: qsTr("Search Projects…")
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
                ScrollBar.vertical: ScrollBar {}

                delegate: Rectangle {
                    id: projItem
                    required property var modelData
                    readonly property var row: modelData
                    width: projList.width
                    height: projRow.implicitHeight + 12
                    radius: 7
                    color: projects !== null && projects.currentId === projItem.modelData.id ? theme.tokens.surface2 : "transparent"
                    border.color: projects !== null && projects.currentId === projItem.modelData.id ? theme.tokens.accentProject : "transparent"

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
                            text: projItem.modelData.asset_count + " assets · " + String(projItem.modelData.updated).slice(0, 10)
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
                            // left-click opens (inspector follows);
                            // right-click opens the menu for the CURRENT
                            // project without switching
                            if (mouse.button === Qt.LeftButton)
                                projects !== null && projects.open(projItem.modelData.id);
                            else
                                projMenu.popup();
                        }
                    }
                }

                // project context menu
                Menu {
                    id: projMenu
                    width: 190
                    padding: 4
                    background: Rectangle {
                        radius: 8
                        color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    FgMenuItem {
                        text: qsTr("Open")
                        height: 28
                        onTriggered: projects !== null && projects.open(projList.currentItem ? projList.currentItem.row.id : -1)
                    }
                    FgMenuItem {
                        text: qsTr("Properties")
                        height: 28
                        onTriggered: projectsRoot.entityProperties("project", projList.currentItem ? projList.currentItem.row.id : -1)
                    }
                    FgMenuItem {
                        text: qsTr("Export…")
                        height: 28
                        onTriggered: {
                            if (projList.currentItem)
                                projects.open(projList.currentItem.row.id);
                            exportDialog.open();
                        }
                    }
                    // a project can collect an ENTIRE collection — its refs
                    // follow live (project_asset kind 'collection')
                    FgMenuItem {
                        id: attachCollItem
                        text: qsTr("Attach collection…")
                        height: 28
                        enabled: library !== null && library.collections.length > 0
                        Menu {
                            id: attachCollSub
                            cascade: true
                            width: 200
                            padding: 4
                            background: Rectangle {
                                radius: 8
                                color: theme.tokens.surface
                                border.color: theme.tokens.border
                            }
                            Repeater {
                                model: library !== null ? library.collections : []
                                FgMenuItem {
                                    id: attachCollTarget
                                    required property var modelData
                                    height: 28
                                    onTriggered: {
                                        if (projList.currentItem && projects !== null)
                                            projectsRoot.runBatch("attach-" + attachCollTarget.modelData.name, function () {
                                                projects.add_asset("collection", attachCollTarget.modelData.id, attachCollTarget.modelData.name);
                                            });
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
                                        color: attachCollTarget.hovered ? theme.tokens.surface2 : "transparent"
                                        radius: 5
                                    }
                                }
                            }
                        }
                    }
                    FgMenuSeparator {
                        topPadding: 3
                        bottomPadding: 3
                        contentItem: Rectangle {
                            implicitHeight: 1
                            color: theme.tokens.border
                        }
                    }
                    FgMenuItem {
                        text: qsTr("Delete project")
                        height: 28
                        onTriggered: {
                            if (projList.currentItem && projects !== null)
                                projects.remove(projList.currentItem.row.id);
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
    Rectangle {
        width: 1
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: sidebar.right
        color: theme.tokens.border
    }

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
                    text: projects !== null && projects.current.name !== undefined ? projects.current.name : ""
                    onEditingFinished: projects !== null && projects.update_meta("name", text)
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: theme.tokens.text
                    placeholderText: qsTr("Project Name")
                    background: Rectangle {
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: nameField.activeFocus ? theme.tokens.accent : theme.tokens.border
                    }
                }
                Item {
                    Layout.fillWidth: true
                }
                ComboBox {
                    id: exportFmt
                    model: [qsTr(".zip"), qsTr(".tar.gz")]
                    Layout.preferredWidth: 92
                    background: Rectangle {
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: exportFmt.displayText
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.text
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 6
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
                        color: exportBtn.enabled ? theme.tokens.accent : theme.tokens.border
                    }
                    contentItem: Text {
                        text: exportBtn.text
                        color: theme.tokens.bg
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 10
                        rightPadding: 10
                    }
                }
                Button {
                    id: runBtn
                    text: qsTr("Run ▸")
                    enabled: projects !== null && projects.currentId >= 0 && previewProfile !== null
                    onClicked: {
                        previewDoc = projects !== null ? projects.preview_html() : "";
                        previewActive = true;
                    }
                    background: Rectangle {
                        radius: 6
                        color: runBtn.enabled ? theme.tokens.accent : theme.tokens.border
                    }
                    contentItem: Text {
                        text: runBtn.text
                        color: runBtn.enabled ? theme.tokens.bg : theme.tokens.textMuted
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 10
                        rightPadding: 10
                    }
                }
                IconButton {
                    icon_name: "help"
                    ToolTip.text: qsTr("Help & guide")
                    onClicked: helpPopup.open()
                }
                Button {
                    id: demoBtn
                    text: demo !== null && demo.installed ? qsTr("Remove demo…") : qsTr("Load demo suite")
                    Layout.preferredHeight: 26
                    onClicked: {
                        if (demo !== null && demo.installed)
                            demoDialog.open();
                        else
                            projectsRoot.runBatch("demo-suite", function () {
                                demo.install();
                            });
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: demo !== null && demo.installed ? qsTr("Delete demo data — choose which kinds to keep") : qsTr("Load the showcase suite: 14 projects with example icons, fonts, snippets and palettes")
                    background: Rectangle {
                        radius: 6
                        color: demoBtn.hovered ? theme.tokens.surface2 : "transparent"
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: demoBtn.text
                        color: theme.tokens.text
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8
                        rightPadding: 8
                    }
                }
            }
        }

        // two-row studio layout, mirroring the Code pane: upper row =
        // studio screens + property inspector; lower row = the live
        // preview spanning the full width
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            // ---- upper row: screen rail + screen area with the property
            // inspector pinned right (the Code pane's editor arrangement)
            RowLayout {
                id: studioRow
                anchors {
                    top: parent.top
                    left: parent.left
                    right: parent.right
                }
                height: parent.height * 0.55 - 0.5
                spacing: 0
                // ---- studio screen rail + screen area
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 360
                    // minimums must SUM below the available width at the
                    // default window (1280 - rail - sidebar ≈ 819px) or the
                    // row overflows past the window edge
                    Layout.minimumWidth: 300
                    Layout.maximumWidth: 420
                    spacing: 0

                    // screen rail: Design · Theme · Assets · Templates ·
                    // Docker · Docs (Revisions lives in the bottom dock)
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Repeater {
                            model: [
                                {
                                    k: "design",
                                    l: qsTr("Design")
                                },
                                {
                                    k: "theme",
                                    l: qsTr("Theme")
                                },
                                {
                                    k: "assets",
                                    l: qsTr("Assets")
                                },
                                {
                                    k: "templates",
                                    l: qsTr("Templates")
                                },
                                {
                                    k: "docker",
                                    l: qsTr("Docker")
                                },
                                {
                                    k: "docs",
                                    l: qsTr("Docs")
                                }
                            ]
                            Button {
                                id: screenBtn
                                required property var modelData
                                required property int index
                                property int idx: index
                                Layout.preferredHeight: 22
                                text: modelData.l
                                font.family: theme.uiFont
                                font.pixelSize: 10
                                onClicked: studioScreen = idx
                                background: Rectangle {
                                    radius: 5
                                    color: studioScreen === screenBtn.idx ? theme.tokens.accentProject : theme.tokens.surface2
                                    border.color: theme.tokens.border
                                }
                                contentItem: Text {
                                    text: screenBtn.text
                                    font.family: theme.uiFont
                                    font.pixelSize: 10
                                    color: studioScreen === screenBtn.idx ? theme.tokens.bg : theme.tokens.text
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }
                    }

                    StackLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: studioScreen

                        // 0 · DESIGN — block canvas + inspector
                        StudioDesign {
                            st: studio
                            prj: projects
                        }

                        // 1 · THEME — the token configurator (was the only
                        // pane before the rework)
                        Flickable {
                            clip: true
                            contentHeight: paramsCol.implicitHeight + 20
                            ScrollBar.vertical: ScrollBar {}

                            ColumnLayout {
                                id: paramsCol
                                width: parent.width - 8
                                x: 4
                                spacing: 10

                                // COLORS -------------------------------------------------
                                SectionLabel {
                                    text: qsTr("Colors")
                                }
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
                                                width: 14
                                                height: 14
                                                radius: 3
                                                color: {
                                                    var c = projectsRoot.st.colors ? projectsRoot.st.colors[roleRow.modelData] : "";
                                                    return c && c !== "" ? c : "transparent";
                                                }
                                                border.color: theme.tokens.border
                                            }
                                            TextField {
                                                id: roleField
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 40
                                                Layout.preferredWidth: 60
                                                text: {
                                                    var c = projectsRoot.st.colors ? projectsRoot.st.colors[roleRow.modelData] : "";
                                                    return c || "";
                                                }
                                                placeholderText: qsTr("auto")
                                                font.family: theme.monoFont
                                                font.pixelSize: 10
                                                color: theme.tokens.text
                                                onEditingFinished: projects !== null && projects.set_setting("colors." + roleRow.modelData, text)
                                                background: Rectangle {
                                                    radius: 4
                                                    color: theme.tokens.surface2
                                                    border.color: roleField.activeFocus ? theme.tokens.accent : theme.tokens.border
                                                }
                                            }
                                        }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: qsTr("Radius")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.textMuted
                                    }
                                    FgSlider {
                                        id: radiusSlider
                                        Layout.fillWidth: true
                                        from: 0
                                        to: 32
                                        stepSize: 1
                                        value: projectsRoot.st.colors ? (projectsRoot.st.colors.radius || 10) : 10
                                        onMoved: projects !== null && projects.set_setting("colors.radius", value)
                                    }
                                    Text {
                                        text: (projectsRoot.st.colors ? (projectsRoot.st.colors.radius || 10) : 10) + "px"
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.text
                                        Layout.preferredWidth: 36
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: qsTr("Prefix")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.textMuted
                                    }
                                    TextField {
                                        id: prefixField
                                        Layout.preferredWidth: 70
                                        text: projectsRoot.st.prefix || "fg"
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.text
                                        onEditingFinished: projects !== null && projects.set_setting("prefix", text)
                                        background: Rectangle {
                                            radius: 4
                                            color: theme.tokens.surface2
                                            border.color: prefixField.activeFocus ? theme.tokens.accent : theme.tokens.border
                                        }
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                    }
                                    ComboBox {
                                        id: palApply
                                        Layout.preferredWidth: 108
                                        model: projectsRoot.paletteOpts
                                        textRole: "name"
                                        background: Rectangle {
                                            radius: 4
                                            color: theme.tokens.surface2
                                            border.color: theme.tokens.border
                                        }
                                        contentItem: Text {
                                            text: palApply.displayText
                                            font.family: theme.monoFont
                                            font.pixelSize: 10
                                            color: theme.tokens.text
                                            verticalAlignment: Text.AlignVCenter
                                            leftPadding: 6
                                        }
                                    }
                                    FgButton {
                                        text: qsTr("Apply")
                                        onClicked: {
                                            if (palApply.currentIndex < 0)
                                                return;
                                            var pal = projectsRoot.paletteOpts[palApply.currentIndex];
                                            projectsRoot.runBatch("palette-" + pal.name, function () {
                                                projects.apply_palette(pal.id);
                                            });
                                        }
                                    }
                                }

                                // TYPE ---------------------------------------------------
                                SectionLabel {
                                    text: qsTr("Type")
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: qsTr("Body")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
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
                                            projects.set_setting("type.body", projectsRoot.fontsModel[idx]);
                                        }
                                        background: Rectangle {
                                            radius: 4
                                            color: theme.tokens.surface2
                                            border.color: theme.tokens.border
                                        }
                                        contentItem: TextInput {
                                            text: bodyFam.editText
                                            font.family: theme.monoFont
                                            font.pixelSize: 10
                                            color: theme.tokens.text
                                            verticalAlignment: TextInput.AlignVCenter
                                            leftPadding: 6
                                            onEditingFinished: projects !== null && projects.set_setting("type.body", text)
                                        }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: qsTr("Heading")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
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
                                            projects.set_setting("type.heading", projectsRoot.fontsModel[idx]);
                                        }
                                        background: Rectangle {
                                            radius: 4
                                            color: theme.tokens.surface2
                                            border.color: theme.tokens.border
                                        }
                                        contentItem: TextInput {
                                            text: headFam.editText
                                            font.family: theme.monoFont
                                            font.pixelSize: 10
                                            color: theme.tokens.text
                                            verticalAlignment: TextInput.AlignVCenter
                                            leftPadding: 6
                                            onEditingFinished: projects !== null && projects.set_setting("type.heading", text)
                                        }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: qsTr("Base / Scale")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.textMuted
                                    }
                                    TextField {
                                        id: baseField
                                        Layout.preferredWidth: 56
                                        text: projectsRoot.st.type ? String(projectsRoot.st.type.baseSize || 16) : "16"
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.text
                                        onEditingFinished: projects !== null && projects.set_setting("type.baseSize", text)
                                        background: Rectangle {
                                            radius: 4
                                            color: theme.tokens.surface2
                                            border.color: baseField.activeFocus ? theme.tokens.accent : theme.tokens.border
                                        }
                                    }
                                    TextField {
                                        id: scaleField
                                        Layout.preferredWidth: 56
                                        text: projectsRoot.st.type ? String(projectsRoot.st.type.scale || 1.25) : "1.25"
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.text
                                        onEditingFinished: projects !== null && projects.set_setting("type.scale", text)
                                        background: Rectangle {
                                            radius: 4
                                            color: theme.tokens.surface2
                                            border.color: scaleField.activeFocus ? theme.tokens.accent : theme.tokens.border
                                        }
                                    }
                                }

                                // ICONS --------------------------------------------------
                                SectionLabel {
                                    text: qsTr("Icons")
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: qsTr("Size")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.textMuted
                                    }
                                    FgSlider {
                                        id: iconSizeSlider
                                        Layout.fillWidth: true
                                        from: 12
                                        to: 128
                                        stepSize: 2
                                        value: projectsRoot.st.iconSize || 32
                                        onMoved: projects !== null && projects.set_setting("iconSize", value)
                                    }
                                    Text {
                                        text: (projectsRoot.st.iconSize || 32) + "px"
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.text
                                        Layout.preferredWidth: 36
                                    }
                                }
                                AddAssetRow {
                                    label: qsTr("Add Icon")
                                    opts: projectsRoot.iconOpts
                                    onPicked: function (id, label) {
                                        projects.add_asset("icon", id, label);
                                    }
                                }

                                // FONTS / SNIPPETS / PALETTES ----------------------------
                                SectionLabel {
                                    text: qsTr("Assets")
                                }
                                AddAssetRow {
                                    label: qsTr("Add Font")
                                    opts: projectsRoot.fontOpts
                                    onPicked: function (id, label) {
                                        projects.add_asset("font", id, label);
                                    }
                                }
                                AddAssetRow {
                                    label: qsTr("Add Snippet")
                                    opts: projectsRoot.snippetOpts
                                    onPicked: function (id, label) {
                                        projects.add_asset("snippet", id, label);
                                    }
                                }
                                AddAssetRow {
                                    label: qsTr("Add Palette")
                                    opts: projectsRoot.paletteOpts
                                    onPicked: function (id, label) {
                                        projects.add_asset("palette", id, label);
                                    }
                                }

                                // attached assets list
                                ListView {
                                    id: assetList
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.min((projects !== null && projects.assets !== null ? projects.assets.length : 0) * 26 + 6, 160)
                                    model: projects !== null && projects.assets !== null ? projects.assets : []
                                    clip: true
                                    ScrollBar.vertical: ScrollBar {}
                                    delegate: RowLayout {
                                        id: assetRow
                                        required property var modelData
                                        width: assetList.width
                                        height: 24
                                        Text {
                                            text: assetRow.modelData.asset_kind + " · " + assetRow.modelData.label
                                            font.family: theme.monoFont
                                            font.pixelSize: 10
                                            color: theme.tokens.text
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        IconButton {
                                            icon_name: "trash"
                                            onClicked: projects.remove_asset(assetRow.modelData.id)
                                        }
                                    }
                                }

                                // PREVIEW ------------------------------------------------
                                SectionLabel {
                                    text: qsTr("Preview")
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: qsTr("Source")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.textMuted
                                    }
                                    ComboBox {
                                        id: pvMode
                                        Layout.preferredWidth: 110
                                        model: [qsTr("Site"), qsTr("Snippet")]
                                        currentIndex: projectsRoot.st.preview && projectsRoot.st.preview.mode === "snippet" ? 1 : 0
                                        onActivated: function (idx) {
                                            projects.set_setting("preview.mode", idx === 1 ? "snippet" : "site");
                                        }
                                        background: Rectangle {
                                            radius: 4
                                            color: theme.tokens.surface2
                                            border.color: theme.tokens.border
                                        }
                                        contentItem: Text {
                                            text: pvMode.displayText
                                            font.family: theme.monoFont
                                            font.pixelSize: 10
                                            color: theme.tokens.text
                                            verticalAlignment: Text.AlignVCenter
                                            leftPadding: 6
                                        }
                                    }
                                    ComboBox {
                                        id: pvSnippet
                                        Layout.fillWidth: true
                                        model: projectsRoot.snippetOpts
                                        textRole: "name"
                                        enabled: pvMode.currentIndex === 1
                                        onActivated: function (idx) {
                                            projects.set_setting("preview.snippetId", String(projectsRoot.snippetOpts[idx].id));
                                        }
                                        background: Rectangle {
                                            radius: 4
                                            color: theme.tokens.surface2
                                            border.color: theme.tokens.border
                                        }
                                        contentItem: Text {
                                            text: pvSnippet.displayText
                                            font.family: theme.monoFont
                                            font.pixelSize: 10
                                            color: theme.tokens.text
                                            verticalAlignment: Text.AlignVCenter
                                            leftPadding: 6
                                        }
                                    }
                                }
                                Item {
                                    Layout.preferredHeight: 8
                                }
                            }   // paramsCol
                        }       // Flickable — Theme screen

                        // 2 · ASSETS — attached artifacts + library pickers
                        StudioAssets {
                            prj: projects
                        }

                        // 3 · TEMPLATES — vars + tenant instances
                        StudioTemplates {
                            st: studio
                        }

                        // 4 · DOCKER — package/ship/inspect containers
                        StudioDocker {
                            st: studio
                        }

                        // 5 · DOCS — characterization + link health
                        StudioDocs {
                            st: studio
                        }
                    }           // StackLayout
                }               // screen-area column

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.fillHeight: true
                    color: theme.tokens.border
                }
                // ---- property inspector (right panel): project facts + the
                // selected preview element with quick parameter edits
                Rectangle {
                    Layout.fillHeight: true
                    Layout.preferredWidth: 250
                    Layout.minimumWidth: 180
                    color: theme.tokens.surface
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8
                        clip: true

                        Text {
                            text: qsTr("INSPECTOR")
                            font.family: theme.headingFont
                            font.pixelSize: 11
                            font.letterSpacing: 1.4
                            font.capitalization: Font.AllUppercase
                            color: theme.tokens.textMuted
                        }

                        Text {
                            text: qsTr("Selected Element")
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            color: theme.tokens.text
                        }
                        Text {
                            Layout.fillWidth: true
                            text: projectsRoot.selInfo && projectsRoot.selInfo.tag ? projectsRoot.selInfo.tag : qsTr("Click an Element in the Preview…")
                            font.family: theme.monoFont
                            font.pixelSize: 11
                            color: projectsRoot.selInfo && projectsRoot.selInfo.tag ? theme.tokens.accentProject : theme.tokens.textMuted
                            // #24 follow-up: WrapAnywhere sliced "preview"
                            // mid-word — prefer word boundaries
                            wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: projectsRoot.selInfo && projectsRoot.selInfo.text !== undefined
                            text: projectsRoot.selInfo.text || ""
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                            wrapMode: Text.WrapAnywhere
                            maximumLineCount: 3
                            elide: Text.ElideRight
                        }
                        TextField {
                            id: selTextEdit
                            Layout.fillWidth: true
                            Layout.preferredHeight: 26
                            placeholderText: qsTr("Edit Element Text…")
                            enabled: projectsRoot.selInfo && projectsRoot.selInfo.tag !== undefined
                            font.family: theme.monoFont
                            font.pixelSize: 11
                            color: theme.tokens.text
                            background: Rectangle {
                                radius: 6
                                color: theme.tokens.surface2
                                border.color: theme.tokens.border
                            }
                            onAccepted: projectsRoot.applySelText(text)
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            TextField {
                                id: styleKey
                                Layout.preferredWidth: 70
                                Layout.preferredHeight: 24
                                placeholderText: "CSS"
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.text
                                background: Rectangle {
                                    radius: 4
                                    color: theme.tokens.surface2
                                    border.color: theme.tokens.border
                                }
                            }
                            TextField {
                                id: styleVal
                                Layout.fillWidth: true
                                Layout.preferredHeight: 24
                                placeholderText: qsTr("Value")
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.text
                                background: Rectangle {
                                    radius: 4
                                    color: theme.tokens.surface2
                                    border.color: theme.tokens.border
                                }
                                onAccepted: {
                                    projectsRoot.applySelStyle(styleKey.text, styleVal.text);
                                    styleVal.text = "";
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: qsTr("Live DOM tweaks apply instantly but reset when the preview regenerates — save a revision (or bake the value into your snippet CSS) to keep them.")
                            font.family: theme.uiFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                            wrapMode: Text.Wrap
                        }

                        Text {
                            text: qsTr("Project")
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            color: theme.tokens.text
                        }
                        Text {
                            Layout.fillWidth: true
                            text: projects !== null && projects.currentId >= 0 ? ("name: " + (projects.current.name || "") + "\ndescription: " + (projects.current.description || "—") + "\nprefix: " + ((projects.settings || {}).prefix || "—")) : qsTr("No Project Open")
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.text
                        }
                        Item {
                            Layout.fillHeight: true
                        }
                    }
                }
            }

            Rectangle {
                anchors {
                    top: studioRow.bottom
                    left: parent.left
                    right: parent.right
                }
                height: 1
                color: theme.tokens.border
            }

            // ---- lower row: live preview + bottom dock + status bar
            // across the full band — the inspector lives in the upper
            // row, so nothing squeezes the preview now
            Rectangle {
                anchors {
                    top: studioRow.bottom
                    left: parent.left
                    right: parent.right
                    bottom: parent.bottom
                }
                clip: true
                color: theme.tokens.surface
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // ---- WYSIWYG preview (click selects, hover reports,
                    // right-click outlines — inspector polls the DOM)
                    Item {
                        id: pvArea
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
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
                                width: Math.min(pvArea.width - 40, 420)
                                text: qsTr("Live Preview Renders Automatically — Tweak Any Parameter Above")
                                font.family: theme.uiFont
                                font.pixelSize: 12
                                color: theme.tokens.textMuted
                                wrapMode: Text.Wrap
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }
                    }

                    // ---- bottom dock: console / logs / revisions / ask
                    Rectangle {
                        id: bottomDock
                        Layout.fillWidth: true
                        Layout.preferredHeight: dockHead.expanded ? (projectsRoot.bottomTab === 3 ? 220 : 190) : 28
                        color: theme.tokens.surface2
                        Behavior on Layout.preferredHeight {
                            NumberAnimation {
                                duration: 90
                            }
                        }
                        RowLayout {
                            id: dockHead
                            property bool expanded: true
                            anchors {
                                top: parent.top
                                left: parent.left
                                right: parent.right
                            }
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            height: 28
                            spacing: 2
                            Repeater {
                                model: [qsTr("Console"), qsTr("Logs"), qsTr("Revisions"), qsTr("Ask"), qsTr("Source")]
                                delegate: Rectangle {
                                    id: dockTabBtn
                                    required property string modelData
                                    required property int index
                                    width: dockTabText.implicitWidth + 18
                                    height: 22
                                    radius: 4
                                    color: projectsRoot.bottomTab === index ? theme.tokens.surface : "transparent"
                                    Text {
                                        id: dockTabText
                                        anchors.centerIn: parent
                                        text: dockTabBtn.modelData
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: projectsRoot.bottomTab === index ? theme.tokens.text : theme.tokens.textMuted
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: projectsRoot.bottomTab = dockTabBtn.index
                                    }
                                }
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            IconButton {
                                icon_name: dockHead.expanded ? "chevrons-down" : "chevrons-up"
                                ToolTip.text: dockHead.visible ? qsTr("Collapse dock") : qsTr("Expand dock")
                                onClicked: dockHead.expanded = !dockHead.expanded
                            }
                        }
                        // dock body
                        Item {
                            anchors {
                                top: dockHead.bottom
                                left: parent.left
                                right: parent.right
                                bottom: parent.bottom
                            }
                            anchors.margins: 12
                            visible: dockHead.expanded
                            clip: true

                            TextArea {
                                visible: projectsRoot.bottomTab === 0
                                anchors.fill: parent
                                readOnly: true
                                wrapMode: TextArea.Wrap
                                text: projectsRoot.consoleText
                                font.family: theme.monoFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                padding: 8
                                background: Rectangle {
                                    color: theme.tokens.bg
                                    radius: 6
                                    border.color: theme.tokens.border
                                }
                                placeholderText: qsTr("Console Output from the Live Preview (console.log / Errors)…")
                                placeholderTextColor: theme.tokens.inkFaint
                            }
                            TextArea {
                                visible: projectsRoot.bottomTab === 1
                                anchors.fill: parent
                                readOnly: true
                                wrapMode: TextArea.Wrap
                                text: projectsRoot.logText
                                font.family: theme.monoFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                background: Rectangle {
                                    color: theme.tokens.bg
                                    radius: 6
                                    border.color: theme.tokens.border
                                }
                            }
                            ColumnLayout {
                                visible: projectsRoot.bottomTab === 2
                                anchors.fill: parent
                                spacing: 6
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    TextField {
                                        id: revLabel
                                        Layout.preferredWidth: 180
                                        Layout.preferredHeight: 26
                                        placeholderText: qsTr("Revision Label…")
                                        font.family: theme.monoFont
                                        font.pixelSize: 11
                                        color: theme.tokens.text
                                        background: Rectangle {
                                            radius: 6
                                            color: theme.tokens.bg
                                            border.color: theme.tokens.border
                                        }
                                    }
                                    Button {
                                        text: qsTr("Save revision")
                                        Layout.preferredHeight: 26
                                        enabled: projects !== null && projects.currentId >= 0
                                        onClicked: {
                                            projects.snapshot(revLabel.text);
                                            revLabel.text = "";
                                        }
                                        background: Rectangle {
                                            radius: 6
                                            color: theme.tokens.accentProject
                                        }
                                        contentItem: Text {
                                            text: parent.text
                                            color: theme.tokens.bg
                                            font.family: theme.uiFont
                                            font.pixelSize: 11
                                            horizontalAlignment: Text.AlignHCenter
                                        }
                                    }
                                }
                                ListView {
                                    id: revList
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    model: projects !== null ? projects.revisions : []
                                    delegate: Rectangle {
                                        id: revRow
                                        required property var modelData
                                        width: revList.width
                                        height: 30
                                        radius: 6
                                        color: theme.tokens.surface2
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 6
                                            spacing: 8
                                            Text {
                                                Layout.preferredWidth: 150
                                                text: revRow.modelData.created
                                                font.family: theme.monoFont
                                                font.pixelSize: 10
                                                color: theme.tokens.textMuted
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: revRow.modelData.label
                                                font.family: theme.uiFont
                                                font.pixelSize: 11
                                                color: theme.tokens.text
                                                elide: Text.ElideRight
                                            }
                                            Button {
                                                text: qsTr("Restore")
                                                Layout.preferredHeight: 22
                                                onClicked: projects.restore_revision(revRow.modelData.id)
                                                background: Rectangle {
                                                    radius: 4
                                                    color: theme.tokens.surface
                                                    border.color: theme.tokens.border
                                                }
                                                contentItem: Text {
                                                    text: parent.text
                                                    color: theme.tokens.text
                                                    font.family: theme.uiFont
                                                    font.pixelSize: 10
                                                    horizontalAlignment: Text.AlignHCenter
                                                }
                                            }
                                            IconButton {
                                                icon_name: "trash"
                                                ToolTip.text: qsTr("Delete revision")
                                                onClicked: projects.delete_revision(revRow.modelData.id)
                                            }
                                        }
                                    }
                                    Text {
                                        anchors.centerIn: parent
                                        visible: revList.count === 0
                                        text: qsTr("No revisions yet — Save revision snapshots the current design tokens")
                                        font.family: theme.uiFont
                                        font.pixelSize: 11
                                        color: theme.tokens.textMuted
                                    }
                                }
                            }
                            ColumnLayout {
                                visible: projectsRoot.bottomTab === 3
                                anchors.fill: parent
                                spacing: 6
                                TextArea {
                                    id: askOut
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    readOnly: true
                                    wrapMode: TextArea.Wrap
                                    text: projectsRoot.askText
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: theme.tokens.text
                                    background: Rectangle {
                                        color: theme.tokens.bg
                                        radius: 6
                                        border.color: theme.tokens.border
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    TextField {
                                        id: askIn
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 26
                                        placeholderText: qsTr("Ask a Local Helper (fengrid-llm / llm CLI) About This Project…")
                                        font.family: theme.monoFont
                                        font.pixelSize: 11
                                        color: theme.tokens.text
                                        background: Rectangle {
                                            radius: 6
                                            color: theme.tokens.bg
                                            border.color: theme.tokens.border
                                        }
                                        onAccepted: projectsRoot.sendAsk()
                                    }
                                    Button {
                                        text: qsTr("Ask")
                                        Layout.preferredHeight: 26
                                        enabled: projects !== null && projects.askHelper !== "" && askIn.text.trim() !== ""
                                        ToolTip.visible: hovered
                                        ToolTip.text: projects !== null && projects.askHelper === "" ? qsTr("Install fengrid-llm or the `llm` CLI (or set llm_command)") : qsTr("Runs the local helper with the project context")
                                        onClicked: projectsRoot.sendAsk()
                                        background: Rectangle {
                                            radius: 6
                                            color: enabled ? theme.tokens.accentProject : theme.tokens.border
                                        }
                                        contentItem: Text {
                                            text: parent.text
                                            color: theme.tokens.bg
                                            font.family: theme.uiFont
                                            font.pixelSize: 11
                                            horizontalAlignment: Text.AlignHCenter
                                        }
                                    }
                                }
                            }
                            // ── Source tab: git panel (VS Code-style) ──
                            Item {
                                visible: projectsRoot.bottomTab === 4
                                anchors.fill: parent
                                SourceControlPanel {
                                    anchors.fill: parent
                                }
                            }
                        }
                    }

                    // ---- status bar: project facts + hover spec
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 26
                        color: theme.tokens.surface
                        Rectangle {
                            anchors.top: parent.top
                            width: parent.width
                            height: 1
                            color: theme.tokens.border
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 10
                            Text {
                                text: projects !== null && projects.currentId >= 0 ? (projects.current.name || "") + "  ·  " + projects.assets.length + " attached" : qsTr("No Project Open")
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.textMuted
                                elide: Text.ElideRight
                                Layout.maximumWidth: 260
                            }
                            Text {
                                Layout.fillWidth: true
                                text: projectsRoot.hoverSpec
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.hlInk
                                elide: Text.ElideMiddle
                            }
                            Text {
                                text: projectsRoot.live ? qsTr("● Live") : qsTr("○ Manual")
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: projectsRoot.live ? theme.tokens.accentProject : theme.tokens.textMuted
                            }
                        }
                    }
                }

                // ---- DOM poller: hover spec + console capture feed the
                // status bar / dock while the preview is on screen
                Timer {
                    interval: 400
                    repeat: true
                    running: projectsRoot.previewActive && pvLoader.status === Loader.Ready
                    onTriggered: {
                        if (!pvLoader.item)
                            return;
                        pvLoader.item.runJavaScript("window.__fgHover ? window.__fgHover() : ''", function (r) {
                            projectsRoot.hoverSpec = r || "";
                        });
                        pvLoader.item.runJavaScript("window.__fgConsole ? window.__fgConsole() : '[]'", function (r) {
                            var arr = [];
                            try {
                                arr = JSON.parse(r || "[]");
                            } catch (e) {}
                            if (arr.length) {
                                projectsRoot.consoleText = (projectsRoot.consoleText + arr.join("\n") + "\n").slice(-20000);
                            }
                        });
                        pvLoader.item.runJavaScript("window.__fgSel ? window.__fgSel() : ''", function (r) {
                            try {
                                projectsRoot.selInfo = JSON.parse(r || "{}");
                            } catch (e) {
                                projectsRoot.selInfo = ({});
                            }
                        });
                    }
                }
            }
        }
    }

    // shared preview state
    property string previewDoc: ""
    property bool previewActive: false
    // studio screens: 0 Design · 1 Theme · 2 Assets · 3 Templates ·
    // 4 Docker · 5 Docs (Revisions stays in the bottom dock)
    property int studioScreen: 0
    // live mode: every settings/meta change regenerates the preview
    // (debounced) — the old behaviour needed a manual Run click and the
    // user read it as "edits don't reach the preview"
    property bool live: true
    property string hoverSpec: ""       // element under the mouse (JS poll)
    property var selInfo: ({})          // selected element descriptor
    property string consoleText: ""
    property string logText: ""
    property int bottomTab: 0           // 0 console 1 logs 2 revisions 3 ask 4 source
    property string askText: ""

    function sendAsk() {
        if (projects === null || askIn.text.trim() === "")
            return;
        askText += "▸ " + askIn.text + "\n";
        projects.ask(askIn.text);
        askIn.text = "";
    }
    function applySelText(txt) {
        if (pvLoader.item)
            pvLoader.item.runJavaScript("window.__fgSetText(" + JSON.stringify(txt) + ")", function (r) {
                selTextEdit.text = "";
            });
    }
    function applySelStyle(key, val) {
        if (!pvLoader.item || (key || "").trim() === "")
            return;
        pvLoader.item.runJavaScript("window.__fgSetStyle(" + JSON.stringify(key) + "," + JSON.stringify(val) + ")");
    }

    function regeneratePreview() {
        if (projects === null || projects.currentId < 0)
            return;
        if (previewProfile === null)
            // no WebEngine: the sandboxed view can't run
            return;
        // Design screen renders the block canvas page; other screens
        // render the boilerplate site as before
        var html = (studio !== null && studioScreen === 0 && studio.currentPageId >= 0) ? studio.pageHtml() : projects.preview_html();
        // WYSIWYG hooks: hover/click/contextmenu capture + console capture,
        // consumed by the inspector poller. Appended only to the PREVIEW
        // doc — exports never carry them.
        var hooks = "<scr" + "ipt>(function(){var hov=null,sel=null;" + "document.addEventListener('mousemove',function(e){hov=e.target;},true);" + "document.addEventListener('click',function(e){e.preventDefault();" + "if(sel){sel.style.outline='';}sel=e.target;sel.style.outline='2px solid #39B8C4';},true);" + "document.addEventListener('contextmenu',function(e){e.preventDefault();" + "if(sel){sel.style.outline='';}sel=e.target;sel.style.outline='2px solid #F5C25C';},true);" + "function desc(el){if(!el||el===document.documentElement)return '';" + "var id=el.id?(' #'+el.id):'';" + "var cls=(typeof el.className==='string'&&el.className.trim())?('.'+el.className.trim().split(/\\s+/).join('.')):'';" + "return el.tagName.toLowerCase()+id+cls;}" + "window.__fgHover=function(){return hov?desc(hov):'';};" + "window.__fgSel=function(){return sel?JSON.stringify({tag:desc(sel)," + "text:(sel.textContent||'').trim().slice(0,200),style:sel.getAttribute('style')||''}):'';};" + "window.__fgSetText=function(t){if(sel){sel.textContent=t;return 1;}return 0;};" + "window.__fgSetStyle=function(k,v){if(sel){sel.style[k]=v;return 1;}return 0;};" + "var log=[];var cap=function(args,k){try{log.push(k+': '+Array.prototype.slice.call(args).map(function(a){return typeof a==='object'?JSON.stringify(a):String(a)}).join(' '));}catch(err){}}" + "var ol=console.log,ow=console.warn,oe=console.error;" + "console.log=function(){cap(arguments,'log');ol.apply(console,arguments);};" + "console.warn=function(){cap(arguments,'warn');ow.apply(console,arguments);};" + "console.error=function(){cap(arguments,'error');oe.apply(console,arguments);};" + "window.onerror=function(m,s,l){log.push('error: '+m+' ('+l+')');return false;};" + "window.__fgConsole=function(){var out=log.splice(0);return JSON.stringify(out);};})();" + "</scr" + "ipt>";
        previewDoc = html.replace("</body>", hooks + "</body>");
        previewActive = true;
        consoleText = "";
        if (pvLoader.item)
            selInfo = ({});
    }

    Timer {
        id: liveDebounce
        interval: 350
        onTriggered: projectsRoot.regeneratePreview()
    }
    // canvas edits refresh the live preview too (debounced like settings)
    Connections {
        target: studio
        function onPageChanged() {
            if (studioScreen === 0)
                liveDebounce.restart();
        }
        function onPagesChanged() {
            if (studioScreen === 0)
                liveDebounce.restart();
        }
    }

    Connections {
        target: projects
        function onMessage(msg) {
            projectsRoot.logText = (projectsRoot.logText + msg + "\n").slice(-20000);
        }
        function onExportDone(path) {
            projectsRoot.logText = (projectsRoot.logText + "exported: " + path + "\n").slice(-20000);
        }
        function onExportFailed(err) {
            projectsRoot.logText = (projectsRoot.logText + "export FAILED: " + err + "\n").slice(-20000);
        }
        function onAskDone(reply) {
            projectsRoot.askText = (projectsRoot.askText + reply + "\n\n").slice(-40000);
        }
        function onAskFailed(err) {
            projectsRoot.askText = (projectsRoot.askText + "✗ " + err + "\n\n").slice(-40000);
        }
        function onCurrentChanged() {
            if (projectsRoot.live)
                liveDebounce.restart();
            projectsRoot.selInfo = ({});
            projectsRoot.hoverSpec = "";
        }
    }
    Connections {
        target: demo
        function onMessage(msg) {
            toast.show(msg);
            refreshPickers();
        }
        function onFailed(err) {
            toast.show(qsTr("Demo data error: %1").arg(err));
        }
        function onChanged() {
            refreshPickers();
            // refresh the project list through the existing search slot
            projects.set_search(projSearch.text);
        }
    }

    // demo removal dialog — per-kind checkboxes (keep tags, drop the rest…)
    Popup {
        id: batchReview
        modal: true
        anchors.centerIn: parent
        width: Math.min(400, projectsRoot.width - 40)
        padding: 16
        background: Rectangle {
            radius: 12
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        contentItem: ColumnLayout {
            spacing: 10
            Text {
                text: qsTr("Batch complete — review")
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
                text: qsTr("The batch ran on its own branch «%1». Keep it " + "(merge into fengrid-main) or discard it " + "(changes revert). The branch is removed " + "either way.").arg(projectsRoot.batchLabel)
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 8
                FgButton {
                    text: qsTr("Discard")
                    onClicked: {
                        projects.batch_finish(projectsRoot.batchLabel, false);
                        batchReview.close();
                    }
                }
                FgButton {
                    text: qsTr("Commit & merge")
                    onClicked: {
                        projects.batch_finish(projectsRoot.batchLabel, true);
                        batchReview.close();
                    }
                }
            }
        }
    }

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

        onOpened: checkedKinds = demo.kinds().map(function (k) {
            return k.id;
        })

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
                text: qsTr("Only demo-created rows are touched — anything " + "you added yourself stays. Projects that lose " + "their assets still work; exports skip the " + "missing files.")
            }
            Repeater {
                model: demo !== null ? demo.kinds() : []
                // #102: shared compact checkbox — consistent with the
                // rest of the forms (raw default indicator was oversized)
                FormCheck {
                    id: kindBox
                    required property var modelData
                    checkLabel: modelData.label
                    checked: demoDialog.checkedKinds.indexOf(modelData.id) >= 0
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    onToggled: {
                        var set = demoDialog.checkedKinds.slice();
                        var i = set.indexOf(kindBox.modelData.id);
                        if (checked && i < 0)
                            set.push(kindBox.modelData.id);
                        else if (!checked && i >= 0)
                            set.splice(i, 1);
                        demoDialog.checkedKinds = set;
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: qsTr("Select all")
                    onClicked: {
                        demoDialog.checkedKinds = demo.kinds().map(function (k) {
                            return k.id;
                        });
                    }
                    background: Rectangle {
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: parent.text
                        color: theme.tokens.text
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    text: qsTr("Keep all")
                    onClicked: demoDialog.checkedKinds = []
                    background: Rectangle {
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: parent.text
                        color: theme.tokens.text
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Item {
                    Layout.fillWidth: true
                }
                Button {
                    id: demoDeleteBtn
                    text: qsTr("Delete")
                    enabled: demoDialog.checkedKinds.length > 0
                    onClicked: {
                        demo.remove(demoDialog.checkedKinds);
                        demoDialog.close();
                    }
                    background: Rectangle {
                        radius: 6
                        color: demoDeleteBtn.enabled ? theme.tokens.accent : theme.tokens.border
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
                Button {
                    text: qsTr("Cancel")
                    onClicked: demoDialog.close()
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
                    }
                }
            }
        }
    }

    FileDialog {
        id: exportDialog
        fileMode: FileDialog.SaveFile
        nameFilters: exportFmt.currentIndex === 1 ? [qsTr("Archives (*.tar.gz)")] : [qsTr("Archives (*.zip)")]
        onAccepted: projects !== null && projects.export(Icons.toLocalPath(selectedFile), exportFmt.currentIndex === 1 ? "targz" : "zip")
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
            ScrollBar.vertical: ScrollBar {}
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
                    text: qsTr("A project is a named set of design tokens plus the " + "library assets (icons, fonts, snippets, palettes) it " + "ships with.\n\nColors: set the six roles explicitly " + "or leave them on 'auto' — auto roles fall back to " + "the first attached palette positionally, then to " + "sane defaults. 'apply' fills the roles from a saved " + "palette.\n\nType: pick body/heading families from " + "the scanned fonts and set the base size and modular " + "scale — the export emits @font-face rules and font " + "stacks.\n\nExport: a zip (or tar.gz) with " + "css/tokens.css, css/fonts.css, css/icons.css, " + "js/icons.js, a boilerplate index.html driven " + "entirely by the tokens, the attached files under " + "assets/, snippet pages, palettes.json and a " + "manifest.json. Run ▸ renders the same boilerplate " + "live in the sandboxed preview.")
                }
            }
        }
    }

    Connections {
        target: projects
        function onMessage(msg) {
            toast.show(msg);
        }
        function onExportDone(path) {
            toast.show(qsTr("Exported: %1").arg(path));
        }
        function onExportFailed(err) {
            toast.show(qsTr("Export failed: %1").arg(err));
        }
    }
}
