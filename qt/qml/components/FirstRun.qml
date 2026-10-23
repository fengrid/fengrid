import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

// One-time setup screen — shown while first_run_done is unset (the
// shell suppresses it in --screenshot runs; QA forces it with
// --dialog firstRun). Single screen: system paths, asset folders,
// look & feel and behavior. Every control writes the same settings
// keys the Settings surface reads, so finishing only persists the
// flag — and the footer shows the ingest that runs concurrently
// (folders added here are indexed by the queued rescan).
Rectangle {
    id: setupRoot
    color: Qt.rgba(0, 0, 0, 0.45)
    signal finished()

    // modal: absorb every click/hover so nothing behind reacts
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
    }

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
        var srcs = library.sources
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
        return true
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

    Rectangle {
        id: card
        width: Math.min(setupRoot.width - 60, 880)
        height: Math.min(setupRoot.height - 60, 700)
        anchors.centerIn: parent
        radius: 12
        color: theme.tokens.surface
        border.color: theme.tokens.border

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // ── header ──
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 26
                Layout.leftMargin: 30
                Layout.rightMargin: 30
                spacing: 8
                RowLayout {
                    spacing: 10
                    // glint-quad mini mark (same glyph as the header)
                    Item {
                        width: 22
                        height: 22
                        Layout.alignment: Qt.AlignVCenter
                        Grid {
                            anchors.fill: parent
                            columns: 2
                            columnSpacing: 2
                            rowSpacing: 2
                            Repeater {
                                model: 4
                                Rectangle {
                                    width: 9
                                    height: 9
                                    radius: 2
                                    color: index === 3
                                           ? theme.tokens.litPane : "transparent"
                                    border.color: index === 3 ? "transparent"
                                                              : theme.tokens.accent
                                    border.width: 1.6
                                }
                            }
                        }
                    }
                    Text {
                        text: qsTr("FENGRID SETUP")
                        font.family: theme.headingFont
                        font.pixelSize: 13
                        font.letterSpacing: 2.4
                        color: theme.tokens.accent
                    }
                }
                Text {
                    text: qsTr("Welcome — let's point Fengrid at your assets")
                    font.family: theme.headingFont
                    font.pixelSize: 21
                    color: theme.tokens.text
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
                Text {
                    text: qsTr("One screen, everything saves as you go: system paths and folders feed the initial scan running right now, then look and behavior. Change any of it later from the main menu → Settings…")
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: theme.tokens.textMuted
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
            }

            // ── body ──
            Flickable {
                id: setupFlick
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.topMargin: 6
                contentHeight: bodyCol.implicitHeight + 24
                clip: true
                ColumnLayout {
                    id: bodyCol
                    x: 30
                    width: setupFlick.width - 60
                    spacing: 0

                    // ── system paths ──
                    SettingsSection {
                        section: "paths"
                        filterRows: false
                        title: qsTr("1 · System paths")
                        Text {
                            text: qsTr("Detected platform locations — uncheck anything you don't want indexed.")
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.textMuted
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                        }
                        Repeater {
                            model: {
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
                                spacing: 14
                                FormCheck {
                                    Layout.preferredWidth: 170
                                    checkLabel: setupRoot.baseName(modelData)
                                    checked: setupRoot.pathEnabled(modelData)
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
                                spacing: 14
                                FormCheck {
                                    Layout.preferredWidth: 170
                                    checkLabel: setupRoot.baseName(modelData)
                                    checked: setupRoot.pathEnabled(modelData)
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
                    }

                    // ── asset folders ──
                    SettingsSection {
                        section: "folders"
                        filterRows: false
                        title: qsTr("2 · Asset folders")
                        Text {
                            text: qsTr("Your own icon and font folders get indexed alongside the system paths.")
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.textMuted
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                        }
                        Repeater {
                            model: setupRoot.customFolders
                            delegate: Rectangle {
                                id: folderRow
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                Layout.preferredHeight: 46
                                radius: 6
                                color: theme.tokens.bg
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
                                        onToggled: {
                                            library.set_path_enabled(
                                                folderRow.modelData.path,
                                                folderRow.modelData.kind,
                                                checked)
                                            setupRoot.rescanKind(
                                                folderRow.modelData.kind)
                                        }
                                    }
                                    IconButton {
                                        icon_name: "trash"
                                        ToolTip.text: qsTr("Remove folder")
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
                    }

                    // ── look & feel ──
                    SettingsSection {
                        section: "look"
                        filterRows: false
                        title: qsTr("3 · Look & feel")

                        SettingRow {
                            section: "look"
                            label: qsTr("Theme")
                            desc: qsTr("Dark or light color scheme.")
                            keys: "theme dark light mode appearance"
                            RowLayout {
                                spacing: 8
                                Layout.alignment: Qt.AlignVCenter
                                Button {
                                    id: darkBtn
                                    Layout.preferredHeight: 30
                                    Layout.preferredWidth: 90
                                    text: qsTr("Dark")
                                    checkable: false
                                    onClicked: theme !== null
                                               && theme.set_theme("dark")
                                    background: Rectangle {
                                        radius: 6
                                        color: theme !== null && theme.isDark
                                               ? theme.tokens.accent
                                               : theme.tokens.bg
                                        border.color: theme.tokens.border
                                    }
                                    contentItem: Text {
                                        text: darkBtn.text
                                        font.family: theme.uiFont
                                        font.pixelSize: 11
                                        color: theme !== null && theme.isDark
                                              ? theme.tokens.bg
                                              : theme.tokens.textMuted
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }
                                Button {
                                    id: lightBtn
                                    Layout.preferredHeight: 30
                                    Layout.preferredWidth: 90
                                    text: qsTr("Light")
                                    onClicked: theme !== null
                                               && theme.set_theme("light")
                                    background: Rectangle {
                                        radius: 6
                                        color: theme !== null && !theme.isDark
                                               ? theme.tokens.accent
                                               : theme.tokens.bg
                                        border.color: theme.tokens.border
                                    }
                                    contentItem: Text {
                                        text: lightBtn.text
                                        font.family: theme.uiFont
                                        font.pixelSize: 11
                                        color: theme !== null && !theme.isDark
                                              ? theme.tokens.bg
                                              : theme.tokens.textMuted
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }
                            }
                        }

                        SettingRow {
                            section: "look"
                            label: qsTr("Icon grid size")
                            desc: qsTr("Default tile size on the Icons pane.")
                            keys: "icon size grid tile px slider zoom"
                            RowLayout {
                                spacing: 10
                                Layout.alignment: Qt.AlignVCenter
                                Slider {
                                    id: sizeRow
                                    from: 16
                                    to: 256
                                    stepSize: 16
                                    Layout.preferredWidth: 190
                                    value: prefs !== null ? prefs.iconSize : 32
                                    onMoved: prefs !== null
                                             && prefs.set_icon_size(
                                                 Math.round(value))
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

                        SettingRow {
                            section: "look"
                            label: qsTr("Startup pane")
                            desc: qsTr("Which pane opens when Fengrid starts.")
                            keys: "startup pane launch default open"
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
                                    color: theme.tokens.bg
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
                    }

                    // ── behavior ──
                    SettingsSection {
                        section: "behavior"
                        filterRows: false
                        title: qsTr("4 · Behavior")

                        SettingRow {
                            section: "behavior"
                            label: qsTr("Slash menu hotkey")
                            desc: qsTr("Opens the slash menu from anywhere — search assets and snippets, run commands. Default Alt + /.")
                            keys: "slash menu palette hotkey shortcut key sequence spotlight alfred vscode search jump"
                            RowLayout {
                                spacing: 8
                                Layout.alignment: Qt.AlignVCenter
                                ShortcutCapture {
                                    Layout.preferredWidth: 170
                                    Layout.preferredHeight: 30
                                    onSequenceEdited: function (seq) {
                                        prefs !== null
                                            && prefs.set_command_shortcut(seq)
                                    }
                                }
                                SettingsButton {
                                    Layout.alignment: Qt.AlignVCenter
                                    text: qsTr("Reset")
                                    onClicked: prefs !== null
                                               && prefs.set_command_shortcut(
                                                   "Alt+/")
                                }
                            }
                        }

                        SettingRow {
                            section: "behavior"
                            label: qsTr("Search mode")
                            desc: qsTr("Default matching style of the asset search box.")
                            keys: "search smart fuzzy regex content mode"
                            ComboBox {
                                id: modeRow
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 30
                                Layout.alignment: Qt.AlignVCenter
                                model: [qsTr("Smart"), qsTr("Fuzzy"),
                                        qsTr("Regex"), qsTr("Content")]
                                Component.onCompleted:
                                    currentIndex = ["smart", "fuzzy", "regex",
                                                    "content"].indexOf(
                                        library !== null ? library.searchMode
                                                         : "smart")
                                onActivated: function (idx) {
                                    library !== null && library.set_search_mode(
                                        ["smart", "fuzzy", "regex", "content"][idx])
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: theme.tokens.bg
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
                            section: "behavior"
                            label: qsTr("Editor keymap")
                            desc: qsTr("Keybindings for the Code pane.")
                            keys: "keymap emacs vim vscode readline keys editor"
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
                                    color: theme.tokens.bg
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

                        SettingRow {
                            section: "behavior"
                            label: qsTr("Palette rule")
                            desc: qsTr("Default harmony rule of the color generator.")
                            keys: "palette color rule generation harmony"
                            ComboBox {
                                id: ruleRow
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 30
                                Layout.alignment: Qt.AlignVCenter
                                model: [qsTr("Pleasing mix"), qsTr("Analogous"),
                                        qsTr("Complementary"), qsTr("Triadic"),
                                        qsTr("Monochrome"), qsTr("Random")]
                                Component.onCompleted: {
                                    var rules = ["pleasing", "analogous",
                                                 "complementary", "triadic",
                                                 "monochrome", "random"]
                                    currentIndex = colors === null ? 0
                                        : Math.max(0, rules.indexOf(colors.rule))
                                }
                                onActivated: function (idx) {
                                    var rules = ["pleasing", "analogous",
                                                 "complementary", "triadic",
                                                 "monochrome", "random"]
                                    colors !== null
                                        && colors.set_rule(rules[idx])
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: theme.tokens.bg
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

                        SettingRow {
                            section: "behavior"
                            label: qsTr("Update check")
                            desc: qsTr("Probe the releases page at startup (you can turn this off later in Settings).")
                            keys: "update check release startup probe version"
                            FormCheck {
                                Layout.alignment: Qt.AlignVCenter
                                checkLabel: ""
                                checked: prefs !== null && prefs.updateCheck
                                onToggled: prefs !== null
                                           && prefs.set_update_check(checked)
                            }
                        }
                    }

                    Item { Layout.preferredHeight: 20 }
                }
                // Basic-style default handles render invisibly on the
                // card — style it token-driven so sections below the
                // fold have a visible affordance
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

            // ── footer: concurrent ingest + finish ──
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: theme.tokens.border
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: 24
                spacing: 12
                BusyIndicator {
                    visible: library !== null && fonts !== null
                             && (library.scanning || fonts.scanning)
                    running: visible
                    Layout.preferredWidth: 18
                    Layout.preferredHeight: 18
                }
                Text {
                    Layout.fillWidth: true
                    text: library === null || fonts === null ? ""
                          : (library.scanning || fonts.scanning)
                            ? qsTr("Indexing in the background — icons %1 · fonts %2 · add folders whenever you like")
                                  .arg(library.scanCount)
                                  .arg(fonts.scanCount)
                            : qsTr("%1 assets ready · %2 font files indexed")
                                  .arg(library.totalAssets)
                                  .arg(fonts.totalFonts)
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                    elide: Text.ElideRight
                }
                SettingsButton {
                    text: qsTr("Get started")
                    onClicked: setupRoot.finished()
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

    // setup must be dismissable, but never traps: Escape = finish (the
    // flag persists only here, and defaults are valid either way)
    Shortcut {
        sequence: "Escape"
        // shortcut capture inside this screen owns Escape while armed
        enabled: !Shell.capturing
        onActivated: setupRoot.finished()
    }
}