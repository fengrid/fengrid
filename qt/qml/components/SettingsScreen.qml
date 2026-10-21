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
    signal closed()

    // absorb clicks/hover so the rail and panes beneath never react
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
    }

    function matches(section, label, keys) {
        if (category !== "all" && section !== category)
            return false
        if (query === "")
            return true
        var hay = (label + " " + keys + " " + section).toLowerCase()
        return hay.indexOf(query.toLowerCase()) >= 0
    }
    function showCategory(name) { category = name }

    // user folders = registered sources that are NOT detected system
    // paths (system icon roots / font dirs are listed separately)
    readonly property var customFolders: {
        if (library === null || prefs === null)
            return []
        var sys = {}
        var icons = prefs.systemIconPaths
        var fontsDirs = prefs.systemFontDirs
        for (var i = 0; i < icons.length; i++)
            sys[icons[i]] = true
        for (var j = 0; j < fontsDirs.length; j++)
            sys[fontsDirs[j]] = true
        var out = []
        var srcs = library.sources          // notify dep: sourcesChanged
        for (var k = 0; k < srcs.length; k++) {
            if (!sys[srcs[k].path])
                out.push(srcs[k])
        }
        return out
    }
    function pathEnabled(path) {
        if (library === null)
            return true
        var s = library.sources
        for (var i = 0; i < s.length; i++) {
            if (s[i].path === path)
                return s[i].enabled
        }
        return true          // not registered yet — defaults to on
    }
    function rescanKind(kind) {
        if (kind === "fontroot")
            fonts.rescan()
        else
            library.rescan()
    }
    function baseName(path) {
        return path.replace(/\\/g, "/").split("/").pop()
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
                spacing: 1
                Repeater {
                    model: [
                        { k: "all", t: qsTr("All settings") },
                        { k: "general", t: qsTr("General") },
                        { k: "appearance", t: qsTr("Appearance") },
                        { k: "library", t: qsTr("Library") },
                        { k: "storage", t: qsTr("Storage") },
                        { k: "editor", t: qsTr("Editor") },
                        { k: "colors", t: qsTr("Colors") },
                        { k: "updates", t: qsTr("Updates") },
                        { k: "about", t: qsTr("About") }
                    ]
                    delegate: Rectangle {
                        id: navItem
                        required property var modelData
                        width: navCol.width
                        height: 30
                        color: settingsRoot.category === modelData.k
                               ? theme.tokens.surface2 : "transparent"
                        Rectangle {      // selection bar
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3
                            height: parent.height - 12
                            radius: 1.5
                            color: settingsRoot.category === modelData.k
                                   ? theme.tokens.accent : "transparent"
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            text: navItem.modelData.t
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: settingsRoot.category === navItem.modelData.k
                                   ? theme.tokens.text : theme.tokens.textMuted
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
                    spacing: 2
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
                    border.color: queryField.activeFocus
                                  ? theme.tokens.accent : theme.tokens.border
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
                            placeholderText: qsTr("Search settings")
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
                IconButton {
                    icon_name: "x"
                    ToolTip.text: qsTr("Close settings (Esc)")
                    onClicked: settingsRoot.closed()
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
                                model: [qsTr("Smart"), qsTr("Fuzzy"),
                                        qsTr("Regex"), qsTr("Content")]
                                function syncIndex() {
                                    currentIndex = ["smart", "fuzzy", "regex",
                                                    "content"].indexOf(
                                        library !== null ? library.searchMode
                                                         : "smart")
                                }
                                Component.onCompleted: syncIndex()
                                onActivated: function (idx) {
                                    library !== null && library.set_search_mode(
                                        ["smart", "fuzzy", "regex", "content"][idx])
                                }
                                Connections {
                                    target: library
                                    function onFiltersChanged() {
                                        modeRow.syncIndex()
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
                            label: qsTr("Startup pane")
                            desc: qsTr("Which pane opens when Fengrid starts.")
                            keys: "startup pane launch start default open"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            ComboBox {
                                id: paneRow
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 30
                                Layout.alignment: Qt.AlignVCenter
                                model: [qsTr("Icons"), qsTr("Fonts"),
                                        qsTr("Colors"), qsTr("Code"),
                                        qsTr("Projects")]
                                Component.onCompleted:
                                    currentIndex = prefs !== null
                                                  ? prefs.startupPane : 0
                                onActivated: function (idx) {
                                    prefs !== null && prefs.set_startup_pane(idx)
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
                                    prefs.start_first_run()
                                    settingsRoot.closed()
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
                                    currentIndex = theme === null || theme.isDark
                                                  ? 0 : 1
                                }
                                Component.onCompleted: syncIndex()
                                onActivated: function (idx) {
                                    theme !== null && theme.set_theme(
                                        idx === 0 ? "dark" : "light")
                                }
                                Connections {
                                    target: theme
                                    function onThemeChanged() {
                                        themeRow.syncIndex()
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
                            label: qsTr("Icon size")
                            desc: qsTr("Grid tile size on the Icons pane, 16–256 px. The header slider writes the same value.")
                            keys: "icon size grid tile thumb thumbnail px slider zoom scale"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 10
                                Layout.alignment: Qt.AlignVCenter
                                Slider {
                                    id: sizeRow
                                    from: 16
                                    to: 256
                                    stepSize: 16
                                    Layout.preferredWidth: 170
                                    value: prefs !== null ? prefs.iconSize : 32
                                    // moved() = user-driven only, so the
                                    // Connections sync below can't loop;
                                    // set_icon_size dedupes per-step writes
                                    onMoved: prefs !== null
                                             && prefs.set_icon_size(
                                                 Math.round(value))
                                    Connections {
                                        target: prefs
                                        function onIconSizeChanged() {
                                            if (!sizeRow.pressed)
                                                sizeRow.value = prefs.iconSize
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
                            model: {
                                // read sources first so the model
                                // re-evaluates on every mutation — user
                                // clicks kill checked bindings, rebuilt
                                // delegates get fresh ones
                                if (library !== null)
                                    library.sources
                                return prefs !== null ? prefs.systemIconPaths
                                                      : []
                            }
                            delegate: RowLayout {
                                id: iconPathRow
                                required property string modelData
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                Layout.leftMargin: 4
                                spacing: 14
                                FormCheck {
                                    Layout.preferredWidth: 170
                                    checkLabel: settingsRoot.baseName(modelData)
                                    checked: settingsRoot.pathEnabled(modelData)
                                    onToggled: {
                                        library.set_path_enabled(modelData,
                                                                 "system",
                                                                 checked)
                                        library.rescan()
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
                            model: {
                                if (library !== null)
                                    library.sources
                                return prefs !== null ? prefs.systemFontDirs
                                                      : []
                            }
                            delegate: RowLayout {
                                id: fontPathRow
                                required property string modelData
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                Layout.leftMargin: 4
                                spacing: 14
                                FormCheck {
                                    Layout.preferredWidth: 170
                                    checkLabel: settingsRoot.baseName(modelData)
                                    checked: settingsRoot.pathEnabled(modelData)
                                    onToggled: {
                                        library.set_path_enabled(modelData,
                                                                 "fontroot",
                                                                 checked)
                                        fonts.rescan()
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
                                        Layout.preferredWidth:
                                            kindChipText.implicitWidth + 12
                                        radius: 3
                                        color: "transparent"
                                        border.color: theme.tokens.border
                                        Text {
                                            id: kindChipText
                                            anchors.centerIn: parent
                                            text: folderRow.modelData.kind
                                                  === "fontroot"
                                                  ? qsTr("FONTS")
                                                  : qsTr("ICONS")
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
                                            text: folderRow.modelData.label
                                                  || folderRow.modelData.path
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
                                        text: qsTr("%1 items").arg(
                                            folderRow.modelData.n)
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
                                        ToolTip.text: qsTr(
                                            "Include in the library")
                                        onToggled: {
                                            library.set_path_enabled(
                                                folderRow.modelData.path,
                                                folderRow.modelData.kind,
                                                checked)
                                            settingsRoot.rescanKind(
                                                folderRow.modelData.kind)
                                        }
                                    }
                                    IconButton {
                                        icon_name: "trash"
                                        ToolTip.text: qsTr(
                                            "Remove folder from library")
                                        onClicked: {
                                            library.remove_folder(
                                                folderRow.modelData.id)
                                            fonts.refresh()
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
                                    folderDialog.kind = "folder"
                                    folderDialog.open()
                                }
                            }
                            SettingsButton {
                                text: qsTr("Add font folder…")
                                onClicked: {
                                    folderDialog.kind = "fontroot"
                                    folderDialog.open()
                                }
                            }
                            Item { Layout.fillWidth: true }
                            SettingsButton {
                                text: qsTr("Re-scan icons")
                                enabled: library !== null
                                         && !library.scanning
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
                            text: library === null || fonts === null ? ""
                                  : (library.scanning || fonts.scanning)
                                    ? qsTr("Indexing… icons %1 · fonts %2")
                                          .arg(library.scanCount)
                                          .arg(fonts.scanCount)
                                    : qsTr("%1 assets indexed · %2 font files")
                                          .arg(library.totalAssets)
                                          .arg(fonts.totalFonts)
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
                                    folderDialog.kind = "folder"
                                    folderDialog.open()
                                }
                            }
                        }

                        // coming-soon callout (spec: personal cloud sync)
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.topMargin: 12
                            Layout.preferredHeight:
                                cloudCol.implicitHeight + 20
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
                                    color: theme.tokens.textMuted
                                }
                            }
                        }

                        Repeater {
                            model: storage !== null
                                   ? storage.backends.filter(function (b) {
                                         return b.key !== "local"
                                     })
                                   : []
                            delegate: RowLayout {
                                id: backendRow
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.topMargin: 14
                                spacing: 20
                                visible: settingsRoot.matches(
                                    "storage", modelData.label,
                                    "storage backend mount remote share "
                                    + modelData.key + " network cloud")
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
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
                                        color: backendRow.modelData.available
                                               ? theme.tokens.textMuted
                                               : theme.tokens.hlInk
                                    }
                                }
                                SettingsButton {
                                    Layout.alignment: Qt.AlignVCenter
                                    text: qsTr("Attach…")
                                    enabled: backendRow.modelData.available
                                    onClicked: storageDialog.openFor(
                                        backendRow.modelData.key,
                                        backendRow.modelData.label,
                                        qsTr("Example: %1 — %2")
                                            .arg(backendRow.modelData.hint)
                                            .arg(backendRow.modelData.status))
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
                                visible: settingsRoot.matches(
                                    "storage", modelData.backendLabel,
                                    "mount attached storage "
                                    + modelData.backend)
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 6
                                    spacing: 10
                                    Rectangle {
                                        Layout.preferredHeight: 16
                                        Layout.preferredWidth:
                                            mountChip.implicitWidth + 12
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
                                        text: mountRow.modelData.healthy
                                              ? qsTr("mounted")
                                              : qsTr("not mounted")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: mountRow.modelData.healthy
                                               ? theme.tokens.textMuted
                                               : theme.tokens.hlInk
                                    }
                                    SettingsButton {
                                        text: qsTr("Eject")
                                        onClicked:
                                            storage.detach(mountRow.modelData.id)
                                    }
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            Layout.topMargin: 10
                            visible: storage === null
                                     || storage.mounts.length === 0
                            text: qsTr("No network or cloud storage attached yet.")
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.textMuted
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
                                model: [qsTr("VS Code"), qsTr("Emacs"),
                                        qsTr("Vim"), qsTr("Readline")]
                                Component.onCompleted:
                                    currentIndex = code === null ? 0
                                        : ({ "vscode": 0, "emacs": 1,
                                             "vim": 2, "readline": 3 }
                                           [code.keymap] || 0)
                                onActivated: function (idx) {
                                    code !== null && code.set_keymap(
                                        ["vscode", "emacs", "vim",
                                         "readline"][idx])
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
                                model: [qsTr("Pleasing mix"), qsTr("Analogous"),
                                        qsTr("Complementary"), qsTr("Triadic"),
                                        qsTr("Monochrome"), qsTr("Random")]
                                function syncIndex() {
                                    var rules = ["pleasing", "analogous",
                                                 "complementary", "triadic",
                                                 "monochrome", "random"]
                                    currentIndex = colors === null ? 0
                                        : Math.max(0, rules.indexOf(colors.rule))
                                }
                                Component.onCompleted: syncIndex()
                                onActivated: function (idx) {
                                    var rules = ["pleasing", "analogous",
                                                 "complementary", "triadic",
                                                 "monochrome", "random"]
                                    colors !== null
                                        && colors.set_rule(rules[idx])
                                }
                                Connections {
                                    target: colors
                                    function onRuleChanged() {
                                        ruleRow.syncIndex()
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
                                onToggled: prefs !== null
                                           && prefs.set_update_check(checked)
                            }
                        }

                        SettingRow {
                            section: "updates"
                            label: qsTr("Release status")
                            desc: updater === null ? ""
                                 : updater.checking
                                   ? qsTr("Checking the releases page…")
                                   : updater.updateAvailable
                                     ? qsTr("Update available: %1")
                                           .arg(updater.latestVersion)
                                     : qsTr("fengrid %1 — no newer release seen.")
                                           .arg(appVersion)
                            keys: "release status version update check now open"
                            rowMatches: settingsRoot.matches(section, label, keys)
                            RowLayout {
                                spacing: 8
                                Layout.alignment: Qt.AlignVCenter
                                SettingsButton {
                                    text: qsTr("Check now")
                                    enabled: updater !== null
                                             && !updater.checking
                                    onClicked: updater.check()
                                }
                                SettingsButton {
                                    text: qsTr("Open releases page")
                                    visible: updater !== null
                                             && updater.updateAvailable
                                    onClicked:
                                        Qt.openUrlExternally(updater.releasesUrl)
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
                            desc: qsTr("Version %1 — MIT licensed, Native IT (S. Davis). The UI asset explorer.")
                                .arg(appVersion)
                            keys: "about version license credit native it help"
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
                                onClicked:
                                    Qt.openUrlExternally(updater.releasesUrl)
                            }
                        }
                    }

                    Item { Layout.preferredHeight: 24 }   // scroll tail
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
                        color: bodyBar.hovered ? theme.tokens.accent
                                               : theme.tokens.textMuted
                    }
                }
            }
        }
    }

    FolderDialog {
        id: folderDialog
        property string kind: "folder"
        onAccepted: {
            var p = Icons.toLocalPath(selectedFolder)
            library.add_folder(p, kind)
            if (kind === "fontroot")
                fonts.rescan()
        }
    }

    StorageDialog {
        id: storageDialog
    }

    Shortcut {
        sequence: "Escape"
        onActivated: settingsRoot.closed()
    }
}