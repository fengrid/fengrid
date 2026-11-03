import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Planning pane (#132): a Kanban board over the project-task model.
// Eight stage columns accordion out of vertical bars (one expanded at a
// time, like the reference board); cards drag between stages, carry
// title/description/status meta, and open into a full task editor with
// project assignment + library-asset links (deep integration).
Item {
    id: planningRoot

    // bridge context property (set in __main__); QA rigs without it
    // degrade to a static board shell
    property var bridge: typeof planning !== "undefined" ? planning : null
    // mirror of the bridge board — rebuilt on tasksChanged
    property var board: bridge !== null ? bridge.board : []
    // accordion state: exactly one stage expanded at a time ("" = all bars)
    property string expandedStage: "todo"
    // drag state (cross-column drag handled at board level so a card can
    // travel between columns without reparenting — software-renderer safe)
    property int dragTaskId: -1
    property string dragStage: ""
    property string dragHoverStage: ""

    signal entityProperties(string kind, int id)
    // a card's project chip asked to open its project (Main switches
    // to the Projects pane and opens it)
    signal projectOpenRequested(int id)

    // QA/tests: popups are unreachable from the QObject tree, so the
    // task editor is resolved through this handle (SideRail.qaModals
    // precedent)
    readonly property var taskDialogRef: taskDialog

    implicitWidth: 1280
    implicitHeight: 800

    function stageMeta(key) {
        for (var i = 0; i < board.length; i++)
            if (board[i].key === key)
                return board[i];
        return null;
    }

    function stageColor(key) {
        var s = stageMeta(key);
        if (!s)
            return theme.tokens.textMuted;
        return theme.isDark ? s.dark : s.light;
    }

    function openTask(taskId) {
        taskDialog.openWith(taskId);
    }

    function newTask(stage) {
        taskDialog.openNew(stage || expandedStage || "todo");
    }

    // ------------------------------------------------------------- drag glue
    // ALL drag coordinates are in planningRoot space. Column positions
    // are resolved with mapToItem so Flickable scroll offsets (the
    // board pans horizontally, columns scroll vertically) never skew
    // the hit test.
    function beginDrag(task, prX, prY) {
        if (!bridge || dragTaskId !== -1)
            return;
        dragTaskId = task.id;
        dragStage = task.stage;
        dragProxy.title = task.title;
        dragProxy.width = Math.max(180, Math.min(260, taskColWidth));
        dragProxyMove(prX, prY);
        dragProxy.visible = true;
    }

    function dragProxyMove(prX, prY) {
        dragProxy.x = prX - dragProxy.width / 2;
        dragProxy.y = prY - 14;
        dragHoverStage = stageAtPoint(dragProxy.x + dragProxy.width / 2,
                                      dragProxy.y);
    }

    function endDrag() {
        if (dragTaskId === -1)
            return;
        var cx = dragProxy.x + dragProxy.width / 2;
        var cy = dragProxy.y + 14;
        var key = stageAtPoint(cx, cy);
        dragProxy.visible = false;
        dragHoverStage = "";
        var tid = dragTaskId;
        dragTaskId = -1;
        dragStage = "";
        if (key === "")
            return;
        var col = columnFor(key);
        if (col === null)
            return;
        var idx;
        if (col.expanded) {
            idx = Math.max(0, col.indexAtY(cx, cy));
        } else {
            // dropped on a collapsed bar: file at the end and expand it
            idx = col.stageData.cards.length;
            expandedStage = key;
        }
        bridge.move_task(tid, key, idx);
    }

    function stageAtPoint(prX, prY) {
        for (var i = 0; i < stageRepeater.count; i++) {
            var col = stageRepeater.itemAt(i);
            if (!col)
                continue;
            var o = col.mapToItem(planningRoot, 0, 0);
            if (prX >= o.x && prX <= o.x + col.width
                    && prY >= o.y && prY <= o.y + col.height)
                return col.stageData.key;
        }
        return "";
    }

    function columnFor(key) {
        for (var i = 0; i < stageRepeater.count; i++) {
            var col = stageRepeater.itemAt(i);
            if (col && col.stageData.key === key)
                return col;
        }
        return null;
    }

    readonly property int taskColWidth: 264
    // when the board is wider than the columns, the expanded column
    // flexes to absorb the leftover (capped — a 700px column is silly)
    readonly property real flexWidth: {
        var bars = board.length - (expandedStage !== "" ? 1 : 0);
        var left = boardArea.width - 32 - bars * 44;
        return Math.max(taskColWidth, Math.min(420, left));
    }

    // drag ghost following the pointer while a card is being dragged
    Rectangle {
        id: dragProxy
        visible: false
        height: 44
        radius: 8
        color: theme.tokens.surface2
        border.color: planningRoot.stageColor(planningRoot.dragHoverStage
                                              || planningRoot.dragStage)
        border.width: 1
        opacity: 0.92
        z: 50
        property string title: ""
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            text: dragProxy.title
            elide: Text.ElideRight
            width: dragProxy.width - 20
            color: theme.tokens.text
            font.family: theme.uiFont
            font.pixelSize: 12
        }
    }

    // ---------------------------------------------------------------- header
    Rectangle {
        id: header
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 56
        color: theme.tokens.surface

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 10

            Text {
                text: qsTr("Planning")
                font.family: theme.headingFont
                font.pixelSize: 17
                font.weight: Font.DemiBold
                color: theme.tokens.text
            }
            Rectangle {
                implicitWidth: 26
                implicitHeight: 20
                radius: 10
                color: theme.tokens.surface2
                border.color: theme.tokens.border
                Text {
                    anchors.centerIn: parent
                    text: bridge !== null ? bridge.totalCount : 0
                    color: theme.tokens.textMuted
                    font.family: theme.monoFont
                    font.pixelSize: 11
                }
            }
            Item {
                Layout.fillWidth: true
            }
            // filter box — mirrors the reference board's "Filter Cards…"
            Rectangle {
                implicitWidth: 220
                implicitHeight: 30
                radius: 6
                color: theme.tokens.surface2
                border.color: filterInput.activeFocus
                              ? theme.tokens.accent : theme.tokens.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 6
                    Image {
                        source: Icons.url("search", theme.tokens.textMuted,
                                          theme.tokens.textMuted, 14)
                        sourceSize: Qt.size(14, 14)
                        Layout.alignment: Qt.AlignVCenter
                    }
                    TextInput {
                        id: filterInput
                        Layout.fillWidth: true
                        color: theme.tokens.text
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        clip: true
                        onTextChanged: {
                            if (bridge !== null)
                                bridge.set_search(text);
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            visible: filterInput.text === ""
                                     && !filterInput.activeFocus
                            text: qsTr("Filter Cards")
                            color: theme.tokens.textMuted
                            font.family: theme.uiFont
                            font.pixelSize: 12
                        }
                    }
                }
            }
            FgButton {
                text: qsTr("New Task")
                onClicked: planningRoot.newTask("")
            }
        }
    }

    Rectangle {
        anchors.top: header.bottom
        width: parent.width
        height: 1
        color: theme.tokens.border
    }

    // ----------------------------------------------------------------- board
    Flickable {
        id: boardArea
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        contentWidth: boardRow.implicitWidth
        clip: true

        Row {
            id: boardRow
            spacing: 10
            x: 16
            y: 16

            Repeater {
                id: stageRepeater
                model: planningRoot.board

                delegate: StageColumn {
                    stageData: modelData
                }
            }
        }
    }

    // ------------------------------------------------------- stage column
    component StageColumn: Rectangle {
        id: col

        property var stageData
        property bool expanded: planningRoot.expandedStage
                                === stageData.key
        property bool hoverDrag: planningRoot.dragTaskId !== -1
                                 && planningRoot.dragHoverStage
                                    === stageData.key

        width: expanded ? planningRoot.flexWidth : 34
        height: boardArea.height - 32
        radius: 8
        color: hoverDrag ? theme.tokens.surface2 : theme.tokens.surface
        border.color: hoverDrag ? planningRoot.stageColor(stageData.key)
                                : theme.tokens.border
        border.width: hoverDrag ? 2 : 1
        Behavior on width {
            NumberAnimation {
                duration: 140
                easing.type: Easing.OutCubic
            }
        }

        function indexAtY(prX, prY) {
            // insertion slot for a drop at (prX, prY) in planningRoot
            // coordinates: first card whose midpoint is below the drop.
            // Cards are mapped per-item so vertical scroll offsets in
            // this column don't skew the comparison. Only TaskCard
            // children count — the empty-stage hint Text is a sibling.
            var n = 0;
            for (var j = 0; j < cardsCol.children.length; j++) {
                var c = cardsCol.children[j];
                if (!c || c.className !== "TaskCard")
                    continue;
                var o = c.mapToItem(planningRoot, 0, 0);
                if (prY < o.y + c.height / 2)
                    return n;
                n++;
            }
            return n;
        }

        // collapsed bar: click anywhere on it to expand the stage
        // (declared under the header content, which keeps the top tap
        // target; during an active drag the grabbing card MouseArea
        // swallows events, so this never fires as a spurious click)
        MouseArea {
            anchors.fill: parent
            enabled: !col.expanded
            onClicked: planningRoot.expandedStage = col.stageData.key
        }

        // header: collapsed = dot + rotated label; expanded = dot + label
        // + count (click toggles)
        Item {
            id: headerBar
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 44

            Rectangle {
                id: dot
                width: 10
                height: 10
                radius: 5
                color: planningRoot.stageColor(col.stageData.key)
                anchors.top: parent.top
                anchors.topMargin: 14
                anchors.left: col.expanded ? parent.left : undefined
                anchors.leftMargin: col.expanded ? 12 : 0
                anchors.horizontalCenter: col.expanded
                                          ? undefined : parent.horizontalCenter
            }

            Text {
                visible: col.expanded
                anchors.left: parent.left
                anchors.leftMargin: 30
                anchors.verticalCenter: dot.verticalCenter
                text: col.stageData.label.toUpperCase()
                color: theme.tokens.text
                font.family: theme.uiFont
                font.pixelSize: 12
                font.weight: Font.DemiBold
                font.letterSpacing: 1.1
            }
            Text {
                visible: col.expanded
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: dot.verticalCenter
                text: col.stageData.cards.length
                color: theme.tokens.textMuted
                font.family: theme.monoFont
                font.pixelSize: 11
            }

            // collapsed: the count + rotated label render at COLUMN
            // level (below this header) — see the collapsed rail
            // content block under headerBar

            HoverHandler {
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                gesturePolicy: TapHandler.ReleaseWithinBounds
                onTapped: {
                    planningRoot.expandedStage =
                            col.expanded ? "" : col.stageData.key;
                }
            }
            Accessible.role: Accessible.Button
            Accessible.name: col.stageData.label
                             + (col.expanded ? " (expanded)" : " (collapsed)")
        }

        // collapsed rail content — anchored to the COLUMN, not the 44px
        // header bar: the rotated label's holder needs the full bar
        // height below the dot/count rows, and anchoring top+bottom
        // with topMargin 56 inside a 44px parent was a degenerate
        // layout that threw the label back up over the dot (#132)
        Text {
            visible: !col.expanded && col.stageData.cards.length > 0
            anchors.top: parent.top
            anchors.topMargin: 30
            anchors.horizontalCenter: parent.horizontalCenter
            text: col.stageData.cards.length
            color: theme.tokens.textMuted
            font.family: theme.monoFont
            font.pixelSize: 10
        }
        Item {
            visible: !col.expanded
            width: 34
            anchors.top: parent.top
            anchors.topMargin: 56
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 8
            Text {
                anchors.centerIn: parent
                rotation: 90
                text: col.stageData.label.toUpperCase()
                color: theme.tokens.textMuted
                font.family: theme.uiFont
                font.pixelSize: 12
                font.letterSpacing: 1.1
            }
        }

        // expanded content: scrollable card stack
        Flickable {
            id: cardsArea
            visible: col.expanded
            anchors.top: headerBar.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            contentHeight: cardsCol.height + 16
            clip: true

            Column {
                id: cardsCol
                x: 12
                y: 8
                width: col.width - 24
                spacing: 10

                Repeater {
                    model: col.stageData.cards

                    delegate: TaskCard {
                        task: modelData
                    }
                }

                Text {
                    visible: col.stageData.cards.length === 0
                    width: cardsCol.width
                    horizontalAlignment: Text.AlignHCenter
                    topPadding: 12
                    text: qsTr("No Tasks — Drop Here")
                    color: theme.tokens.textMuted
                    font.family: theme.uiFont
                    font.pixelSize: 11
                }
            }
        }
    }

    // --------------------------------------------------------------- card
    component TaskCard: Rectangle {
        id: card

        property var task
        property bool dragging: planningRoot.dragTaskId === task.id
        readonly property bool isBlocked: task.stage === "blocked"

        width: cardsCol.width
        height: cardBody.implicitHeight + 20
        radius: 8
        color: dragging ? theme.tokens.surface : theme.tokens.surface2
        border.color: dragging ? planningRoot.stageColor(task.stage)
                               : theme.tokens.border
        border.width: dragging ? 2 : 1
        opacity: dragging ? 0.35 : 1.0

        // stage-colored left accent stripe (blocked reads red, like the
        // reference board)
        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 3
            radius: 2
            color: planningRoot.stageColor(card.task.stage)
        }

        ColumnLayout {
            id: cardBody
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            anchors.topMargin: 10
            anchors.bottomMargin: 10
            spacing: 5

            Text {
                Layout.fillWidth: true
                text: card.task.title
                color: theme.tokens.text
                font.family: theme.uiFont
                font.pixelSize: 13
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                visible: card.task.description !== ""
                text: card.task.description
                color: theme.tokens.textMuted
                font.family: theme.uiFont
                font.pixelSize: 12
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                // project chip — the deep integration: click opens the
                // project in the Projects pane
                Rectangle {
                    visible: card.task.projectName !== ""
                    implicitWidth: projRow.implicitWidth + 12
                    implicitHeight: 20
                    radius: 10
                    color: theme.tokens.surface
                    border.color: theme.tokens.border
                    Row {
                        id: projRow
                        anchors.centerIn: parent
                        spacing: 4
                        Rectangle {
                            width: 14
                            height: 14
                            radius: 7
                            color: theme.tokens.accentProject
                            Text {
                                anchors.centerIn: parent
                                text: card.task.projectName.length
                                      ? card.task.projectName.charAt(0)
                                            .toUpperCase() : "?"
                                color: "#101418"
                                font.family: theme.uiFont
                                font.pixelSize: 9
                                font.weight: Font.Bold
                            }
                        }
                        Text {
                            text: card.task.projectName
                            color: theme.tokens.textMuted
                            font.family: theme.uiFont
                            font.pixelSize: 11
                        }
                    }
                    HoverHandler {
                        cursorShape: Qt.PointingHandCursor
                    }
                    TapHandler {
                        onTapped: planningRoot.projectOpenRequested(
                                      card.task.project_id)
                    }
                    Accessible.role: Accessible.Button
                    Accessible.name: qsTr("Open Project") + card.task.projectName
                }
                // status note chip (free-form short state, e.g. needs input)
                Rectangle {
                    visible: card.task.status_note !== ""
                    implicitWidth: noteText.implicitWidth + 14
                    implicitHeight: 20
                    radius: 10
                    color: "transparent"
                    border.color: isBlocked ? theme.tokens.accentColor
                                            : theme.tokens.border
                    Text {
                        id: noteText
                        anchors.centerIn: parent
                        text: card.task.status_note
                        color: isBlocked ? theme.tokens.accentColor
                                         : theme.tokens.textMuted
                        font.family: theme.monoFont
                        font.pixelSize: 11
                    }
                }
                Item {
                    Layout.fillWidth: true
                }
                // linked-asset count chip
                Row {
                    spacing: 4
                    visible: card.task.assetCount > 0
                    Image {
                        anchors.verticalCenter: parent.verticalCenter
                        source: Icons.url("image", theme.tokens.textMuted,
                                          theme.tokens.textMuted, 12)
                        sourceSize: Qt.size(12, 12)
                    }
                    Text {
                        text: card.task.assetCount
                        color: theme.tokens.textMuted
                        font.family: theme.monoFont
                        font.pixelSize: 11
                    }
                }
                Text {
                    text: card.task.shortId
                    color: theme.tokens.textMuted
                    font.family: theme.monoFont
                    font.pixelSize: 11
                }
            }
        }

        MouseArea {
            id: cardMouse
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton
            property real pressX: 0
            property real pressY: 0
            property bool moved: false
            onPressed: (mouse) => {
                pressX = mouse.x;
                pressY = mouse.y;
                moved = false;
            }
            onPositionChanged: (mouse) => {
                if (!pressed)
                    return;
                var dx = mouse.x - pressX;
                var dy = mouse.y - pressY;
                if (!moved && dx * dx + dy * dy > 36) {
                    // a real drag: take the grab away from the column
                    // and board Flickables (they would otherwise pan
                    // instead of moving the card (the #132 retest bug)
                    moved = true;
                    preventStealing = true;
                    var g0 = mapToItem(planningRoot, mouse.x, mouse.y);
                    planningRoot.beginDrag(card.task, g0.x, g0.y);
                }
                if (moved) {
                    var g = mapToItem(planningRoot, mouse.x, mouse.y);
                    planningRoot.dragProxyMove(g.x, g.y);
                }
            }
            onReleased: (mouse) => {
                if (moved) {
                    planningRoot.endDrag();
                } else {
                    planningRoot.openTask(card.task.id);
                }
                preventStealing = false;
            }
            onCanceled: {
                planningRoot.endDrag();
                preventStealing = false;
            }
            Accessible.role: Accessible.ListItem
            Accessible.name: card.task.title
                             + " — " + card.task.stage
                             + (card.task.projectName !== ""
                                ? " — " + card.task.projectName : "")
        }
    }

    // ---------------------------------------------------------- task dialog
    PlanningTaskDialog {
        id: taskDialog
        boardRoot: planningRoot
    }

    Connections {
        target: bridge
        function onPendingOpenTaskChanged() {
            if (bridge !== null && bridge.pendingOpenTask > 0)
                taskDialog.openWith(bridge.pendingOpenTask);
        }
    }
    Component.onCompleted: {
        // --qa-select can land BEFORE this loader finishes (asynchronous)
        if (bridge !== null && bridge.pendingOpenTask > 0)
            taskDialog.openWith(bridge.pendingOpenTask);
    }
}
