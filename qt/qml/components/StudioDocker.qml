import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// DOCKER screen — package, ship, and inspect projects in containers.
// Config (image/name/ports/volumes/env/build context) persists in the
// project settings; actions run against the local docker daemon; the
// file browser attaches Fengrid's tools to container-local storage.
Item {
    id: dockRoot
    component SectionLabel: Text {
        font.family: theme.monoFont
        font.pixelSize: 9
        font.letterSpacing: 1.4
        color: theme.tokens.accent
    }


    property var st: null               // Studio bridge
    property string browsePath: "/"
    property string logText: ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: st && st.dockerOk
                      ? qsTr("docker %1 — connected").arg(dockerVersion())
                      : qsTr("docker daemon not reachable")
                font.family: theme.monoFont; font.pixelSize: 10
                color: st && st.dockerOk ? theme.tokens.success
                                         : theme.tokens.litPane
            }
            Item { Layout.fillWidth: true }
            Text {
                property var state: st ? st.dockerState : {"exists": false}
                text: state.exists
                      ? (state.running
                         ? qsTr("● %1 running — %2").arg(state.status)
                           .arg(state.ports.join(" "))
                         : qsTr("○ %1 stopped").arg(state.status))
                      : qsTr("no container yet")
                font.family: theme.monoFont; font.pixelSize: 10
                color: state.exists && state.running
                       ? theme.tokens.success : theme.tokens.textMuted
            }
        }

        GridLayout {
            columns: 2
            columnSpacing: 10
            rowSpacing: 6
            Layout.fillWidth: true

            Text { text: qsTr("image (tag)"); font.family: theme.uiFont
                   font.pixelSize: 10; color: theme.tokens.textMuted }
            FormInput { id: cfgImage; Layout.fillWidth: true }
            Text { text: qsTr("container name"); font.family: theme.uiFont
                   font.pixelSize: 10; color: theme.tokens.textMuted }
            FormInput { id: cfgName; Layout.fillWidth: true }
            Text { text: qsTr("ports (host:cont, …)")
                   font.family: theme.uiFont; font.pixelSize: 10
                   color: theme.tokens.textMuted }
            FormInput { id: cfgPorts; Layout.fillWidth: true }
            Text { text: qsTr("volumes (/host:/cont, …)")
                   font.family: theme.uiFont; font.pixelSize: 10
                   color: theme.tokens.textMuted }
            FormInput { id: cfgVolumes; Layout.fillWidth: true }
            Text { text: qsTr("env (NAME=value, …)")
                   font.family: theme.uiFont; font.pixelSize: 10
                   color: theme.tokens.textMuted }
            FormInput { id: cfgEnv; Layout.fillWidth: true }
            Text { text: qsTr("build context (dir with Dockerfile)")
                   font.family: theme.uiFont; font.pixelSize: 10
                   color: theme.tokens.textMuted }
            RowLayout {
                Layout.fillWidth: true
                FormInput { id: cfgCtx; Layout.fillWidth: true }
                FgButton {
                    text: qsTr("Browse…")
                    onClicked: ctxDialog.open()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            FgButton {
                text: qsTr("Save config")
                onClicked: dockRoot.writeCfg()
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Stored with the project settings")
            }
            FgButton {
                text: qsTr("Build")
                enabled: st && st.dockerOk
                onClicked: { dockRoot.writeCfg(); st.dockerBuild() }
            }
            FgButton {
                text: qsTr("Run")
                enabled: st && st.dockerOk
                onClicked: { dockRoot.writeCfg(); st.dockerRun() }
            }
            FgButton {
                text: qsTr("Stop")
                enabled: st && st.dockerOk
                onClicked: st.dockerStop()
            }
            FgButton {
                text: qsTr("Remove")
                enabled: st && st.dockerOk
                onClicked: st.dockerRm()
            }
            FgButton {
                text: qsTr("Logs")
                enabled: st && st.dockerOk
                onClicked: st.dockerLogs(300)
            }
        }

        // logs
        SectionLabel { text: qsTr("Logs") }
        TextArea {
            id: logView
            Layout.fillWidth: true
            Layout.preferredHeight: 130
            readOnly: true
            wrapMode: TextArea.Wrap
            text: dockRoot.logText
            font.family: theme.monoFont; font.pixelSize: 10
            color: theme.tokens.text
            background: Rectangle {
                radius: 6; color: theme.tokens.bg
                border.color: theme.tokens.border
            }
        }

        // container filesystem browser
        SectionLabel { text: qsTr("Container files") }
        RowLayout {
            Layout.fillWidth: true
            FormInput {
                id: pathField
                Layout.fillWidth: true
                label: ""
                text: dockRoot.browsePath
                onEditingFinished: dockRoot.browsePath = text
            }
            FgButton {
                text: qsTr("List")
                enabled: st && st.dockerOk
                onClicked: dockRoot.refresh()
            }
        }
        ListView {
            id: fileList
            Layout.fillWidth: true
            Layout.preferredHeight: 150
            clip: true
            model: []
            ScrollBar.vertical: ScrollBar { }
            delegate: RowLayout {
                width: fileList.width
                spacing: 6
                Text {
                    text: modelData.dir ? "▸ " : "· "
                    color: theme.tokens.textMuted
                    font.pixelSize: 10
                }
                Text {
                    Layout.fillWidth: true
                    text: modelData.name
                    font.family: theme.monoFont; font.pixelSize: 10
                    color: modelData.dir ? theme.tokens.accent
                                         : theme.tokens.text
                    elide: Text.ElideRight
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: modelData.dir
                                     ? Qt.PointingHandCursor
                                     : Qt.ArrowCursor
                        onClicked: {
                            if (modelData.dir) {
                                dockRoot.browsePath = modelData.path
                                dockRoot.refresh()
                            }
                        }
                    }
                }
                FgButton {
                    text: qsTr("Copy out")
                    flat: true
                    ToolTip.visible: hovered
                    ToolTip.text: qsTr("Copy into a local scratch dir so " +
                                       "scans/imports can process it")
                    onClicked: st.dockerCopyOut(modelData.path)
                }
            }
            Text {
                anchors.centerIn: parent
                visible: fileList.count === 0
                text: qsTr("Run the container, then browse its files here")
                color: theme.tokens.textMuted
                font.family: theme.uiFont; font.pixelSize: 10
            }
        }
        Item { Layout.fillHeight: true }
    }

    function dockerVersion() { return "daemon" }

    function writeCfg() {
        var env = {}
        var bits = cfgEnv.text.split(",")
        for (var i = 0; i < bits.length; i++) {
            var kv = bits[i].split("=")
            if (kv.length === 2 && kv[0].trim())
                env[kv[0].trim()] = kv[1].trim()
        }
        var ports = cfgPorts.text.split(",").map(function (s) {
            return s.trim() }).filter(function (s) { return s !== "" })
        var vols = cfgVolumes.text.split(",").map(function (s) {
            return s.trim() }).filter(function (s) { return s !== "" })
        st.setDockerCfg(JSON.stringify({
            image: cfgImage.text.trim(),
            name: cfgName.text.trim(),
            ports: ports, volumes: vols, env: env,
            context: cfgCtx.text.trim()
        }))
    }

    function loadCfg() {
        var cfg = st ? st.dockerCfg : {}
        cfgImage.text = cfg.image || ""
        cfgName.text = cfg.name || ""
        cfgPorts.text = (cfg.ports || []).join(", ")
        cfgVolumes.text = (cfg.volumes || []).join(", ")
        var envBits = []
        for (var k in (cfg.env || {}))
            envBits.push(k + "=" + cfg.env[k])
        cfgEnv.text = envBits.join(", ")
        cfgCtx.text = cfg.context || ""
    }

    function refresh() {
        if (!st) return
        fileList.model = st.dockerBrowse(browsePath)
    }

    Component.onCompleted: loadCfg()
    Connections {
        target: st
        function onDockerChanged() { dockRoot.loadCfg() }
        function onDockerLog(text) { dockRoot.logText = text }
    }

    FolderDialog {
        id: ctxDialog
        onAccepted: cfgCtx.text = Icons.toLocalPath(selectedFolder)
    }
}
