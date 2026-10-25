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
                    text: qsTr("filter families…")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }

            Text {
                text: fonts !== null
                      ? (fonts.scanning
                         ? qsTr("indexing… %1").arg(fonts.scanCount)
                         : qsTr("%1 families · %2 files")
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
                enabled: fonts !== null && fonts.selectedFamily !== ""
                         && !fonts.scanning
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
                label: fonts !== null && fonts.selectedFamily !== ""
                       ? qsTr("Export CSS — %1").arg(fonts.selectedFamily)
                       : qsTr("Export CSS")
                onClicked: cssDialog.openWith(fonts.selectedFamily)
            }
            ExportButton {
                label: qsTr(".zip")
                onClicked: zipExport.openWith(
                    [{ id: "zip", label: qsTr("ZIP (fonts + CSS + README)") }],
                    library !== null ? library.lastExportDir : "")
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
                    anchors.leftMargin: 10
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    text: qsTr("Fengrid 123")
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
                MouseArea {
                    id: famMa
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    // single click selects; the Details tab of the
                    // property inspector (right panel) carries the
                    // specimen view — no more popup on click
                    onClicked: function (mouse) {
                        if (fonts === null)
                            return
                        // left-click selects (inspector follows);
                        // right-click opens the menu for the CURRENT
                        // selection without moving it
                        if (mouse.button === Qt.LeftButton)
                            fonts.select(model.family)
                        else
                            famMenu.popup()
                    }
                }
            }
        }

        // family context menu: details, exports, collection
        Menu {
            id: famMenu
            width: 190
            padding: 4
            background: Rectangle {
                radius: 8; color: theme.tokens.surface
                border.color: theme.tokens.border
            }
            FgMenuItem {
                text: qsTr("Export CSS…")
                height: 28
                onTriggered:
                    cssDialog.openWith(fonts.selectedFamily)
            }
            FgMenuItem {
                text: qsTr("Export ZIP…")
                height: 28
                onTriggered: zipExport.openWith(
                    [{ id: "zip", label: qsTr("ZIP (fonts + CSS + README)") }],
                    library !== null ? library.lastExportDir : "")
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
                         ? qsTr("No fonts indexed yet")
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
    function openExportZip() {
        zipExport.openWith(
            [{ id: "zip", label: qsTr("ZIP (fonts + CSS + README)") }],
            library !== null ? library.lastExportDir : "")
    }
    FontsCssDialog { id: cssDialog }
    ExportDialog {
        id: zipExport
        headline: qsTr("Export font family")
        onDoExport: function (formats, dest) {
            if (fonts === null || fonts.selectedFamily === "")
                return
            fonts.export_zip(fonts.selectedFamily, dest)
        }
    }
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
