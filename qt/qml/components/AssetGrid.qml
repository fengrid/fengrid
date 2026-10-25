import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: gridRoot
    property int iconPx: 32
    property alias currentIndex: grid.currentIndex
    property alias count: grid.count
    // multi-select: checkbox click, Ctrl-click toggle, Shift-click range;
    // empty checkboxes show ONLY on hover of a preview — once any box is
    // checked, every checkbox stays visible (bulk-selection affordance)
    property var selectedIds: []
    readonly property bool anySelected: selectedIds.length > 0
    function toggleSelect(id) {
        var next = []
        for (var i = 0; i < selectedIds.length; i++)
            if (selectedIds[i] !== id)
                next.push(selectedIds[i])
        if (next.length === selectedIds.length)
            next.push(id)
        selectedIds = next
    }
    function isSelected(id) {
        return selectedIds.indexOf(id) >= 0
    }
    Connections {
        target: library
        function onListsChanged() { gridRoot.selectedIds = [] }
    }

    GridView {
        id: grid
        anchors.fill: parent
        anchors.margins: 10
        model: library.model
        clip: true
        reuseItems: true
        cacheBuffer: 1200
        currentIndex: -1
        cellWidth: Math.max(gridRoot.iconPx + 24, 84)
        cellHeight: cellWidth + 26

        ScrollBar.vertical: ScrollBar { }

        delegate: Item {
            width: grid.cellWidth
            height: grid.cellHeight

            Rectangle {
                id: card
                anchors.fill: parent
                anchors.margins: 4
                radius: 8
                color: cardMa.containsMouse ? theme.tokens.surface2
                                            : theme.tokens.surface
                border.color: grid.currentIndex === index
                              ? theme.tokens.litPane
                              : (cardMa.containsMouse ? theme.tokens.accent
                                                      : theme.tokens.border)
                border.width: grid.currentIndex === index ? 2 : 1

                // selection checkbox — empty boxes hover-only; once ANY
                // box is checked every checkbox is visible everywhere
                Rectangle {
                    id: selBox
                    width: 16
                    height: 16
                    radius: 4
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.margins: 5
                    visible: cardMa.containsMouse || gridRoot.anySelected
                    color: gridRoot.isSelected(model.id)
                           ? theme.tokens.accent : theme.tokens.surface
                    border.color: gridRoot.isSelected(model.id)
                                  ? theme.tokens.accent
                                  : theme.tokens.textMuted
                    border.width: 1
                    z: 3
                    IconImage {
                        anchors.centerIn: parent
                        name: "check"
                        px: 10
                        tint: theme.tokens.bg
                        visible: gridRoot.isSelected(model.id)
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: gridRoot.toggleSelect(model.id)
                    }
                }

                Image {
                    id: thumb
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -10
                    width: gridRoot.iconPx
                    height: gridRoot.iconPx
                    source: Icons.fileUrl(model.path)
                    asynchronous: true
                    sourceSize.width: gridRoot.iconPx * 2
                    sourceSize.height: gridRoot.iconPx * 2
                    fillMode: Image.PreserveAspectFit
                    visible: status !== Image.Error
                }
                IconImage {
                    id: placeholder
                    anchors.centerIn: thumb
                    visible: thumb.status === Image.Error
                    name: "image"
                    px: Math.min(28, gridRoot.iconPx)
                    tint: theme.tokens.textMuted
                }
                // starred badge — filled star, top-right of the card
                Image {
                    id: starBadge
                    visible: model.starred === true || model.starred === 1
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: 5
                    width: 13
                    height: 13
                    sourceSize.width: 26
                    sourceSize.height: 26
                    source: Icons.url("star", theme.tokens.litPane,
                                      theme.tokens.litPane)
                }
                Text {
                    id: cardLabel
                    anchors.bottom: parent.bottom
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottomMargin: 6
                    width: parent.width - 12
                    text: model.name
                    elide: Text.ElideRight
                    horizontalAlignment: Text.AlignHCenter
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.textMuted
                    ToolTip.visible: cardMa.containsMouse && cardLabel.truncated
                    ToolTip.text: model.name
                    ToolTip.delay: 350
                }
                MouseArea {
                    id: cardMa
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    onClicked: function (mouse) {
                        // left-click selects (inspector follows);
                        // right-click opens the menu for the CURRENT
                        // selection without moving it
                        if (mouse.button === Qt.LeftButton) {
                            if (mouse.modifiers & (Qt.ControlModifier
                                                   | Qt.ShiftModifier)) {
                                var start = grid.currentIndex >= 0
                                            ? grid.currentIndex : index
                                if (mouse.modifiers & Qt.ShiftModifier) {
                                    // range from the anchor item
                                    var lo = Math.min(start, index)
                                    var hi = Math.max(start, index)
                                    var ids = []
                                    for (var r = lo; r <= hi; r++) {
                                        var rid = library.row_id(r)
                                        if (rid >= 0 && !gridRoot
                                            .isSelected(rid))
                                            ids.push(rid)
                                    }
                                    gridRoot.selectedIds =
                                            gridRoot.selectedIds.concat(ids)
                                } else {
                                    gridRoot.toggleSelect(model.id)
                                }
                                grid.currentIndex = index
                            } else {
                                gridRoot.selectedIds = []
                                grid.currentIndex = index
                            }
                            grid.forceActiveFocus()
                        } else if (gridRoot.anySelected) {
                            bulkMenu.popup()
                        } else {
                            cardMenu.popup()
                        }
                    }
                    onDoubleClicked: library.copy_name(index)
                }
            }
        }

        // right-click context menu for the selected asset
        Menu {
            id: cardMenu
            width: 210
            padding: 4

            background: Rectangle {
                radius: 8
                color: theme.tokens.surface
                border.color: theme.tokens.border
            }

            onOpened: {
                var st = library.is_starred(grid.currentIndex)
                starItem.starred = st
                starItem.text = st ? qsTr("Unstar") : qsTr("Star")
            }

            FgMenuItem {
                id: starItem
                property bool starred: false
                height: 30
                onTriggered: library.set_starred(grid.currentIndex, !starred)
                contentItem: Text {
                    text: starItem.text
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: starItem.starred ? theme.tokens.textMuted
                                            : theme.tokens.hlInk
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 10
                }
                background: Rectangle {
                    color: starItem.hovered ? theme.tokens.surface2
                                            : "transparent"
                    radius: 5
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
                id: copyItem
                text: qsTr("Copy name")
                height: 30
                onTriggered: library.copy_name(grid.currentIndex)
                contentItem: Text {
                    text: copyItem.text
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 10
                }
                background: Rectangle {
                    color: copyItem.hovered ? theme.tokens.surface2
                                            : "transparent"
                    radius: 5
                }
            }
            // LINK TO — typed links to collections / libraries / projects
            // (targets pulled live when the submenu opens; cascade handles
            // open/close — hover-popup was the broken-submenu bug, #21)
            FgMenuItem {
                id: linkItem
                text: qsTr("Link to…")
                height: 30
                contentItem: Text {
                    text: linkItem.text
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 10
                }
                background: Rectangle {
                    color: linkItem.hovered ? theme.tokens.surface2
                                            : "transparent"
                    radius: 5
                }
                Menu {
                    id: linkSub
                        cascade: true
                    onAboutToShow: targets = taxonomy !== null
                                   ? taxonomy.link_targets() : []
                    property var targets: []
                    width: 230
                    padding: 4
                    background: Rectangle {
                        radius: 8; color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    Repeater {
                        model: linkItem.targets
                        FgMenuItem {
                            id: linkTarget
                            required property var modelData
                            height: 28
                            onTriggered: {
                                var row = library.row(grid.currentIndex)
                                if (row === null || taxonomy === null)
                                    return
                                taxonomy.add_link("icon", row.id,
                                                  linkTarget.modelData.kind,
                                                  linkTarget.modelData.id, "")
                            }
                            contentItem: Text {
                                text: linkTarget.modelData.label
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                            }
                            background: Rectangle {
                                color: linkTarget.hovered
                                       ? theme.tokens.surface2 : "transparent"
                                radius: 5
                            }
                        }
                    }
                }
            }
            // GENERATE ID — one item per id-type custom field
            FgMenuItem {
                id: genIdItem
                property var idFields: []
                text: qsTr("Generate ID…")
                height: 30
                enabled: idFields.length > 0
                onHoveredChanged: {
                    if (!hovered || taxonomy === null)
                        return
                    var out = []
                    var all = taxonomy.fields
                    for (var i = 0; i < all.length; i++)
                        if (all[i].type === "id")
                            out.push(all[i])
                    idFields = out
                    genIdSub.open(genIdItem, genIdItem.width, 0)
                }
                contentItem: Text {
                    text: genIdItem.text
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: genIdItem.enabled
                           ? theme.tokens.text : theme.tokens.textMuted
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 10
                }
                background: Rectangle {
                    color: genIdItem.hovered ? theme.tokens.surface2
                                             : "transparent"
                    radius: 5
                }
                Menu {
                    id: genIdSub
                    width: 200
                    padding: 4
                    background: Rectangle {
                        radius: 8; color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    Repeater {
                        model: genIdItem.idFields
                        FgMenuItem {
                            id: genIdTarget
                            required property var modelData
                            height: 28
                            onTriggered: {
                                var row = library.row(grid.currentIndex)
                                if (row === null || taxonomy === null)
                                    return
                                taxonomy.generate_id(row.id,
                                                     genIdTarget.modelData.id)
                            }
                            contentItem: Text {
                                text: genIdTarget.modelData.name
                                font.family: theme.monoFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                            }
                            background: Rectangle {
                                color: genIdTarget.hovered
                                       ? theme.tokens.surface2 : "transparent"
                                radius: 5
                            }
                        }
                    }
                }
            }
            FgMenuItem {
                id: exportItem
                text: qsTr("Export…")
                height: 30
                onTriggered: cardExport.openWith(
                    [{ id: "png", label: "PNG" },
                     { id: "jpeg", label: "JPEG" },
                     { id: "webp", label: "WebP" },
                     { id: "ico", label: "ICO" },
                     { id: "pdf", label: "PDF" },
                     { id: "gif", label: "GIF" },
                     { id: "tiff", label: "TIFF" },
                     { id: "bmp", label: "BMP" }],
                    library !== null ? library.lastExportDir : "")
            }
            FgMenuItem {
                id: collMenuItem
                text: qsTr("Add to collection")
                height: 30
                enabled: library !== null && library.collections.length > 0
                contentItem: Text {
                    text: collMenuItem.text
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 10
                }
                background: Rectangle {
                    color: collMenuItem.hovered ? theme.tokens.surface2
                                                : "transparent"
                    radius: 5
                }

                Menu {
                    id: collSubmenu
                        cascade: true
                    width: 190
                    padding: 4
                    background: Rectangle {
                        radius: 8
                        color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    Repeater {
                        model: library !== null ? library.collections : []
                        FgMenuItem {
                            id: collItem
                            required property var modelData
                            text: collItem.modelData.name
                            height: 28
                            onTriggered: library.add_to_collection(
                                grid.currentIndex, collItem.modelData.id)
                            contentItem: Text {
                                text: collItem.modelData.name
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                            }
                            background: Rectangle {
                                color: collItem.hovered
                                       ? theme.tokens.surface2 : "transparent"
                                radius: 5
                            }
                        }
                    }
                }
            }

        // bulk actions over the multi-selection (right-click while ≥1
        // checkbox is checked)
        Menu {
            id: bulkMenu
            width: 220
            padding: 4
            background: Rectangle {
                radius: 8
                color: theme.tokens.surface
                border.color: theme.tokens.border
            }
            FgMenuItem {
                text: qsTr("Star all selected (%1)").arg(
                          gridRoot.selectedIds.length)
                height: 28
                onTriggered: {
                    for (var i = 0; i < gridRoot.selectedIds.length; i++)
                        library.set_starred_item(gridRoot.selectedIds[i],
                                                 true)
                    gridRoot.selectedIds = []
                }
            }
            FgMenuItem {
                text: qsTr("Unstar all selected")
                height: 28
                onTriggered: {
                    for (var i = 0; i < gridRoot.selectedIds.length; i++)
                        library.set_starred_item(gridRoot.selectedIds[i],
                                                 false)
                    gridRoot.selectedIds = []
                }
            }
            FgMenuItem {
                id: bulkCollItem
                text: qsTr("Add all to collection…")
                height: 28
                enabled: library !== null
                         && library.collections.length > 0
                Menu {
                    id: bulkCollSub
                        cascade: true
                    width: 200
                    padding: 4
                    background: Rectangle {
                        radius: 8; color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    Repeater {
                        model: library !== null ? library.collections : []
                        FgMenuItem {
                            id: bulkCollTarget
                            required property var modelData
                            height: 28
                            onTriggered: {
                                for (var i = 0; i < gridRoot.selectedIds
                                         .length; i++)
                                    library.add_item_to_collection(
                                        bulkCollTarget.modelData.id, "icon",
                                        gridRoot.selectedIds[i], "")
                                gridRoot.selectedIds = []
                            }
                            contentItem: Text {
                                text: bulkCollTarget.modelData.name
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                            }
                            background: Rectangle {
                                color: bulkCollTarget.hovered
                                       ? theme.tokens.surface2 : "transparent"
                                radius: 5
                            }
                        }
                    }
                }
            }
            FgMenuItem {
                text: qsTr("Clear selection")
                height: 28
                onTriggered: gridRoot.selectedIds = []
            }
        }
        }

        // empty / first-run / no-match states
        Column {
            anchors.centerIn: parent
            visible: grid.count === 0
            spacing: 14

            Grid {
                anchors.horizontalCenter: parent.horizontalCenter
                columns: 2
                spacing: 6
                Repeater {
                    model: 4
                    Rectangle {
                        width: 26; height: 26; radius: 6
                        color: "transparent"
                        border.color: theme.tokens.border
                        border.width: 2
                    }
                }
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(340, gridRoot.width - 40)
                text: (library !== null && library.scanning)
                      ? qsTr("Indexing your icon folders…")
                      : (library !== null && library.totalAssets === 0
                         ? qsTr("No assets found on this machine yet")
                         : qsTr("No assets match the current filters"))
                color: theme.tokens.text
                font.family: theme.uiFont
                font.pixelSize: 14
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }
            Button {
                id: emptyCta
                anchors.horizontalCenter: parent.horizontalCenter
                enabled: library === null ? false : !library.scanning
                text: library !== null && library.scanning ? qsTr("Scanning…")
                      : (library !== null && library.totalAssets === 0
                         ? qsTr("Scan now") : qsTr("Clear filters"))
                onClicked: library.totalAssets === 0 ? library.rescan()
                                                     : library.clear_filters()
                background: Rectangle {
                    radius: 6
                    color: emptyCta.enabled ? theme.tokens.accent
                                            : theme.tokens.border
                }
                contentItem: Text {
                    text: emptyCta.text
                    color: theme.tokens.bg
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 14
                    rightPadding: 14
                    topPadding: 6
                    bottomPadding: 6
                }
            }
        }
    }

    // unified export: multi-format, destination, size option
    property string exportSize: "orig"
    ExportDialog {
        id: cardExport
        headline: qsTr("Export asset")
        options: [
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    text: qsTr("size")
                    font.family: theme.monoFont; font.pixelSize: 10
                    color: theme.tokens.textMuted
                    Layout.preferredWidth: 40
                }
                ComboBox {
                    id: exportSizeBox
                    model: ["orig", "16", "32", "64", "128", "256"]
                    currentIndex: 0
                    onActivated: function (idx) {
                        cardExport.exportSize = exportSizeBox.model[idx]
                    }
                    background: Rectangle {
                        radius: 4; color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: exportSizeBox.displayText
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: theme.tokens.text
                        verticalAlignment: Text.AlignVCenter; leftPadding: 6
                    }
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: qsTr("applies to every selected format")
                    font.family: theme.uiFont; font.pixelSize: 9
                    color: theme.tokens.textMuted
                }
            }
        ]
        onDoExport: function (formats, dest) {
            for (var i = 0; i < formats.length; i++)
                library.export_asset(grid.currentIndex, formats[i],
                                     cardExport.exportSize, dest)
        }
    }
    Toast { id: exportToast }
    Connections {
        target: library
        function onExportDone(path) {
            exportToast.show(qsTr("Exported: %1").arg(path))
        }
        function onExportFailed(err) {
            exportToast.show(qsTr("Export failed: %1").arg(err))
        }
    }
}