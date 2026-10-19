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
                onClicked: {
                    exportZip = false
                    exportDialog.open()
                }
            }
            ExportButton {
                label: qsTr(".zip")
                onClicked: {
                    exportZip = true
                    exportDialog.open()
                }
            }
            IconButton {
                icon_name: "refresh"
                enabled: fonts !== null && !fonts.scanning
                ToolTip.text: qsTr("Re-scan font folders")
                onClicked: fonts.rescan()
            }
        }
    }

    property bool exportZip: false

    FolderDialog {
        id: exportDialog
        onAccepted: {
            var dest = Icons.toLocalPath(selectedFolder)
            if (fonts === null || fonts.selectedFamily === "")
                return
            if (exportZip)
                fonts.export_zip(fonts.selectedFamily, dest)
            else
                fonts.export_css(fonts.selectedFamily, dest)
        }
    }

    // selected-family detail strip (files, weights) — a slim footer row
    Rectangle {
        id: detailStrip
        height: fonts !== null && fonts.selectedFamily !== "" ? 64 : 0
        visible: height > 0
        color: theme.tokens.surface
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        border.width: 0

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 8
            visible: detailStrip.height > 0

            Text {
                text: fonts !== null ? fonts.selectedFamily : ""
                font.family: theme.headingFont
                font.pixelSize: 16
                color: theme.tokens.text
            }
            Repeater {
                model: fonts !== null && fonts.selectedFamily !== ""
                       ? fonts.family_files(fonts.selectedFamily) : []
                Rectangle {
                    required property var modelData
                    radius: 4
                    height: 24
                    width: fileLabel.implicitWidth + 16
                    color: theme.tokens.surface2
                    Text {
                        id: fileLabel
                        anchors.centerIn: parent
                        text: (modelData.style || "Regular") + " · "
                              + (modelData.weight || 400)
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                }
            }
            Item { Layout.fillWidth: true }
            Text {
                text: qsTr("Select a family card to inspect it")
                visible: fonts !== null && fonts.selectedFamily === ""
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
            }
        }
    }

    GridView {
        id: famGrid
        anchors.top: toolbar.bottom
        anchors.bottom: detailStrip.top
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
                              ? theme.tokens.litPane
                              : (famMa.containsMouse ? theme.tokens.accent
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
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    anchors.left: parent.left
                    anchors.leftMargin: 10
                    text: model.family
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.textMuted
                    width: parent.width - 20
                    elide: Text.ElideRight
                }
                Text {
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    text: model.files + " · " + model.weights
                    font.family: theme.monoFont
                    font.pixelSize: 9
                    color: theme.tokens.textMuted
                }
                MouseArea {
                    id: famMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (fonts !== null)
                            fonts.select(model.family)
                    }
                }
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
}
