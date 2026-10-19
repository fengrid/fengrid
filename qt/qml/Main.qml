import QtQuick
import QtQuick.Controls

// Placeholder shell — the workbench layout lands in M1
// (docs/architecture/0001-qt6-rewrite.md §10).
// Brand mark: the glint-quad (branding/assets/fengrid-mark.svg).
ApplicationWindow {
    id: root
    width: 960
    height: 640
    visible: true
    title: qsTr("Fengrid — the UI asset explorer")
    color: "#101418"

    Column {
        anchors.centerIn: parent
        spacing: 16

        // glint-quad: three outlined panes, one lit (amber, bottom-right)
        Grid {
            id: quad
            anchors.horizontalCenter: parent.horizontalCenter
            columns: 2
            spacing: 8

            Repeater {
                model: 4
                Rectangle {
                    width: 56
                    height: 56
                    radius: 12
                    color: index === 3 ? "#F5C25C" : "transparent"
                    border.color: index === 3 ? "transparent" : "#39B8C4"
                    border.width: 3
                }
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: qsTr("Fengrid")
            font.family: "Inter"
            font.pixelSize: 24
            font.weight: Font.DemiBold
            color: "#E7EDF2"
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: qsTr("skeleton — pipelines drafted, workbench pending (M1)")
            font.family: "Iosevka"
            font.pixelSize: 12
            color: "#39B8C4"
        }
    }
}
