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
        "families": true, "ftypes": true, "themes": true, "contexts": true,
        "exts": true, "collections": true, "smart": true,
        "libraries": true, "tags": true
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
        // smooth the hover/active switch — an abrupt transparent<->surface2
        // flip reads as "flicker" when the mouse sweeps across rows
        Behavior on color { ColorAnimation { duration: 90 } }

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
            width: parent.width - countText.implicitWidth - 46
            text: itemRoot.label
            font.family: theme.uiFont
            font.pixelSize: 12
            color: itemRoot.active ? theme.tokens.text : theme.tokens.textMuted
            elide: Text.ElideRight
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
            onClicked: itemRoot.picked()
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

                background: Rectangle {
                    implicitWidth: tab.implicitWidth
                    implicitHeight: tab.implicitHeight
                    radius: 7
                    color: "transparent"

                    // hover/active wash in the pane's accent
                    Rectangle {
                        anchors.fill: parent
                        radius: 7
                        color: tab.accent
                        opacity: tab.checked ? 0.16 : (tab.hovered ? 0.10 : 0)
                        Behavior on opacity { NumberAnimation { duration: 120 } }
                    }

                    // accent glow underline for the active tab — layered
                    // translucent fills, no MultiEffect (software-renderer
                    // friendly)
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
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width + 12
                            height: parent.height + 8
                            radius: 6
                            color: tab.accent
                            opacity: 0.25
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
        anchors.bottom: parent.bottom
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
                        && fonts.typeFilter === ""
                onPicked: {
                    if (fonts === null)
                        return
                    fonts.set_family_filter("")
                    fonts.set_type_filter("")
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
                        : rail.pane === 2
                          ? (colors !== null && colors.collectionFilter === ""
                             && !colors.starredOnly)
                          : (code !== null && code.collectionFilter === ""
                             && !code.starredOnly)
                onPicked: {
                    if (rail.pane === 0 && library !== null)
                        library.set_collection("")
                    else if (rail.pane === 2 && colors !== null)
                        colors.set_collection("")
                    else if (rail.pane === 3 && code !== null)
                        code.set_collection("")
                }
            }
            RailItem {
                visible: rail.showCollections && rail.pane !== 0
                label: qsTr("Starred")
                count: String(library !== null
                              ? library.starred_count(rail.pane === 2
                                                      ? "palette" : "snippet")
                              : 0)
                active: rail.pane === 2
                        ? (colors !== null && colors.starredOnly)
                        : (code !== null && code.starredOnly)
                onPicked: {
                    if (rail.pane === 2 && colors !== null)
                        colors.set_starred_only(!colors.starredOnly)
                    else if (rail.pane === 3 && code !== null)
                        code.set_starred_only(!code.starredOnly)
                }
            }
            Repeater {
                model: library !== null && rail.sectOpen.collections !== false
                       ? library.collections : []
                RailItem {
                    id: collRow
                    required property var modelData
                    // context-specific: a collection is listed when it holds
                    // refs of the current pane's kind — or when it's empty,
                    // so newly created collections stay reachable everywhere
                    visible: rail.showCollections
                             && (rail.pane === 0 || collRow.modelData.n === 0
                                 || (collRow.modelData.counts
                                     && collRow.modelData.counts[rail.paneKind] > 0))
                             // the dedicated Starred row covers the seeded
                             // starred collection on the palette/snippet panes
                             && !(rail.pane !== 0
                                  && collRow.modelData.name
                                     === "Starred Assets")
                    label: collRow.modelData.name
                    sub: collRow.modelData.tags
                    count: rail.pane === 0
                           ? String(collRow.modelData.n)
                           : String(rail.kindCount(collRow.modelData.counts))
                    indent: collRow.modelData.parentId > 0
                    active: rail.pane === 0
                            ? (library !== null && library.collectionFilter
                               === String(collRow.modelData.id))
                            : rail.pane === 2
                              ? (colors !== null && colors.collectionFilter
                                 === String(collRow.modelData.id))
                              : (code !== null && code.collectionFilter
                                 === String(collRow.modelData.id))
                    onPicked: {
                        // clicking a collection filters the ACTIVE pane's
                        // content (each bridge keeps its own filter state)
                        var cid = String(collRow.modelData.id)
                        if (rail.pane === 0 && library !== null)
                            library.set_collection(cid)
                        else if (rail.pane === 2 && colors !== null)
                            colors.set_collection(cid)
                        else if (rail.pane === 3 && code !== null)
                            code.set_collection(cid)
                    }
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            collMenu.target = collRow.modelData
                            collMenu.popup()
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
                        text: qsTr("comma-separated")
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
                        text: qsTr("new collection…")
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

            // smart collections — live criteria membership; listed under the
            // collections block on every pane that carries their kind
            SectionHeader {
                label: qsTr("Smart")
                sectionKey: "smart"
                visible: rail.showCollections }
            Repeater {
                model: {
                    if (rail.sectOpen.smart === false)
                        return []
                    var out = []
                    var all = taxonomy !== null ? taxonomy.smartCollections : []
                    for (var i = 0; i < all.length; i++)
                        if (all[i].item_kind === rail.paneKind)
                            out.push(all[i])
                    return out
                }
                RailItem {
                    id: smartRow
                    required property var modelData
                    label: smartRow.modelData.name
                    count: String(smartRow.modelData.n)
                    accent: theme.tokens.hlInk
                    active: rail.pane === 0
                            ? (library !== null && library.activeSmart
                               === String(smartRow.modelData.id))
                            : rail.pane === 2
                              ? (colors !== null && colors.smartFilter
                                 === String(smartRow.modelData.id))
                              : (code !== null && code.smartFilter
                                 === String(smartRow.modelData.id))
                    onPicked: {
                        var sid = String(smartRow.modelData.id)
                        if (rail.pane === 0 && library !== null)
                            library.set_smart_collection(sid)
                        else if (rail.pane === 2 && colors !== null)
                            colors.set_smart(sid)
                        else if (rail.pane === 3 && code !== null)
                            code.set_smart(sid)
                    }
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            smartMenu.target = smartRow.modelData
                            smartMenu.popup()
                        }
                    }
                }
            }

            // add/configure affordance for smart collections
            Rectangle {
                visible: rail.showCollections
                         && rail.sectOpen.smart !== false
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
                    IconImage { name: "zap"; px: 12; tint: theme.tokens.textMuted }
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

            // saved libraries (tag sets) — Icons pane: they resolve to asset
            // views; clicking one activates the multi-tag filter
            SectionHeader {
                label: qsTr("Libraries")
                sectionKey: "libraries"
                visible: rail.showIconSections }
            Repeater {
                model: taxonomy !== null
                       && rail.sectOpen.libraries !== false
                       ? taxonomy.libraryViews : []
                RailItem {
                    id: libRow
                    required property var modelData
                    visible: rail.showIconSections
                    label: libRow.modelData.name
                    count: String(libRow.modelData.n)
                    accent: theme.tokens.accent
                    active: library !== null
                            && library.activeLibraryView
                               === String(libRow.modelData.id)
                    onPicked: library !== null && library.set_library_view(
                        String(libRow.modelData.id))
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            libMenu.target = libRow.modelData
                            libMenu.popup()
                        }
                    }
                }
            }
            // "+ new library" row — the add/configure affordance for the
            // section (creates and later edits via right-click)
            Rectangle {
                visible: rail.showIconSections
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
                visible: rail.showIconSections }
            Repeater {
                model: library !== null && rail.sectOpen.tags !== false
                       ? library.tags : []
                RailItem {
                    id: tagRow
                    visible: rail.showIconSections
                    required property var modelData
                    label: "#" + modelData.name
                    count: String(modelData.n)
                    active: library !== null && library.tagFilter === modelData.name
                    onPicked: library.set_tag(
                        library.tagFilter === modelData.name ? "" : modelData.name)
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
                visible: rail.showIconSections
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
                        label: qsTr("name")
                    },
                    FormInput {
                        id: libTags
                        label: qsTr("tags (comma-separated)")
                    },
                    FormCheck {
                        id: libAll
                        checkLabel: qsTr("match ALL tags (else any)")
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
                        label: qsTr("name")
                    },
                    FormInput {
                        id: smartTags
                        label: qsTr("tags (comma-separated)")
                    },
                    FormInput {
                        id: smartQ
                        label: qsTr("name contains…")
                    },
                    FormCheck {
                        id: smartAll
                        checkLabel: qsTr("match ALL tags (else any)")
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
                        label: qsTr("new name")
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

            // add-folder source (native FolderDialog — no server involved)
            Rectangle {
                visible: rail.showIconSections
                Layout.fillWidth: true
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                Layout.bottomMargin: 10
                height: 26
                radius: 6
                color: addMa.containsMouse ? theme.tokens.surface2 : "transparent"
                Behavior on color { ColorAnimation { duration: 90 } }
                border.color: theme.tokens.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    spacing: 6
                    IconImage { name: "folder-plus"; px: 13; tint: theme.tokens.textMuted }
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("Add folder…")
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        color: theme.tokens.textMuted
                    }
                }
                MouseArea {
                    id: addMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: folderDialog.open()
                }
                FolderDialog {
                    id: folderDialog
                    onAccepted: library.add_folder(Icons.toLocalPath(selectedFolder))
                }
            }
        }
    }
}
