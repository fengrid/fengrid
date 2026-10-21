import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "components"

ApplicationWindow {
    id: root
    width: 1280
    height: 800
    minimumWidth: 960
    minimumHeight: 560
    visible: true
    // the title carries the active database — switching relaunches the
    // process, so the window name always matches what's loaded
    title: dbs !== null ? qsTr("Fengrid — %1").arg(dbs.currentLabel)
                        : "Fengrid — the UI asset explorer"
    color: theme.tokens.bg
    font.family: theme.uiFont
    font.pixelSize: 13

    Component.onCompleted: {
        if (typeof startupNotice !== "undefined" && startupNotice !== "")
            toast.show(startupNotice)
    }

    property int iconSize: sizeSlider.value
    // 0 = icons, 1 = fonts, 2 = colors, 3 = code, 4 = projects (top-bar
    // pane switcher); --pane N (QA) overrides via the initialPane context
    property int pane: typeof initialPane !== "undefined" ? initialPane : 0

    // ── overlays: settings (content area) + first-run setup (modal) ──
    property bool settingsOpen: false
    // computed in __main__ (flag unset && not a screenshot run); flipped
    // afterwards by prefs.firstRunNeededChanged
    property bool setupOpen: typeof initialFirstRun !== "undefined"
                             && initialFirstRun
    property string pendingCategory: ""

    header: Rectangle {
        height: 52
        // subtle vertical depth: surface fading toward bg at the bottom,
        // with a hairline divider — reads as a floating translucent bar
        // over the content
        gradient: Gradient {
            GradientStop { position: 0; color: theme.tokens.surface }
            GradientStop { position: 0.82; color: theme.tokens.surface }
            GradientStop { position: 1; color: Qt.rgba(
                theme.tokens.surface.r, theme.tokens.surface.g,
                theme.tokens.surface.b, 0.86) }
        }
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: theme.tokens.border
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 10
            spacing: 12

            // main menu (VS Code-style hamburger) — Settings & friends
            IconButton {
                id: menuBtn
                icon_name: "menu"
                Layout.alignment: Qt.AlignVCenter
                ToolTip.text: qsTr("Main menu")
                onClicked: mainMenu.open()
            }
            Menu {
                id: mainMenu
                parent: Overlay.overlay
                width: 230
                padding: 4
                background: Rectangle {
                    radius: 8
                    color: theme.tokens.surface
                    border.color: theme.tokens.border
                }
                // recompute on every open: mapToItem creates no binding
                // dependency on the button's position, so a create-time
                // binding would go stale after the first layout pass
                onAboutToShow: {
                    var p = menuBtn.mapToItem(Overlay.overlay, 0,
                                              menuBtn.height)
                    x = p.x
                    y = p.y + 6
                }
                // ── databases: current / Quick access / Recent ──
                MenuItem {
                    enabled: false
                    font.pixelSize: 11
                    font.letterSpacing: 1.2
                    font.capitalization: Font.AllUppercase
                    text: dbs !== null
                          ? qsTr("Database — %1").arg(dbs.currentLabel)
                          : qsTr("Database")
                }
                MenuItem {
                    visible: dbs !== null && dbs.quick.length > 0
                    enabled: false
                    text: qsTr("Quick access")
                }
                Repeater {
                    model: dbs !== null ? dbs.quick : []
                    delegate: MenuItem {
                        required property var modelData
                        enabled: modelData.exists
                        text: modelData.label + (modelData.exists ? ""
                                                                  : qsTr(" (missing)"))
                        onClicked: dbs.switchTo(modelData.path)
                    }
                }
                MenuItem {
                    visible: dbs !== null && dbs.recent.length > 0
                    enabled: false
                    text: qsTr("Recent")
                }
                Repeater {
                    model: dbs !== null ? dbs.recent : []
                    delegate: MenuItem {
                        required property var modelData
                        enabled: modelData.exists
                        text: modelData.label + " · " + modelData.when
                              + (modelData.exists ? "" : qsTr(" (missing)"))
                        onClicked: dbs.switchTo(modelData.path)
                    }
                }
                MenuSeparator {
                    visible: dbs !== null && (dbs.quick.length > 0
                                              || dbs.recent.length > 0)
                }
                MenuItem {
                    visible: dbs !== null
                    text: dbs !== null && dbs.currentStarred
                          ? qsTr("Unstar current database")
                          : qsTr("Star current database")
                    onTriggered: dbs.starCurrent()
                }
                MenuItem {
                    visible: dbs !== null
                    text: qsTr("New database…")
                    onTriggered: newDbDialog.open()
                }
                MenuItem {
                    visible: dbs !== null
                    text: qsTr("Open database…")
                    onTriggered: openDbDialog.open()
                }
                MenuItem {
                    visible: dbs !== null && dbs.recent.length > 0
                    text: qsTr("Clear recent")
                    onTriggered: dbs.clearRecent()
                }
                MenuSeparator { visible: dbs !== null }

                MenuItem {
                    text: qsTr("Settings…")
                    height: 28
                    onTriggered: root.openSettings()
                }
                MenuItem {
                    text: qsTr("Check for updates")
                    height: 28
                    enabled: updater !== null
                    onTriggered: {
                        updater.check()
                        toast.show(qsTr("Checking for updates…"))
                    }
                }
                MenuSeparator {}
                MenuItem {
                    text: qsTr("About Fengrid")
                    height: 28
                    onTriggered: root.openSettings("about")
                }
            }

            // glint-quad mini mark (branding/assets/fengrid-mark.svg shape)
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
                            color: index === 3 ? theme.tokens.litPane : "transparent"
                            border.color: index === 3 ? "transparent" : theme.tokens.accent
                            border.width: 1.6
                        }
                    }
                }
            }

            Text {
                text: qsTr("Fengrid")
                font.family: theme.headingFont
                font.pixelSize: 20
                font.letterSpacing: 1.6
                font.capitalization: Font.AllUppercase
                color: theme.tokens.text
            }

            Rectangle {
                width: 1
                height: 22
                color: theme.tokens.border
                Layout.alignment: Qt.AlignVCenter
            }

            // search mode: smart (FTS) | fuzzy | regex | content
            ComboBox {
                id: searchModeBox
                Layout.preferredHeight: 32
                Layout.preferredWidth: 104
                model: [qsTr("Smart"), qsTr("Fuzzy"), qsTr("Regex"),
                        qsTr("Content")]
                ToolTip.visible: hovered
                ToolTip.text: qsTr(
                    "Smart: fast indexed prefix search · Fuzzy: close matches"
                    + " rank first · Regex: regular expressions over names"
                    + " and paths · Content: search inside snippets and text"
                    + " files (bounded I/O)")
                onActivated: function (idx) {
                    library !== null && library.set_search_mode(
                        ["smart", "fuzzy", "regex", "content"][idx])
                }
                // the persisted mode can also change from Settings —
                // re-sync on every filters change (user picks above kill
                // any currentIndex binding)
                function syncIndex() {
                    currentIndex = ["smart", "fuzzy", "regex", "content"]
                        .indexOf(library !== null ? library.searchMode
                                                  : "smart")
                }
                Component.onCompleted: syncIndex()
                Connections {
                    target: library
                    function onFiltersChanged() { searchModeBox.syncIndex() }
                }
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
                contentItem: Text {
                    text: searchModeBox.displayText
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8
                }
            }

            Rectangle {
                id: searchBox
                // flexible: fills the space the pane switcher leaves, so the
                // right-side controls never clip at minimum window width
                Layout.fillWidth: true
                Layout.minimumWidth: 140
                Layout.maximumWidth: 320
                Layout.preferredHeight: 32
                radius: 6
                color: theme.tokens.surface2
                border.color: searchField.activeFocus ? theme.tokens.accent
                                                      : theme.tokens.border

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 8
                    spacing: 6

                    IconImage { name: "search"; px: 15; tint: theme.tokens.textMuted }

                    TextField {
                        id: searchField
                        Layout.fillWidth: true
                        placeholderText: qsTr("search assets  ( / )")
                        color: theme.tokens.text
                        placeholderTextColor: theme.tokens.textMuted
                        background: null
                        selectByMouse: true
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        onTextChanged: searchDebounce.restart()
                    }

                    IconImage {
                        name: "x"
                        px: 13
                        tint: theme.tokens.textMuted
                        visible: searchField.text.length > 0
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                searchField.clear()
                                searchField.forceActiveFocus()
                            }
                        }
                    }
                }

                Timer {
                    id: searchDebounce
                    interval: 180
                    onTriggered: library.set_search(searchField.text)
                }
            }

            Item { Layout.fillWidth: true }

            IconImage {
                name: "grid"
                px: 15
                tint: theme.tokens.textMuted
                Layout.alignment: Qt.AlignVCenter
            }
            Slider {
                id: sizeSlider
                from: 16
                to: 256
                stepSize: 16
                value: prefs !== null ? prefs.iconSize : 32
                Layout.preferredWidth: 110
                Layout.alignment: Qt.AlignVCenter
                // moved() = user-driven only (no feedback loop with the
                // sync below); set_icon_size dedupes per-step writes
                onMoved: prefs !== null
                         && prefs.set_icon_size(Math.round(value))
                Connections {
                    // a drag writes `value` imperatively, killing the
                    // binding above — re-sync from Settings while idle
                    target: prefs
                    function onIconSizeChanged() {
                        if (!sizeSlider.pressed)
                            sizeSlider.value = prefs.iconSize
                    }
                }
            }
            Text {
                text: sizeSlider.value + "px"
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
                Layout.preferredWidth: 34
                Layout.alignment: Qt.AlignVCenter
            }

            IconButton {
                icon_name: theme.isDark ? "sun" : "moon"
                ToolTip.text: theme.isDark ? qsTr("Switch to light")
                                           : qsTr("Switch to dark")
                onClicked: theme.toggle()
            }
            IconButton {
                icon_name: "refresh"
                enabled: !library.scanning
                ToolTip.text: qsTr("Re-scan library")
                onClicked: library.rescan()
            }
            BusyIndicator {
                visible: library.scanning
                running: library.scanning
                Layout.preferredWidth: 18
                Layout.preferredHeight: 18
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        SideRail {
            id: sideRail
            Layout.preferredWidth: 210
            Layout.fillHeight: true
            pane: root.pane
            onPanePicked: idx => root.pane = idx
        }
        Rectangle {
            width: 1
            Layout.fillHeight: true
            color: theme.tokens.border
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.pane

            AssetGrid {
                id: grid
                iconPx: root.iconSize
            }
            Fonts {}
            Colors {}
            Code {}
            Projects {}
        }

        Rectangle {
            width: 1
            Layout.fillHeight: true
            color: theme.tokens.border
            visible: inspectorPanel.visible
        }
        InspectorPanel {
            id: inspectorPanel
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            gridView: grid
            index: grid.currentIndex
            visible: root.pane === 0 && grid.currentIndex >= 0
        }
        // universal Properties panel for the other asset kinds (fonts,
        // color schemes, code snippets) — tags, custom fields, links
        PropertiesPanel {
            id: propsPanel
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            itemKind: root.pane === 1 ? "font"
                      : root.pane === 2 ? "palette" : "snippet"
            itemId: root.pane === 1
                    ? (fonts !== null
                       ? fonts.family_primary_id(fonts.selectedFamily) : -1)
                    : root.pane === 2
                      ? (colors !== null ? colors.paletteId : -1)
                      : (code !== null ? code.currentId : -1)
            visible: root.pane >= 1 && root.pane <= 3 && itemId >= 0
        }
    }

    // full-window accent flash on pane switch — a translucent wash of the
    // incoming pane's category color, fading fast
    Rectangle {
        id: paneFlash
        anchors.fill: parent
        color: theme.tokens.accent
        opacity: 0
        z: 99
        enabled: false
        function flash() {
            color = [theme.tokens.accentIcon, theme.tokens.accentFont,
                     theme.tokens.accentColor, theme.tokens.accentCode,
                     theme.tokens.accentProject][root.pane]
            paneFlashAnim.restart()
        }
        Connections {
            target: root
            function onPaneChanged() { paneFlash.flash() }
        }
        NumberAnimation {
            id: paneFlashAnim
            target: paneFlash
            property: "opacity"
            from: 0.07
            to: 0
            duration: 300
            easing.type: Easing.OutCubic
        }
    }

    footer: Rectangle {
        height: 26
        color: theme.tokens.surface
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 6
            Text {
                text: library !== null
                      ? (library.scanning
                         ? qsTr("indexing… %1").arg(library.scanCount)
                         : qsTr("%1 assets%2").arg(library.totalAssets)
                           .arg(library.lastScan !== ""
                                ? qsTr(" · indexed ") + library.lastScan : ""))
                      : ""
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
            }
            Item { Layout.fillWidth: true }
            Text {
                id: versionText
                // shows the version; flips to an amber notice when the
                // background release probe finds something newer — click
                // either state to re-check / open the releases page
                text: updater !== null && updater.updateAvailable
                      ? qsTr("update available: ") + updater.latestVersion
                      + " — click to open"
                      : "fengrid " + appVersion
                font.family: theme.monoFont
                font.pixelSize: 11
                color: updater !== null && updater.updateAvailable
                       ? theme.tokens.hlInk : theme.tokens.textMuted
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (updater === null)
                            return
                        if (updater.updateAvailable)
                            Qt.openUrlExternally(updater.releasesUrl)
                        else
                            updater.check()
                    }
                }
            }
        }
    }

    // ── settings overlay: covers the content area; header + footer stay
    // live (the menu button must keep working). Rebuilt on every open so
    // every creation-time binding captures current bridge state.
    Loader {
        id: settingsLoader
        anchors.fill: parent
        z: 50
        active: root.settingsOpen
        sourceComponent: SettingsScreen {
            onClosed: root.settingsOpen = false
        }
        onLoaded: {
            if (root.pendingCategory !== "") {
                item.showCategory(root.pendingCategory)
                root.pendingCategory = ""
            }
        }
    }
    function openSettings(category) {
        root.pendingCategory = category || ""
        root.settingsOpen = true
    }

    // ── first-run setup: full-window modal overlay (covers header and
    // footer — nothing is configurable behind it) ──
    Loader {
        id: setupLoader
        parent: Overlay.overlay
        anchors.fill: parent
        z: 60
        active: root.setupOpen
        sourceComponent: FirstRun {
            onFinished: {
                // persists first_run_done; the Connections below closes
                prefs.complete_first_run()
                toast.show(qsTr("Setup saved — change anything later from the main menu, Settings…"))
                menuBtn.flash()
            }
        }
    }
    Connections {
        target: prefs
        function onFirstRunNeededChanged() {
            root.setupOpen = prefs.firstRunNeeded
        }
    }
    // pane shortcuts are window-scoped; components outside this file
    // (Colors' Space, Code's Ctrl+S) gate on the Shell singleton
    Connections {
        target: root
        function onSettingsOpenChanged() {
            Shell.overlayOpen = root.settingsOpen || root.setupOpen
        }
        function onSetupOpenChanged() {
            Shell.overlayOpen = root.settingsOpen || root.setupOpen
        }
    }

    Shortcut {
        sequence: "/"
        enabled: !searchField.activeFocus && !root.settingsOpen
                 && !root.setupOpen
        onActivated: {
            searchField.forceActiveFocus()
            searchField.selectAll()
        }
    }
    Shortcut {
        sequence: "Ctrl+C"
        enabled: grid.currentIndex >= 0 && !root.settingsOpen
                 && !root.setupOpen
        onActivated: library.copy_name(grid.currentIndex)
    }
    Shortcut {
        sequence: "Escape"
        enabled: grid.currentIndex >= 0 && !root.settingsOpen
                 && !root.setupOpen
        onActivated: grid.currentIndex = -1
    }
    // Ctrl+, — settings (toggle); blocked while setup is modal
    Shortcut {
        sequence: "Ctrl+,"
        enabled: !root.setupOpen
        onActivated: root.settingsOpen = !root.settingsOpen
    }
    // Ctrl+1..5 — quick pane switching matching the top-bar order
    Shortcut { sequence: "Ctrl+1"; enabled: !root.settingsOpen && !root.setupOpen; onActivated: root.pane = 0 }
    Shortcut { sequence: "Ctrl+2"; enabled: !root.settingsOpen && !root.setupOpen; onActivated: root.pane = 1 }
    Shortcut { sequence: "Ctrl+3"; enabled: !root.settingsOpen && !root.setupOpen; onActivated: root.pane = 2 }
    Shortcut { sequence: "Ctrl+4"; enabled: !root.settingsOpen && !root.setupOpen; onActivated: root.pane = 3 }
    Shortcut { sequence: "Ctrl+5"; enabled: !root.settingsOpen && !root.setupOpen; onActivated: root.pane = 4 }

    // ── database pickers (menu → New/Open database…) ──
    FileDialog {
        id: openDbDialog
        title: qsTr("Open database")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("Fengrid database (*.db)"),
                      qsTr("All files (*)")]
        onAccepted: dbs !== null
                     && dbs.openDatabase(Icons.toLocalPath(selectedFile))
    }
    FileDialog {
        id: newDbDialog
        title: qsTr("New database")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("Fengrid database (*.db)")]
        defaultSuffix: "db"
        currentFolder: dbs !== null ? dbs.defaultDir : ""
        onAccepted: dbs !== null
                     && dbs.createDatabase(Icons.toLocalPath(selectedFile))
    }

    // QA: --dialog <name> opens a registered modal after load — delayed so
    // the window is mapped first (a Popup opened pre-show never appears)
    function openQaModal(name) {
        // the full-screen surfaces aren't Popups — open them directly
        if (name === "settings") {
            root.openSettings()
            return
        }
        if (name === "settings-storage") {
            root.openSettings("storage")
            return
        }
        if (name === "firstRun") {
            root.setupOpen = true
            return
        }
        if (name === "menu") {
            mainMenu.open()
            return
        }
        var dlg = (sideRail && sideRail.qaModals
                   && sideRail.qaModals[name])
                  ? sideRail.qaModals[name]
                  : (inspectorPanel && inspectorPanel.qaModals
                     ? inspectorPanel.qaModals[name] : null)
        if (dlg)
            dlg.open()
    }
    Timer {
        interval: 400
        running: typeof qaOpenModal !== "undefined" && qaOpenModal !== ""
        onTriggered: openQaModal(qaOpenModal)
    }

    Toast { id: toast }

    Connections {
        target: library
        function onMessage(msg) { toast.show(msg) }
        function onExportDone(path) { toast.show(qsTr("Exported to %1").arg(path)) }
        function onExportFailed(err) { toast.show(qsTr("Export failed: %1").arg(err)) }
    }
    Connections {
        target: fonts
        function onMessage(msg) { toast.show(msg) }
        function onExportDone(path) { toast.show(qsTr("Exported to %1").arg(path)) }
        function onExportFailed(err) { toast.show(qsTr("Export failed: %1").arg(err)) }
    }
    Connections {
        target: colors
        function onMessage(msg) { toast.show(msg) }
        function onExportDone(path) { toast.show(qsTr("Exported to %1").arg(path)) }
        function onExportFailed(err) { toast.show(qsTr("Export failed: %1").arg(err)) }
    }
    Connections {
        target: code
        function onMessage(msg) { toast.show(msg) }
        function onImportFailed(err) { toast.show(qsTr("Import failed: %1").arg(err)) }
    }
    Connections {
        target: projects
        function onMessage(msg) { toast.show(msg) }
        function onExportDone(path) { toast.show(qsTr("Exported to %1").arg(path)) }
        function onExportFailed(err) { toast.show(qsTr("Export failed: %1").arg(err)) }
    }
    Connections {
        target: dbs
        function onMessage(msg) { toast.show(msg) }
    }
    Connections {
        target: storage
        function onMessage(msg) { toast.show(msg) }
        // the source row itself belongs to the library bridge
        function onAttached(path, kind) {
            library.add_folder(path, kind)
            if (kind === "fontroot")
                fonts.rescan()
        }
        function onDetached(path) {
            library.remove_folder_path(path)
            fonts.refresh()
        }
    }
}
