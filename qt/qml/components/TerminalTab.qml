import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// Terminal color theme designer (Colors pane, "Terminal" sub-tab).
// Working theme lives in the `terms` bridge; presets come from the Gogh
// collection; exports cover iTerm2 / Windows Terminal / Guake / GNOME /
// kitty / alacritty / JSON; persistence is "Save to snippets" (the theme
// becomes a live-preview snippet, collectable and project-attachable).
Item {
    id: termRoot

    // quick access to the working theme dict
    function t() {
        return terms !== null && terms.theme !== undefined
               && terms.theme !== null ? terms.theme : {}
    }
    function slotColor(pool, slot) {
        var th = t()
        return th[pool] && th[pool][slot] ? th[pool][slot] : "transparent"
    }

    Connections {
        target: terms
        function onMessage(msg) { toast.show(msg) }
        function onExportDone(path) {
            toast.show(qsTr("Exported: %1").arg(path))
        }
        function onExportFailed(err) {
            toast.show(qsTr("Export failed: %1").arg(err))
        }
    }

    Toast { id: toast }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        // ---- top row: preset + name + derive anchors
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            ComboBox {
                id: presetBox
                Layout.preferredWidth: 170
                Layout.preferredHeight: 28
                model: terms !== null
                       ? terms.presets().map(function (p) { return p.name }) : []
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Example themes from the Gogh collection")
                background: Rectangle {
                    radius: 6; color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
                contentItem: Text {
                    text: presetBox.displayText
                    font.family: theme.monoFont; font.pixelSize: 11
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter; leftPadding: 8
                }
            }
            Button {
                text: qsTr("Load")
                enabled: presetBox.currentIndex >= 0
                onClicked: terms.load_preset(presetBox.currentText)
                background: Rectangle {
                    radius: 6; color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
                contentItem: Text {
                    text: parent.text
                    color: theme.tokens.text
                    font.family: theme.uiFont; font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
            TextField {
                id: nameField
                Layout.fillWidth: true
                text: t().name || ""
                onEditingFinished: terms.set_name(text)
                placeholderText: qsTr("Theme Name")
                font.family: theme.monoFont; font.pixelSize: 11
                color: theme.tokens.text
                background: Rectangle {
                    radius: 6; color: theme.tokens.surface2
                    border.color: nameField.activeFocus
                                  ? theme.tokens.accent : theme.tokens.border
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: qsTr("Derive From")
                font.family: theme.monoFont; font.pixelSize: 10
                color: theme.tokens.textMuted
            }
            TextField {
                id: dBg; text: t().bg || "#1E2127"
                Layout.preferredWidth: 92
                font.family: theme.monoFont; font.pixelSize: 11
                color: theme.tokens.text
                background: Rectangle {
                    radius: 4; color: theme.tokens.surface2
                    border.color: dBg.activeFocus ? theme.tokens.accent
                                                  : theme.tokens.border
                }
            }
            TextField {
                id: dFg; text: t().fg || "#D8DEE9"
                Layout.preferredWidth: 92
                font.family: theme.monoFont; font.pixelSize: 11
                color: theme.tokens.text
                background: Rectangle {
                    radius: 4; color: theme.tokens.surface2
                    border.color: dFg.activeFocus ? theme.tokens.accent
                                                  : theme.tokens.border
                }
            }
            TextField {
                id: dAcc; text: t().normal ? (t().normal.cyan || "") : ""
                Layout.preferredWidth: 92
                placeholderText: qsTr("Accent")
                font.family: theme.monoFont; font.pixelSize: 11
                color: theme.tokens.text
                background: Rectangle {
                    radius: 4; color: theme.tokens.surface2
                    border.color: dAcc.activeFocus ? theme.tokens.accent
                                                   : theme.tokens.border
                }
            }
            Button {
                text: qsTr("Derive 16 colors")
                onClicked: terms.derive(dBg.text, dFg.text, dAcc.text)
                background: Rectangle {
                    radius: 6
                    color: parent.hovered ? Qt.lighter(theme.tokens.accentColor, 1.1)
                                          : theme.tokens.accentColor
                }
                contentItem: Text {
                    text: parent.text
                    color: "#101418"
                    font.family: theme.uiFont; font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
            Item { Layout.fillWidth: true }
        }

        // ---- editor: slots (left) + preview (right)
        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: Rectangle { color: theme.tokens.border; width: 1 }

            // slot editor
            Flickable {
                SplitView.preferredWidth: 360
                SplitView.minimumWidth: 300
                clip: true
                contentHeight: slotsCol.implicitHeight + 12
                ScrollBar.vertical: ScrollBar { }

                ColumnLayout {
                    id: slotsCol
                    width: parent.width - 8
                    x: 4
                    spacing: 8

                    // core colors
                    Repeater {
                        model: ["bg", "fg", "cursor", "selection"]
                        RowLayout {
                            id: coreRow
                            required property string modelData
                            Layout.fillWidth: true
                            Text {
                                text: coreRow.modelData
                                font.family: theme.monoFont; font.pixelSize: 10
                                color: theme.tokens.textMuted
                                Layout.preferredWidth: 64
                            }
                            Rectangle {
                                width: 14; height: 14; radius: 3
                                color: termRoot.t()[coreRow.modelData]
                                       || "transparent"
                                border.color: theme.tokens.border
                            }
                            TextField {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 60
                                text: termRoot.t()[coreRow.modelData] || ""
                                onEditingFinished: terms.set_value(
                                    coreRow.modelData, text)
                                font.family: theme.monoFont; font.pixelSize: 10
                                color: theme.tokens.text
                                background: Rectangle {
                                    radius: 4; color: theme.tokens.surface2
                                    border.color: parent.activeFocus
                                                  ? theme.tokens.accent
                                                  : theme.tokens.border
                                }
                            }
                        }
                    }

                    SectionHeader { title: qsTr("ANSI normal") }
                    Repeater {
                        model: ["black", "red", "green", "yellow", "blue",
                                "magenta", "cyan", "white"]
                        SlotRow { pool: "normal"; slot: modelData }
                    }
                    SectionHeader { title: qsTr("ANSI bright") }
                    Repeater {
                        model: ["brightBlack", "brightRed", "brightGreen",
                                "brightYellow", "brightBlue", "brightMagenta",
                                "brightCyan", "brightWhite"]
                        SlotRow { pool: "bright"; slot: modelData }
                    }
                }
            }

            // live terminal preview (pure QML — no WebEngine needed here)
            ColumnLayout {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 260
                spacing: 8

                Rectangle {
                    id: termMock
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 10
                    color: termRoot.t().bg || "#1E2127"
                    border.color: theme.tokens.border

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 22
                            color: termRoot.t().selection || "#3B4252"
                            radius: 10
                            Row {
                                anchors.left: parent.left
                                anchors.leftMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 6
                                Repeater {
                                    model: [
                                        termRoot.t().bright
                                            ? termRoot.t().bright.brightRed : "#f00",
                                        termRoot.t().bright
                                            ? termRoot.t().bright.brightYellow : "#ff0",
                                        termRoot.t().normal
                                            ? termRoot.t().normal.green : "#0f0"]
                                    Rectangle {
                                        required property var modelData
                                        width: 9; height: 9; radius: 99
                                        color: termRoot.bound(modelData)
                                    }
                                }
                            }
                        }

                        Flickable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            contentHeight: termLines.implicitHeight + 12
                            ColumnLayout {
                                id: termLines
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.margins: 14
                                spacing: 3
                                Repeater {
                                    // [prompt-slot, prompt-text, rest-slot, rest-text]
                                    model: [
                                        ["green", "$", "fg", " ls ~/assets"],
                                        ["yellow", "→", "fg", " building bundle…"],
                                        ["green", "✓", "green", " tests 128/128 passed"],
                                        ["brightRed", "✗", "brightRed", " lint: 2 warnings"],
                                        ["blue", "$", "fg", " git push origin main"],
                                        ["cyan", "→", "cyan", " deployed in 3.2s"],
                                        ["magenta", "$", "brightWhite", " tail -f server.log"],
                                        ["brightBlack", "…", "brightBlack", " streaming"]]
                                    Row {
                                        required property var modelData
                                        spacing: 0
                                        Text {
                                            text: parent.modelData[1] + " "
                                            font.family: theme.monoFont
                                            font.pixelSize: 12
                                            color: termRoot.colorOf(
                                                parent.modelData[0].startsWith("bright")
                                                ? "bright" : "normal",
                                                parent.modelData[0])
                                        }
                                        Text {
                                            text: parent.modelData[3]
                                            font.family: theme.monoFont
                                            font.pixelSize: 12
                                            color: termRoot.colorOf(
                                                parent.modelData[2].startsWith("bright")
                                                ? "bright" : "normal",
                                                parent.modelData[2])
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // export row
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    ComboBox {
                        id: fmtBox
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 28
                        model: terms !== null ? terms.formats() : []
                        background: Rectangle {
                            radius: 6; color: theme.tokens.surface2
                            border.color: theme.tokens.border
                        }
                        contentItem: Text {
                            text: fmtBox.displayText
                            font.family: theme.monoFont; font.pixelSize: 11
                            color: theme.tokens.text
                            verticalAlignment: Text.AlignVCenter; leftPadding: 8
                        }
                    }
                    Button {
                        text: qsTr("Export…")
                        onClicked: termExportDialog.open()
                        background: Rectangle {
                            radius: 6; color: theme.tokens.surface2
                            border.color: theme.tokens.border
                        }
                        contentItem: Text {
                            text: parent.text
                            color: theme.tokens.text
                            font.family: theme.uiFont; font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                    Button {
                        text: qsTr("Save to snippets")
                        onClicked: terms.save_as_snippet()
                        ToolTip.visible: hovered
                        ToolTip.text: qsTr(
                            "Stores a live-preview snippet (collectable, project-attachable)")
                        background: Rectangle {
                            radius: 6
                            color: parent.hovered
                                   ? Qt.lighter(theme.tokens.accentColor, 1.1)
                                   : theme.tokens.accentColor
                        }
                        contentItem: Text {
                            text: parent.text
                            color: "#101418"
                            font.family: theme.uiFont; font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 8; rightPadding: 8
                        }
                    }
                    Item { Layout.fillWidth: true }
                }
            }
        }
    }

    function colorOf(pool, slot) {
        // resolve a slot to a visible color, falling back to the fg color
        var th = t()
        if (th[pool] && th[pool][slot])
            return th[pool][slot]
        return th.fg || theme.tokens.text
    }
    function bound(v) {
        return typeof v === "string" && v !== "" ? v : "transparent"
    }

    component SlotRow: RowLayout {
        property string pool
        property string slot
        Layout.fillWidth: true
        Text {
            text: slot
            font.family: theme.monoFont; font.pixelSize: 10
            color: theme.tokens.textMuted
            Layout.preferredWidth: 86
        }
        Rectangle {
            width: 14; height: 14; radius: 3
            color: termRoot.slotColor(pool, slot)
            border.color: theme.tokens.border
        }
        TextField {
            Layout.fillWidth: true
            Layout.minimumWidth: 60
            text: termRoot.slotColor(pool, slot) === "transparent"
                  ? "" : termRoot.slotColor(pool, slot)
            onEditingFinished: terms.set_value(pool + "." + slot, text)
            font.family: theme.monoFont; font.pixelSize: 10
            color: theme.tokens.text
            background: Rectangle {
                radius: 4; color: theme.tokens.surface2
                border.color: parent.activeFocus ? theme.tokens.accent
                                                 : theme.tokens.border
            }
        }
    }

    component SectionHeader: Text {
        property string title
        text: title
        topPadding: 4
        font.family: theme.monoFont
        font.pixelSize: 9
        font.letterSpacing: 1.4
        font.capitalization: Font.AllUppercase
        color: theme.tokens.accentColor
    }

    FileDialog {
        id: termExportDialog
        fileMode: FileDialog.SaveFile
        nameFilters: fmtBox.currentText === "iterm2"
                     ? [qsTr("iTerm2 Colors (*.itermcolors)")]
                     : fmtBox.currentText === "windows"
                       ? [qsTr("Windows Terminal (*.json)")]
                       : [qsTr("Theme files (*)")]
        onAccepted: terms.export(Icons.toLocalPath(selectedFile),
                                 fmtBox.currentText)
    }
}
