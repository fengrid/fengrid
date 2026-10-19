import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ApplicationWindow {
    id: root
    width: 1280
    height: 800
    minimumWidth: 960
    minimumHeight: 560
    visible: true
    title: qsTr("Fengrid — the UI asset explorer")
    color: theme.tokens.bg
    font.family: theme.uiFont
    font.pixelSize: 13

    property int iconSize: sizeSlider.value

    // tinted Feather-style icon button (content is token-driven, no emoji)
    component IconButton: ToolButton {
        id: btn
        property string icon_name: ""
        property int icon_px: 16
        icon.width: 0
        icon.height: 0
        implicitWidth: 30
        implicitHeight: 30
        contentItem: IconImage {
            name: btn.icon_name
            tint: btn.hovered || btn.pressed ? theme.tokens.text
                                             : theme.tokens.textMuted
            px: btn.icon_px
            anchors.centerIn: parent
        }
        background: Rectangle {
            radius: 6
            color: btn.pressed ? theme.tokens.surface2
                               : (btn.hovered ? theme.tokens.surface2 : "transparent")
        }
        ToolTip.visible: hovered && ToolTip.text.length > 0
        ToolTip.delay: 400
    }

    header: Rectangle {
        height: 52
        color: theme.tokens.surface

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 10
            spacing: 12

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

            Rectangle {
                id: searchBox
                Layout.preferredWidth: 320
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

                    IconImage { name: "search"; px: 15; tint: theme.tokens.textMuted }

                    TextField {
                        id: searchField
                        Layout.fillWidth: true
                        placeholderText: qsTr("search assets  ( / )")
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
                px: 15
                tint: theme.tokens.textMuted
                Layout.alignment: Qt.AlignVCenter
            }
            Slider {
                id: sizeSlider
                from: 16
                to: 256
                stepSize: 16
                value: 32
                Layout.preferredWidth: 130
                Layout.alignment: Qt.AlignVCenter
            }
            Text {
                text: sizeSlider.value + "px"
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
                Layout.preferredWidth: 40
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

    RowLayout {
        anchors.fill: parent
        spacing: 0

        SideRail {
            Layout.preferredWidth: 210
            Layout.fillHeight: true
        }
        Rectangle {
            width: 1
            Layout.fillHeight: true
            color: theme.tokens.border
        }

        AssetGrid {
            id: grid
            Layout.fillWidth: true
            Layout.fillHeight: true
            iconPx: root.iconSize
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
            visible: grid.currentIndex >= 0
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
                text: library !== null
                      ? (library.scanning
                         ? qsTr("indexing… %1").arg(library.scanCount)
                         : qsTr("%1 assets%2").arg(library.totalAssets)
                           .arg(library.lastScan !== ""
                                ? qsTr(" · indexed ") + library.lastScan : ""))
                      : ""
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "fengrid " + appVersion
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
            }
        }
    }

    Shortcut {
        sequence: "/"
        enabled: !searchField.activeFocus
        onActivated: {
            searchField.forceActiveFocus()
            searchField.selectAll()
        }
    }
    Shortcut {
        sequence: "Ctrl+C"
        enabled: grid.currentIndex >= 0
        onActivated: library.copy_name(grid.currentIndex)
    }
    Shortcut {
        sequence: "Escape"
        enabled: grid.currentIndex >= 0
        onActivated: grid.currentIndex = -1
    }

    Toast { id: toast }

    Connections {
        target: library
        function onMessage(msg) { toast.show(msg) }
        function onExportDone(path) { toast.show(qsTr("Exported to %1").arg(path)) }
        function onExportFailed(err) { toast.show(qsTr("Export failed: %1").arg(err)) }
    }
}
