import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

Rectangle {
    id: rail
    color: theme.tokens.surface

    // pane switching: 0 = icons, 1 = fonts, 2 = colors, 3 = code (Main owns
    // the state)
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

    Flickable {
        id: flick
        anchors.fill: parent
        contentHeight: railCol.implicitHeight + 20
        clip: true
        ScrollBar.vertical: ScrollBar { }

        ColumnLayout {
            id: railCol
            width: rail.width
            spacing: 2

            // pane items carry their category accent (Icons teal, Fonts
            // violet, Colors rose, Code coral, Projects green)
            SectionLabel { text: qsTr("Panes") }
            RailItem {
                label: qsTr("Icons")
                accent: theme.tokens.accentIcon
                active: rail.pane === 0
                onPicked: rail.panePicked(0)
            }
            RailItem {
                label: qsTr("Fonts")
                accent: theme.tokens.accentFont
                active: rail.pane === 1
                onPicked: rail.panePicked(1)
            }
            RailItem {
                label: qsTr("Colors")
                accent: theme.tokens.accentColor
                active: rail.pane === 2
                onPicked: rail.panePicked(2)
            }
            RailItem {
                label: qsTr("Code")
                accent: theme.tokens.accentCode
                active: rail.pane === 3
                onPicked: rail.panePicked(3)
            }
            RailItem {
                label: qsTr("Projects")
                accent: theme.tokens.accentProject
                active: rail.pane === 4
                onPicked: rail.panePicked(4)
            }

            // FONTS-pane rail content — font families and file types live
            // here, not in the Icons pane's theme/type lists
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
            SectionLabel {
                text: qsTr("Families")
                visible: rail.pane === 1 && fonts !== null
                         && fonts.families.length > 0
            }
            Repeater {
                model: fonts !== null && rail.pane === 1 ? fonts.families : []
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
            SectionLabel {
                text: qsTr("Types")
                visible: rail.pane === 1 && fonts !== null
                         && fonts.fontTypes.length > 0
            }
            Repeater {
                model: fonts !== null && rail.pane === 1 ? fonts.fontTypes : []
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

            SectionLabel { text: qsTr("Themes")
                           visible: rail.showIconSections
                                    && library.themes.length > 0 }
            Repeater {
                model: library.themes
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

            SectionLabel { text: qsTr("Contexts")
                           visible: rail.showIconSections
                                    && library.contexts.length > 0 }
            Repeater {
                model: library.contexts
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

            SectionLabel { text: qsTr("Types")
                           visible: rail.showIconSections
                                    && library.exts.length > 0 }
            Repeater {
                model: library.exts
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

            SectionLabel { text: qsTr("Collections")
                           visible: rail.showCollections }
            Repeater {
                model: library.collections
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
                MenuItem {
                    text: qsTr("New sub-collection…")
                    height: 28
                    enabled: collMenu.target !== null
                    onTriggered: {
                        subDialog.parentId = collMenu.target.id
                        subDialog.open()
                    }
                }
                MenuItem {
                    text: qsTr("Edit tags…")
                    height: 28
                    enabled: collMenu.target !== null
                    onTriggered: {
                        subDialog.parentId = collMenu.target.id
                        subDialog.tagMode = true
                        subDialog.open()
                    }
                }
                MenuItem {
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
                footer: RowLayout {
                    spacing: 8
                    Item { Layout.fillWidth: true }
                    Button {
                        text: qsTr("Cancel")
                        onClicked: subDialog.close()
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
                            leftPadding: 14; rightPadding: 14
                        }
                    }
                    Button {
                        enabled: subInput.text.trim() !== ""
                        text: subDialog.tagMode ? qsTr("Save") : qsTr("Create")
                        onClicked: subDialog.commit()
                        background: Rectangle {
                            radius: 6
                            color: subInput.text.trim() !== ""
                                   ? theme.tokens.accent : theme.tokens.border
                        }
                        contentItem: Text {
                            text: parent.text
                            color: theme.tokens.bg
                            font.family: theme.uiFont; font.pixelSize: 12
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 14; rightPadding: 14
                        }
                    }
                }
            }
            Rectangle {
                visible: rail.showCollections
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
            SectionLabel { text: qsTr("Smart")
                           visible: rail.showCollections }
            Repeater {
                model: {
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
            SectionLabel { text: qsTr("Libraries")
                           visible: rail.showIconSections }
            Repeater {
                model: taxonomy !== null ? taxonomy.libraryViews : []
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

            SectionLabel { text: qsTr("Tags"); visible: rail.showIconSections }
            Repeater {
                model: library.tags
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
                MenuItem {
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
                MenuItem {
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
                MenuItem {
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
                MenuItem {
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
                MenuItem {
                    text: qsTr("Rename tag…")
                    height: 28
                    enabled: tagMenu.target !== null
                    onTriggered: {
                        renameDialog.oldName = tagMenu.target.name
                        renameDialog.open()
                    }
                }
                MenuItem {
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
