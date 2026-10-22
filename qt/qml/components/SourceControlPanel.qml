import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Source control panel (Projects pane right rail) — GittyUp/VS Code-style:
// active worktree + branch, staged/unstaged/untracked change lists, small
// action buttons (commit, branch, merge, delete, push), and the history.
// Backed by the `sc` bridge (core.projects_git); inert when git is missing.
Rectangle {
    id: scRoot
    color: theme.tokens.surface
    radius: 8

    property bool hasRepo: sc !== null && sc.hasRepo()
    property string branch: hasRepo ? sc.currentBranch : ""
    property var st: hasRepo ? sc.status : {}

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 6

        // ── header: worktree + branch + status pill ──
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            IconImage { name: "git-branch"; px: 14
                        tint: theme.tokens.accentProject }
            Text {
                text: scRoot.hasRepo ? scRoot.branch : qsTr("no repository")
                font.family: theme.monoFont
                font.pixelSize: 11
                font.weight: Font.DemiBold
                color: theme.tokens.text
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Rectangle {
                visible: scRoot.hasRepo
                radius: 7
                width: statusText.implicitWidth + 12
                height: 18
                color: scRoot.st.clean ? theme.tokens.success
                                       : theme.tokens.litPane
                Text {
                    id: statusText
                    anchors.centerIn: parent
                    text: scRoot.st.clean ? qsTr("clean") : qsTr("dirty")
                    font.family: theme.monoFont
                    font.pixelSize: 9
                    color: "#101418"
                }
            }
        }

        // ── action row: small buttons (commit / branch / merge / push) ──
        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            component ScButton: AbstractButton {
                id: sb
                property string label
                property bool enabled2: true
                implicitHeight: 24
                enabled: enabled2 && scRoot.hasRepo
                contentItem: Text {
                    text: sb.label
                    color: sb.enabled ? theme.tokens.text : theme.tokens.textMuted
                    font.family: theme.uiFont
                    font.pixelSize: 10
                    horizontalAlignment: Text.AlignHCenter
                }
                background: Rectangle {
                    radius: 5
                    color: sb.hovered || sb.pressed
                           ? theme.tokens.surface2 : "transparent"
                    border.color: theme.tokens.border
                }
            }
            ScButton {
                label: qsTr("Commit")
                enabled2: !scRoot.st.clean
                onClicked: {
                    if (commitField.text.trim() !== "") {
                        sc.commit(commitField.text)
                        commitField.text = ""
                    } else {
                        toast2.show(qsTr("Enter a commit message first"))
                    }
                }
            }
            ScButton {
                label: qsTr("Branch…")
                onClicked: branchDialog.open()
            }
            ScButton {
                label: qsTr("Merge…")
                enabled2: scRoot.branch !== "fengrid-main"
                onClicked: mergeMenu.popup()
            }
            ScButton {
                label: qsTr("Push")
                onClicked: sc.push("origin")
            }
        }

        TextInput {
            id: commitField
            Layout.fillWidth: true
            height: 26
            color: theme.tokens.text
            font.family: theme.monoFont
            font.pixelSize: 11
            clip: true
            verticalAlignment: TextInput.AlignVCenter
            Rectangle {
                anchors.fill: parent
                radius: 6
                color: theme.tokens.surface2
                border.color: commitField.activeFocus
                              ? theme.tokens.accent : theme.tokens.border
                z: -1
            }
            Text {
                visible: commitField.text === ""
                anchors.fill: parent
                anchors.leftMargin: 8
                verticalAlignment: Text.AlignVCenter
                text: qsTr("commit message…")
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
            }
            leftPadding: 8
        }

        // ── changes: staged / unstaged / untracked ──
        SectionHeader { text: qsTr("Changes") }
        Repeater {
            model: {
                var rows = []
                var s = scRoot.st
                if (s && s.staged)
                    for (var i = 0; i < s.staged.length; i++)
                        rows.push({ p: s.staged[i], k: "staged" })
                if (s && s.unstaged)
                    for (var j = 0; j < s.unstaged.length; j++)
                        rows.push({ p: s.unstaged[j], k: "unstaged" })
                if (s && s.untracked)
                    for (var u = 0; u < s.untracked.length; u++)
                        rows.push({ p: s.untracked[u], k: "untracked" })
                return rows
            }
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 6
                Rectangle {
                    width: 8; height: 8; radius: 4
                    color: modelData.k === "staged" ? theme.tokens.success
                          : modelData.k === "unstaged" ? theme.tokens.litPane
                          : theme.tokens.textMuted
                }
                Text {
                    text: modelData.p
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.text
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
                Text {
                    text: modelData.k === "staged" ? qsTr("+")
                          : modelData.k === "unstaged" ? qsTr("~") : qsTr("?")
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.textMuted
                }
            }
        }
        Text {
            visible: scRoot.st.clean === true
            text: qsTr("Working tree clean")
            font.family: theme.uiFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
        }

        // ── branches ──
        SectionHeader { text: qsTr("Branches") }
        Repeater {
            model: hasRepo ? sc.branchList : []
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 4
                Text {
                    text: modelData.name
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: modelData.current ? theme.tokens.accentProject
                          : theme.tokens.text
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: sc.checkout(modelData.name)
                    }
                }
                Text {
                    text: modelData.current ? qsTr("●") : ""
                    color: theme.tokens.accentProject
                    font.pixelSize: 9
                }
                IconButton {
                    icon_name: "trash"
                    icon_px: 10
                    implicitWidth: 20; implicitHeight: 20
                    visible: modelData.name !== "fengrid-main"
                    ToolTip.text: qsTr("Delete merged branch")
                    onClicked: {
                        if (sc.is_merged(modelData.name)) {
                            sc.delete_branch(modelData.name)
                        } else {
                            deleteWarn.target = modelData.name
                            deleteWarn.open()
                        }
                    }
                }
            }
        }

        // ── history ──
        SectionHeader { text: qsTr("History") }
        Repeater {
            model: hasRepo ? sc.history : []
            ColumnLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 0
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Rectangle { width: 6; height: 6; radius: 3
                                color: theme.tokens.accentProject }
                    Text {
                        text: modelData.message
                        font.family: theme.uiFont
                        font.pixelSize: 10
                        color: theme.tokens.text
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text {
                        text: modelData.sha
                        font.family: theme.monoFont
                        font.pixelSize: 9
                        color: theme.tokens.textMuted
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }

    component SectionHeader: Text {
        topPadding: 8
        font.family: theme.headingFont
        font.pixelSize: 11
        font.letterSpacing: 1.2
        font.capitalization: Font.AllUppercase
        color: theme.tokens.textMuted
    }

    Toast { id: toast2 }

    Dialog {
        id: branchDialog
        width: 280
        padding: 16
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        background: Rectangle {
            radius: 12; color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        contentItem: ColumnLayout {
            spacing: 8
            Text { text: qsTr("New working branch")
                   font.family: theme.headingFont; font.pixelSize: 13 }
            TextField {
                id: branchName
                placeholderText: qsTr("my-experiment")
                Layout.fillWidth: true
            }
        }
        footer: FgDialogFooter {
            acceptLabel: qsTr("Create")
            acceptEnabled: branchName.text.trim() !== ""
            onCancelClicked: branchDialog.close()
            onAcceptClicked: {
                sc.create_branch(branchName.text.trim())
                branchName.text = ""
                branchDialog.close()
            }
        }
    }

    Menu {
        id: mergeMenu
        width: 220
        Repeater {
            model: {
                var out = []
                var all = hasRepo ? sc.branchList : []
                for (var i = 0; i < all.length; i++)
                    if (!all[i].current)
                        out.push(all[i].name)
                return out
            }
            FgMenuItem {
                required property string modelData
                text: qsTr("Merge '%1'").arg(modelData)
                height: 28
                onTriggered: sc.merge(modelData)
            }
        }
    }

    Dialog {
        id: deleteWarn
        property string target: ""
        width: 320
        padding: 16
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        background: Rectangle {
            radius: 12; color: theme.tokens.surface
            border.color: theme.tokens.litPane
        }
        contentItem: ColumnLayout {
            spacing: 10
            Text {
                text: qsTr("Delete unmerged branch?")
                font.family: theme.headingFont; font.pixelSize: 13
            }
            Text {
                text: qsTr("'%1' has commits that are NOT merged into"
                           + " fengrid-main. Deleting it discards that"
                           + " work permanently.")
                      .arg(deleteWarn.target)
                wrapMode: Text.Wrap
                font.family: theme.uiFont; font.pixelSize: 11
                color: theme.tokens.text
                Layout.fillWidth: true
            }
        }
        footer: FgDialogFooter {
            acceptLabel: qsTr("Delete anyway")
            onCancelClicked: deleteWarn.close()
            onAcceptClicked: {
                sc.delete_branch(deleteWarn.target)
                deleteWarn.close()
            }
        }
    }
}
