import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

// VS Code-style settings surface: category tree on the left, a search
// box that filters every row, controls applied live (no OK/Cancel —
// each control writes the same key the rest of the app reads). The
// shell loads this through a Loader, so it is rebuilt on every open:
// creation-time bindings capture current bridge state. Only the three
// controls the header can also change while this is open (theme, search
// mode, icon size) keep a live Connections sync.
Rectangle {
    id: settingsRoot
    color: theme.tokens.bg

    property string category: "all"
    property string query: ""
    signal closed

    // absorb clicks/hover so the rail and panes beneath never react
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
    }

    function matches(section, label, keys) {
        if (category !== "all" && section !== category)
            return false;
        if (query === "")
            return true;
        var hay = (label + " " + keys + " " + section).toLowerCase();
        return hay.indexOf(query.toLowerCase()) >= 0;
    }
    function showCategory(name) {
        category = name;
    }

    // dataio options flow: QML edits a COPY of the map, writes it back
    function setImportOpt(k, v) {
        var m = JSON.parse(JSON.stringify(dataio !== null ? dataio.importOpts : {}));
        m[k] = v;
        dataio.setImportOpts(m);
    }
    function setExportOpt(k, v) {
        var m = JSON.parse(JSON.stringify(dataio !== null ? dataio.exportOpts : {}));
        m[k] = v;
        dataio.setExportOpts(m);
    }
    function url2path(u) {
        return Icons.toLocalPath(u);   // single source of truth (#41)
    }
    // #81 dialog telemetry: every browse-button click, retry and dialog
    // resolution lands in crash.log via the prefs bridge, so a "the
    // buttons do nothing" report can be discriminated (click line with
    // no resolution line = the native dialog never mapped) instead of
    // guessed at. name = dialog site id, event = click|retry-click|
    // resolved-accepted|resolved-rejected, ms = open→resolution time.
    function dialogEvent(name, event, ms) {
        if (prefs !== null)
            prefs.noteDialogEvent(name, event, ms || 0);
    }
    // #51: every file/folder dialog opens in the last folder the user
    // visited (persisted in prefs.lastDialogDir, a plain local path —
    // encodeURI turns it into the file:// URL the dialogs bind to)
    function lastDialogUrl() {
        return (prefs !== null && prefs.lastDialogDir !== "") ? encodeURI("file://" + prefs.lastDialogDir) : "";
    }
    function rememberDialogDir(u) {
        if (prefs !== null && u !== undefined && u !== "")
            prefs.rememberDialogDir(url2path(u));
    }
    function toggleFmt(list, fmt) {
        var out = [];
        for (var i = 0; i < list.length; i++)
            if (list[i] !== fmt)
                out.push(list[i]);
        if (out.length === list.length)
            out.push(fmt);
        return out.length ? out : ["png"];
    }
    // live dataio state for the section
    property var watchRows: []
    property var transportRows: []
    property var backupRows: []
    property string addWatchPath: ""
    property string addWatchTransport: "local"
    property int addWatchInterval: 60
    property string csvPath: ""
    property string adminResult: ""
    property bool jobBusy: false
    property int jobDone: 0
    property int jobTotal: 0
    property string csvColumn: "0"
    property string pendingRestore: ""
    // #98: VS Code snippet scan results — set by the Import & Watch row's
    // scan button, read by the snippet scan popup
    property var snipScanResults: []
    function refreshData() {
        if (dataio === null)
            return;
        watchRows = dataio.watches();
        transportRows = dataio.transports();
        backupRows = dataio.backups();
        csvPath = (dataio.importOpts.csv_path || "");
        jobBusy = dataio.jobRunning;
    }
    Component.onCompleted: refreshData()
    Connections {
        target: dataio
        function onWatchesChanged() {
            settingsRoot.watchRows = dataio.watches();
        }
        function onBackupsChanged() {
            settingsRoot.backupRows = dataio.backups();
        }
        function onTransportsChanged() {
            settingsRoot.transportRows = dataio.transports();
        }
        function onJobStarted(kind) {
            settingsRoot.jobBusy = true;
            settingsRoot.jobDone = 0;
            settingsRoot.jobTotal = 0;
        }
        function onJobProgress(kind, done, total) {
            settingsRoot.jobDone = done;
            settingsRoot.jobTotal = total;
        }
        function onJobDone(kind, msg) {
            settingsRoot.jobBusy = false;
        }
        function onJobFailed(kind, err) {
            settingsRoot.jobBusy = false;
        }
        function onAdminDone(op, summary) {
            settingsRoot.adminResult = summary;
        }
        function onStatsChanged() {
        }
    }

    // user folders = registered sources that are NOT detected system
    // paths (system icon roots / font dirs are listed separately)
    readonly property var customFolders: {
        if (library === null || prefs === null)
            return [];
        var sys = {};
        var icons = prefs.systemIconPaths;
        var fontsDirs = prefs.systemFontDirs;
        for (var i = 0; i < icons.length; i++)
            sys[icons[i]] = true;
        for (var j = 0; j < fontsDirs.length; j++)
            sys[fontsDirs[j]] = true;
        var out = [];
        var srcs = library.sources;          // notify dep: sourcesChanged
        for (var k = 0; k < srcs.length; k++) {
            if (!sys[srcs[k].path])
                out.push(srcs[k]);
        }
        return out;
    }
    readonly property var enabledMap: {
        var map = {};
        if (library === null)
            return map;
        var s = library.sources;
        for (var i = 0; i < s.length; i++)
            map[s[i].path] = s[i].enabled;
        return map;
    }
    function pathEnabled(path) {
        if (library === null)
            return true;
        return path in enabledMap ? enabledMap[path] : true;
    }
    function rescanKind(kind) {
        if (kind === "fontroot")
            fonts.rescan();
        else
            library.rescan();
    }
    function baseName(path) {
        return path.replace(/\\/g, "/").split("/").pop();
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── category tree ──
        Rectangle {
            Layout.preferredWidth: 188
            Layout.fillHeight: true
            color: theme.tokens.surface
            Rectangle {
                anchors.right: parent.right
                width: 1
                height: parent.height
                color: theme.tokens.border
            }
            Column {
                id: navCol
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.topMargin: 12
                // #56 tightened the nav list; #47 settled it at 1 — the
                // merge of the two briefly duplicated the assignment,
                // which made SettingsScreen fail to load entirely (#76)
                spacing: 1
                // #55: a back button in the left panel — same close path
                // as the corner X, discoverable where the eye starts
                AbstractButton {
                    width: parent.width
                    implicitHeight: 28
                    HoverHandler {
                        cursorShape: Qt.PointingHandCursor
                    }
                    contentItem: Row {
                        leftPadding: 10
                        spacing: 8
                        IconImage {
                            name: "chevron-left"
                            px: 13
                            tint: theme.tokens.textMuted
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: qsTr("Back")
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: theme.tokens.text
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    background: Rectangle {
                        radius: 5
                        color: parent.hovered ? theme.tokens.surface2 : "transparent"
                    }
                    onClicked: settingsRoot.closed()
                }
                Repeater {
                    model: [
                        {
                            k: "all",
                            t: qsTr("All settings")
                        },
                        {
                            k: "general",
                            t: qsTr("General")
                        },
                        {
                            k: "appearance",
                            t: qsTr("Appearance")
                        },
                        {
                            k: "library",
                            t: qsTr("Library")
                        },
                        {
                            k: "storage",
                            t: qsTr("Storage")
                        },
                        {
                            k: "import",
                            t: qsTr("Import & Watch")
                        },
                        {
                            k: "export",
                            t: qsTr("Export")
                        },
                        {
                            k: "backup",
                            t: qsTr("Backup")
                        },
                        {
                            k: "database",
                            t: qsTr("Database")
                        },
                        {
                            k: "sc",
                            t: qsTr("Source control")
                        },
                        {
                            k: "editor",
                            t: qsTr("Editor")
                        },
                        {
                            k: "colors",
                            t: qsTr("Colors")
                        },
                        {
                            k: "updates",
                            t: qsTr("Updates")
                        },
                        {
                            k: "about",
                            t: qsTr("About")
                        }
                    ]
                    delegate: Rectangle {
                        id: navItem
                        required property var modelData
                        width: navCol.width
                        height: 30
                        color: settingsRoot.category === modelData.k ? theme.tokens.surface2 : "transparent"
                        Rectangle {
                            // selection bar
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3
                            height: parent.height - 12
                            radius: 1.5
                            color: settingsRoot.category === modelData.k ? theme.tokens.accent : "transparent"
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            text: navItem.modelData.t
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: settingsRoot.category === navItem.modelData.k ? theme.tokens.text : theme.tokens.textMuted
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: settingsRoot.category = navItem.modelData.k
                        }
                    }
                }
            }
        }

        // ── right pane: header + rows ──
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.margins: 18
                spacing: 14

                ColumnLayout {
                    Layout.fillWidth: true
                    // #56: breathing room under the page title
                    spacing: 4
                    Text {
                        text: qsTr("Settings")
                        font.family: theme.headingFont
                        font.pixelSize: 17
                        color: theme.tokens.text
                    }
                    Text {
                        text: qsTr("Changes apply immediately — there is nothing to save.")
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.textMuted
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 250
                    Layout.preferredHeight: 30
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: queryField.activeFocus ? theme.tokens.accent : theme.tokens.border
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 9
                        anchors.rightMargin: 9
                        spacing: 7
                        IconImage {
                            name: "search"
                            px: 14
                            tint: theme.tokens.textMuted
                        }
                        TextField {
                            id: queryField
                            Layout.fillWidth: true
                            placeholderText: qsTr("Search Settings")
                            background: null
                            color: theme.tokens.text
                            placeholderTextColor: theme.tokens.textMuted
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            selectByMouse: true
                            onTextChanged: settingsRoot.query = text
                        }
                    }
                }
            }

            Flickable {
                id: flick
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentHeight: body.implicitHeight + 36
                clip: true
                ColumnLayout {
                    id: body
                    x: 22
                    width: flick.width - 44
                    spacing: 0

                    // ────────────────────────────── general
                    SettingsSection {
                        section: "general"
                        title: qsTr("General")

                        SettingRow {
                            section: "general"
                            label: qsTr("Search mode")
                            desc: qsTr("Smart: indexed prefix search · Fuzzy: close matches rank first · Regex: patterns over names and paths · Content: inside text files.")
                            keys: "search find mode smart fuzzy regex content index query"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ComboBox {
                                id: modeRow
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 30
                                Layout.alignment: Qt.AlignVCenter
                                model: [qsTr("Smart"), qsTr("Fuzzy"), qsTr("Regex"), qsTr("Content")]
                                function syncIndex() {
                                    currentIndex = ["smart", "fuzzy", "regex", "content"].indexOf(library !== null ? library.searchMode : "smart");
                                }
                                Component.onCompleted: syncIndex()
                                onActivated: function (idx) {
                                    library !== null && library.set_search_mode(["smart", "fuzzy", "regex", "content"][idx]);
                                }
                                Connections {
                                    target: library
                                    function onFiltersChanged() {
                                        modeRow.syncIndex();
                                    }
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: theme.tokens.surface2
                                    border.color: theme.tokens.border
                                }
                                contentItem: Text {
                                    text: modeRow.displayText
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: theme.tokens.text
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 8
                                }
                            }
                        }

                        SettingRow {
                            section: "general"
                            label: qsTr("Web previews")
                            desc: qsTr("Live HTML previews in Code and Projects (WebEngine). Auto: launch verifies this display can run the web engine (a few seconds on GL-less machines) and only disables previews if it measurably cannot. Always: force previews on. Off: never start the web engine.")
                            keys: "web previews webengine html live code projects enable disable software rendering"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ComboBox {
                                id: webPreviewsRow
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 30
                                Layout.alignment: Qt.AlignVCenter
                                model: [qsTr("Auto"), qsTr("Always on"), qsTr("Off")]
                                function syncIndex() {
                                    currentIndex = ["auto", "on", "off"].indexOf(prefs !== null ? prefs.webPreviews : "auto");
                                }
                                Component.onCompleted: syncIndex()
                                onActivated: function (idx) {
                                    prefs !== null && prefs.set_web_previews(["auto", "on", "off"][idx]);
                                }
                                Connections {
                                    target: prefs
                                    function onWebPreviewsChanged() {
                                        webPreviewsRow.syncIndex();
                                    }
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: theme.tokens.surface2
                                    border.color: theme.tokens.border
                                }
                                contentItem: Text {
                                    text: webPreviewsRow.displayText
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: theme.tokens.text
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 8
                                }
                            }
                        }

                        SettingRow {
                            section: "general"
                            label: qsTr("Slash menu hotkey")
                            desc: qsTr("Opens the slash menu — search assets and snippets, run commands, jump anywhere. Default Alt + /.")
                            keys: "slash menu palette hotkey shortcut key sequence spotlight alfred vscode search jump"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                Layout.alignment: Qt.AlignVCenter
                                ShortcutCapture {
                                    Layout.preferredWidth: 170
                                    Layout.preferredHeight: 30
                                    onSequenceEdited: function (seq) {
                                        prefs !== null && prefs.set_command_shortcut(seq);
                                    }
                                }
                                SettingsButton {
                                    Layout.alignment: Qt.AlignVCenter
                                    text: qsTr("Reset")
                                    onClicked: prefs !== null && prefs.set_command_shortcut("Alt+/")
                                }
                            }
                        }

                        SettingRow {
                            section: "general"
                            label: qsTr("Startup pane")
                            desc: qsTr("Which pane opens when Fengrid starts.")
                            keys: "startup pane launch start default open"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ComboBox {
                                id: paneRow
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 30
                                Layout.alignment: Qt.AlignVCenter
                                model: [qsTr("Icons"), qsTr("Fonts"), qsTr("Colors"), qsTr("Code"), qsTr("Projects")]
                                Component.onCompleted: currentIndex = prefs !== null ? prefs.startupPane : 0
                                onActivated: function (idx) {
                                    prefs !== null && prefs.set_startup_pane(idx);
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: theme.tokens.surface2
                                    border.color: theme.tokens.border
                                }
                                contentItem: Text {
                                    text: paneRow.displayText
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: theme.tokens.text
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 8
                                }
                            }
                        }

                        SettingRow {
                            section: "general"
                            label: qsTr("First-time setup")
                            desc: qsTr("Walk through the one-time setup screen again — system paths, folders, look and behavior.")
                            keys: "first run setup wizard welcome configure re-run again"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            SettingsButton {
                                Layout.alignment: Qt.AlignVCenter
                                text: qsTr("Run setup again…")
                                onClicked: {
                                    prefs.start_first_run();
                                    settingsRoot.closed();
                                }
                            }
                        }
                    }

                    // ────────────────────────────── appearance
                    SettingsSection {
                        section: "appearance"
                        title: qsTr("Appearance")

                        SettingRow {
                            section: "appearance"
                            label: qsTr("Theme")
                            desc: qsTr("Dark or light color scheme — applies everywhere at once.")
                            keys: "theme dark light color scheme appearance mode"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ComboBox {
                                id: themeRow
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 30
                                Layout.alignment: Qt.AlignVCenter
                                model: [qsTr("Dark"), qsTr("Light")]
                                function syncIndex() {
                                    currentIndex = theme === null || theme.isDark ? 0 : 1;
                                }
                                Component.onCompleted: syncIndex()
                                onActivated: function (idx) {
                                    theme !== null && theme.set_theme(idx === 0 ? "dark" : "light");
                                }
                                Connections {
                                    target: theme
                                    function onThemeChanged() {
                                        themeRow.syncIndex();
                                    }
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: theme.tokens.surface2
                                    border.color: theme.tokens.border
                                }
                                contentItem: Text {
                                    text: themeRow.displayText
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: theme.tokens.text
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 8
                                }
                            }
                        }

                        SettingRow {
                            section: "appearance"
                            label: qsTr("Accent color")
                            desc: qsTr("The main accent Fengrid tints active states with — pane outlines, selection, primary buttons. Pick from the brand palette.")
                            keys: "accent color scheme tint brand teal amber violet coral rose green"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 6
                                Layout.alignment: Qt.AlignVCenter
                                Repeater {
                                    model: theme !== null ? theme.accentOptions : []
                                    delegate: Rectangle {
                                        required property var modelData
                                        readonly property bool sel: theme !== null && theme.accent === modelData.id
                                        readonly property color c: theme !== null && theme.isDark ? modelData.dark : modelData.light
                                        width: 26
                                        height: 20
                                        radius: 5
                                        color: c
                                        border.width: sel ? 2 : 0
                                        border.color: theme.tokens.text
                                        opacity: sel ? 1 : 0.62
                                        ToolTip.visible: ma.hovered
                                        ToolTip.text: modelData.name
                                        MouseArea {
                                            id: ma
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: theme !== null && theme.set_accent(modelData.id)
                                        }
                                        Accessible.role: Accessible.RadioButton
                                        Accessible.name: modelData.name
                                        Accessible.checked: sel
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "appearance"
                            label: qsTr("Icon size")
                            desc: qsTr("Grid tile size on the Icons pane, 16–256 px. The header slider writes the same value.")
                            keys: "icon size grid tile thumb thumbnail px slider zoom scale"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 10
                                Layout.alignment: Qt.AlignVCenter
                                FgSlider {
                                    id: sizeRow
                                    from: 16
                                    to: 256
                                    stepSize: 16
                                    Layout.preferredWidth: 170
                                    value: prefs !== null ? prefs.iconSize : 32
                                    // moved() = user-driven only, so the
                                    // Connections sync below can't loop;
                                    // set_icon_size dedupes per-step writes
                                    onMoved: prefs !== null && prefs.set_icon_size(Math.round(value))
                                    Connections {
                                        target: prefs
                                        function onIconSizeChanged() {
                                            if (!sizeRow.pressed)
                                                sizeRow.value = prefs.iconSize;
                                        }
                                    }
                                }
                                Text {
                                    text: Math.round(sizeRow.value) + "px"
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: theme.tokens.textMuted
                                    Layout.preferredWidth: 40
                                }
                            }
                        }
                    }

                    // ────────────────────────────── library
                    SettingsSection {
                        section: "library"
                        title: qsTr("Library")

                        SettingRow {
                            section: "library"
                            label: qsTr("System icon paths")
                            desc: qsTr("Detected platform icon roots. Unchecking a path removes its assets from the library; checking re-indexes it.")
                            keys: "system paths icons roots detected pixmaps themes hicolor scan"
                            rowMatches: settingsRoot.matches(section, label, keys)
                        }
                        Repeater {
                            model: prefs !== null ? prefs.systemIconPaths : []
                            delegate: RowLayout {
                                id: iconPathRow
                                required property string modelData
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                Layout.leftMargin: 4
                                spacing: 14
                                FormCheck {
                                    id: iconCheck
                                    Layout.preferredWidth: 170
                                    checkLabel: settingsRoot.baseName(modelData)
                                    checked: settingsRoot.pathEnabled(modelData)
                                    onToggled: {
                                        var isChecked = checked;
                                        Qt.callLater(function () {
                                            library.set_path_enabled(modelData, "system", isChecked);
                                            library.rescan();
                                        });
                                    }
                                    Connections {
                                        target: library
                                        function onSourcesChanged() {
                                            iconCheck.checked = settingsRoot.pathEnabled(modelData);
                                        }
                                    }
                                }
                                Text {
                                    text: iconPathRow.modelData
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: theme.tokens.textMuted
                                    Layout.fillWidth: true
                                    elide: Text.ElideMiddle
                                }
                            }
                        }

                        SettingRow {
                            section: "library"
                            label: qsTr("System font directories")
                            desc: qsTr("Detected platform font folders feeding the Fonts pane.")
                            keys: "font fonts directories system truetype opentype ttf otf"
                            rowMatches: settingsRoot.matches(section, label, keys)
                        }
                        Repeater {
                            model: prefs !== null ? prefs.systemFontDirs : []
                            delegate: RowLayout {
                                id: fontPathRow
                                required property string modelData
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                Layout.leftMargin: 4
                                spacing: 14
                                FormCheck {
                                    id: fontCheck
                                    Layout.preferredWidth: 170
                                    checkLabel: settingsRoot.baseName(modelData)
                                    checked: settingsRoot.pathEnabled(modelData)
                                    onToggled: {
                                        var isChecked = checked;
                                        Qt.callLater(function () {
                                            library.set_path_enabled(modelData, "fontroot", isChecked);
                                            fonts.rescan();
                                        });
                                    }
                                    Connections {
                                        target: library
                                        function onSourcesChanged() {
                                            fontCheck.checked = settingsRoot.pathEnabled(modelData);
                                        }
                                    }
                                }
                                Text {
                                    text: fontPathRow.modelData
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: theme.tokens.textMuted
                                    Layout.fillWidth: true
                                    elide: Text.ElideMiddle
                                }
                            }
                        }

                        SettingRow {
                            section: "library"
                            label: qsTr("Asset folders")
                            desc: qsTr("Your own icon and font folders — added through the folder picker, indexed like the system paths.")
                            keys: "folders custom assets add remove icons fonts user"
                            rowMatches: settingsRoot.matches(section, label, keys)
                        }
                        Repeater {
                            model: settingsRoot.customFolders
                            delegate: Rectangle {
                                id: folderRow
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                Layout.preferredHeight: 46
                                radius: 6
                                color: theme.tokens.surface2
                                border.color: theme.tokens.border
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 6
                                    spacing: 10
                                    Rectangle {
                                        Layout.preferredHeight: 16
                                        Layout.preferredWidth: kindChipText.implicitWidth + 12
                                        radius: 3
                                        color: "transparent"
                                        border.color: theme.tokens.border
                                        Text {
                                            id: kindChipText
                                            anchors.centerIn: parent
                                            text: folderRow.modelData.kind === "fontroot" ? qsTr("FONTS") : qsTr("ICONS")
                                            font.family: theme.monoFont
                                            font.pixelSize: 8
                                            font.letterSpacing: 1
                                            color: theme.tokens.textMuted
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 0
                                        Text {
                                            text: folderRow.modelData.label || folderRow.modelData.path
                                            font.family: theme.uiFont
                                            font.pixelSize: 12
                                            color: theme.tokens.text
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            text: folderRow.modelData.path
                                            font.family: theme.monoFont
                                            font.pixelSize: 9
                                            color: theme.tokens.textMuted
                                            Layout.fillWidth: true
                                            elide: Text.ElideMiddle
                                        }
                                    }
                                    Text {
                                        text: qsTr("%1 items").arg(folderRow.modelData.n)
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.textMuted
                                    }
                                    FormCheck {
                                        Layout.alignment: Qt.AlignVCenter
                                        checkLabel: ""
                                        checked: folderRow.modelData.enabled
                                        ToolTip.visible: hovered
                                        ToolTip.delay: 400
                                        ToolTip.text: qsTr("Include in the library")
                                        onToggled: {
                                            var isChecked = checked;
                                            var p = folderRow.modelData.path;
                                            var k = folderRow.modelData.kind;
                                            Qt.callLater(function () {
                                                library.set_path_enabled(p, k, isChecked);
                                                settingsRoot.rescanKind(k);
                                            });
                                        }
                                    }
                                    IconButton {
                                        icon_name: "trash"
                                        ToolTip.text: qsTr("Remove folder from library")
                                        onClicked: {
                                            library.remove_folder(folderRow.modelData.id);
                                            fonts.refresh();
                                        }
                                    }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.topMargin: 12
                            spacing: 8
                            SettingsButton {
                                text: qsTr("Add icon folder…")
                                onClicked: {
                                    folderDialogLoader.open("folder");
                                }
                            }
                            SettingsButton {
                                text: qsTr("Add font folder…")
                                onClicked: {
                                    folderDialogLoader.open("fontroot");
                                }
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            SettingsButton {
                                text: qsTr("Re-scan icons")
                                enabled: library !== null && !library.scanning
                                onClicked: library.rescan()
                            }
                            SettingsButton {
                                text: qsTr("Re-scan fonts")
                                enabled: fonts !== null && !fonts.scanning
                                onClicked: fonts.rescan()
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            Layout.topMargin: 8
                            text: library === null || fonts === null ? "" : (library.scanning || fonts.scanning) ? qsTr("Indexing… icons %1 · fonts %2").arg(library.scanCount).arg(fonts.scanCount) : qsTr("%1 assets indexed · %2 font files").arg(library.totalAssets).arg(fonts.totalFonts)
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }
                    }

                    // ────────────────────────────── storage
                    SettingsSection {
                        section: "storage"
                        title: qsTr("Storage")

                        SettingRow {
                            section: "storage"
                            label: qsTr("Local folders")
                            desc: qsTr("Attach local directories through the folder picker — they scan like any other asset folder.")
                            keys: "local folder directory disk drive picker path"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            SettingsButton {
                                Layout.alignment: Qt.AlignVCenter
                                text: qsTr("Add folder…")
                                onClicked: {
                                    folderDialogLoader.open("folder");
                                }
                            }
                        }

                        // coming-soon callout (spec: personal cloud sync)
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.topMargin: 12
                            Layout.preferredHeight: cloudCol.implicitHeight + 20
                            radius: 6
                            color: theme.tokens.surface2
                            border.color: theme.tokens.border
                            ColumnLayout {
                                id: cloudCol
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 3
                                Text {
                                    text: qsTr("Personal cloud sync — coming soon")
                                    font.family: theme.uiFont
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                    color: theme.tokens.accent
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: qsTr("Syncing your library with Dropbox, Google Drive or OneDrive is on the way. Until then, attach such a folder as a local path once it exists on disk — or mount it yourself with one of the backends below.")
                                    wrapMode: Text.Wrap
                                    font.family: theme.uiFont
                                    font.pixelSize: 10
                                    // #56: loosen wrapped body text
                                    lineHeight: 1.3
                                    lineHeightMode: Text.ProportionalHeight
                                    color: theme.tokens.textMuted
                                }
                            }
                        }

                        Repeater {
                            model: storage !== null ? storage.backends.filter(function (b) {
                                return b.key !== "local";
                            }) : []
                            delegate: RowLayout {
                                id: backendRow
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.topMargin: 14
                                spacing: 20
                                visible: settingsRoot.matches("storage", modelData.label, "storage backend mount remote share " + modelData.key + " network cloud")
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    // #56: label/description gap
                                    spacing: 4
                                    Text {
                                        text: backendRow.modelData.label
                                        font.family: theme.uiFont
                                        font.pixelSize: 13
                                        color: theme.tokens.text
                                        Layout.fillWidth: true
                                        wrapMode: Text.Wrap
                                    }
                                    Text {
                                        text: backendRow.modelData.status
                                        Layout.fillWidth: true
                                        wrapMode: Text.Wrap
                                        font.family: theme.uiFont
                                        font.pixelSize: 11
                                        // #56: loosen wrapped body text
                                        lineHeight: 1.3
                                        lineHeightMode: Text.ProportionalHeight
                                        color: backendRow.modelData.available ? theme.tokens.textMuted : theme.tokens.hlInk
                                    }
                                }
                                SettingsButton {
                                    Layout.alignment: Qt.AlignVCenter
                                    text: qsTr("Attach…")
                                    enabled: backendRow.modelData.available
                                    onClicked: storageDialog.openFor(backendRow.modelData.key, backendRow.modelData.label, qsTr("Example: %1 — %2").arg(backendRow.modelData.hint).arg(backendRow.modelData.status))
                                }
                            }
                        }

                        Repeater {
                            model: storage !== null ? storage.mounts : []
                            delegate: Rectangle {
                                id: mountRow
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                Layout.preferredHeight: 46
                                radius: 6
                                color: theme.tokens.surface2
                                border.color: theme.tokens.border
                                visible: settingsRoot.matches("storage", modelData.backendLabel, "mount attached storage " + modelData.backend)
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 6
                                    spacing: 10
                                    Rectangle {
                                        Layout.preferredHeight: 16
                                        Layout.preferredWidth: mountChip.implicitWidth + 12
                                        radius: 3
                                        color: "transparent"
                                        border.color: theme.tokens.border
                                        Text {
                                            id: mountChip
                                            anchors.centerIn: parent
                                            text: mountRow.modelData.backend
                                            font.family: theme.monoFont
                                            font.pixelSize: 8
                                            font.letterSpacing: 1
                                            color: theme.tokens.textMuted
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 0
                                        Text {
                                            text: mountRow.modelData.uri
                                            font.family: theme.uiFont
                                            font.pixelSize: 12
                                            color: theme.tokens.text
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            text: mountRow.modelData.local_path
                                            font.family: theme.monoFont
                                            font.pixelSize: 9
                                            color: theme.tokens.textMuted
                                            Layout.fillWidth: true
                                            elide: Text.ElideMiddle
                                        }
                                    }
                                    Text {
                                        text: mountRow.modelData.healthy ? qsTr("Mounted") : qsTr("Not Mounted")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: mountRow.modelData.healthy ? theme.tokens.textMuted : theme.tokens.hlInk
                                    }
                                    SettingsButton {
                                        text: qsTr("Eject")
                                        onClicked: storage.detach(mountRow.modelData.id)
                                    }
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            Layout.topMargin: 10
                            visible: storage === null || storage.mounts.length === 0
                            text: qsTr("No network or cloud storage attached yet.")
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.textMuted
                        }
                    }

                    // ────────────────────────── import & watch
                    SettingsSection {
                        section: "import"
                        title: qsTr("Import & Watch")

                        SettingRow {
                            section: "import"
                            label: qsTr("Import files")
                            desc: qsTr("Bring icons and fonts in from files, ZIP archives or whole folders.")
                            keys: "import ingest add files zip folder archive upload ingest assets fonts icons"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                SettingsButton {
                                    text: qsTr("Files…")
                                    onClicked: filesDialogLoader.open()
                                }
                                SettingsButton {
                                    text: qsTr("ZIP…")
                                    onClicked: zipDialogLoader.open()
                                }
                                SettingsButton {
                                    text: qsTr("Folder…")
                                    onClicked: folderImportLoader.open()
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("Import code snippets")
                            desc: qsTr("Bring in VS Code and massCode snippets. Scan finds files at VS Code's default snippet folder; Files… picks any .code-snippets, .json or massCode database.")
                            keys: "import snippets code vscode masscode scan detect location vs code default files"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                SettingsButton {
                                    text: qsTr("Scan VS Code…")
                                    onClicked: {
                                        // #98: scan the default User/snippets
                                        // folders of VS Code and its variants;
                                        // the popup lists what it found (or
                                        // the not-found message) and imports
                                        // on click
                                        settingsRoot.snipScanResults = code !== null ? code.scan_vscode_snippets() : [];
                                        snippetScanPopup.open();
                                    }
                                }
                                SettingsButton {
                                    text: qsTr("Files…")
                                    onClicked: snippetFileDialogLoader.open()
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("File storage mode")
                            desc: qsTr("Copy embeds files into Fengrid's data folder (self-contained). Link keeps them where they are and symlinks — needs read permission on the original location.")
                            keys: "copy link embed symlink mode storage external permission embedded readonly"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 6
                                Chip {
                                    label: "Copy"
                                    on: dataio !== null && dataio.importOpts.mode === "copy"
                                    onPicked: settingsRoot.setImportOpt("mode", "copy")
                                }
                                Chip {
                                    label: "Link"
                                    on: dataio !== null && dataio.importOpts.mode === "link"
                                    onPicked: settingsRoot.setImportOpt("mode", "link")
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("Format conversion")
                            desc: qsTr("Convert icons on the way in (SVG is rasterised first). Fonts and colors are never rewritten.")
                            keys: "convert conversion format png bmp ico webp rasterize transform target"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            Flow {
                                spacing: 6
                                Repeater {
                                    model: ["none", "png", "bmp", "ico", "webp"]
                                    Chip {
                                        required property var modelData
                                        label: modelData
                                        on: dataio !== null && dataio.importOpts.convert === modelData
                                        onPicked: settingsRoot.setImportOpt("convert", modelData)
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("Rename template")
                            desc: qsTr("Tokens: {name} {ext} {n} {guid} {rand} {csv}. Empty = keep original names.")
                            keys: "rename template naming pattern tokens guid random enumeration"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            FormInput {
                                label: qsTr("Template")
                                text: dataio !== null ? (dataio.importOpts.template || "") : ""
                                onTextChanged: settingsRoot.setImportOpt("template", text)
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("Prefix / suffix")
                            desc: qsTr("Wrapped around every imported name.")
                            keys: "prefix suffix prepend append rename"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                FormInput {
                                    Layout.fillWidth: true
                                    label: qsTr("Prefix")
                                    text: dataio !== null ? (dataio.importOpts.prefix || "") : ""
                                    onTextChanged: settingsRoot.setImportOpt("prefix", text)
                                }
                                FormInput {
                                    Layout.fillWidth: true
                                    label: qsTr("Suffix")
                                    text: dataio !== null ? (dataio.importOpts.suffix || "") : ""
                                    onTextChanged: settingsRoot.setImportOpt("suffix", text)
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("Find / replace (regex)")
                            desc: qsTr("Applied to the original name before tokens; an invalid pattern is skipped, never aborts the import.")
                            keys: "regex find replace substitution pattern rename sed"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                FormInput {
                                    Layout.fillWidth: true
                                    label: qsTr("Find")
                                    text: dataio !== null ? (dataio.importOpts.find || "") : ""
                                    onTextChanged: settingsRoot.setImportOpt("find", text)
                                }
                                FormInput {
                                    Layout.fillWidth: true
                                    label: qsTr("Replace")
                                    text: dataio !== null ? (dataio.importOpts.repl || "") : ""
                                    onTextChanged: settingsRoot.setImportOpt("repl", text)
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("Enumeration style")
                            desc: qsTr("Cardinal counting, random suffixes or generated GUIDs appended to each name.")
                            keys: "enumeration cardinal random guid counter sequence numbered sort"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ColumnLayout {
                                spacing: 6
                                Flow {
                                    spacing: 6
                                    Repeater {
                                        model: ["none", "enum", "random", "guid"]
                                        Chip {
                                            required property var modelData
                                            label: modelData
                                            on: dataio !== null && dataio.importOpts.style === modelData
                                            onPicked: settingsRoot.setImportOpt("style", modelData)
                                        }
                                    }
                                }
                                RowLayout {
                                    spacing: 8
                                    FormInput {
                                        Layout.preferredWidth: 90
                                        label: qsTr("Start")
                                        text: dataio !== null ? String(dataio.importOpts.start || 1) : "1"
                                        onTextChanged: settingsRoot.setImportOpt("start", parseInt(text) || 1)
                                    }
                                    FormInput {
                                        Layout.preferredWidth: 90
                                        label: qsTr("Pad")
                                        text: dataio !== null ? String(dataio.importOpts.pad || 2) : "2"
                                        onTextChanged: settingsRoot.setImportOpt("pad", Math.max(0, parseInt(text) || 0))
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("CSV name list")
                            desc: qsTr("Supplied names consumed one per imported file ({csv} token).")
                            keys: "csv names list spreadsheet batch rename data column"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                SettingsButton {
                                    text: settingsRoot.csvPath === "" ? qsTr("Choose CSV…") : settingsRoot.csvPath.split("/").pop()
                                    onClicked: csvDialogLoader.open()
                                }
                                FormInput {
                                    Layout.preferredWidth: 90
                                    label: qsTr("Column")
                                    text: settingsRoot.csvColumn
                                    onTextChanged: {
                                        settingsRoot.csvColumn = text;
                                        settingsRoot.setImportOpt("csv_column", text);
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("Import progress")
                            desc: qsTr("One file in memory at a time; archives stream through a 64KB buffer and index in chunks — large batches stay flat on memory.")
                            keys: "progress memory performance large batch streaming big quantities"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 10
                                visible: settingsRoot.jobBusy
                                Layout.fillWidth: true
                                ProgressBar {
                                    id: jobProgress
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 6
                                    from: 0
                                    to: settingsRoot.jobTotal > 0 ? settingsRoot.jobTotal : 1
                                    value: settingsRoot.jobTotal > 0 ? settingsRoot.jobDone : 0
                                    indeterminate: settingsRoot.jobTotal <= 0
                                    background: Rectangle {
                                        radius: 3
                                        color: theme.tokens.surface2
                                    }
                                    contentItem: Item {
                                        clip: true
                                        Rectangle {
                                            visible: !jobProgress.indeterminate
                                            height: parent.height
                                            width: jobProgress.visualPosition * jobProgress.width
                                            radius: 3
                                            color: theme.tokens.accent
                                        }
                                        Rectangle {
                                            visible: jobProgress.indeterminate
                                            height: parent.height
                                            width: Math.max(40, jobProgress.width * 0.3)
                                            radius: 3
                                            color: theme.tokens.accent
                                            SequentialAnimation on x {
                                                loops: Animation.Infinite
                                                running: jobProgress.visible && jobProgress.indeterminate
                                                NumberAnimation {
                                                    from: -80
                                                    to: jobProgress.width
                                                    duration: 900
                                                }
                                                NumberAnimation {
                                                    from: jobProgress.width
                                                    to: -80
                                                    duration: 900
                                                }
                                            }
                                        }
                                    }
                                }
                                Text {
                                    text: settingsRoot.jobTotal > 0 ? settingsRoot.jobDone + " / " + settingsRoot.jobTotal : qsTr("Working…")
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: theme.tokens.textMuted
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("Watch folders & dropboxes")
                            desc: qsTr("Scanned periodically for changes; new and changed files are indexed automatically.")
                            keys: "watch watcher folder dropbox periodic sync auto scan ftp sftp scp http rsync remote network s3 dropbox inbox"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ColumnLayout {
                                spacing: 8
                                Layout.fillWidth: true

                                RowLayout {
                                    spacing: 8
                                    Layout.fillWidth: true
                                    FormInput {
                                        Layout.fillWidth: true
                                        label: qsTr("Path or Remote Spec")
                                        text: settingsRoot.addWatchPath
                                        onTextChanged: settingsRoot.addWatchPath = text
                                    }
                                    SettingsButton {
                                        text: qsTr("Add")
                                        enabled: settingsRoot.addWatchPath.trim() !== "" && dataio !== null
                                        onClicked: {
                                            dataio.watchAdd(settingsRoot.addWatchPath.trim(), settingsRoot.addWatchTransport, settingsRoot.addWatchInterval);
                                            settingsRoot.addWatchPath = "";
                                        }
                                    }
                                }
                                Flow {
                                    spacing: 6
                                    Repeater {
                                        model: settingsRoot.transportRows.filter(function (t) {
                                            return t.kind !== "soon";
                                        })
                                        Chip {
                                            required property var modelData
                                            opacity: modelData.available ? 1 : 0.45
                                            label: modelData.key
                                            on: settingsRoot.addWatchTransport === modelData.key
                                            onPicked: {
                                                if (modelData.available)
                                                    settingsRoot.addWatchTransport = modelData.key;
                                            }
                                        }
                                    }
                                }
                                RowLayout {
                                    spacing: 6
                                    Text {
                                        text: qsTr("Every")
                                        font.family: theme.uiFont
                                        font.pixelSize: 11
                                        color: theme.tokens.textMuted
                                    }
                                    Repeater {
                                        model: [30, 60, 300]
                                        Chip {
                                            required property var modelData
                                            label: modelData === 60 ? "1m" : modelData === 300 ? "5m" : modelData + "s"
                                            on: settingsRoot.addWatchInterval === modelData
                                            onPicked: settingsRoot.addWatchInterval = modelData
                                        }
                                    }
                                }

                                Repeater {
                                    model: settingsRoot.watchRows
                                    RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: 8
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 0
                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.label || modelData.path
                                                font.family: theme.uiFont
                                                font.pixelSize: 12
                                                color: theme.tokens.text
                                                elide: Text.ElideMiddle
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.transport + " · " + (modelData.interval >= 300 ? Math.round(modelData.interval / 60) + "m" : modelData.interval + "s") + (modelData.lastHits ? " · " + modelData.lastHits + " new" : "")
                                                font.family: theme.monoFont
                                                font.pixelSize: 9
                                                color: theme.tokens.textMuted
                                                elide: Text.ElideRight
                                            }
                                        }
                                        FormCheck {
                                            checkLabel: qsTr("On")
                                            checked: modelData.enabled
                                            onToggled: dataio.watchToggle(modelData.id, checked)
                                        }
                                        SettingsButton {
                                            text: qsTr("Run")
                                            onClicked: dataio.watchRunNow(modelData.id)
                                        }
                                        SettingsButton {
                                            text: qsTr("Remove")
                                            onClicked: dataio.watchRemove(modelData.id)
                                        }
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    visible: settingsRoot.watchRows.length === 0
                                    text: qsTr("No watch folders yet — add a local dropbox above.")
                                    font.family: theme.uiFont
                                    font.pixelSize: 11
                                    color: theme.tokens.textMuted
                                }
                            }
                        }

                        SettingRow {
                            section: "import"
                            label: qsTr("Cloud storage")
                            desc: qsTr("Amazon S3-compatible storage attaches through the Storage section; remote pulls need rsync/scp/curl installed.")
                            keys: "cloud s3 amazon onedrive icloud google drive coming soon remote tools"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 6
                                Chip {
                                    label: "S3 (Storage)"
                                    on: false
                                    onPicked: {}
                                }
                                Text {
                                    text: qsTr("OneDrive · iCloud · Google Drive — coming soon")
                                    font.family: theme.uiFont
                                    font.pixelSize: 11
                                    font.italic: true
                                    color: theme.tokens.textMuted
                                }
                            }
                        }

                        Loader {
                            id: filesDialogLoader
                            active: false
                            property int openStamp: 0
                            sourceComponent: FileDialog {
                                id: filesDialog
                                title: qsTr("Import files")
                                currentFolder: settingsRoot.lastDialogUrl()
                                fileMode: FileDialog.OpenFiles
                                nameFilters: [qsTr("Assets (*.png *.svg *.bmp *.ico *.webp *.gif *.jpg *.jpeg *.tiff *.ttf *.otf *.ttc)"), qsTr("All files (*)")]
                                onAccepted: {
                                    settingsRoot.dialogEvent("files", "resolved-accepted", Date.now() - filesDialogLoader.openStamp);
                                    var paths = [];
                                    for (var i = 0; i < selectedFiles.length; i++)
                                        paths.push(settingsRoot.url2path(selectedFiles[i]));
                                    dataio.importStart(paths);
                                    settingsRoot.rememberDialogDir(filesDialog.currentFolder);
                                    filesDialogLoader.active = false;
                                }
                                onRejected: {
                                    settingsRoot.dialogEvent("files", "resolved-rejected", Date.now() - filesDialogLoader.openStamp);
                                    settingsRoot.rememberDialogDir(filesDialog.currentFolder);
                                    filesDialogLoader.active = false;
                                }
                            }
                            // #81 dead-attempt recycle guard +
                            // click/resolve telemetry — see zipDialogLoader
                            // below for the full rationale (same class).
                            onLoaded: item.open()
                            function open() {
                                settingsRoot.dialogEvent("files", active ? "retry-click" : "click", 0);
                                if (active)
                                    active = false;
                                openStamp = Date.now();
                                active = true;
                            }
                        }
                        // native dialogs load lazily: instantiating a
                        // QtQuick.Dialogs object on a real desktop session
                        // touches the XDG portal — a hanging portal on
                        // some desktops froze the whole Settings screen
                        // at open (elementary/GNOME reports). Nothing
                        // portal-related is created until the user
                        // clicks a browse button.
                        Loader {
                            id: zipDialogLoader
                            active: false
                            property int openStamp: 0
                            sourceComponent: FileDialog {
                                id: zipDialog
                                title: qsTr("Import ZIP archive")
                                currentFolder: settingsRoot.lastDialogUrl()
                                fileMode: FileDialog.OpenFile
                                nameFilters: [qsTr("ZIP archives (*.zip)")]
                                onAccepted: {
                                    settingsRoot.dialogEvent("zip", "resolved-accepted", Date.now() - zipDialogLoader.openStamp);
                                    dataio.importZip(settingsRoot.url2path(selectedFile));
                                    settingsRoot.rememberDialogDir(zipDialog.currentFolder);
                                    zipDialogLoader.active = false;
                                }
                                onRejected: {
                                    settingsRoot.dialogEvent("zip", "resolved-rejected", Date.now() - zipDialogLoader.openStamp);
                                    settingsRoot.rememberDialogDir(zipDialog.currentFolder);
                                    zipDialogLoader.active = false;
                                }
                            }
                            // #81: a native dialog that never maps (the
                            // portal-hang / absent-dialog-backend class)
                            // leaves the Loader active forever — every
                            // later click then silently no-ops, so the
                            // buttons look dead for the rest of the
                            // session. A mapped native dialog is modal
                            // and keeps these browse buttons
                            // unreachable, so active==true at click time
                            // can only mean the previous attempt died
                            // silently: recycle the Loader and retry.
                            // (The earlier "item null right after
                            // active=true" diagnosis was disproven by an
                            // offscreen test — a synchronous Loader has
                            // its item immediately; onLoaded stays as
                            // belt-and-braces only.)
                            onLoaded: item.open()
                            function open() {
                                settingsRoot.dialogEvent("zip", active ? "retry-click" : "click", 0);
                                if (active)
                                    active = false;
                                openStamp = Date.now();
                                active = true;
                            }
                        }
                        Loader {
                            id: csvDialogLoader
                            active: false
                            property int openStamp: 0
                            sourceComponent: FileDialog {
                                id: csvDialog
                                title: qsTr("CSV name list")
                                currentFolder: settingsRoot.lastDialogUrl()
                                fileMode: FileDialog.OpenFile
                                nameFilters: [qsTr("CSV files (*.csv)")]
                                onAccepted: {
                                    settingsRoot.dialogEvent("csv", "resolved-accepted", Date.now() - csvDialogLoader.openStamp);
                                    settingsRoot.csvPath = settingsRoot.url2path(selectedFile);
                                    settingsRoot.setImportOpt("csv_path", settingsRoot.csvPath);
                                    settingsRoot.rememberDialogDir(csvDialog.currentFolder);
                                    csvDialogLoader.active = false;
                                }
                                onRejected: {
                                    settingsRoot.dialogEvent("csv", "resolved-rejected", Date.now() - csvDialogLoader.openStamp);
                                    settingsRoot.rememberDialogDir(csvDialog.currentFolder);
                                    csvDialogLoader.active = false;
                                }
                            }
                            // #81 dead-attempt recycle guard +
                            // click/resolve telemetry — see zipDialogLoader
                            // for the full rationale (same class).
                            onLoaded: item.open()
                            function open() {
                                settingsRoot.dialogEvent("csv", active ? "retry-click" : "click", 0);
                                if (active)
                                    active = false;
                                openStamp = Date.now();
                                active = true;
                            }
                        }
                        Loader {
                            id: folderImportLoader
                            active: false
                            property int openStamp: 0
                            sourceComponent: FolderDialog {
                                id: folderImportDialog
                                title: qsTr("Import folder as source")
                                currentFolder: settingsRoot.lastDialogUrl()
                                onAccepted: {
                                    settingsRoot.dialogEvent("folder", "resolved-accepted", Date.now() - folderImportLoader.openStamp);
                                    dataio.importFolder(settingsRoot.url2path(selectedFolder));
                                    settingsRoot.rememberDialogDir(folderImportDialog.currentFolder);
                                    folderImportLoader.active = false;
                                }
                                onRejected: {
                                    settingsRoot.dialogEvent("folder", "resolved-rejected", Date.now() - folderImportLoader.openStamp);
                                    settingsRoot.rememberDialogDir(folderImportDialog.currentFolder);
                                    folderImportLoader.active = false;
                                }
                            }
                            // #81 dead-attempt recycle guard +
                            // click/resolve telemetry — see zipDialogLoader
                            // for the full rationale (same class).
                            onLoaded: item.open()
                            function open() {
                                settingsRoot.dialogEvent("folder", active ? "retry-click" : "click", 0);
                                if (active)
                                    active = false;
                                openStamp = Date.now();
                                active = true;
                            }
                        }

                        // #98: snippet file picker — same lazy-loader pattern
                        // as the other dialogs (portal hang avoidance)
                        Loader {
                            id: snippetFileDialogLoader
                            active: false
                            property int openStamp: 0
                            sourceComponent: FileDialog {
                                id: snippetFileDialog
                                title: qsTr("Import code snippets")
                                currentFolder: settingsRoot.lastDialogUrl()
                                fileMode: FileDialog.OpenFile
                                nameFilters: [qsTr("Snippets (*.code-snippets *.json *.sqlite *.db *.sqlite3)"), qsTr("All files (*)")]
                                onAccepted: {
                                    settingsRoot.dialogEvent("snippets", "resolved-accepted", Date.now() - snippetFileDialogLoader.openStamp);
                                    // kind = "" → the bridge infers it from
                                    // the file extension
                                    code !== null && code.import_snippets("", settingsRoot.url2path(selectedFile));
                                    settingsRoot.rememberDialogDir(snippetFileDialog.currentFolder);
                                    snippetFileDialogLoader.active = false;
                                }
                                onRejected: {
                                    settingsRoot.dialogEvent("snippets", "resolved-rejected", Date.now() - snippetFileDialogLoader.openStamp);
                                    settingsRoot.rememberDialogDir(snippetFileDialog.currentFolder);
                                    snippetFileDialogLoader.active = false;
                                }
                            }
                            onLoaded: item.open()
                            function open() {
                                settingsRoot.dialogEvent("snippets", active ? "retry-click" : "click", 0);
                                if (active)
                                    active = false;
                                openStamp = Date.now();
                                active = true;
                            }
                        }

                        // #98: VS Code snippet scan results popup — lists
                        // the files found at default locations; clicking
                        // one imports it immediately
                        Popup {
                            id: snippetScanPopup
                            parent: Overlay.overlay
                            anchors.centerIn: parent
                            width: 380
                            height: Math.min(320, snipColumn.implicitHeight + 56)
                            modal: true
                            background: Rectangle {
                                radius: 8
                                color: theme.tokens.surface
                                border.color: theme.tokens.border
                            }
                            ColumnLayout {
                                id: snipColumn
                                anchors.fill: parent
                                anchors.margins: 14
                                spacing: 8
                                Text {
                                    text: settingsRoot.snipScanResults.length ? qsTr("VS Code snippets found") : qsTr("No snippet files found at VS Code's default locations")
                                    font.family: theme.headingFont
                                    font.pixelSize: 13
                                    color: theme.tokens.text
                                }
                                Text {
                                    visible: settingsRoot.snipScanResults.length === 0
                                    text: qsTr("Checked: VS Code, Insiders, VSCodium and Cursor. You can still import any file with Files… below.")
                                    font.family: theme.uiFont
                                    font.pixelSize: 10
                                    color: theme.tokens.textMuted
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                                ListView {
                                    visible: settingsRoot.snipScanResults.length > 0
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    model: settingsRoot.snipScanResults
                                    delegate: ItemDelegate {
                                        required property var modelData
                                        width: ListView.view.width
                                        height: 34
                                        contentItem: RowLayout {
                                            spacing: 8
                                            ColumnLayout {
                                                spacing: 1
                                                Layout.fillWidth: true
                                                Text {
                                                    text: modelData.name
                                                    font.family: theme.monoFont
                                                    font.pixelSize: 11
                                                    color: theme.tokens.text
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                                Text {
                                                    text: modelData.app
                                                    font.family: theme.uiFont
                                                    font.pixelSize: 9
                                                    color: theme.tokens.textMuted
                                                }
                                            }
                                            SettingsButton {
                                                text: qsTr("Import")
                                                onClicked: {
                                                    code !== null && code.import_snippets("", modelData.path);
                                                    snippetScanPopup.close();
                                                }
                                            }
                                        }
                                    }
                                    ScrollBar.vertical: ScrollBar {}
                                }
                                FgDialogFooter {
                                    acceptLabel: qsTr("Close")
                                    onCancelClicked: snippetScanPopup.close()
                                    onAcceptClicked: snippetScanPopup.close()
                                }
                            }
                        }
                    }

                    // ────────────────────────────────────── export
                    SettingsSection {
                        section: "export"
                        title: qsTr("Export")

                        SettingRow {
                            section: "export"
                            label: qsTr("Icon formats (multi-select)")
                            desc: qsTr("Every checked format is written per icon in one pass.")
                            keys: "export formats png jpeg webp ico pdf gif tiff bmp convert multiple"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            Flow {
                                spacing: 6
                                Repeater {
                                    model: ["png", "jpeg", "webp", "ico", "pdf", "gif", "tiff", "bmp"]
                                    Chip {
                                        required property var modelData
                                        label: modelData
                                        on: dataio !== null && dataio.exportOpts.icon_fmts.indexOf(modelData) >= 0
                                        onPicked: settingsRoot.setExportOpt("icon_fmts", settingsRoot.toggleFmt(dataio.exportOpts.icon_fmts, modelData))
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "export"
                            label: qsTr("Icon size")
                            desc: qsTr("Default resize target; ICO keeps its multi-size packing.")
                            keys: "export size resize px dimensions scale 16 32 64 128 256"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            Flow {
                                spacing: 6
                                Repeater {
                                    model: ["16", "32", "64", "128", "256", "orig"]
                                    Chip {
                                        required property var modelData
                                        label: modelData === "orig" ? qsTr("orig") : modelData + "px"
                                        on: dataio !== null && String(dataio.exportOpts.icon_size) === modelData
                                        onPicked: settingsRoot.setExportOpt("icon_size", modelData)
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "export"
                            label: qsTr("Tint / color filter")
                            desc: qsTr("Recolors icons through their alpha channel — the cross-set recolor you'd otherwise open an editor for. Empty = original colors.")
                            keys: "tint color filter recolor mono paint hue photoshop filter overlay"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            FormInput {
                                label: qsTr("Hex (e.g. #39B8C4)")
                                text: dataio !== null ? (dataio.exportOpts.tint || "") : ""
                                onTextChanged: settingsRoot.setExportOpt("tint", text)
                            }
                        }

                        SettingRow {
                            section: "export"
                            label: qsTr("Batch script / operation")
                            desc: qsTr("Runs per exported file: argv tokens {in} {out} {dir} {name}. Never a shell; keep it off unless you need it.")
                            keys: "script batch operation command hook automate post-process pipeline"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ColumnLayout {
                                spacing: 6
                                Layout.fillWidth: true
                                FormCheck {
                                    checkLabel: qsTr("Run a Script on Each Exported File")
                                    checked: dataio !== null && !!dataio.exportOpts.script_enabled
                                    onToggled: settingsRoot.setExportOpt("script_enabled", checked)
                                }
                                FormInput {
                                    Layout.fillWidth: true
                                    visible: dataio !== null && !!dataio.exportOpts.script_enabled
                                    label: qsTr("Command (argv)")
                                    text: dataio !== null ? (dataio.exportOpts.script || "") : ""
                                    onTextChanged: settingsRoot.setExportOpt("script", text)
                                }
                            }
                        }

                        SettingRow {
                            section: "export"
                            label: qsTr("Webfonts")
                            desc: qsTr("Fonts export as woff2/woff packages with a relative @font-face stylesheet — no conversion site needed.")
                            keys: "fonts webfont woff woff2 ttf package css font-face variants weight style"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            Flow {
                                spacing: 6
                                Repeater {
                                    model: ["woff2", "woff", "ttf"]
                                    Chip {
                                        required property var modelData
                                        label: modelData
                                        on: dataio !== null && dataio.exportOpts.font_fmts.indexOf(modelData) >= 0
                                        onPicked: settingsRoot.setExportOpt("font_fmts", settingsRoot.toggleFmt(dataio.exportOpts.font_fmts, modelData))
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "export"
                            label: qsTr("Color code lists")
                            desc: qsTr("Ship HEX · HSL · RGB · CMYK codes alongside palette exports.")
                            keys: "color codes hex hsl rgb cmyk list text csv markdown palette export values"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            Flow {
                                spacing: 6
                                Repeater {
                                    model: ["txt", "csv", "md"]
                                    Chip {
                                        required property var modelData
                                        label: modelData
                                        on: dataio !== null && dataio.exportOpts.color_codes === modelData
                                        onPicked: settingsRoot.setExportOpt("color_codes", modelData)
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "export"
                            label: qsTr("Snippet format")
                            desc: qsTr("Bundle round-trips into Fengrid; the others feed editors.")
                            keys: "snippets export vscode masscode bundle json code files format"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            Flow {
                                spacing: 6
                                Repeater {
                                    model: ["bundle", "vscode", "masscode", "files"]
                                    Chip {
                                        required property var modelData
                                        label: modelData
                                        on: dataio !== null && dataio.exportOpts.snippet_kind === modelData
                                        onPicked: settingsRoot.setExportOpt("snippet_kind", modelData)
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "export"
                            label: qsTr("Library bundle")
                            desc: qsTr("Portable zip of every asset + tags, collections and project membership — importing rebuilds all of it.")
                            keys: "bundle library collection project export import portable archive round trip json manifest"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                SettingsButton {
                                    text: qsTr("Export bundle…")
                                    enabled: dataio !== null && !dataio.jobRunning
                                    onClicked: exportDestLoader.open()
                                }
                                SettingsButton {
                                    text: qsTr("Import bundle…")
                                    enabled: dataio !== null && !dataio.jobRunning
                                    onClicked: bundleImportLoader.open()
                                }
                            }
                        }

                        SettingRow {
                            section: "export"
                            label: qsTr("Last export folder")
                            desc: qsTr("Where exports land by default.")
                            keys: "export folder destination output path directory last"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            Text {
                                text: library !== null && library.lastExportDir !== "" ? library.lastExportDir : qsTr("—")
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.textMuted
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true
                            }
                        }

                        Loader {
                            id: exportDestLoader
                            active: false
                            property int openStamp: 0
                            sourceComponent: FolderDialog {
                                id: exportDestDialog
                                title: qsTr("Export library bundle to…")
                                currentFolder: settingsRoot.lastDialogUrl()
                                onAccepted: {
                                    settingsRoot.dialogEvent("exportDest", "resolved-accepted", Date.now() - exportDestLoader.openStamp);
                                    dataio.exportBundle("library", settingsRoot.url2path(selectedFolder), true);
                                    settingsRoot.rememberDialogDir(exportDestDialog.currentFolder);
                                    exportDestLoader.active = false;
                                }
                                onRejected: {
                                    settingsRoot.dialogEvent("exportDest", "resolved-rejected", Date.now() - exportDestLoader.openStamp);
                                    settingsRoot.rememberDialogDir(exportDestDialog.currentFolder);
                                    exportDestLoader.active = false;
                                }
                            }
                            // #81 dead-attempt recycle guard +
                            // click/resolve telemetry — see zipDialogLoader
                            // for the full rationale (same class).
                            onLoaded: item.open()
                            function open() {
                                settingsRoot.dialogEvent("exportDest", active ? "retry-click" : "click", 0);
                                if (active)
                                    active = false;
                                openStamp = Date.now();
                                active = true;
                            }
                        }
                        Loader {
                            id: bundleImportLoader
                            active: false
                            property int openStamp: 0
                            sourceComponent: FileDialog {
                                id: bundleImportDialog
                                title: qsTr("Import fengrid bundle")
                                currentFolder: settingsRoot.lastDialogUrl()
                                fileMode: FileDialog.OpenFile
                                nameFilters: [qsTr("Fengrid bundles (*.zip)")]
                                onAccepted: {
                                    settingsRoot.dialogEvent("bundleImport", "resolved-accepted", Date.now() - bundleImportLoader.openStamp);
                                    dataio.importBundle(settingsRoot.url2path(selectedFile), "copy");
                                    settingsRoot.rememberDialogDir(bundleImportDialog.currentFolder);
                                    bundleImportLoader.active = false;
                                }
                                onRejected: {
                                    settingsRoot.dialogEvent("bundleImport", "resolved-rejected", Date.now() - bundleImportLoader.openStamp);
                                    settingsRoot.rememberDialogDir(bundleImportDialog.currentFolder);
                                    bundleImportLoader.active = false;
                                }
                            }
                            // #81 dead-attempt recycle guard +
                            // click/resolve telemetry — see zipDialogLoader
                            // for the full rationale (same class).
                            onLoaded: item.open()
                            function open() {
                                settingsRoot.dialogEvent("bundleImport", active ? "retry-click" : "click", 0);
                                if (active)
                                    active = false;
                                openStamp = Date.now();
                                active = true;
                            }
                        }
                    }

                    // ──────────────────────────────────────── backup
                    SettingsSection {
                        section: "backup"
                        title: qsTr("Backup & Restore")

                        SettingRow {
                            section: "backup"
                            label: qsTr("Back up now")
                            desc: qsTr("One .tar.gz package: manifest (versions, settings, preferences, config, environment, logs), full database copies, and restore.sh / restore.ps1 scripts pinned to this release tag.")
                            keys: "backup save snapshot copy archive safety dump"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            SettingsButton {
                                text: qsTr("Back up…")
                                enabled: dataio !== null && !dataio.jobRunning
                                onClicked: dataio.backupNow("")
                            }
                        }

                        SettingRow {
                            section: "backup"
                            label: qsTr("Automatic backup on quit")
                            desc: qsTr("Takes one more snapshot when Fengrid closes (skipped if a job is mid-flight).")
                            keys: "auto backup quit exit automatic schedule safety"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            FormCheck {
                                checkLabel: qsTr("Back Up When the App Closes")
                                checked: dataio !== null && dataio.autoBackup
                                onToggled: dataio.setAutoBackup(checked)
                            }
                        }

                        SettingRow {
                            section: "backup"
                            label: qsTr("Restore")
                            desc: qsTr("In-app restore replaces the live database and restarts (current kept as .pre-restore). The package's restore.sh/restore.ps1 rebuild a machine from scratch — they refuse to run where Fengrid is active and verify checksums.")
                            keys: "restore recover rollback import backup undo replace recovery"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ColumnLayout {
                                spacing: 6
                                Layout.fillWidth: true
                                Repeater {
                                    model: settingsRoot.backupRows
                                    RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: 8
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 0
                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.name
                                                font.family: theme.monoFont
                                                font.pixelSize: 10
                                                color: theme.tokens.text
                                                elide: Text.ElideMiddle
                                            }
                                            Text {
                                                text: (modelData.bytes / 1048576).toFixed(1) + " MB" + (modelData.created ? " · " + modelData.created : "")
                                                font.family: theme.monoFont
                                                font.pixelSize: 9
                                                color: theme.tokens.textMuted
                                            }
                                        }
                                        Item {
                                            Layout.fillWidth: true
                                        }
                                        SettingsButton {
                                            text: qsTr("Restore…")
                                            onClicked: {
                                                settingsRoot.pendingRestore = modelData.path;
                                                restoreConfirm.open();
                                            }
                                        }
                                        SettingsButton {
                                            text: qsTr("Remove")
                                            onClicked: dataio.deleteBackup(modelData.path)
                                        }
                                    }
                                }
                                Text {
                                    visible: settingsRoot.backupRows.length === 0
                                    text: qsTr("No backups yet.")
                                    font.family: theme.uiFont
                                    font.pixelSize: 11
                                    color: theme.tokens.textMuted
                                }
                            }
                        }

                        Dialog {
                            id: restoreConfirm
                            parent: Overlay.overlay
                            anchors.centerIn: parent
                            width: 340
                            modal: true
                            title: qsTr("Restore backup?")
                            onAccepted: dataio.restoreBackup(settingsRoot.pendingRestore)
                            Text {
                                width: parent.width
                                wrapMode: Text.Wrap
                                font.family: theme.uiFont
                                font.pixelSize: 12
                                color: theme.tokens.text
                                text: qsTr("This replaces the current database and restarts Fengrid. Your present database is saved alongside as .pre-restore.")
                            }
                            // themed footer (Ok|Cancel's Basic footer sits
                            // flush against the dialog edge)
                            footer: FgDialogFooter {
                                acceptLabel: qsTr("Restore")
                                onCancelClicked: restoreConfirm.reject()
                                onAcceptClicked: restoreConfirm.accept()
                            }
                        }
                    }

                    // ───────────────────────────────── source control
                    SettingsSection {
                        section: "sc"
                        title: qsTr("Source control")

                        SettingRow {
                            section: "sc"
                            label: qsTr("Git availability")
                            desc: qsTr("Revision control for Projects and Libraries — one repository per object, default branch fengrid-main.")
                            keys: "git source control repository lfs version control project library"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                Layout.fillWidth: true
                                Text {
                                    Layout.fillWidth: true
                                    text: sc !== null && sc.gitAvailable() ? (sc.lfsAvailable() ? qsTr("Git + Git-LFS Detected") : qsTr("Git Detected (Git-LFS Not Found — Large Files Commit Directly)")) : qsTr("Git Not Installed — Install It to Enable Version Control")
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: theme.tokens.textMuted
                                }
                            }
                        }

                        SettingRow {
                            section: "sc"
                            label: qsTr("Forge access token")
                            desc: qsTr("Personal access token for GitHub / Codeberg / Forgejo / Gitea remotes. Stored locally, never committed.")
                            keys: "token github codeberg forgejo gitea remote push access"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                Layout.fillWidth: true
                                TextField {
                                    id: scTokenField
                                    Layout.fillWidth: true
                                    echoMode: TextInput.Password
                                    placeholderText: qsTr("GHP_… / Token")
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                }
                            }
                        }

                        SettingRow {
                            section: "sc"
                            label: qsTr("Maintain repositories")
                            desc: qsTr("Sweep every Project/Library repo: report uncommitted changes, drop merged dangling branches (stale ones force-dropped), run git gc.")
                            keys: "maintenance cleanup gc prune branches stale"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                FgButton {
                                    text: qsTr("Run maintenance")
                                    onClicked: sc !== null && sc.maintenance_all()
                                }
                            }
                        }
                    }

                    // ─────────────────────────────────────── database
                    SettingsSection {
                        section: "database"
                        title: qsTr("Database")

                        SettingRow {
                            section: "database"
                            label: qsTr("Statistics")
                            desc: qsTr("Live size and row counts of the active SQLite database.")
                            keys: "database stats size rows tables sqlite wal statistics space"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 10
                                Layout.fillWidth: true
                                Text {
                                    Layout.fillWidth: true
                                    text: dataio !== null && dataio.stats.bytes !== undefined ? ((dataio.stats.bytes / 1048576).toFixed(1) + " MB" + (dataio.stats.wal_bytes ? " · WAL " + (dataio.stats.wal_bytes / 1024).toFixed(0) + " KB" : "") + " · " + dataio.stats.tables.length + " tables") : qsTr("—")
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: theme.tokens.textMuted
                                    elide: Text.ElideRight
                                }
                                SettingsButton {
                                    text: qsTr("Refresh")
                                    onClicked: dataio.refreshStats()
                                }
                            }
                        }

                        SettingRow {
                            section: "database"
                            label: qsTr("Integrity check")
                            desc: qsTr("PRAGMA quick_check — catches corruption early.")
                            keys: "integrity check quick_check verify repair corrupt health"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            SettingsButton {
                                text: qsTr("Run check")
                                enabled: dataio !== null && !dataio.jobRunning
                                onClicked: dataio.adminRun("check")
                            }
                        }

                        SettingRow {
                            section: "database"
                            label: qsTr("Maintenance")
                            desc: qsTr("VACUUM compacts, checkpoint folds the WAL back in, optimize updates planner statistics.")
                            keys: "vacuum checkpoint wal compact optimize maintain pragma defragment"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                SettingsButton {
                                    text: qsTr("VACUUM")
                                    enabled: dataio !== null && !dataio.jobRunning
                                    onClicked: dataio.adminRun("vacuum")
                                }
                                SettingsButton {
                                    text: qsTr("Checkpoint WAL")
                                    enabled: dataio !== null && !dataio.jobRunning
                                    onClicked: dataio.adminRun("checkpoint")
                                }
                                SettingsButton {
                                    text: qsTr("Optimize")
                                    enabled: dataio !== null && !dataio.jobRunning
                                    onClicked: dataio.adminRun("optimize")
                                }
                            }
                        }

                        SettingRow {
                            section: "database"
                            label: qsTr("Search index")
                            desc: qsTr("Rebuild the FTS5 index if search results ever look wrong (instant — it is external-content).")
                            keys: "fts search index rebuild fts5 fulltext reindex"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            SettingsButton {
                                text: qsTr("Rebuild search index")
                                enabled: dataio !== null && !dataio.jobRunning
                                onClicked: dataio.adminRun("rebuild_fts")
                            }
                        }

                        SettingRow {
                            section: "database"
                            label: qsTr("Repair orphaned rows")
                            desc: qsTr("Removes tags, field values, links and project references pointing at deleted items.")
                            keys: "repair orphan cleanup sweep dangling rows garbage maintenance"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            SettingsButton {
                                text: qsTr("Sweep orphans")
                                enabled: dataio !== null && !dataio.jobRunning
                                onClicked: dataio.adminRun("sweep")
                            }
                        }

                        SettingRow {
                            section: "database"
                            label: qsTr("Last result")
                            desc: qsTr("Outcome of the most recent database operation.")
                            keys: "result log output last operation status"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            Text {
                                Layout.fillWidth: true
                                text: settingsRoot.adminResult !== "" ? settingsRoot.adminResult : qsTr("—")
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.textMuted
                                wrapMode: Text.Wrap
                            }
                        }
                    }

                    // ────────────────────────────── editor
                    SettingsSection {
                        section: "editor"
                        title: qsTr("Editor")

                        SettingRow {
                            section: "editor"
                            label: qsTr("Keymap")
                            desc: qsTr("Editor keybindings for the Code pane — applies to all three tabs.")
                            keys: "keymap keys keyboard emacs vim vscode readline bindings editor"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ComboBox {
                                id: keymapRow
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 30
                                Layout.alignment: Qt.AlignVCenter
                                model: [qsTr("VS Code"), qsTr("Emacs"), qsTr("Vim"), qsTr("Readline")]
                                Component.onCompleted: currentIndex = code === null ? 0 : ({
                                        "vscode": 0,
                                        "emacs": 1,
                                        "vim": 2,
                                        "readline": 3
                                    }[code.keymap] || 0)
                                onActivated: function (idx) {
                                    code !== null && code.set_keymap(["vscode", "emacs", "vim", "readline"][idx]);
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: theme.tokens.surface2
                                    border.color: theme.tokens.border
                                }
                                contentItem: Text {
                                    text: keymapRow.displayText
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: theme.tokens.text
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 8
                                }
                            }
                        }
                    }

                    // ────────────────────────────── colors
                    SettingsSection {
                        section: "colors"
                        title: qsTr("Colors")

                        SettingRow {
                            section: "colors"
                            label: qsTr("Palette generation rule")
                            desc: qsTr("Default harmony rule when the generator builds a palette.")
                            keys: "palette color generation rule harmony analogous complementary triadic monochrome random pleasing"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ComboBox {
                                id: ruleRow
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 30
                                Layout.alignment: Qt.AlignVCenter
                                model: [qsTr("Pleasing mix"), qsTr("Analogous"), qsTr("Complementary"), qsTr("Triadic"), qsTr("Monochrome"), qsTr("Random")]
                                function syncIndex() {
                                    var rules = ["pleasing", "analogous", "complementary", "triadic", "monochrome", "random"];
                                    currentIndex = colors === null ? 0 : Math.max(0, rules.indexOf(colors.rule));
                                }
                                Component.onCompleted: syncIndex()
                                onActivated: function (idx) {
                                    var rules = ["pleasing", "analogous", "complementary", "triadic", "monochrome", "random"];
                                    colors !== null && colors.set_rule(rules[idx]);
                                }
                                Connections {
                                    target: colors
                                    function onRuleChanged() {
                                        ruleRow.syncIndex();
                                    }
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: theme.tokens.surface2
                                    border.color: theme.tokens.border
                                }
                                contentItem: Text {
                                    text: ruleRow.displayText
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: theme.tokens.text
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 8
                                }
                            }
                        }
                    }

                    // ────────────────────────────── updates
                    SettingsSection {
                        section: "updates"
                        title: qsTr("Updates")

                        SettingRow {
                            section: "updates"
                            label: qsTr("Check for updates at startup")
                            desc: qsTr("Quietly probes the releases page a few seconds after launch. Applies from the next start.")
                            keys: "update release check startup probe github version auto"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            FormCheck {
                                Layout.alignment: Qt.AlignVCenter
                                checkLabel: ""
                                checked: prefs !== null && prefs.updateCheck
                                onToggled: prefs !== null && prefs.set_update_check(checked)
                            }
                        }

                        SettingRow {
                            section: "updates"
                            label: qsTr("Release status")
                            desc: updater === null ? "" : updater.checking ? qsTr("Checking the releases page…") : updater.updateAvailable ? qsTr("Update available: %1").arg(updater.latestVersion) : qsTr("Fengrid %1 — No Newer Release Seen.").arg(appVersion)
                            keys: "release status version update check now open"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                Layout.alignment: Qt.AlignVCenter
                                SettingsButton {
                                    text: qsTr("Check now")
                                    enabled: updater !== null && !updater.checking
                                    onClicked: updater.check()
                                }
                                SettingsButton {
                                    text: qsTr("Open releases page")
                                    visible: updater !== null && updater.updateAvailable
                                    onClicked: Qt.openUrlExternally(updater.releasesUrl)
                                }
                            }
                        }
                    }

                    // ────────────────────────────── about
                    SettingsSection {
                        section: "about"
                        title: qsTr("About")

                        SettingRow {
                            section: "about"
                            label: qsTr("Fengrid")
                            desc: qsTr("Version %1 — MIT licensed, Native IT (S. Davis). The UI asset explorer.").arg(appVersion)
                            keys: "about version license credit native it help"
                            rowMatches: settingsRoot.matches(section, label, keys)
                        }
                        // build provenance (#43): hidden when the binary
                        // carries no stamp and git metadata is absent
                        SettingRow {
                            section: "about"
                            visible: appCommit !== ""
                            label: qsTr("Build commit")
                            desc: appCommit
                            keys: "commit build hash git revision sha about version"
                            rowMatches: settingsRoot.matches(section, label, keys)
                        }
                        SettingRow {
                            section: "about"
                            label: qsTr("Library database")
                            desc: prefs !== null ? prefs.dbPath : ""
                            keys: "database data file path db library sqlite location"
                            rowMatches: settingsRoot.matches(section, label, keys)
                        }
                        SettingRow {
                            section: "about"
                            label: qsTr("Releases")
                            desc: updater !== null ? updater.releasesUrl : ""
                            keys: "releases github page changelog download source"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            SettingsButton {
                                Layout.alignment: Qt.AlignVCenter
                                text: qsTr("Open releases page")
                                enabled: updater !== null
                                onClicked: Qt.openUrlExternally(updater.releasesUrl)
                            }
                        }
                    }

                    Item {
                        Layout.preferredHeight: 24
                    }   // scroll tail
                }
                // Basic-style default handles render invisibly on the
                // card — style it token-driven so the overflow below the
                // fold has a visible affordance
                ScrollBar.vertical: ScrollBar {
                    id: bodyBar
                    policy: ScrollBar.AsNeeded
                    hoverEnabled: true
                    width: 10
                    background: Rectangle {
                        implicitWidth: 10
                        color: "transparent"
                    }
                    contentItem: Rectangle {
                        implicitWidth: 6
                        radius: 3
                        color: bodyBar.hovered ? theme.tokens.accent : theme.tokens.textMuted
                    }
                }
            }
        }
    }

    // lazy: the shared folder picker — portal-free until opened
    Loader {
        id: folderDialogLoader
        active: false
        property int openStamp: 0
        property string kind: "folder"
        sourceComponent: FolderDialog {
            id: folderDialog
            onAccepted: {
                settingsRoot.dialogEvent("sources", "resolved-accepted", Date.now() - folderDialogLoader.openStamp);
                var p = Icons.toLocalPath(selectedFolder);
                library.add_folder(p, folderDialogLoader.kind);
                if (folderDialogLoader.kind === "fontroot")
                    fonts.rescan();
                settingsRoot.rememberDialogDir(folderDialog.currentFolder);
                folderDialogLoader.active = false;
            }
            onRejected: {
                settingsRoot.dialogEvent("sources", "resolved-rejected", Date.now() - folderDialogLoader.openStamp);
                settingsRoot.rememberDialogDir(folderDialog.currentFolder);
                folderDialogLoader.active = false;
            }
        }
        // #81 dead-attempt recycle guard: a dialog that never maps
        // leaves the Loader active and every later click no-ops —
        // rationale on zipDialogLoader in the settings sections.
        function open(kind_) {
            kind = kind_ || "folder";
            settingsRoot.dialogEvent("sources", active ? "retry-click" : "click", 0);
            if (active)
                active = false;
            openStamp = Date.now();
            active = true;
            item.open();
        }
    }

    // #55: close X in the screen's top-right corner
    IconButton {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 10
        z: 2
        icon_name: "x"
        ToolTip.text: qsTr("Close settings (Esc)")
        onClicked: settingsRoot.closed()
    }

    StorageDialog {
        id: storageDialog
    }

    Shortcut {
        sequence: "Escape"
        // palette over settings / armed shortcut capture own Escape
        enabled: !Shell.paletteOpen && !Shell.capturing
        onActivated: settingsRoot.closed()
    }
}
