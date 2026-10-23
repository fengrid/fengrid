import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// DOCS screen — auto-characterization: asset usage, link health,
// page inventory. The "describe" report the export manifest carries.
Item {
    id: docsRoot
    component SectionLabel: Text {
        font.family: theme.monoFont
        font.pixelSize: 9
        font.letterSpacing: 1.4
        color: theme.tokens.accent
    }


    property var st: null
    property var u: ({})

    function refresh() {
        if (st)
            u = st.usage
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 10

        SectionLabel { text: qsTr("Project report") }
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: docsRoot.u.pages !== undefined
                      ? qsTr("%1 pages · %2 blocks").arg(docsRoot.u.pages)
                        .arg(docsRoot.u.blocks)
                      : qsTr("no project open")
                font.family: theme.monoFont; font.pixelSize: 11
                color: theme.tokens.text
            }
            Item { Layout.fillWidth: true }
            Button {
                text: qsTr("Refresh")
                onClicked: docsRoot.refresh()
            }
        }

        SectionLabel { text: qsTr("Attached assets") }
        Flow {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: {
                    var a = docsRoot.u.attached_assets || {}
                    var out = []
                    for (var k in a) out.push(k + " (" + a[k] + ")")
                    return out
                }
                Rectangle {
                    radius: 9
                    color: theme.tokens.surface2
                    border.color: theme.tokens.border
                    width: chip.implicitWidth + 16
                    height: 22
                    Text {
                        id: chip
                        anchors.centerIn: parent
                        text: modelData
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: theme.tokens.text
                    }
                }
            }
        }

        SectionLabel { text: qsTr("Block types used") }
        Flow {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: {
                    var t = docsRoot.u.block_types || {}
                    var out = []
                    for (var k in t) out.push(k + " ×" + t[k])
                    return out
                }
                Rectangle {
                    radius: 9
                    color: "transparent"
                    border.color: theme.tokens.accentCode
                    width: chip2.implicitWidth + 16
                    height: 22
                    Text {
                        id: chip2
                        anchors.centerIn: parent
                        text: modelData
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: theme.tokens.text
                    }
                }
            }
        }

        SectionLabel { text: qsTr("Link health") }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font.family: theme.uiFont; font.pixelSize: 10
            color: (docsRoot.u.unresolved_refs || []).length > 0
                   ? theme.tokens.litPane : theme.tokens.success
            text: {
                var bad = docsRoot.u.unresolved_refs || []
                if (bad.length === 0)
                    return qsTr("All [[ refs ]] resolve ✓")
                return qsTr("Unresolved refs: %1").arg(bad.join(", "))
            }
        }

        SectionLabel { text: qsTr("Refs in use") }
        Text {
            Layout.fillWidth: true
            font.family: theme.monoFont; font.pixelSize: 10
            color: theme.tokens.textMuted
            text: {
                var r = docsRoot.u.refs || {}
                var out = []
                for (var k in r) out.push("[[ " + k + " ]] ×" + r[k])
                return out.join("\n") || qsTr("none yet")
            }
        }
        Item { Layout.fillHeight: true }
    }

    Component.onCompleted: refresh()
    Connections {
        target: st
        function onPagesChanged() { docsRoot.refresh() }
    }
    Connections {
        target: projects
        function onCurrentChanged() { docsRoot.refresh() }
    }
}
