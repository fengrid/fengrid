import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

Rectangle {
    id: rail
    color: theme.tokens.surface

    // pane switching: tab row at the top of the rail (color-coded, one tab
    // per pane); Main owns the state
    property int pane: 0
    signal panePicked(int idx)
    // a library row asked for its inspector (Main hosts the overlay)
    signal entityProperties(string kind, int id)
    // the sticky Import Assets button — Main opens the import interface
    signal importRequested()

    // CONTEXT-SPECIFIC RAIL — the rail's contents follow the active pane:
    // icon-only sections (themes / contexts / types / tags / add-folder)
    // render only on the Icons pane, and the Collections list tracks the
    // pane's own ref kind (icon, palette, snippet) with per-kind counts.
    // Fonts and Projects don't carry collection refs yet, so those panes
    // hide the collections block entirely.
    // QA modal registry (--dialog <name>) — popups are unreachable from
    // the QObject tree, so Main.qml resolves them through this map
    readonly property var qaModals: ({
        "libDialog": libDialog, "smartDialog": smartDialog,
        "renameDialog": renameDialog, "subDialog": subDialog
    })

    property string paneKind: pane === 0 ? "icon"
                              : pane === 1 ? "font"
                              : pane === 2 ? "palette"
                              : pane === 3 ? "snippet" : ""
    property bool showIconSections: pane === 0
    property bool showCollections: paneKind !== ""

    // per-kind collection count for a row (falls back to 0)
    function kindCount(counts) {
        if (pane === 0 || !counts)
            return -1        // -1 = show the total instead
        return counts[paneKind] || 0
    }

    // COLLAPSIBLE SECTIONS — every list section in the rail carries a
    // chevron header that toggles its rows; state lives for the session
    property var sectOpen: ({
        "families": false, "ftypes": false, "themes": false, "contexts": false,
        "exts": false, "collections": false, "smart": false,
        "libraries": false, "tags": false, "presets": false
    })
    function toggleSection(key) {
        var next = Object.assign({}, sectOpen)
        next[key] = !next[key]
        sectOpen = next
    }

    // `library !== null` guards: context properties are nulled during app
    // teardown while lingering bindings re-evaluate — without the guard the
    // exit path spams TypeErrors (seen in the first offscreen QA run).
    component RailItem: Rectangle {
        id: itemRoot
        property string label
        property string sub: ""           // secondary line (collection tags)
        property string count: ""
        property string badge: ""         // type pill: smart / preset / remote
        property bool active: false
        property color accent: theme.tokens.accent   // per-category accent
        property bool indent: false       // sub-collection nesting
        signal picked()

        Layout.fillWidth: true
        Layout.leftMargin: indent ? 24 : 8
        Layout.rightMargin: 8
        height: sub === "" ? 26 : 36
        radius: 6
        color: active ? theme.tokens.surface2
                      : (itemMa.containsMouse ? theme.tokens.surface2 : "transparent")
        border.color: itemRoot.activeFocus ? itemRoot.accent : "transparent"
        border.width: itemRoot.activeFocus ? 2 : 0
        // smooth the hover/active switch — an abrupt transparent<->surface2
        // flip reads as "flicker" when the mouse sweeps across rows
        Behavior on color { ColorAnimation { duration: 90 } }

        // A11Y-1: the rail is keyboard-reachable — Tab moves between
        // rows, Return/Space activates, Up/Down walk the focus chain
        activeFocusOnTab: true
        Keys.onReturnPressed: itemRoot.picked()
        Keys.onEnterPressed: itemRoot.picked()
        Keys.onSpacePressed: itemRoot.picked()
        Keys.onDownPressed: {
            var n = nextItemInFocusChain(true)
            if (n && n !== itemRoot)
                n.forceActiveFocus()
        }
        Keys.onUpPressed: {
            var n = nextItemInFocusChain(false)
            if (n && n !== itemRoot)
                n.forceActiveFocus()
        }
        Accessible.role: Accessible.ListItem
        Accessible.name: itemRoot.label
                        + (itemRoot.count !== "" ? " (" + itemRoot.count + ")"
                                                 : "")
        Accessible.selected: itemRoot.active

        Rectangle {
            width: 3
            height: parent.height - 8
            radius: 1.5
            anchors.left: parent.left
            anchors.leftMargin: itemRoot.indent ? 8 : 0
            anchors.verticalCenter: parent.verticalCenter
            color: itemRoot.accent
            visible: itemRoot.active
        }
        Text {
            id: labelText
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - countText.implicitWidth
                   - badgeText.implicitWidth - 52
            text: itemRoot.label
            font.family: theme.uiFont
            font.pixelSize: 12
            color: itemRoot.active ? theme.tokens.text : theme.tokens.textMuted
            elide: Text.ElideRight
        }
        // type pill — smart / preset / remote indicator (combined lists)
        Rectangle {
            anchors.right: countText.left
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            visible: itemRoot.badge !== ""
            width: badgeText.implicitWidth + 10
            height: 14
            radius: 7
            color: theme.tokens.surface2
            border.color: theme.tokens.border
            Text {
                id: badgeText
                anchors.centerIn: parent
                text: itemRoot.badge
                font.family: theme.monoFont
                font.pixelSize: 8
                color: theme.tokens.textMuted
            }
        }
        Text {
            id: countText
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            text: itemRoot.count
            font.family: theme.monoFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
        }
        MouseArea {
            id: itemMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                itemRoot.forceActiveFocus()
                itemRoot.picked()
            }
        }
    }

    component SectionLabel: Text {
        Layout.fillWidth: true
        Layout.leftMargin: 14
        topPadding: 14
        bottomPadding: 4
        font.family: theme.headingFont
        font.pixelSize: 12
        font.letterSpacing: 1.4
        font.capitalization: Font.AllUppercase
        color: theme.tokens.textMuted
    }

    // collapsible section header — chevron + label; clicking toggles the
    // section's rows (the visible bindings of the section's items AND in
    // rail.sectOpen[key])
    component SectionHeader: Item {
        id: sectHdr
        property string label
        property string sectionKey
        property bool open: rail.sectOpen[sectionKey] !== false
        Layout.fillWidth: true
        height: 26
        IconImage {
            name: sectHdr.open ? "chevron-down" : "chevron-right"
            px: 12
            anchors.left: parent.left
            anchors.leftMargin: 2
            anchors.verticalCenter: parent.verticalCenter
            tint: theme.tokens.textMuted
        }
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            text: sectHdr.label
            topPadding: 6
            bottomPadding: 4
            font.family: theme.headingFont
            font.pixelSize: 12
            font.letterSpacing: 1.4
            font.capitalization: Font.AllUppercase
            color: theme.tokens.textMuted
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: rail.toggleSection(sectHdr.sectionKey)
        }
        // A11Y-3: the chevron direction alone is color/shape signaling —
        // expose the expanded state to assistive tech, and let the
        // section be toggled from the keyboard
        activeFocusOnTab: true
        Keys.onReturnPressed: rail.toggleSection(sectHdr.sectionKey)
        Keys.onEnterPressed: rail.toggleSection(sectHdr.sectionKey)
        Keys.onSpacePressed: rail.toggleSection(sectHdr.sectionKey)
        Rectangle {
            anchors.fill: parent
            radius: 6
            color: "transparent"
            border.color: theme.tokens.accent
            border.width: 2
            visible: sectHdr.activeFocus
        }
        Accessible.role: Accessible.Button
        Accessible.name: sectHdr.label
        Accessible.description: sectHdr.open
                                ? qsTr("Expanded — Press to Collapse")
                                : qsTr("Collapsed — Press to Expand")
    }

    // ------------------------------------------------------------- pane tabs
    // color-coded tab row: one compact icon tab per pane; the active tab
    // carries its category accent (glow underline + tinted glyph) and
    // switching tabs drives the main UI's pane
    Rectangle {
        id: tabBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 44
        color: "transparent"

        Row {
            anchors.centerIn: parent
            spacing: 2

            component PaneTab: AbstractButton {
                id: tab
                property string iconName
                property color accent
                property int paneIdx
                checked: rail.pane === paneIdx
                hoverEnabled: true
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                onClicked: rail.panePicked(paneIdx)
                opacity: checked || hovered ? 1 : 0.65
                Behavior on opacity { NumberAnimation { duration: 120 } }
                implicitWidth: 34
                implicitHeight: 32
                // A11Y-2: the pane glyph must be announced
                Accessible.role: Accessible.PageTab
                Accessible.name: {
                    var names = ["Icons", "Fonts", "Colors", "Code",
                                 "Projects"]
                    return (names[paneIdx] || "pane")
                            + (checked ? " (active)" : "")
                }
                Accessible.checkable: true
                Accessible.checked: checked

                background: Rectangle {
                    implicitWidth: tab.implicitWidth
                    implicitHeight: tab.implicitHeight
                    radius: 7
                    color: "transparent"

                    // #96: NO accent wash box behind the active tab —
                    // the tinted glyph + underline carry the state (the
                    // 0.16-opacity wash read as a 3D-shaded chip)

                    // accent glow underline for the active tab — realistic
                    // light emission with smooth radial falloff via Canvas
                    // (software-renderer friendly, no GraphicalEffects /
                    // MultiEffect dependency)
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: -1
                        width: parent.width - 12
                        height: 2.5
                        radius: 1.25
                        opacity: tab.checked ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: 160 } }
                        color: tab.accent
                        // #96 round 3: realistic glow — the flat halo
                        // (round 1) and the 3-step rings (round 2) both
                        // showed geometric boundaries that broke the
                        // light-emission illusion. A Canvas-drawn radial
                        // gradient provides continuous falloff from
                        // bright at the line to fully transparent, the
                        // way a real indicator light diffuses.
                        Canvas {
                            id: glowCanvas
                            anchors.centerIn: parent
                            width: parent.width + 28
                            height: parent.height + 28

                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.clearRect(0, 0, width, height)
                                var cx = width / 2
                                var cy = height / 2
                                var r = Math.max(width, height) / 2
                                var acc = tab.accent
                                var rgb = Math.round(acc.r * 255) + "," +
                                          Math.round(acc.g * 255) + "," +
                                          Math.round(acc.b * 255)
                                var g = ctx.createRadialGradient(
                                    cx, cy, 0, cx, cy, r)
                                g.addColorStop(0.0,
                                    "rgba(" + rgb + ", 0.42)")
                                g.addColorStop(0.2,
                                    "rgba(" + rgb + ", 0.16)")
                                g.addColorStop(0.5,
                                    "rgba(" + rgb + ", 0.06)")
                                g.addColorStop(1.0,
                                    "rgba(" + rgb + ", 0)")
                                ctx.fillStyle = g
                                ctx.fillRect(0, 0, width, height)
                            }

                            Component.onCompleted: requestPaint()
                            onWidthChanged: requestPaint()
                            onHeightChanged: requestPaint()
                            Connections {
                                target: tab
                                function onAccentChanged() {
                                    glowCanvas.requestPaint()
                                }
                            }
                        }
                    }
                }

                contentItem: Item {
                    IconImage {
                        name: tab.iconName
                        px: 15
                        anchors.centerIn: parent
                        tint: tab.checked ? tab.accent
                              : theme.tokens.textMuted
                    }
                }
            }

            PaneTab { iconName: "image";   accent: theme.tokens.accentIcon;    paneIdx: 0; ToolTip.text: qsTr("Icons") }
            PaneTab { iconName: "type";    accent: theme.tokens.accentFont;    paneIdx: 1; ToolTip.text: qsTr("Fonts") }
            PaneTab { iconName: "droplet"; accent: theme.tokens.accentColor;   paneIdx: 2; ToolTip.text: qsTr("Colors") }
            PaneTab { iconName: "code";    accent: theme.tokens.accentCode;    paneIdx: 3; ToolTip.text: qsTr("Code") }
            PaneTab { iconName: "package"; accent: theme.tokens.accentProject; paneIdx: 4; ToolTip.text: qsTr("Projects") }
        }

        // hairline separating the tab row from the rail content
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: theme.tokens.border
        }
    }

    Flickable {
        id: flick
        anchors.top: tabBar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: importBar.top
        contentHeight: railCol.implicitHeight + 20
        clip: true
        ScrollBar.vertical: ScrollBar { }

        ColumnLayout {
            id: railCol
            width: rail.width
            spacing: 2

            // pane items carry their category accent (Icons teal, Fonts
            // violet, Colors rose, Code coral, Projects green)

            // FONTS-pane rail content — font TYPES first, then FAMILIES
            // (families moved beneath types so the format filter reads
            // before the long family list); both sections collapse
            SectionLabel { text: qsTr("Fonts"); visible: rail.pane === 1 }
            RailItem {
                visible: rail.pane === 1
                label: qsTr("All fonts")
                accent: theme.tokens.accentFont
                count: fonts !== null ? String(fonts.totalFonts) : ""
                active: fonts !== null && fonts.familyFilter === ""
                        && fonts.typeFilter === "" && !fonts.starredOnly
                onPicked: {
                    if (fonts === null)
                        return
                    fonts.set_family_filter("")
                    fonts.set_type_filter("")
                    fonts.set_starred_only(false)
                }
            }
            SectionHeader {
                label: qsTr("Types")
                sectionKey: "ftypes"
                visible: rail.pane === 1 && fonts !== null
                         && fonts.fontTypes.length > 0
            }
            Repeater {
                model: fonts !== null && rail.pane === 1
                       && rail.sectOpen.ftypes !== false
                       ? fonts.fontTypes : []
                RailItem {
                    id: fontTypeRow
                    visible: rail.pane === 1
                    required property var modelData
                    label: fontTypeRow.modelData.name.toUpperCase()
                    count: String(fontTypeRow.modelData.n)
                    accent: theme.tokens.accentFont
                    active: fonts !== null && fonts.typeFilter
                            === String(fontTypeRow.modelData.name)
                    onPicked: fonts !== null && fonts.set_type_filter(
                        String(fontTypeRow.modelData.name))
                }
            }
            SectionHeader {
                label: qsTr("Families")
                sectionKey: "families"
                visible: rail.pane === 1 && fonts !== null
                         && fonts.families.length > 0
            }
            Repeater {
                model: fonts !== null && rail.pane === 1
                       && rail.sectOpen.families !== false
                       ? fonts.families : []
                RailItem {
                    id: famNavRow
                    visible: rail.pane === 1
                    required property var modelData
                    label: famNavRow.modelData.name
                    count: String(famNavRow.modelData.n)
                    accent: theme.tokens.accentFont
                    active: fonts !== null && fonts.familyFilter
                            === String(famNavRow.modelData.name)
                    onPicked: fonts !== null && fonts.set_family_filter(
                        String(famNavRow.modelData.name))
                }
            }

            SectionLabel { text: qsTr("Library"); visible: rail.showIconSections }
            RailItem {
                visible: rail.showIconSections
                label: qsTr("All assets")
                count: library !== null ? String(library.iconCount) : ""
                active: library !== null && library.themeFilter === ""
                        && library.contextFilter === "" && library.extFilter === ""
                onPicked: {
                    library.set_theme("")
                    library.set_context("")
                    library.set_ext("")
                }
            }

            SectionHeader {
                label: qsTr("Themes")
                sectionKey: "themes"
                visible: rail.showIconSections
                         && library.themes.length > 0 }
            Repeater {
                model: library !== null && rail.sectOpen.themes !== false
                       ? library.themes : []
                RailItem {
                    visible: rail.showIconSections
                    required property var modelData
                    label: modelData.name
                    count: String(modelData.n)
                    active: library !== null && library.themeFilter === modelData.name
                    onPicked: library.set_theme(
                        library.themeFilter === modelData.name ? "" : modelData.name)
                }
            }

            SectionHeader {
                label: qsTr("Contexts")
                sectionKey: "contexts"
                visible: rail.showIconSections
                         && library.contexts.length > 0 }
            Repeater {
                model: library !== null && rail.sectOpen.contexts !== false
                       ? library.contexts : []
                RailItem {
                    visible: rail.showIconSections
                    required property var modelData
                    label: modelData.name
                    count: String(modelData.n)
                    active: library !== null && library.contextFilter === modelData.name
                    onPicked: library.set_context(
                        library.contextFilter === modelData.name ? "" : modelData.name)
                }
            }

            SectionHeader {
                label: qsTr("Types")
                sectionKey: "exts"
                visible: rail.showIconSections
                         && library.exts.length > 0 }
            Repeater {
                model: library !== null && rail.sectOpen.exts !== false
                       ? library.exts : []
                RailItem {
                    visible: rail.showIconSections
                    required property var modelData
                    label: modelData.name.toUpperCase()
                    count: String(modelData.n)
                    active: library !== null && library.extFilter === modelData.name
                    onPicked: library.set_ext(
                        library.extFilter === modelData.name ? "" : modelData.name)
                }
            }

            SectionHeader {
                label: qsTr("Collections")
                sectionKey: "collections"
                visible: rail.showCollections }
            // ── pinned pseudo-collections: everything (works even for
            // items never added to any collection) and the starred view ──
            RailItem {
                visible: rail.showCollections
                         && rail.sectOpen.collections !== false
                label: qsTr("All assets")
                count: rail.pane === 0
                       ? String(library !== null ? library.totalAssets : 0)
                       : rail.pane === 2
                         ? String(colors !== null ? colors.palettes.length : 0)
                         : String(code !== null ? code.snippetCount : 0)
                active: rail.pane === 0
                        ? (library !== null && library.collectionFilter === "")
                        : rail.pane === 1
                          ? (fonts !== null && fonts.collectionFilter === ""
                             && !fonts.starredOnly)
                          : rail.pane === 2
                            ? (colors !== null
                               && colors.collectionFilter === ""
                               && !colors.starredOnly)
                            : (code !== null && code.collectionFilter === ""
                               && !code.starredOnly)
                onPicked: {
                    if (rail.pane === 0 && library !== null)
                        library.set_collection("")
                    else if (rail.pane === 1 && fonts !== null)
                        fonts.set_collection("")
                    else if (rail.pane === 2 && colors !== null)
                        colors.set_collection("")
                    else if (rail.pane === 3 && code !== null)
                        code.set_collection("")
                }
            }
            RailItem {
                visible: rail.showCollections && rail.pane !== 0
                label: qsTr("Starred")
                // fonts pane: the fonts bridge owns a reactive starred
                // count (#40); palettes/snippets keep the library query
                count: String(rail.pane === 1
                              ? (fonts !== null ? fonts.starredCount : 0)
                              : (library !== null
                                 ? library.starred_count(rail.pane === 2
                                                         ? "palette"
                                                         : "snippet")
                                 : 0))
                active: rail.pane === 1
                        ? (fonts !== null && fonts.starredOnly)
                        : rail.pane === 2
                          ? (colors !== null && colors.starredOnly)
                          : (code !== null && code.starredOnly)
                onPicked: {
                    if (rail.pane === 1 && fonts !== null)
                        fonts.set_starred_only(!fonts.starredOnly)
                    else if (rail.pane === 2 && colors !== null)
                        colors.set_starred_only(!colors.starredOnly)
                    else if (rail.pane === 3 && code !== null)
                        code.set_starred_only(!code.starredOnly)
                }
            }
            Repeater {
                model: {
                    if (!rail.showCollections
                            || rail.sectOpen.collections === false)
                        return []
                    var out = []
                    // user collections first …
                    var colls = library !== null
                                ? library.collections : []
                    for (var i = 0; i < colls.length; i++) {
                        var c = colls[i]
                        var show = rail.pane === 0 || c.n === 0
                                   || (c.counts
                                       && c.counts[rail.paneKind] > 0)
                        var starred = rail.pane !== 0
                                      && c.name === "Starred Assets"
                        if (show && !starred)
                            out.push({t: "collection", row: c})
                    }
                    // … then Smart Collections for this pane's kind
                    var smarts = taxonomy !== null
                                 ? taxonomy.smartCollections : []
                    for (var j = 0; j < smarts.length; j++)
                        if (smarts[j].item_kind === rail.paneKind)
                            out.push({t: "smart", row: smarts[j]})
                    return out
                }
                RailItem {
                    id: collRow
                    required property var modelData
                    // combined list: user collections + Smart Collections
                    // (badge "smart"); user rows keep the tree/counts rules
                    readonly property bool isSmart:
                        modelData.t === "smart"
                    readonly property var row: modelData.row
                    // context-specific: a collection is listed when it holds
                    // refs of the current pane's kind — or when it's empty,
                    // so newly created collections stay reachable everywhere
                    visible: rail.showCollections
                             && (collRow.isSmart
                                 || rail.pane === 0 || collRow.row.n === 0
                                 || (collRow.row.counts
                                     && collRow.row.counts[rail.paneKind] > 0))
                             // the dedicated Starred row covers the seeded
                             // starred collection on the palette/snippet panes
                             && !(rail.pane !== 0 && !collRow.isSmart
                                  && collRow.row.name
                                     === "Starred Assets")
                    label: collRow.row.name
                    sub: collRow.isSmart ? "" : collRow.row.tags
                    badge: collRow.isSmart ? "smart" : ""
                    count: collRow.isSmart
                           ? String(collRow.row.n)
                           : (rail.pane === 0
                              ? String(collRow.row.n)
                              : String(rail.kindCount(collRow.row.counts)))
                    indent: !collRow.isSmart
                            && collRow.row.parentId > 0
                    active: collRow.isSmart
                            ? rail.pane === 0
                              ? (library !== null && library.activeSmart
                                 === String(collRow.row.id))
                              : rail.pane === 1
                                ? (fonts !== null && fonts.smartFilter
                                   === String(collRow.row.id))
                              : rail.pane === 2
                                ? (colors !== null && colors.smartFilter
                                   === String(collRow.row.id))
                              : (code !== null && code.smartFilter
                                 === String(collRow.row.id))
                            : rail.pane === 0
                            ? (library !== null && library.collectionFilter
                               === String(collRow.row.id))
                            : rail.pane === 1
                              ? (fonts !== null && fonts.collectionFilter
                                 === String(collRow.row.id))
                            : rail.pane === 2
                              ? (colors !== null && colors.collectionFilter
                                 === String(collRow.row.id))
                              : (code !== null && code.collectionFilter
                                 === String(collRow.row.id))
                    onPicked: {
                        // clicking filters the ACTIVE pane's content
                        // (each bridge keeps its own filter state)
                        var idv = String(collRow.row.id)
                        if (collRow.isSmart) {
                            if (rail.pane === 0 && library !== null)
                                library.set_smart_collection(idv)
                            else if (rail.pane === 1 && fonts !== null)
                                fonts.set_smart(idv)
                            else if (rail.pane === 2 && colors !== null)
                                colors.set_smart(idv)
                            else if (rail.pane === 3 && code !== null)
                                code.set_smart(idv)
                            return
                        }
                        if (rail.pane === 0 && library !== null)
                            library.set_collection(idv)
                        else if (rail.pane === 1 && fonts !== null)
                            fonts.set_collection(idv)
                        else if (rail.pane === 2 && colors !== null)
                            colors.set_collection(idv)
                        else if (rail.pane === 3 && code !== null)
                            code.set_collection(idv)
                    }
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            if (collRow.isSmart) {
                                smartMenu.target = collRow.row
                                smartMenu.popup()
                            } else {
                                collMenu.target = collRow.row
                                collMenu.popup()
                            }
                        }
                    }
                }
            }
            // contextual menu for a collection row
            Menu {
                id: collMenu
                property var target: null
                width: 190
                padding: 4
                background: Rectangle {
                    radius: 8; color: theme.tokens.surface
                    border.color: theme.tokens.border
                }
                FgMenuItem {
                    text: qsTr("New sub-collection…")
                    height: 28
                    enabled: collMenu.target !== null
                    onTriggered: {
                        subDialog.parentId = collMenu.target.id
                        subDialog.open()
                    }
                }
                FgMenuItem {
                    text: qsTr("Edit tags…")
                    height: 28
                    enabled: collMenu.target !== null
                    onTriggered: {
                        subDialog.parentId = collMenu.target.id
                        subDialog.tagMode = true
                        subDialog.open()
                    }
                }
                FgMenuItem {
                    text: qsTr("Delete collection")
                    height: 28
                    enabled: collMenu.target !== null
                    onTriggered: library.delete_collection(collMenu.target.id)
                }
            }
            // shared name/tags input for new sub-collections + tag edits
            Dialog {
                id: subDialog
                objectName: "subDialog"
                property int parentId: 0
                property bool tagMode: false
                width: 300
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
                    spacing: 8
                    Text {
                        text: subDialog.tagMode ? qsTr("Edit collection tags")
                                                : qsTr("New sub-collection")
                        font.family: theme.headingFont; font.pixelSize: 13
                        font.letterSpacing: 1.2
                        font.capitalization: Font.AllUppercase
                        color: theme.tokens.text
                    }
                    Text {
                        visible: subDialog.tagMode
                        text: qsTr("Comma-Separated")
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 26
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: subInput.activeFocus ? theme.tokens.accent
                                                           : theme.tokens.border
                        TextInput {
                            id: subInput
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: TextInput.AlignVCenter
                            font.family: theme.monoFont
                            font.pixelSize: 11
                            color: theme.tokens.text
                            clip: true
                            onAccepted: subDialog.commit()
                        }
                    }
                }
                function commit() {
                    if (subInput.text.trim() === "")
                        return
                    if (tagMode)
                        library.set_collection_tags(parentId, subInput.text)
                    else
                        library.create_sub_collection(subInput.text.trim(),
                                                      parentId)
                    subInput.text = ""
                    close()
                }
                onOpened: {
                    subInput.text = tagMode && collMenu.target
                        ? (collMenu.target.tags || "") : ""
                    subInput.forceActiveFocus()
                }
                onClosed: tagMode = false

                // footer actions — the other form dialogs all expose
                // explicit Cancel/primary buttons; Enter-only commit was
                // inconsistent with them
                footer: FgDialogFooter {
                    acceptLabel: subDialog.tagMode ? qsTr("Save")
                                                   : qsTr("Create")
                    acceptEnabled: subInput.text.trim() !== ""
                    onCancelClicked: subDialog.close()
                    onAcceptClicked: subDialog.commit()
                }
            }
            Rectangle {
                visible: rail.showCollections
                         && rail.sectOpen.collections !== false
                Layout.fillWidth: true
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                height: 26
                radius: 6
                color: theme.tokens.surface2
                border.color: collInput.activeFocus ? theme.tokens.accent : theme.tokens.border

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 6
                    spacing: 4
                    TextInput {
                        id: collInput
                        Layout.fillWidth: true
                        font.family: theme.monoFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                        clip: true
                        onAccepted: {
                            if (text.trim() !== "")
                                library.create_collection(text.trim())
                            text = ""
                        }
                    }
                    Text {
                        visible: collInput.text === ""
                        Layout.fillWidth: true
                        text: qsTr("New Collection…")
                        font.family: theme.uiFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                    IconImage {
                        name: "plus"
                        px: 12
                        tint: theme.tokens.textMuted
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (collInput.text.trim() !== "")
                                    library.create_collection(collInput.text.trim())
                                collInput.text = ""
                            }
                        }
                    }
                }
            }

            // "+ new smart collection" — the add affordance for the smart
            // rows inside the combined Collections list
            Rectangle {
                visible: rail.showCollections
                         && rail.sectOpen.collections !== false
                Layout.fillWidth: true
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                height: 26
                radius: 6
                color: newSmartMa.containsMouse ? theme.tokens.surface2
                                                : "transparent"
                Behavior on color { ColorAnimation { duration: 90 } }
                border.color: theme.tokens.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    spacing: 6
                    IconImage { name: "zap"; px: 11; tint: theme.tokens.textMuted }
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("New smart collection…")
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        color: theme.tokens.textMuted
                    }
                }
                MouseArea {
                    id: newSmartMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        smartDialog.editId = 0
                        smartDialog.stashName = ""
                        smartDialog.stashTags = ""
                        smartDialog.stashQ = ""
                        smartDialog.stashAll = false
                        smartDialog.open()
                    }
                }
            }

            // saved libraries (tag sets) — shown on every pane with an
            // asset kind; rows appear when the view matches assets of
            // THE ACTIVE PANE'S kind (pane separation, per-kind counts)
            SectionHeader {
                label: qsTr("Libraries")
                sectionKey: "libraries"
                visible: rail.paneKind !== ""
                         || (presets !== null
                             && presets.libraries.length > 0) }
            Repeater {
                // ONE Libraries list: user libraries (tag sets) first,
                // then curated preset packs for the active pane's kind
                // (badge "preset", sub shows remote/local state)
                model: {
                    if (rail.sectOpen.libraries === false)
                        return []
                    var out = []
                    var views = taxonomy !== null
                                ? taxonomy.libraryViews : []
                    for (var i = 0; i < views.length; i++)
                        if (rail.pane === 0 || (views[i].counts
                                && views[i].counts[rail.paneKind] > 0))
                            out.push({t: "library", row: views[i]})
                    var packs = presets !== null ? presets.libraries : []
                    for (var j = 0; j < packs.length; j++)
                        if (rail.paneKind === ""
                            || packs[j].kind === rail.paneKind)
                            out.push({t: "preset", row: packs[j]})
                    return out
                }
                RailItem {
                    id: libRow
                    required property var modelData
                    readonly property bool isPreset:
                        modelData.t === "preset"
                    readonly property var row: modelData.row
                    visible: libRow.isPreset || rail.paneKind !== ""
                    label: libRow.row.name
                    badge: libRow.isPreset ? "preset" : ""
                    sub: libRow.isPreset
                         ? (libRow.row.downloaded > 0
                            ? "preset · " + libRow.row.downloaded + " local"
                            : "preset · remote")
                         : (libRow.row.tags || "")
                    count: String(libRow.isPreset
                                  ? libRow.row.entries
                                  : (rail.pane === 0
                                     ? libRow.row.n
                                     : (libRow.row.counts
                                        ? (libRow.row.counts[rail.paneKind]
                                           || 0) : 0)))
                    accent: theme.tokens.accent
                    active: libRow.isPreset
                            ? false
                            : (rail.pane === 0
                               ? (library !== null
                                  && library.activeLibraryView
                                  === String(libRow.row.id))
                               : (rail.pane === 2
                                  ? colors !== null
                                    && colors.libraryTagFilter
                                       === String(libRow.row.tags || "")
                                  : code !== null
                                    && code.libraryTagFilter
                                       === String(libRow.row.tags || "")))
                    onPicked: {
                        if (libRow.isPreset) {
                            presetsDialog.openLibrary(libRow.row.id)
                            return
                        }
                        if (rail.pane === 0 && library !== null) {
                            library.set_library_view(
                                String(libRow.row.id))
                            return
                        }
                        // panes 2/3: the view's tag set filters the pane
                        var tags = String(libRow.row.tags || "")
                        var all = libRow.row.match_all === 1
                        if (rail.pane === 2 && colors !== null)
                            colors.set_library_tags(tags, all)
                        else if (rail.pane === 3 && code !== null)
                            code.set_library_tags(tags, all)
                    }
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            if (libRow.isPreset) {
                                rail.entityProperties(
                                    "preset", libRow.row.id)
                                return
                            }
                            libMenu.target = libRow.row
                            libMenu.popup()
                        }
                    }
                }
            }
            // "+ new library" row — the add/configure affordance for the
            // section (creates and later edits via right-click)
            Rectangle {
                visible: rail.paneKind !== ""
                         && rail.sectOpen.libraries !== false
                Layout.fillWidth: true
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                height: 26
                radius: 6
                color: newLibMa.containsMouse ? theme.tokens.surface2
                                              : "transparent"
                Behavior on color { ColorAnimation { duration: 90 } }
                border.color: theme.tokens.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    spacing: 6
                    IconImage { name: "plus"; px: 12; tint: theme.tokens.textMuted }
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("New library…")
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        color: theme.tokens.textMuted
                    }
                }
                MouseArea {
                    id: newLibMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        libDialog.editId = 0
                        libDialog.stashName = ""
                        libDialog.stashTags = ""
                        libDialog.stashAll = false
                        libDialog.open()
                    }
                }
            }

            SectionHeader {
                label: qsTr("Tags")
                sectionKey: "tags"
                visible: rail.paneKind !== "" }
            Repeater {
                model: library !== null && rail.sectOpen.tags !== false
                       ? library.tags : []
                RailItem {
                    id: tagRow
                    // per-pane tagonomy: a tag shows when entities of the
                    // ACTIVE pane's kind carry it (counts per kind)
                    visible: rail.paneKind !== ""
                             && (rail.pane === 0
                                 || (tagRow.modelData.counts
                                     && tagRow.modelData.counts[rail.paneKind]
                                     > 0))
                    required property var modelData
                    label: "#" + modelData.name
                    count: String(rail.pane === 0
                                  ? modelData.n
                                  : (modelData.counts
                                     ? (modelData.counts[rail.paneKind] || 0)
                                     : 0))
                    active: rail.pane === 0
                            ? (library !== null
                               && library.tagFilter === modelData.name)
                            : (rail.pane === 2
                               ? colors !== null
                                 && colors.libraryTagFilter === modelData.name
                               : code !== null
                                 && code.libraryTagFilter === modelData.name)
                    onPicked: {
                        if (rail.pane === 0 && library !== null) {
                            library.set_tag(
                                library.tagFilter === modelData.name
                                ? "" : modelData.name)
                            return
                        }
                        if (rail.pane === 2 && colors !== null)
                            colors.set_library_tags(
                                colors.libraryTagFilter === modelData.name
                                ? "" : modelData.name, false)
                        else if (rail.pane === 3 && code !== null)
                            code.set_library_tags(
                                code.libraryTagFilter === modelData.name
                                ? "" : modelData.name, false)
                    }
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            tagMenu.target = tagRow.modelData
                            tagMenu.popup()
                        }
                    }
                }
            }
            Text {
                visible: rail.pane === 0
                         && rail.sectOpen.tags !== false
                Layout.fillWidth: true
                Layout.leftMargin: 14
                topPadding: 6
                text: qsTr("Select an asset to tag it")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
                wrapMode: Text.Wrap
            }

            // right-click menus + dialogs for libraries / smart collections /
            // tags (added with the taxonomy layer)
            Menu {
                id: libMenu
                property var target: null
                width: 190
                padding: 4
                background: Rectangle {
                    radius: 8; color: theme.tokens.surface
                    border.color: theme.tokens.border
                }
                FgMenuItem {
                    text: qsTr("Configure…")
                    height: 28
                    enabled: libMenu.target !== null
                    onTriggered: {
                        libDialog.editId = libMenu.target.id
                        libDialog.stashName = libMenu.target.name
                        libDialog.stashTags = libMenu.target.tags || ""
                        libDialog.stashAll = libMenu.target.match_all === 1
                        libDialog.open()
                    }
                }
                FgMenuItem {
                    text: qsTr("Properties")
                    height: 28
                    enabled: libMenu.target !== null
                    onTriggered: rail.entityProperties(
                        "library", libMenu.target.id)
                }
                FgMenuItem {
                    text: qsTr("Delete library")
                    height: 28
                    enabled: libMenu.target !== null
                    onTriggered: taxonomy.delete_library_view(libMenu.target.id)
                }
            }
            Menu {
                id: smartMenu
                property var target: null
                width: 190
                padding: 4
                background: Rectangle {
                    radius: 8; color: theme.tokens.surface
                    border.color: theme.tokens.border
                }
                FgMenuItem {
                    text: qsTr("Edit criteria…")
                    height: 28
                    enabled: smartMenu.target !== null
                    onTriggered: {
                        var crit = smartMenu.target.criteria || {}
                        smartDialog.editId = smartMenu.target.id
                        smartDialog.stashName = smartMenu.target.name
                        smartDialog.stashTags = (crit.tags || []).join(", ")
                        smartDialog.stashAll = !!crit.tag_match_all
                        smartDialog.stashQ = crit.q || ""
                        smartDialog.open()
                    }
                }
                FgMenuItem {
                    text: qsTr("Delete smart collection")
                    height: 28
                    enabled: smartMenu.target !== null
                    onTriggered: taxonomy.delete_smart(smartMenu.target.id)
                }
            }
            Menu {
                id: tagMenu
                property var target: null
                width: 190
                padding: 4
                background: Rectangle {
                    radius: 8; color: theme.tokens.surface
                    border.color: theme.tokens.border
                }
                FgMenuItem {
                    text: qsTr("Rename tag…")
                    height: 28
                    enabled: tagMenu.target !== null
                    onTriggered: {
                        renameDialog.oldName = tagMenu.target.name
                        renameDialog.open()
                    }
                }
                FgMenuItem {
                    text: qsTr("Delete tag")
                    height: 28
                    enabled: tagMenu.target !== null
                    onTriggered: library.delete_tag(tagMenu.target.name)
                }
            }

            // dialogs use the shared FormDialog/FormInput shell — fixed
            // width, centered on the window, themed footer buttons
            FormDialog {
                id: libDialog
                objectName: "libDialog"
                heading: editId ? qsTr("Configure library") : qsTr("New library")
                acceptEnabled: libName.text.trim() !== ""
                property int editId: 0
                // stash slots the callers write before open(); fields are
                // seeded imperatively onOpened (bindings would break after
                // the first user edit and go stale on the next open)
                property string stashName: ""
                property string stashTags: ""
                property bool stashAll: false

                fields: [
                    FormInput {
                        id: libName
                        label: qsTr("Name")
                    },
                    FormInput {
                        id: libTags
                        label: qsTr("Tags (Comma-Separated)")
                    },
                    FormCheck {
                        id: libAll
                        checkLabel: qsTr("Match ALL Tags (Else Any)")
                    }
                ]
                onOpened: {
                    libName.text = libDialog.stashName
                    libTags.text = libDialog.stashTags
                    libAll.checked = libDialog.stashAll
                    libName.forceActiveFocus()
                }
                onApply: {
                    if (editId)
                        taxonomy.update_library_view(editId, libName.text,
                                                     libTags.text,
                                                     libAll.checked)
                    else
                        taxonomy.create_library_view(libName.text,
                                                     libTags.text,
                                                     libAll.checked)
                }
            }

            FormDialog {
                id: smartDialog
                objectName: "smartDialog"
                heading: editId ? qsTr("Edit smart collection")
                              : qsTr("New smart collection")
                acceptEnabled: smartName.text.trim() !== ""
                property int editId: 0
                property string stashName: ""
                property string stashTags: ""
                property string stashQ: ""
                property bool stashAll: false

                fields: [
                    FormInput {
                        id: smartName
                        label: qsTr("Name")
                    },
                    FormInput {
                        id: smartTags
                        label: qsTr("Tags (Comma-Separated)")
                    },
                    FormInput {
                        id: smartQ
                        label: qsTr("Name Contains…")
                    },
                    FormCheck {
                        id: smartAll
                        checkLabel: qsTr("Match ALL Tags (Else Any)")
                    }
                ]
                onApply: {
                    var crit = {
                        tags: smartTags.text.split(",").map(
                            function (t) { return t.trim() }).filter(
                            function (t) { return t !== "" }),
                        tag_match_all: smartAll.checked,
                        q: smartQ.text.trim()
                    }
                    var critJson = JSON.stringify(crit)
                    if (smartDialog.editId)
                        taxonomy.update_smart(smartDialog.editId,
                                              smartName.text, critJson)
                    else
                        taxonomy.create_smart(smartName.text, rail.paneKind,
                                              critJson)
                }
            }

            FormDialog {
                id: renameDialog
                objectName: "renameDialog"
                heading: qsTr("Rename tag")
                acceptLabel: qsTr("Rename")
                acceptEnabled: renameInput.text.trim() !== ""
                               && renameInput.text.trim()
                                  !== renameDialog.oldName
                property string oldName: ""

                fields: [
                    FormInput {
                        id: renameInput
                        label: qsTr("New Name")
                    }
                ]
                onOpened: {
                    renameInput.text = renameDialog.oldName
                    renameInput.forceActiveFocus()
                }
                onApply: library.rename_tag(renameDialog.oldName,
                                            renameInput.text)
            }

            Item { Layout.fillHeight: true; Layout.minimumHeight: 8 }
        }
    }

    // sticky import affordance — pinned below the scrollable rail, NOT
    // inside it; launches the full import interface (replaces the old
    // per-list "Add folder…" rows)
    Rectangle {
        id: importBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 40
        color: theme.tokens.surface
        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 1
            color: theme.tokens.border
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 6
            radius: 6
            color: importMa.containsMouse ? theme.tokens.accent
                                          : theme.tokens.surface2
            border.color: importMa.containsMouse ? theme.tokens.accent
                                                 : theme.tokens.border
            Row {
                anchors.centerIn: parent
                spacing: 7
                IconImage {
                    name: "download"
                    px: 13
                    tint: importMa.containsMouse ? theme.tokens.bg
                                                 : theme.tokens.text
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: qsTr("Import Assets")
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    color: importMa.containsMouse ? theme.tokens.bg
                                                  : theme.tokens.text
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            MouseArea {
                id: importMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: rail.importRequested()
            }
        }
    }
}
