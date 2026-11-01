import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Effects
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

    // the Qt Quick Controls default palette — every default-styled
    // Button/ComboBox/Menu contentItem binds to these, so any control
    // that skips its own themed skin still renders with theme colors.
    // Before this, default Button text was #000 (the light control
    // palette) sitting on themed dark backgrounds — illegible (#87).
    palette.window: theme.tokens.bg
    palette.windowText: theme.tokens.text
    palette.button: theme.tokens.surface2
    palette.buttonText: theme.tokens.text
    palette.text: theme.tokens.text
    palette.base: theme.tokens.surface
    palette.toolTipBase: theme.tokens.surface2
    palette.toolTipText: theme.tokens.text
    palette.placeholderText: theme.tokens.textMuted
    palette.accent: theme.tokens.accent
    palette.highlight: theme.tokens.accent
    palette.highlightedText: theme.tokens.bg
    palette.link: theme.tokens.accent

    Component.onCompleted: {
        if (typeof startupNotice !== "undefined" && startupNotice !== "")
            toast.show(startupNotice)
    }

    property int iconSize: sizeSlider.value
    // 0 = icons, 1 = fonts, 2 = colors, 3 = code, 4 = projects (top-bar
    // pane switcher); --pane N (QA) overrides via the initialPane context
    property int pane: typeof initialPane !== "undefined" ? initialPane : 0

    // entity inspector overlay — Documentation / License / Sources tabs
    // for Projects and saved Libraries (opened from their context menus)
    property string entityKind: ""
    property int entityId: -1
    // lazy-loaded panes (instantiated via Loader on first access, #61)
    property var fontsPane: null
    property var colorsPane: null
    property var codePane: null
    property var projectsPane: null
    // blur the main UI behind open modal windows (Preset Libraries,
    // entity inspector, Settings) — read by the blur-behind host.
    // CRASH GUARD: the MultiEffect layer is shader-based; on the
    // software scene graph (QT_QUICK_BACKEND=software, GLX-less
    // displays) engaging it segfaults (user report) — never enable it
    // there
    readonly property bool blurUi: softwareRenderer === false
                                    && ((presetsDialog !== null
                                        && presetsDialog.visible)
                                    || (entityInspector !== null
                                        && entityInspector.visible)
                                    || root.settingsOpen)
    function openEntityInspector(kind, id) {
        entityKind = String(kind)
        entityId = parseInt(id)
        entityInspector.visible = true
        entityProps.activeTab = entityProps.defaultTab()
    }

    // ── overlays: settings (content area) + first-run setup (modal) ──
    property bool settingsOpen: false
    // computed in __main__ (flag unset && not a screenshot run); flipped
    // afterwards by prefs.firstRunNeededChanged
    property bool setupOpen: typeof initialFirstRun !== "undefined"
                            && initialFirstRun
    property string pendingCategory: ""
    // ── status-bar tip ticker + short-lived notices. Details win: while
    // a notice (scan summaries, export results, errors) is live the tips
    // step aside; notices decay and the rotation resumes.
    property var statusTips: [
        qsTr("Use the space bar to generate new color combinations!"),
        qsTr("Alt + / opens the slash menu — jump anywhere, run anything"),
        qsTr("Lock a swatch to keep it fixed while generating"),
        qsTr("Right-click anything for its context menu"),
        qsTr("Hover a color swatch for WCAG contrast readouts"),
        qsTr("Mark snippets with tags to build smart collections"),
        qsTr("Watch folders ingest new assets automatically — Settings → Import & Watch"),
        qsTr("Save a project revision before big token changes")
    ]
    property int statusTipIdx: 0
    property string statusNotice: ""
    property string statusTip:
        statusTips[statusTipIdx % statusTips.length]
    property bool paletteOpen: false

    function updateOverlayGate() {
        Shell.overlayOpen = root.settingsOpen || root.setupOpen
                            || root.paletteOpen
        Shell.paletteOpen = root.paletteOpen
    }

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
                // #116: hidden items inside a Menu still reserve their
                // height in the content layout (Qt 6 menu geometry) —
                // every conditional item pins height to 0 when hidden,
                // otherwise the menu shows a ~90px dead band when no
                // quick-access/recent databases exist
                FgMenuItem {
                    enabled: false
                    font.pixelSize: 11
                    font.letterSpacing: 1.2
                    font.capitalization: Font.AllUppercase
                    text: dbs !== null
                        ? qsTr("Database — %1").arg(dbs.currentLabel)
                        : qsTr("Database")
                }
                FgMenuItem {
                    visible: dbs !== null && dbs.quick.length > 0
                    height: visible ? implicitHeight : 0
                    enabled: false
                    text: qsTr("Quick access")
                }
                Repeater {
                    model: dbs !== null ? dbs.quick : []
                    delegate: FgMenuItem {
                        required property var modelData
                        enabled: modelData.exists
                        text: modelData.label + (modelData.exists ? ""
                                                                : qsTr(" (missing)"))
                        onClicked: dbs.switchTo(modelData.path)
                    }
                }
                FgMenuItem {
                    visible: dbs !== null && dbs.recent.length > 0
                    height: visible ? implicitHeight : 0
                    enabled: false
                    text: qsTr("Recent")
                }
                Repeater {
                    model: dbs !== null ? dbs.recent : []
                    delegate: FgMenuItem {
                        required property var modelData
                        enabled: modelData.exists
                        text: modelData.label + " · " + modelData.when
                            + (modelData.exists ? "" : qsTr(" (missing)"))
                        onClicked: dbs.switchTo(modelData.path)
                    }
                }
                FgMenuSeparator {
                    visible: dbs !== null && (dbs.quick.length > 0
                                            || dbs.recent.length > 0)
                    height: visible ? implicitHeight : 0
                }
                FgMenuItem {
                    visible: dbs !== null
                    text: dbs !== null && dbs.currentStarred
                        ? qsTr("Unstar current database")
                        : qsTr("Star current database")
                    onTriggered: dbs.starCurrent()
                }
                FgMenuItem {
                    visible: dbs !== null
                    text: qsTr("New database…")
                    onTriggered: newDbDialog.open()
                }
                FgMenuItem {
                    visible: dbs !== null
                    text: qsTr("Open database…")
                    onTriggered: openDbDialog.open()
                }
                FgMenuItem {
                    visible: dbs !== null && dbs.recent.length > 0
                    height: visible ? implicitHeight : 0
                    text: qsTr("Clear recent")
                    onTriggered: dbs.clearRecent()
                }
                FgMenuSeparator { visible: dbs !== null }

                FgMenuItem {
                    text: qsTr("Settings…")
                    height: 28
                    onTriggered: root.openSettings()
                }
                FgMenuItem {
                    text: qsTr("Check for updates")
                    height: 28
                    enabled: updater !== null
                    onTriggered: {
                        updater.check()
                        toast.show(qsTr("Checking for updates…"))
                    }
                }
                FgMenuSeparator {}
                FgMenuItem {
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

                    IconImage {
                        name: "search"
                        // header inline icons are 13px with the optical
                        // 0.71 inset (Icons.url) — ink lands on the text
                        // cap-height, one quiet tier below the clickable
                        // 16px IconButton glyphs
                        px: 13
                        tint: theme.tokens.textMuted
                        // magnifier = mouse entry into the slash menu
                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -7
                            cursorShape: Qt.PointingHandCursor
                            onClicked: commandPalette.show("")
                        }
                    }

                    TextField {
                        id: searchField
                        Layout.fillWidth: true
                        // the tip for the slash-menu hotkey rides in
                        // the placeholder and follows the user's binding
                        placeholderText: qsTr("Search Assets  ( / )  ·  %1")
                            .arg(prefs !== null ? prefs.formattedShortcut
                                                : "Alt + /")
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
                px: 13
                tint: theme.tokens.textMuted
                Layout.alignment: Qt.AlignVCenter
            }
            FgSlider {
                id: sizeSlider
                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: qsTr("Grid tile size — icons and font previews")
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

    // ── blur-behind host: the whole main UI blurs while a modal window
    // (Preset Libraries, entity inspector, Settings) is open ──
    Item {
        id: blurHost
        anchors.fill: parent

    RowLayout {
        id: mainContent
        anchors.fill: parent
        spacing: 0

        // A11Y/UX: while a modal window is open the whole UI renders
        // through a blur layer (see root.blurUi) — content stays live
        // but softly out of focus behind the dialog
        layer.enabled: root.blurUi
        layer.effect: MultiEffect {
            blurEnabled: true
            blur: 0.5
            blurMax: 28
        }

        SideRail {
            id: sideRail
            Layout.preferredWidth: 210
            Layout.fillHeight: true
            pane: root.pane
            onPanePicked: idx => root.pane = idx
            onEntityProperties: (kind, id) =>
                root.openEntityInspector(kind, id)
            onImportRequested: root.openSettings("import")
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

            // Pane 0 (Icons) — always instantiated (default startup pane)
            AssetGrid {
                id: grid
                iconPx: root.iconSize
            }

            // Panes 1–4: lazy-loaded via Loader to avoid the 20+ s engine.load
            // hit on software-rendered machines (#61). The Loader's source
            // component is only compiled when the pane is first activated.
            Loader {
                id: fontsLoader
                active: root.pane === 1 || root.startupPane === 1
                asynchronous: true
                sourceComponent: Fonts {}
                onStatusChanged: if (status === Loader.Ready) fontsPane = item
            }
            Loader {
                id: colorsLoader
                active: root.pane === 2 || root.startupPane === 2
                asynchronous: true
                sourceComponent: Colors {}
                onStatusChanged: if (status === Loader.Ready) colorsPane = item
            }
            Loader {
                id: codeLoader
                active: root.pane === 3 || root.startupPane === 3
                asynchronous: true
                sourceComponent: Code {}
                onStatusChanged: if (status === Loader.Ready) codePane = item
            }
            Loader {
                id: projectsLoader
                active: root.pane === 4 || root.startupPane === 4
                asynchronous: true
                sourceComponent: Projects {
                    id: projectsPane
                    onEntityProperties: (kind, id) => root.openEntityInspector(kind, id)
                }
                onStatusChanged: if (status === Loader.Ready) projectsPane = item
            }
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
            // checkbox multi-selection → aggregate summary + bulk export
            selectedIds: grid.selectedIds
            visible: root.pane === 0
                    && (grid.currentIndex >= 0 || grid.selectedIds.length > 0)
        }
        // universal Properties panel for the other asset kinds (fonts,
        // color schemes, code snippets) — tags, custom fields, links
        PropertiesPanel {
            id: propsPanel
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            itemKind: root.pane === 1 ? "font" : "palette"
            itemId: root.pane === 1
                    ? (fonts !== null
                    ? fonts.family_primary_id(fonts.selectedFamily) : -1)
                    : (colors !== null ? colors.paletteId : -1)
            // #115: checkbox multi-selection on the Fonts pane → the
            // panel shows an aggregate summary instead of single-item
            // detail (same pattern as the Icons pane's InspectorPanel)
            selectedIds: root.pane === 1 && fontsPane !== null && fonts !== null
                    ? fonts.checked_family_ids(fontsPane.checkedFams) : []
            // pane 3 hosts its own PropertiesPanel in the editor row —
            // the snippet preview spans the FULL lower band, so the
            // Main-level inspector would push it out of the window
            visible: root.pane >= 1 && root.pane <= 2
                    && (itemId >= 0 || selectedIds.length > 1)
        }
    }
    }   // blurHost

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
            function onPaneChanged() {
                paneFlash.flash()
                // curated specimen text rotates once per pane open
                if (root.pane === 1 && fonts !== null)
                    fonts.reshuffle_preview_text()
            }
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

    // ── preset libraries browser: curated remote catalogues ──
    PresetsDialog {
        id: presetsDialog
    }

    // ── entity inspector overlay: Documentation / License / Sources for
    // Projects and saved Libraries, opened from their context menus ──
    Rectangle {
        id: entityInspector
        visible: false
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: 340
        z: 120
        color: theme.tokens.surface
        border.color: theme.tokens.border
        clip: true

        PropertiesPanel {
            id: entityProps
            anchors.fill: parent
            anchors.margins: 1
            itemKind: root.entityKind
            itemId: root.entityId
        }
        // close affordance above the panel (the PropertiesPanel has no
        // chrome of its own — it was designed as a dock)
        Rectangle {
            anchors.top: parent.top
            anchors.right: parent.right
            width: 26
            height: 26
            radius: 13
            color: closeMa.containsMouse ? theme.tokens.surface2
                                        : "transparent"
            z: 2
            Text {
                anchors.centerIn: parent
                text: "✕"
                font.pixelSize: 12
                color: theme.tokens.textMuted
            }
            MouseArea {
                id: closeMa
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                hoverEnabled: true
                onClicked: entityInspector.visible = false
            }
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
                // pane-scoped count (#23): the label always names the
                // ACTIVE pane's metric so it can't be misread against
                // the rail badge of a different scope
                text: {
                    if (root.pane === 0 && library !== null)
                        return library.scanning
                                ? qsTr("Indexing… %1").arg(library.scanCount)
                                : qsTr("%1 assets%2").arg(library.totalAssets)
                                .arg(library.lastScan !== ""
                                    ? qsTr(" · indexed ")
                                        + library.lastScan : "")
                    if (root.pane === 1 && fonts !== null)
                        return qsTr("%1 font files · %2 families").arg(
                            fonts.totalFonts).arg(fonts.families.length)
                    if (root.pane === 2 && colors !== null)
                        return qsTr("%1 palettes").arg(colors.palettes.length)
                    if (root.pane === 3 && code !== null)
                        return qsTr("%1 snippets").arg(code.snippetCount)
                    if (root.pane === 4 && projects !== null)
                        return qsTr("%1 projects").arg(projects.projects.length)
                    return ""
                }
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
            }
            // uncommitted-changes reminder — discrete but bright red, per
            // the source-control spec (dirty project repo at any time)
            Text {
                id: uncommittedNote
                text: sc !== null && sc.hasUncommitted
                    ? qsTr("● %1: uncommitted changes — commit or stash")
                        .arg(sc.currentBranch) : ""
                visible: text !== ""
                font.family: theme.monoFont
                font.pixelSize: 11
                color: "#E5484D"
                // A11Y-3: the red is decorative — the ● marker + words
                // carry the meaning; make sure AT reads it in the bar
                Accessible.role: Accessible.StaticText
                Accessible.name: text
            }

            // tip ticker / notification area — yields to every detail:
            // hidden while scanning, while a notice is live, and while
            // the version notice is up
            Text {
                // the separator keeps the tip visually distinct from the
                // indexed details it must never displace
                text: "| " + root.statusTip
                visible: library !== null && !library.scanning
                        && root.statusNotice === ""
                        && !(updater !== null && updater.updateAvailable)
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
                opacity: 0.85
                elide: Text.ElideRight
                Layout.maximumWidth: 420
                MouseArea {
                    id: statusTipMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.statusTipIdx++
                }
                ToolTip.visible: statusTipMouse.containsMouse
                ToolTip.text: root.statusTip
            }
            Text {
                text: root.statusNotice !== "" ? "| " + root.statusNotice : ""
                visible: root.statusNotice !== ""
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.text
                elide: Text.ElideRight
                Layout.maximumWidth: 420
            }
            Item { Layout.fillWidth: true }
            Text {
                id: versionText
                // shows the version; flips to an amber notice when the
                // background release probe finds something newer — click
                // either state to re-check / open the releases page
                text: updater !== null && updater.updateAvailable
                        ? qsTr("Update Available: ") + updater.latestVersion
                        + " — Click to Open"
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
        // already open → onLoaded never fires again; consume here
        if (settingsLoader.active && settingsLoader.item
                && root.pendingCategory !== "") {
            settingsLoader.item.showCategory(root.pendingCategory)
            root.pendingCategory = ""
        }
    }

    // ── slash menu dispatch (the palette signals; every action lives
    // here because the palette file cannot see Main's ids) ──
    function paletteAction(kind, payload) {
        var d = {}
        try {
            d = JSON.parse(payload)
        } catch (e) {
            d = {}
        }
        if (kind === "command")
            root.runCommand(d.id || "")
        else if (kind === "asset")
            root.revealAsset(d)
        else if (kind === "snippet") {
            root.pane = 3
            code.open_snippet(d.id)
        } else if (kind === "db")
            dbs.switchTo(d.path)
        else if (kind === "fallback") {
            root.pane = 0
            // hand the query to the header quick search (pre-existing
            // debounce flow — Enter in the palette = old search)
            library.set_search(d.query || "")
            searchField.text = d.query || ""
        }
    }

    function runCommand(id) {
        if (id.indexOf("settings-") === 0) {
            openSettings(id.slice("settings-".length))
            return
        }
        switch (id) {
        case "go-icons": root.pane = 0; break
        case "go-fonts": root.pane = 1; break
        case "go-colors": root.pane = 2; break
        case "go-code": root.pane = 3; break
        case "go-projects": root.pane = 4; break
        case "open-settings": openSettings(); break
        case "run-setup":
            prefs.start_first_run()   // flips setupOpen via Connections
            break
        case "command-shortcut": openSettings("general"); break
        case "rescan-library": library.rescan(); break
        case "new-snippet":
            root.pane = 3
            code.new_snippet()
            break
        case "rescan-fonts": fonts.rescan(); break
        case "toggle-theme": theme.toggle(); break
        case "generate-palette":
            root.pane = 2
            colors.generate()
            break
        case "check-updates":
            if (updater !== null) {
                updater.check()
                toast.show(qsTr("Checking for updates…"))
            }
            break
        case "new-db": newDbDialog.open(); break
        case "open-db": openDbDialog.open(); break
        case "star-db":
            if (dbs !== null)
                dbs.starCurrent()
            break
        case "clear-recent":
            if (dbs !== null)
                dbs.clearRecent()
            break
        default:
            toast.show(qsTr("Unknown command: %1").arg(id))
        }
    }

    function revealAsset(d) {
        if (d.kind === "font") {
            root.pane = 1
            if (d.family)
                fonts.select(d.family)
            return
        }
        root.pane = 0
        var i = library.index_of_path(d.path)
        if (i < 0) {
            // current search/filters hide it — clear both, re-locate
            library.set_search("")
            library.clear_filters()
            searchField.text = ""
            i = library.index_of_path(d.path)
        }
        if (i >= 0)
            grid.currentIndex = i
        else
            toast.show(qsTr("Not in the current view: %1").arg(d.path))
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
        function onSettingsOpenChanged() { root.updateOverlayGate() }
        function onSetupOpenChanged() { root.updateOverlayGate() }
    }

    // ── slash menu: opens with the configured sequence (Alt+/ by
    // default, rebindable in Settings / first-run). Lives in the
    // overlay so its backdrop dims the header and status bar too ──
    CommandPalette {
        id: commandPalette
        parent: Overlay.overlay
        z: 55
        onOpened: {
            root.paletteOpen = true
            root.updateOverlayGate()
        }
        onClosed: {
            root.paletteOpen = false
            root.updateOverlayGate()
        }
        onActivated: function (kind, payload) {
            root.paletteAction(kind, payload)
        }
    }

    // ── launch splash: self-gating (see SplashOverlay) — opens while a
    // scan runs on a still-empty DB, closes when the scans go quiet ──
    SplashOverlay {
        id: splashOverlay
        parent: Overlay.overlay
        z: 58
    }

    // QA: --qa-select <icon> selects the asset (inspector visible in
    // shots), then FENGRID_QA_INSPECTOR_SCROLL scrolls the inspector
    // body to prove the pinned footer + scroll-behind behaviour
    Timer {
        interval: 500
        running: typeof qaIconPath !== "undefined" && qaIconPath !== ""
        onTriggered: {
            var i = library.index_of_path(qaIconPath)
            if (i >= 0)
                grid.currentIndex = i
            if (typeof qaInspectorScroll !== "undefined"
                    && qaInspectorScroll > 0) {
                scrollTimer.start()
            }
        }
    }
    Timer {
        id: scrollTimer
        interval: 400
        onTriggered: inspectorPanel.bodyFlick.contentY = qaInspectorScroll
    }
    // QA: FENGRID_QA_SELECT_IDS="1,2,3" pre-checks grid checkboxes so the
    // inspector's aggregate multi-selection view renders in screenshots
    Timer {
        interval: 500
        running: typeof qaSelectIds !== "undefined" && qaSelectIds.length > 0
        onTriggered: {
            grid.selectedIds = qaSelectIds
            var r = library.row_of_asset(qaSelectIds[0])
            if (r >= 0)
                grid.currentIndex = r
        }
    }

    Shortcut {
        sequence: prefs !== null ? prefs.commandShortcut : "Alt+/"
        enabled: !root.setupOpen && !Shell.capturing
        onActivated: commandPalette.open ? commandPalette.hide()
                                        : commandPalette.show("")
    }

    Shortcut {
        sequence: "/"
        enabled: !searchField.activeFocus && !root.settingsOpen
                && !root.setupOpen && !root.paletteOpen
                && !Shell.capturing
        onActivated: {
            searchField.forceActiveFocus()
            searchField.selectAll()
        }
    }
    Shortcut {
        sequence: "Ctrl+C"
        enabled: grid.currentIndex >= 0 && !root.settingsOpen
                && !root.setupOpen && !root.paletteOpen
                && !Shell.capturing
        onActivated: library.copy_name(grid.currentIndex)
    }
    Shortcut {
        sequence: "Escape"
        enabled: grid.currentIndex >= 0 && !root.settingsOpen
                && !root.setupOpen && !root.paletteOpen
                && !Shell.capturing
        onActivated: grid.currentIndex = -1
    }
    // Ctrl+, — settings (toggle); blocked while setup is modal
    Shortcut {
        // sequences list form: some platforms map the sequence to
        // multiple key bindings and QML warns on the single form
        sequences: ["Ctrl+,"]
        enabled: !root.setupOpen && !root.paletteOpen && !Shell.capturing
        onActivated: root.settingsOpen = !root.settingsOpen
    }
    // Ctrl+1..5 — quick pane switching matching the top-bar order
    Shortcut { sequence: "Ctrl+1"; enabled: !root.settingsOpen && !root.setupOpen && !root.paletteOpen && !Shell.capturing; onActivated: root.pane = 0 }
    Shortcut { sequence: "Ctrl+2"; enabled: !root.settingsOpen && !root.setupOpen && !root.paletteOpen && !Shell.capturing; onActivated: root.pane = 1 }
    Shortcut { sequence: "Ctrl+3"; enabled: !root.settingsOpen && !root.setupOpen && !root.paletteOpen && !Shell.capturing; onActivated: root.pane = 2 }
    Shortcut { sequence: "Ctrl+4"; enabled: !root.settingsOpen && !root.setupOpen && !root.paletteOpen && !Shell.capturing; onActivated: root.pane = 3 }
    Shortcut { sequence: "Ctrl+5"; enabled: !root.settingsOpen && !root.setupOpen && !root.paletteOpen && !Shell.capturing; onActivated: root.pane = 4 }

    // global undo/redo — routes to the FOCUSED pane's undo bridge
    // (project settings changes for Projects, palette edits for Colors;
    // editors keep their own TextEdit undo for caret-level edits)
    Shortcut {
        sequences: [StandardKey.Undo]
        enabled: !root.settingsOpen && !root.paletteOpen
                && ((root.pane === 4 && undoProjects !== null
                    && undoProjects.canUndo)
                    || (root.pane === 2 && undoColors !== null
                && undoColors.canUndo))
        onActivated: root.pane === 4 ? undoProjects.undo()
                                    : undoColors.undo()
    }
    Shortcut {
        sequences: [StandardKey.Redo]
        enabled: !root.settingsOpen && !root.paletteOpen
                && ((root.pane === 4 && undoProjects !== null
                    && undoProjects.canRedo)
                    || (root.pane === 2 && undoColors !== null
                        && undoColors.canRedo))
        onActivated: root.pane === 4 ? undoProjects.redo()
                                    : undoColors.redo()
    }
    // uncommitted changes pending at close — prompt commit or stash first
    onClosing: function (close) {
        if (sc !== null && sc.hasRepo() && sc.hasUncommitted) {
            close.accepted = false
            closePrompt.open()
        }
    }
    Dialog {
        id: closePrompt
        width: 340
        padding: 16
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        background: Rectangle {
            radius: 12; color: theme.tokens.surface
            border.color: theme.tokens.litPane
        }
        contentItem: ColumnLayout {
            spacing: 10
            Text {
                text: qsTr("Uncommitted changes")
                font.family: theme.headingFont; font.pixelSize: 13
            }
            Text {
                text: qsTr("The current project has uncommitted changes.")
                        + " Commit them before closing, or stash them"
                        + " to return later."
                wrapMode: Text.Wrap
                font.family: theme.uiFont; font.pixelSize: 11
                color: theme.tokens.text
                Layout.fillWidth: true
            }
            TextField {
                id: closeMsg
                Layout.fillWidth: true
                placeholderText: qsTr("Commit Message…")
                font.family: theme.monoFont; font.pixelSize: 11
            }
        }
        // three-way close: Quit anyway / Stash & close / Commit (primary)
        footer: Item {
            implicitHeight: closeRow.implicitHeight + 16
            RowLayout {
                id: closeRow
                spacing: 8
                anchors {
                    left: parent.left; leftMargin: 16
                    right: parent.right; rightMargin: 16
                    bottom: parent.bottom; bottomMargin: 16
                }
                FgButton {
                    text: qsTr("Quit anyway")
                    onClicked: closePrompt.closeAndQuit()
                }
                FgButton {
                    text: qsTr("Stash & close")
                    ToolTip.visible: hovered
                    ToolTip.text: qsTr("Set the changes aside — restore " +
                                        "them with «Restore stash» in the " +
                                        "Projects source panel")
                    onClicked: {
                        sc.stash(closeMsg.text.trim() !== ""
                                ? closeMsg.text : "WIP before close")
                        closePrompt.stashAndClose()
                    }
                }
                Button {
                    text: qsTr("Commit")
                    enabled: closeMsg.text.trim() !== ""
                    onClicked: closePrompt.commitAndClose()
                    background: Rectangle {
                        radius: 6; color: theme.tokens.accent
                    }
                    contentItem: Text {
                        text: qsTr("Commit")
                        color: theme.tokens.bg
                        font.family: theme.uiFont; font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }
        function stashAndClose() {
            Qt.quit()
        }
        function commitAndClose() {
            sc.commit(closeMsg.text)
            closeMsg.text = ""
            close()
            Qt.quit()
        }
        function closeAndQuit() {
            close()
            Qt.quit()
        }
    }

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
        if (name.indexOf("settings-") === 0) {
            // settings-storage, settings-import, settings-sc, …
            root.openSettings(name.slice("settings-".length))
            return
        }
        if (name === "firstRun") {
            root.setupOpen = true
            return
        }
        if (name === "presets") {
            presetsDialog.openLibrary(
                -1, root.pane === 0 ? "icon"
                    : root.pane === 1 ? "font"
                    : root.pane === 4 ? "template" : "")
            return
        }
        if (name === "fonts-css") {
            root.pane = 1
            // Ensure Fonts pane is loaded before calling its method
            if (fontsPane === null && fontsLoader.status === Loader.Ready) {
                fontsPane = fontsLoader.item
            }
            if (fontsPane !== null) {
                fontsPane.openExportCss()
            } else {
                // Force load and retry once the loader finishes — signal
                // handlers are read-only on dynamically created objects,
                // so the poll exposes a plain property-var callback
                fontsLoader.active = true
                var poll = Qt.createQmlObject(
                    "import QtQuick; Timer { interval: 100; repeat: true;"
                    + " property var onReady: null;"
                    + " onTriggered: if (onReady) onReady() }",
                    fontsLoader, "qaFontsCssPoll")
                poll.onReady = function() {
                    if (fontsLoader.status === Loader.Ready) {
                        fontsPane = fontsLoader.item
                        fontsPane.openExportCss()
                        poll.stop()
                        poll.destroy()
                    }
                }
                poll.start()
            }
            return
        }
        if (name === "colorPicker") {
            root.pane = 2
            if (colorsPane === null && colorsLoader.status === Loader.Ready) {
                colorsPane = colorsLoader.item
            }
            if (colorsPane !== null) {
                Qt.callLater(function() {
                    if (colorsPane !== null)
                        colorsPane.openColorPicker()
                })
            } else {
                colorsLoader.active = true
                var poll2 = Qt.createQmlObject(
                    "import QtQuick; Timer { interval: 100; repeat: true;"
                    + " property var onReady: null;"
                    + " onTriggered: if (onReady) onReady() }",
                    colorsLoader, "qaColorPickerPoll")
                poll2.onReady = function() {
                    if (colorsLoader.status === Loader.Ready) {
                        colorsPane = colorsLoader.item
                        colorsPane.openColorPicker()
                        poll2.stop()
                        poll2.destroy()
                    }
                }
                poll2.start()
            }
            return
        }
        if (name === "entity") {
            // first project (or library) in the DB → its inspector
            root.pane = 4
            // Ensure Projects pane is loaded
            if (projectsPane === null && projectsLoader.status === Loader.Ready) {
                projectsPane = projectsLoader.item
            }
            var rows = (projectsPane !== null) ? projectsPane.projects : []
            if (rows.length > 0) {
                root.openEntityInspector("project", rows[0].id)
                entityProps.activeTab = 2
            }
            return
        }
        if (name === "entity-license") {
            root.pane = 4
            var rowsL = projects !== null ? projects.projects : []
            if (rowsL.length > 0) {
                root.openEntityInspector("project", rowsL[0].id)
                entityProps.activeTab = 3
            }
            return
        }
        if (name === "entity-sources") {
            root.pane = 4
            var rowsS = projects !== null ? projects.projects : []
            if (rowsS.length > 0) {
                root.openEntityInspector("project", rowsS[0].id)
                entityProps.activeTab = 4
            }
            return
        }
        if (name === "menu") {
            mainMenu.open()
            return
        }
        if (name === "commandBar") {
            commandPalette.show("")
            return
        }
        // QA: the full user recipe — palette open, then the
        // "Open settings" row activated (dispatch + hide), used to
        // reproduce the launch-time freeze on frozen builds
        if (name === "paletteSettings") {
            commandPalette.show("")
            palQaTimer.start()
            return
        }
        if (name === "splash") {
            splashOverlay.force = true
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
        id: palQaTimer
        interval: 700
        onTriggered: {
            commandPalette.query = "open settings"
            commandPalette.rebuild()
            commandPalette.activate(0)
        }
    }
    Timer {
        interval: 400
        running: typeof qaOpenModal !== "undefined" && qaOpenModal !== ""
        onTriggered: openQaModal(qaOpenModal)
    }

    Toast { id: toast }

    Timer {
        interval: 6000
        running: root.statusNotice === "" && !root.paletteOpen
                && !root.settingsOpen && !root.setupOpen
        repeat: true
        onTriggered: root.statusTipIdx++
    }
    Timer {
        id: noticeDecay
        interval: 8000
        onTriggered: root.statusNotice = ""
    }
    // source control: refresh repo status so the red reminder tracks the
    // working tree (cheap — one `git status --porcelain` per tick)
    Timer {
        interval: 15000
        repeat: true
        running: sc !== null && sc.hasRepo()
        onTriggered: sc.refresh()
    }
    function statusNote(msg) {
        root.statusNotice = msg
        noticeDecay.restart()
    }

    Connections {
        target: dataio
        function onMessage(msg) { toast.show(msg); root.statusNote(msg) }
        // import/watch jobs index on their own connection — the main
        // bridge models must re-walk (fingerprints keep this cheap)
        function onImportFinished(report) {
            library.rescan()
            fonts.rescan()
        }
    }

    Connections {
        target: library
        function onMessage(msg) { toast.show(msg); root.statusNote(msg) }
        function onExportDone(path) {
            var m = qsTr("Exported to %1").arg(path)
            toast.show(m); root.statusNote(m)
        }
        function onExportFailed(err) {
            var m = qsTr("Export failed: %1").arg(err)
            toast.show(m); root.statusNote(m)
        }
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
