import QtQuick
import QtQuick.Controls
import "."

Item {
    id: gridRoot
    property int iconPx: 32
    property alias currentIndex: grid.currentIndex
    property alias count: grid.count

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
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        grid.currentIndex = index
                        grid.forceActiveFocus()
                    }
                    onDoubleClicked: library.copy_name(index)
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
}
