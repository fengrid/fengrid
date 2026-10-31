import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// Fonts pane (M2): family-grouped grid, filter, CSS/ZIP export.
// Previews are plain QML Text in each family's face — system fonts are
// registered with QFontDatabase, so no WebEngine is involved here.
Item {
    id: fontsRoot

    property string filter: ""

    // multi-select (#39/#52): the same pattern as AssetGrid — checkbox
    // click toggles, Ctrl-click toggles, Shift-click fills a range;
    // empty checkboxes show ONLY on hover of a card, once ANY box is
    // checked every checkbox stays visible. Export targets the checked
    // families when ≥1 is checked, else the selected family.
    property var checkedFams: []
    readonly property bool anyChecked: checkedFams.length > 0
    function toggleSelect(family) {
        var next = []
        for (var i = 0; i < checkedFams.length; i++)
            if (checkedFams[i] !== family)
                next.push(checkedFams[i])
        if (next.length === checkedFams.length)
            next.push(family)
        checkedFams = next
    }
    function isSelected(family) {
        return checkedFams.indexOf(family) >= 0
    }

    // `fonts !== null` guards mirror SideRail's: context properties are
    // nulled during app teardown while lingering bindings re-evaluate
    Rectangle {
        id: toolbar
        height: 40
        color: theme.tokens.surface
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 10
            spacing: 10

            IconImage { name: "file-text"; px: 14; tint: theme.tokens.textMuted }

            Rectangle {
                id: filterBox
                Layout.preferredWidth: 240
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: filterField.activeFocus ? theme.tokens.accent
                                                      : theme.tokens.border
                TextInput {
                    id: filterField
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                    onTextChanged: fontsRoot.filter = text
                }
                Text {
                    visible: filterField.text === ""
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Filter Families…")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }

            Text {
                text: fonts !== null
                      ? (fonts.scanning
                         ? qsTr("Indexing… %1").arg(fonts.scanCount)
                         : qsTr("%1 Families · %2 Files")
                             .arg(fonts.totalFamilies).arg(fonts.totalFonts))
                      : ""
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
            }

            Item { Layout.fillWidth: true }

            component ExportButton: AbstractButton {
                id: expBtn
                property string label
                implicitHeight: 26
                enabled: fonts !== null && !fonts.scanning
                         && (fontsRoot.anyChecked
                             || fonts.selectedFamily !== "")
                contentItem: Text {
                    text: expBtn.label
                    color: expBtn.enabled ? theme.tokens.text : theme.tokens.textMuted
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 10; rightPadding: 10
                }
                background: Rectangle {
                    radius: 6
                    color: expBtn.pressed ? theme.tokens.surface2
                                          : (expBtn.hovered ? theme.tokens.surface2
                                                            : "transparent")
                    border.color: theme.tokens.border
                }
            }
            ExportButton {
                // #114: the .zip button is redundant — the CSS dialog's
                // «Save as ZIP…» covers the same flow; one entry point
                label: fontsRoot.anyChecked
                       ? qsTr("Export Font(s) — %1 families")
                             .arg(fontsRoot.checkedFams.length)
                       : (fonts !== null && fonts.selectedFamily !== ""
                          ? qsTr("Export Font(s) — %1").arg(fonts.selectedFamily)
                          : qsTr("Export Font(s)"))
                onClicked: cssDialog.openWith(fontsRoot.anyChecked
                                              ? fontsRoot.checkedFams
                                              : fonts.selectedFamily)
            }
            IconButton {
                icon_name: "refresh"
                enabled: fonts !== null && !fonts.scanning
                ToolTip.text: qsTr("Re-scan font folders")
                onClicked: fonts.rescan()
            }
        }
    }

    // selected-family detail strip — removed: the property inspector's
    // Details tab (right panel) carries the family, variants and specimen

    GridView {
        id: famGrid
        anchors.top: toolbar.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 10
        clip: true
        reuseItems: true
        cacheBuffer: 800
        model: fonts !== null ? fonts.model : null
        cellWidth: 220
        cellHeight: 120

        ScrollBar.vertical: ScrollBar { }

        delegate: Item {
            width: famGrid.cellWidth
            height: famGrid.cellHeight

            Rectangle {
                id: famCard
                anchors.fill: parent
                anchors.margins: 4
                radius: 8
                color: famMa.containsMouse ? theme.tokens.surface2
                                           : theme.tokens.surface
                border.color: fonts !== null && fonts.selectedFamily === model.family
                              ? theme.tokens.accentFont
                              : (famMa.containsMouse ? theme.tokens.accentFont
                                                     : theme.tokens.border)
                border.width: fonts !== null && fonts.selectedFamily === model.family
                              ? 2 : 1

                Text {
                    id: preview
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    anchors.left: parent.left
                    // clear the selection checkbox (#39/#52) when visible
                    anchors.leftMargin: famSelBox.visible ? 28 : 10
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    // curated default specimen: a passage whose word
                    // shapes fit this preview size (bucket "medium" at
                    // the fixed 26px card size); swaps at only three
                    // breakpoints pane-wide; disabled when the user
                    // types custom text in the inspector's sample field
                    text: fonts !== null && !fonts.sampleCustom
                          ? fonts.preview_text(26) : qsTr("Fengrid 123")
                    font.family: model.family
                    font.pixelSize: 26
                    elide: Text.ElideRight
                    color: theme.tokens.text
                }
                Text {
                    id: famName
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    anchors.left: parent.left
                    anchors.leftMargin: 10
                    width: parent.width - 20
                    text: model.family
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.textMuted
                    elide: Text.ElideRight
                }
                Text {
                    id: famMeta
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    // files count only — the weights list moved to the
                    // property inspector's Details tab (it overflowed the
                    // cells and crowded out the family name)
                    text: model.files === 1 ? qsTr("1 file")
                          : qsTr("%1 files").arg(model.files)
                    font.family: theme.monoFont
                    font.pixelSize: 9
                    color: theme.tokens.textMuted
                    visible: famName.truncated !== true
                }
                // selection checkbox (#39/#52) — empty boxes hover-only; once ANY
                // box is checked every checkbox is visible everywhere
                Rectangle {
                    id: famSelBox
                    width: 16
                    height: 16
                    radius: 4
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.margins: 5
                    visible: famMa.containsMouse || fontsRoot.anyChecked
                    color: fontsRoot.isSelected(model.family)
                           ? theme.tokens.accentFont : theme.tokens.surface
                    border.color: fontsRoot.isSelected(model.family)
                                  ? theme.tokens.accentFont
                                  : theme.tokens.textMuted
                    border.width: 1
                    z: 3
                    IconImage {
                        anchors.centerIn: parent
                        name: "check"
                        px: 10
                        tint: theme.tokens.bg
                        visible: fontsRoot.isSelected(model.family)
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: fontsRoot.toggleSelect(model.family)
                    }
                }
                MouseArea {
                    id: famMa
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    onClicked: function (mouse) {
                        if (fonts === null)
                            return
                        if (mouse.button === Qt.LeftButton) {
                            if (mouse.modifiers & (Qt.ControlModifier
                                                   | Qt.ShiftModifier)) {
                                // Ctrl toggles this card; Shift fills a
                                // range from the anchor card (AssetGrid
                                // semantics — #39/#52)
                                var start = famGrid.currentIndex >= 0
                                            ? famGrid.currentIndex : index
                                if (mouse.modifiers & Qt.ShiftModifier) {
                                    var lo = Math.min(start, index)
                                    var hi = Math.max(start, index)
                                    var next = fontsRoot.checkedFams.slice()
                                    for (var r = lo; r <= hi; r++) {
                                        var fam = fonts.model.family_at(r)
                                        if (fam !== ""
                                            && next.indexOf(fam) < 0)
                                            next.push(fam)
                                    }
                                    fontsRoot.checkedFams = next
                                } else {
                                    fontsRoot.toggleSelect(model.family)
                                }
                                famGrid.currentIndex = index
                            } else {
                                fontsRoot.checkedFams = []
                                famGrid.currentIndex = index
                                fonts.select(model.family)
                            }
                            famGrid.forceActiveFocus()
                        } else {
                            // right-click opens the menu for the CURRENT
                            // selection without moving it
                            famMenu.popup()
                        }
                    }
                }
            }
        }

        // family context menu: pane-specific exports + the COMMON
        // asset entries (edit / star / taxonomy / properties). All
        // actions target the CURRENT selection (right-click never
        // moves it) — see FontsCssDialog for the export flows.
        Menu {
            id: famMenu
            width: 210
            padding: 4
            background: Rectangle {
                radius: 8; color: theme.tokens.surface
                border.color: theme.tokens.border
            }
            onAboutToShow: starItem.starred =
                           fonts !== null && fonts.selectedFamily !== ""
                           && fonts.family_starred(fonts.selectedFamily)

            // ── pane-specific ──
            FgMenuItem {
                text: qsTr("Export CSS + webfonts…")
                height: 28
                onTriggered: cssDialog.openWith(fonts.selectedFamily)
            }
            FgMenuSeparator {
                topPadding: 3; bottomPadding: 3
                contentItem: Rectangle { implicitHeight: 1; color: theme.tokens.border }
            }
            // ── common: edit ──
            FgMenuItem {
                text: qsTr("Copy name")
                height: 28
                onTriggered: library !== null && fonts !== null
                             && fonts.selectedFamily !== ""
                             && library.copy_text(fonts.selectedFamily)
            }
            // ── common: star ──
            FgMenuItem {
                id: starItem
                property bool starred: false
                text: starred ? qsTr("Unstar family") : qsTr("Star family")
                height: 28
                enabled: fonts !== null && fonts.selectedFamily !== ""
                onTriggered: fonts.star_family(fonts.selectedFamily,
                                               !starred)
            }
            // ── common: taxonomy — collections (submenu) ──
            FgMenuItem {
                id: famCollItem
                text: qsTr("Add to collection…")
                height: 28
                enabled: library !== null
                         && library.collections.length > 0
                         && fonts !== null && fonts.selectedFamily !== ""
                Menu {
                    id: famCollSub
                    cascade: true
                    width: 220
                    padding: 4
                    background: Rectangle {
                        radius: 8; color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    Repeater {
                        model: library !== null ? library.collections : []
                        FgMenuItem {
                            id: famCollTarget
                            required property var modelData
                            height: 28
                            onTriggered: {
                                if (fonts === null
                                        || fonts.selectedFamily === "")
                                    return
                                library.add_item_to_collection(
                                    famCollTarget.modelData.id, "font",
                                    fonts.family_primary_id(
                                        fonts.selectedFamily),
                                    fonts.selectedFamily)
                            }
                            contentItem: Text {
                                text: famCollTarget.modelData.name
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                            }
                            background: Rectangle {
                                color: famCollTarget.hovered
                                       ? theme.tokens.surface2
                                       : "transparent"
                                radius: 5
                            }
                        }
                    }
                }
            }
            // ── common: taxonomy — links (submenu) ──
            FgMenuItem {
                id: famLinkItem
                text: qsTr("Link to…")
                height: 28
                enabled: taxonomy !== null
                         && taxonomy.link_targets().length > 0
                         && fonts !== null && fonts.selectedFamily !== ""
                Menu {
                    id: famLinkSub
                    cascade: true
                    width: 230
                    padding: 4
                    background: Rectangle {
                        radius: 8; color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    Repeater {
                        model: taxonomy !== null
                               ? taxonomy.link_targets() : []
                        FgMenuItem {
                            id: famLinkTarget
                            required property var modelData
                            height: 28
                            onTriggered: {
                                if (fonts === null
                                        || fonts.selectedFamily === "")
                                    return
                                taxonomy.add_link(
                                    "font",
                                    fonts.family_primary_id(
                                        fonts.selectedFamily),
                                    famLinkTarget.modelData.kind,
                                    famLinkTarget.modelData.id, "")
                            }
                            contentItem: Text {
                                text: famLinkTarget.modelData.label
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                            }
                            background: Rectangle {
                                color: famLinkTarget.hovered
                                       ? theme.tokens.surface2
                                       : "transparent"
                                radius: 5
                            }
                        }
                    }
                }
            }
            // ── common: properties ──
            FgMenuItem {
                text: qsTr("Properties")
                height: 28
                enabled: fonts !== null && fonts.selectedFamily !== ""
                onTriggered: fonts.select(fonts.selectedFamily)
                // selecting re-targets the property inspector (left-
                // click behaviour, explicitly chosen here)
            }
        }

        // empty / scanning states — mirrors AssetGrid's empty column
        Column {
            anchors.centerIn: parent
            visible: famGrid.count === 0
            spacing: 14
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: fonts !== null && fonts.scanning
                      ? qsTr("Indexing your font folders…")
                      : (fonts !== null && fonts.totalFonts === 0
                         ? qsTr("No fonts indexed yet — run a scan to "
                                + "populate the Types and Families lists")
                         : qsTr("No families match the filter"))
                color: theme.tokens.text
                font.family: theme.uiFont
                font.pixelSize: 14
            }
            Button {
                id: fontCta
                anchors.horizontalCenter: parent.horizontalCenter
                enabled: fonts === null ? false : !fonts.scanning
                text: fonts !== null && fonts.scanning ? qsTr("Scanning…")
                      : qsTr("Scan now")
                onClicked: fonts.rescan()
                background: Rectangle {
                    radius: 6
                    color: fontCta.enabled ? theme.tokens.accent
                                           : theme.tokens.border
                }
                contentItem: Text {
                    text: fontCta.text
                    color: theme.tokens.bg
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }

    // export dialogs (unified interface) + result feedback
    function openExportCss() { cssDialog.openWith(fonts.selectedFamily) }
    FontsCssDialog { id: cssDialog }
    Toast { id: exportToast }
    Connections {
        target: fonts
        function onExportDone(path) {
            exportToast.show(qsTr("Exported: %1").arg(path))
        }
        function onExportFailed(err) {
            exportToast.show(qsTr("Export failed: %1").arg(err))
        }
    }
}
