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
                        grid.currentIndex = index
                        grid.forceActiveFocus()
                        if (mouse.button === Qt.RightButton)
                            cardMenu.popup()
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

            MenuItem {
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
            MenuSeparator {
                topPadding: 3
                bottomPadding: 3
                contentItem: Rectangle {
                    implicitHeight: 1
                    color: theme.tokens.border
                }
            }
            MenuItem {
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
            MenuItem {
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
                onHoveredChanged: if (hovered) collSubmenu.popup(
                                      collMenuItem, collMenuItem.width, 0)
                onClicked: collSubmenu.popup(
                               collMenuItem, collMenuItem.width, 0)

                Menu {
                    id: collSubmenu
                    width: 190
                    padding: 4
                    background: Rectangle {
                        radius: 8
                        color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    Repeater {
                        model: library !== null ? library.collections : []
                        MenuItem {
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
