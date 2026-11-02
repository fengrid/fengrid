import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Task editor for the Planning board (#132): every card expands into
// this — full field editing (title/description/stage/priority/due
// date/status), project assignment, and per-task library-asset links
// (the deep integration with asset management). Follows the app's
// dialog idiom (surface, border, themed combos/inputs).
Dialog {
    id: dlg

    property var boardRoot: null
    // currently edited task ({} when creating)
    property var task: ({})
    property bool creating: true

    width: 500
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    padding: 16

    background: Rectangle {
        radius: 12
        color: theme.tokens.surface
        border.color: theme.tokens.border
    }

    function openNew(stage) {
        creating = true;
        task = {id: -1, title: "", description: "", stage: stage || "todo",
                 priority: "", due_date: "", status_note: "",
                 project_id: 0, projectName: "", assets: [],
                 shortId: ""};
        loadFields();
        titleInput.forceActiveFocus();
        open();
    }

    function openWith(taskId) {
        creating = false;
        task = boardRoot !== null && boardRoot.bridge !== null
                ? boardRoot.bridge.task(taskId) : {};
        if (!task || task.id === undefined) {
            close();
            return;
        }
        loadFields();
        open();
    }

    function loadFields() {
        titleInput.text = task.title || "";
        descInput.text = task.description || "";
        stageCombo.selectKey(task.stage || "todo");
        priorityCombo.selectKey(task.priority || "");
        dueInput.text = task.due_date || "";
        statusInput.text = task.status_note || "";
        projectCombo.selectId(task.project_id || 0);
        assetKindCombo.selectKey("icon");
        assetItemCombo.selectId(0);
        reloadAssets();
    }

    function reloadAssets() {
        assetsList.model = task.assets || [];
    }

    function save() {
        if (boardRoot === null || boardRoot.bridge === null)
            return;
        var t = titleInput.text.trim();
        if (t === "") {
            boardRoot.bridge.toast(qsTr("A Title Is Required"));
            return;
        }
        var due = dueInput.text.trim();
        if (due !== "" && !/^\d{4}-\d{2}-\d{2}$/.test(due)) {
            boardRoot.bridge.toast(
                        qsTr("Due Date Must Be YYYY-MM-DD Or Empty"));
            return;
        }
        var b = boardRoot.bridge;
        if (creating) {
            var pid = projectCombo.currentId > 0
                    ? String(projectCombo.currentId) : "";
            var tid = b.create_task(t, stageCombo.currentKey, pid);
            b.update_task(tid, "description", descInput.text);
            b.update_task(tid, "priority", priorityCombo.currentKey);
            b.update_task(tid, "due_date", due);
            b.update_task(tid, "status_note", statusInput.text.trim());
        } else {
            var id = task.id;
            b.update_task(id, "title", t);
            b.update_task(id, "description", descInput.text);
            b.update_task(id, "due_date", due);
            b.update_task(id, "status_note", statusInput.text.trim());
            b.update_task(id, "priority", priorityCombo.currentKey);
            // project + stage go through their dedicated slots
            b.assign_project(id, projectCombo.currentId);
            if (stageCombo.currentKey !== (task.stage || "")) {
                // keep the card at the top of its new stage
                var cards = boardRoot.stageMeta(stageCombo.currentKey);
                b.move_task(id, stageCombo.currentKey,
                            cards ? cards.cards.length : 0);
            }
        }
        close();
    }

    contentItem: ColumnLayout {
        spacing: 10

        Text {
            text: dlg.creating ? qsTr("New Task")
                               : qsTr("Edit Task") + (dlg.task.shortId
                                   ? "  ·  " + dlg.task.shortId : "")
            font.family: theme.headingFont
            font.pixelSize: 14
            font.letterSpacing: 1.0
            font.capitalization: Font.AllUppercase
            color: theme.tokens.text
        }

        FormInput {
            id: titleInput
            label: qsTr("Title")
        }

        // description — multiline editor in the same field idiom
        ColumnLayout {
            spacing: 3
            Layout.fillWidth: true
            Text {
                text: qsTr("Description")
                font.family: theme.monoFont
                font.pixelSize: 10
                font.letterSpacing: 0.8
                font.capitalization: Font.AllUppercase
                color: theme.tokens.textMuted
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 72
                radius: 6
                color: theme.tokens.surface2
                border.color: descInput.activeFocus
                              ? theme.tokens.accent : theme.tokens.border
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 6
                    TextArea {
                        id: descInput
                        wrapMode: TextArea.Wrap
                        color: theme.tokens.text
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        background: null
                    }
                }
            }
        }

        RowLayout {
            spacing: 10
            Layout.fillWidth: true

            // themed combo — the same surface/border idiom the Settings
            // rows use (no default light-styled controls)
            component MiniCombo: ComboBox {
                id: combo
                property int currentId: 0
                property string currentKey: ""
                implicitHeight: 30
                implicitWidth: 160
                textRole: "name"
                font.family: theme.uiFont
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: combo.activeFocus
                                  ? theme.tokens.accent : theme.tokens.border
                }
                contentItem: Text {
                    text: combo.displayText
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8
                }
                delegate: ItemDelegate {
                    id: del
                    required property var modelData
                    width: combo.width
                    contentItem: Text {
                        text: del.modelData.name
                        color: theme.tokens.text
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignVCenter
                    }
                    highlighted: combo.highlightedIndex === index
                    background: Rectangle {
                        color: del.highlighted
                               ? theme.tokens.surface2 : "transparent"
                    }
                    onClicked: {
                        combo.currentIndex = index;
                        combo.currentId = del.modelData.id || 0;
                        combo.currentKey = del.modelData.key || "";
                        combo.popup.close();
                    }
                }
                popup: Popup {
                    y: combo.height + 2
                    width: combo.width
                    height: Math.min(contentItem.implicitHeight + 8, 240)
                    padding: 2
                    background: Rectangle {
                        radius: 6
                        color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    contentItem: ListView {
                        clip: true
                        implicitHeight: contentHeight
                        model: combo.popup.visible ? combo.delegateModel
                                                   : null
                        currentIndex: combo.highlightedIndex
                    }
                }
                function selectKey(k) {
                    for (var i = 0; i < model.length; i++)
                        if ((model[i].key || "") === k) {
                            currentIndex = i;
                            currentKey = k;
                            currentId = model[i].id || 0;
                            return;
                        }
                    currentIndex = 0;
                    currentKey = model.length ? (model[0].key || "")
                                              : currentKey;
                    currentId = model.length ? (model[0].id || 0) : 0;
                }
                function selectId(idv) {
                    for (var i = 0; i < model.length; i++)
                        if ((model[i].id || 0) === idv) {
                            currentIndex = i;
                            currentId = idv;
                            currentKey = model[i].key || "";
                            return;
                        }
                    currentIndex = 0;
                    currentId = model.length ? (model[0].id || 0) : 0;
                    currentKey = model.length ? (model[0].key || "") : "";
                }
            }

            ColumnLayout {
                spacing: 3
                Text {
                    text: qsTr("Stage")
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    font.letterSpacing: 0.8
                    font.capitalization: Font.AllUppercase
                    color: theme.tokens.textMuted
                }
                MiniCombo {
                    id: stageCombo
                    Layout.fillWidth: true
                    model: boardRoot !== null && boardRoot.bridge !== null
                           ? boardRoot.bridge.stages : []
                }
            }
            ColumnLayout {
                spacing: 3
                Text {
                    text: qsTr("Priority")
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    font.letterSpacing: 0.8
                    font.capitalization: Font.AllUppercase
                    color: theme.tokens.textMuted
                }
                MiniCombo {
                    id: priorityCombo
                    Layout.fillWidth: true
                    model: [
                        {key: "", name: qsTr("None")},
                        {key: "low", name: qsTr("Low")},
                        {key: "normal", name: qsTr("Normal")},
                        {key: "high", name: qsTr("High")}
                    ]
                }
            }
        }

        RowLayout {
            spacing: 10
            Layout.fillWidth: true
            FormInput {
                id: dueInput
                label: qsTr("Due Date (YYYY-MM-DD)")
                Layout.fillWidth: true
            }
            FormInput {
                id: statusInput
                label: qsTr("Status Note")
                Layout.fillWidth: true
            }
        }

        // project assignment — deep integration with Projects
        ColumnLayout {
            spacing: 3
            Layout.fillWidth: true
            Text {
                text: qsTr("Project")
                font.family: theme.monoFont
                font.pixelSize: 10
                font.letterSpacing: 0.8
                font.capitalization: Font.AllUppercase
                color: theme.tokens.textMuted
            }
            MiniCombo {
                id: projectCombo
                Layout.fillWidth: true
                model: {
                    var opts = boardRoot !== null
                            && boardRoot.bridge !== null
                            ? boardRoot.bridge.project_options() : [];
                    return [{id: 0, name: qsTr("No Project")}]
                            .concat(opts);
                }
            }
        }

        // linked assets
        ColumnLayout {
            spacing: 6
            Layout.fillWidth: true
            Text {
                text: qsTr("Linked Assets")
                font.family: theme.monoFont
                font.pixelSize: 10
                font.letterSpacing: 0.8
                font.capitalization: Font.AllUppercase
                color: theme.tokens.textMuted
            }
            Repeater {
                id: assetsList
                delegate: RowLayout {
                    required property var modelData
                    width: dlg.availableWidth
                    spacing: 6
                    Rectangle {
                        width: 18
                        height: 18
                        radius: 4
                        color: theme.tokens.surface2
                        border.color: theme.tokens.border
                        Image {
                            anchors.centerIn: parent
                            source: Icons.url(
                                        modelData.assetKind === "font"
                                        ? "type" : modelData.assetKind
                                        === "palette" ? "droplet"
                                        : modelData.assetKind === "snippet"
                                        ? "code" : "image",
                                        theme.tokens.textMuted,
                                        theme.tokens.textMuted, 11)
                            sourceSize: Qt.size(11, 11)
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.name
                        elide: Text.ElideRight
                        color: theme.tokens.text
                        font.family: theme.uiFont
                        font.pixelSize: 12
                    }
                    IconButton {
                        icon_name: "trash"
                        icon_px: 13
                        ToolTip.text: qsTr("Unlink Asset")
                        onClicked: {
                            boardRoot.bridge.unlink_asset(dlg.task.id,
                                                          modelData.id);
                            dlg.task = boardRoot.bridge.task(dlg.task.id);
                            dlg.reloadAssets();
                        }
                    }
                }
            }
            RowLayout {
                spacing: 6
                Layout.fillWidth: true
                ColumnLayout {
                    spacing: 3
                    Text {
                        text: qsTr("Kind")
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        font.letterSpacing: 0.8
                        font.capitalization: Font.AllUppercase
                        color: theme.tokens.textMuted
                    }
                    MiniCombo {
                        id: assetKindCombo
                        implicitWidth: 120
                        model: [
                            {key: "icon", name: qsTr("Icon")},
                            {key: "font", name: qsTr("Font")},
                            {key: "snippet", name: qsTr("Snippet")},
                            {key: "palette", name: qsTr("Palette")}
                        ]
                        onCurrentKeyChanged: {
                            assetItemCombo.selectId(0);
                        }
                    }
                }
                ColumnLayout {
                    spacing: 3
                    Layout.fillWidth: true
                    Text {
                        text: qsTr("Asset")
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        font.letterSpacing: 0.8
                        font.capitalization: Font.AllUppercase
                        color: theme.tokens.textMuted
                    }
                    MiniCombo {
                        id: assetItemCombo
                        Layout.fillWidth: true
                        model: {
                            var k = assetKindCombo.currentKey || "icon";
                            var opts = boardRoot !== null
                                    && boardRoot.bridge !== null
                                    ? boardRoot.bridge.asset_options(k)
                                    : [];
                            return [{id: 0,
                                      name: qsTr("Pick An Asset")}]
                                    .concat(opts);
                        }
                    }
                }
                FgButton {
                    text: qsTr("Link")
                    onClicked: {
                        var aid = assetItemCombo.currentId;
                        if (aid <= 0 || dlg.creating
                                || dlg.task.id === undefined)
                            return;
                        if (boardRoot.bridge.link_asset(dlg.task.id,
                                                        assetKindCombo
                                                        .currentKey,
                                                        String(aid), "")) {
                            dlg.task = boardRoot.bridge.task(dlg.task.id);
                            dlg.reloadAssets();
                        }
                    }
                }
            }
            Text {
                visible: dlg.creating
                text: qsTr("Link Assets After Saving The Task")
                color: theme.tokens.textMuted
                font.family: theme.uiFont
                font.pixelSize: 11
            }
        }

        // footer: delete on the left, cancel/save on the right
        RowLayout {
            spacing: 8
            Layout.fillWidth: true
            Layout.topMargin: 4
            FgButton {
                visible: !dlg.creating
                text: qsTr("Delete")
                onClicked: {
                    boardRoot.bridge.delete_task(dlg.task.id);
                    dlg.close();
                }
            }
            Item {
                Layout.fillWidth: true
            }
            FgButton {
                text: qsTr("Cancel")
                onClicked: dlg.close()
            }
            FgButton {
                text: qsTr("Save")
                onClicked: dlg.save()
            }
        }
    }
}
