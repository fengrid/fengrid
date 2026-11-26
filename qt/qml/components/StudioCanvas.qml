import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// CANVAS screen — the Projects pane's collaborative design + code canvas.
//
//   left   boards · layers · library (every pane's assets, draggable)
//   centre infinite pan/zoom board: frames, shapes, text, stickies,
//          code cells and nodes BOUND to library objects (icons, images,
//          fonts, palettes, snippets, collections) that render live
//   right  inspector for the selection (geometry, style, text, code,
//          [[ ref ]] binding + usage) or the board when nothing is picked
//
// All state lives in the Canvas bridge (core/canvas.py): every edit is a
// Lamport-stamped op, so the REST API and other peers edit the same
// board concurrently and their changes stream in on the bridge's poll.
// View-only state (pan, zoom, live drag/resize deltas) stays here and is
// committed as ONE op on release.
Item {
    id: cvRoot

    property var cb: null               // Canvas bridge (injected)
    signal message(string text)

    // ---------------------------------------------------------- view
    property real zoom: 1.0
    property real panX: 80
    property real panY: 60
    readonly property real minZoom: 0.05
    readonly property real maxZoom: 16
    property string tool: "select"
    property bool spaceHeld: false
    property string editId: ""           // node in inline text edit
    property string connectFrom: ""
    // live drag (committed as one move on release)
    property bool dragging: false
    property real dragDX: 0
    property real dragDY: 0
    property var dragSet: ({})
    // live resize of the single selection
    property string rzId: ""
    property real rzX: 0
    property real rzY: 0
    property real rzW: 0
    property real rzH: 0
    // library panel
    property int leftTab: 1              // 0 layers · 1 library
    property string libKind: "icon"
    property string libQuery: ""
    property var libItems: []
    property var libDrag: ({})           // {kind, id, name} while dragging
    property real cursorWX: 0
    property real cursorWY: 0

    readonly property var nodesList: cb ? cb.nodes : []
    readonly property var sel: cb ? cb.selection : []
    readonly property var selNodes: cb ? cb.selectedNodes : []
    readonly property var one: selNodes.length === 1 ? selNodes[0] : null
    readonly property int gridSize: cb && cb.boardSettings && cb.boardSettings.grid ? cb.boardSettings.grid : 8

    // ------------------------------------------------------- helpers
    // theme tokens are strings — Qt.lighter(x, 1) turns one into a color
    // whose r/g/b we can read, for translucent overlays
    function tint(c, a) {
        var q = Qt.lighter(c, 1.0);
        return Qt.rgba(q.r, q.g, q.b, a);
    }
    function col(v, fb) {
        return (v === undefined || v === null || v === "") ? fb : v;
    }
    function num(v, fb) {
        var n = Number(v);
        return isNaN(n) ? fb : n;
    }
    function isSel(id) {
        return sel.indexOf(id) >= 0;
    }
    function nodeById(id) {
        for (var i = 0; i < nodesList.length; ++i)
            if (nodesList[i].id === id)
                return nodesList[i];
        return null;
    }
    function toWorld(sx, sy) {
        return Qt.point((sx - panX) / zoom, (sy - panY) / zoom);
    }
    function zoomAt(sx, sy, factor) {
        var nz = Math.max(minZoom, Math.min(maxZoom, zoom * factor));
        var w = toWorld(sx, sy);
        zoom = nz;
        panX = sx - w.x * nz;
        panY = sy - w.y * nz;
    }
    function setZoom(z) {
        zoomAt(viewport.width / 2, viewport.height / 2, z / zoom);
    }
    function fitTo(list) {
        if (!list || list.length === 0) {
            zoom = 1;
            panX = 80;
            panY = 60;
            return;
        }
        var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
        for (var i = 0; i < list.length; ++i) {
            var n = list[i];
            x0 = Math.min(x0, n.x);
            y0 = Math.min(y0, n.y);
            x1 = Math.max(x1, n.x + n.w);
            y1 = Math.max(y1, n.y + n.h);
        }
        var pad = 60;
        var z = Math.min((viewport.width - 2 * pad) / Math.max(1, x1 - x0), (viewport.height - 2 * pad) / Math.max(1, y1 - y0));
        zoom = Math.max(minZoom, Math.min(4, z));
        panX = (viewport.width - (x1 - x0) * zoom) / 2 - x0 * zoom;
        panY = (viewport.height - (y1 - y0) * zoom) / 2 - y0 * zoom;
    }
    function descendantsOf(ids) {
        var set = {};
        for (var i = 0; i < ids.length; ++i)
            set[ids[i]] = true;
        var grew = true;
        while (grew) {
            grew = false;
            for (var k = 0; k < nodesList.length; ++k) {
                var n = nodesList[k];
                if (n.parent && set[n.parent] && !set[n.id]) {
                    set[n.id] = true;
                    grew = true;
                }
            }
        }
        return set;
    }
    // geometry a node is DRAWN with right now (live drag/resize applied)
    function gx(n) {
        if (rzId === n.id)
            return rzX;
        return n.x + (dragging && dragSet[n.id] === true ? dragDX : 0);
    }
    function gy(n) {
        if (rzId === n.id)
            return rzY;
        return n.y + (dragging && dragSet[n.id] === true ? dragDY : 0);
    }
    function gw(n) {
        return rzId === n.id ? rzW : n.w;
    }
    function gh(n) {
        return rzId === n.id ? rzH : n.h;
    }
    function snap(v) {
        return Math.round(v / gridSize) * gridSize;
    }
    // layers panel rows: top-most first, children indented under parents
    function layerRows(list) {
        var byParent = {};
        for (var i = 0; i < list.length; ++i) {
            var pid = list[i].parent || "";
            if (!byParent[pid])
                byParent[pid] = [];
            byParent[pid].push(list[i]);
        }
        var out = [];
        var stack = [];
        var roots = (byParent[""] || []).slice().reverse();
        for (var r = roots.length - 1; r >= 0; --r)
            stack.push({
                n: roots[r],
                depth: 0
            });
        while (stack.length > 0 && out.length < 2000) {
            var top = stack.pop();
            out.push(top);
            if (top.depth >= 8)
                continue;
            var kids = (byParent[top.n.id] || []).slice().reverse();
            for (var k = kids.length - 1; k >= 0; --k)
                stack.push({
                    n: kids[k],
                    depth: top.depth + 1
                });
        }
        return out;
    }
    function refreshLib() {
        libItems = cb ? cb.libraryItems(libKind, libQuery) : [];
    }
    function boardPalette() {
        var out = [];
        for (var i = 0; i < nodesList.length; ++i) {
            var v = nodesList[i].view;
            if (v && v.hexes)
                for (var k = 0; k < v.hexes.length && out.length < 24; ++k)
                    if (out.indexOf(v.hexes[k]) < 0)
                        out.push(v.hexes[k]);
        }
        return out;
    }
    function placeAtCenter(kind, id) {
        var w = toWorld(viewport.width / 2, viewport.height / 2);
        cb.placeAsset(kind, id, snap(w.x), snap(w.y));
    }
    function startTool(t) {
        tool = t;
        connectFrom = "";
        viewport.forceActiveFocus();
    }
    function restoreViewport() {
        var vp = cb && cb.boardSettings ? cb.boardSettings.viewport : null;
        if (vp && vp.length === 3) {
            panX = vp[0];
            panY = vp[1];
            zoom = vp[2];
        } else {
            fitTo(nodesList);
        }
    }

    Connections {
        target: cb
        function onBoardChanged() {
            cvRoot.restoreViewport();
            cvRoot.editId = "";
        }
        function onNodesChanged() {
            linkLayer.requestPaint();
        }
        function onMessage(text) {
            cvRoot.message(text);
        }
    }
    onZoomChanged: {
        gridLayer.requestPaint();
        linkLayer.requestPaint();
        vpSave.restart();
    }
    onPanXChanged: {
        gridLayer.requestPaint();
        linkLayer.requestPaint();
        vpSave.restart();
    }
    onPanYChanged: {
        gridLayer.requestPaint();
        linkLayer.requestPaint();
        vpSave.restart();
    }
    onDragDXChanged: linkLayer.requestPaint()
    onDragDYChanged: linkLayer.requestPaint()
    Component.onCompleted: {
        refreshLib();
        Qt.callLater(restoreViewport);
    }
    Timer {
        id: vpSave
        interval: 700
        onTriggered: if (cvRoot.cb && cvRoot.cb.boardId > 0)
            cvRoot.cb.saveViewport(cvRoot.panX, cvRoot.panY, cvRoot.zoom)
    }

    // ---------------------------------------------------- local parts
    component PanelLabel: Text {
        font.family: theme.monoFont
        font.pixelSize: 9
        font.letterSpacing: 1.4
        color: theme.tokens.textMuted
    }
    component ToolBtn: Rectangle {
        id: tb
        property string label: ""
        property string glyph: ""        // Icons name (optional)
        property string tip: ""
        property bool active: false
        signal clicked
        implicitWidth: glyph !== "" ? 30 : Math.max(30, tbText.implicitWidth + 16)
        implicitHeight: 28
        radius: 6
        color: active ? theme.tokens.accentProject : (tbMouse.containsMouse ? theme.tokens.surface2 : "transparent")
        Text {
            id: tbText
            visible: tb.glyph === ""
            anchors.centerIn: parent
            text: tb.label
            font.family: theme.uiFont
            font.pixelSize: 11
            font.weight: Font.DemiBold
            color: tb.active ? theme.tokens.bg : theme.tokens.text
        }
        IconImage {
            visible: tb.glyph !== ""
            anchors.centerIn: parent
            name: tb.glyph
            px: 14
            tint: tb.active ? theme.tokens.bg : theme.tokens.text
        }
        MouseArea {
            id: tbMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: tb.clicked()
        }
        ToolTip.visible: tbMouse.containsMouse && tip !== ""
        ToolTip.delay: 400
        ToolTip.text: tip
        Accessible.role: Accessible.Button
        Accessible.name: tip !== "" ? tip : label
    }
    component NumField: ColumnLayout {
        id: nf
        property string label: ""
        property real value: 0
        property int decimals: 0
        signal committed(real v)
        spacing: 2
        Layout.fillWidth: true
        PanelLabel {
            text: nf.label
        }
        TextField {
            id: nfIn
            Layout.fillWidth: true
            Layout.preferredHeight: 26
            text: Number(nf.value).toFixed(nf.decimals)
            selectByMouse: true
            font.family: theme.monoFont
            font.pixelSize: 11
            color: theme.tokens.text
            background: Rectangle {
                radius: 5
                color: theme.tokens.surface2
                border.color: nfIn.activeFocus ? theme.tokens.accent : theme.tokens.border
            }
            onEditingFinished: {
                var v = Number(text);
                if (!isNaN(v) && v !== nf.value)
                    nf.committed(v);
            }
        }
    }
    component ColorField: RowLayout {
        id: cf
        property string label: ""
        property string value: ""
        signal committed(string v)
        spacing: 6
        Layout.fillWidth: true
        PanelLabel {
            text: cf.label
            Layout.preferredWidth: 46
        }
        Rectangle {
            Layout.preferredWidth: 22
            Layout.preferredHeight: 22
            radius: 5
            color: cf.value !== "" ? cf.value : "transparent"
            border.color: theme.tokens.border
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    colorDlg.target = cf;
                    colorDlg.openWith(cf.value !== "" ? cf.value : "#3388cc");
                }
            }
        }
        TextField {
            id: cfIn
            Layout.fillWidth: true
            Layout.preferredHeight: 26
            text: cf.value
            placeholderText: qsTr("none")
            font.family: theme.monoFont
            font.pixelSize: 11
            color: theme.tokens.text
            background: Rectangle {
                radius: 5
                color: theme.tokens.surface2
                border.color: cfIn.activeFocus ? theme.tokens.accent : theme.tokens.border
            }
            onEditingFinished: if (text !== cf.value)
                cf.committed(text.trim())
        }
    }

    ColorPickerDialog {
        id: colorDlg
        property var target: null
        onAcceptedHex: hex => {
            if (colorDlg.target)
                colorDlg.target.committed(hex);
        }
    }
    FolderDialog {
        id: exportDlg
        title: qsTr("Export board to folder")
        onAccepted: if (cvRoot.cb)
            cvRoot.cb.exportBundle(selectedFolder.toString())
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ═══════════════════════════════════════════ LEFT: boards/layers/library
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 244
            color: theme.tokens.surface
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    PanelLabel {
                        text: qsTr("BOARDS")
                        Layout.fillWidth: true
                    }
                    IconButton {
                        icon_name: "plus"
                        icon_px: 14
                        implicitWidth: 24
                        implicitHeight: 24
                        ToolTip.text: qsTr("New board")
                        onClicked: if (cvRoot.cb)
                            cvRoot.cb.newBoard(qsTr("Board %1").arg(cvRoot.cb.boards.length + 1))
                    }
                }
                ListView {
                    id: boardList
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(contentHeight, 124)
                    clip: true
                    model: cvRoot.cb ? cvRoot.cb.boards : []
                    spacing: 2
                    delegate: Rectangle {
                        id: brow
                        required property var modelData
                        width: ListView.view.width
                        height: 26
                        radius: 5
                        color: cvRoot.cb && cvRoot.cb.boardId === modelData.id ? theme.tokens.surface2 : (bm.containsMouse ? theme.tokens.surface2 : "transparent")
                        border.color: cvRoot.cb && cvRoot.cb.boardId === modelData.id ? theme.tokens.accentProject : "transparent"
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            Text {
                                Layout.fillWidth: true
                                text: brow.modelData.name
                                elide: Text.ElideRight
                                font.family: theme.uiFont
                                font.pixelSize: 12
                                color: theme.tokens.text
                            }
                            Text {
                                text: brow.modelData.nodes
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.textMuted
                            }
                        }
                        MouseArea {
                            id: bm
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: cvRoot.cb.setBoard(brow.modelData.id)
                        }
                    }
                }

                // layers | library switch
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Repeater {
                        model: [qsTr("Layers"), qsTr("Library")]
                        ToolBtn {
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            label: modelData
                            active: cvRoot.leftTab === index
                            onClicked: cvRoot.leftTab = index
                        }
                    }
                }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: cvRoot.leftTab

                    // ---- LAYERS (top-most first; children indented)
                    ListView {
                        id: layerList
                        clip: true
                        spacing: 1
                        model: cvRoot.layerRows(cvRoot.nodesList)
                        delegate: Rectangle {
                            id: lrow
                            required property var modelData
                            width: ListView.view.width
                            height: 24
                            radius: 4
                            color: cvRoot.isSel(modelData.n.id) ? cvRoot.tint(theme.tokens.accentProject, 0.22) : (lm.containsMouse ? theme.tokens.surface2 : "transparent")
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 6 + lrow.modelData.depth * 12
                                anchors.rightMargin: 4
                                spacing: 6
                                Text {
                                    text: ({
                                            frame: "#",
                                            group: "▣",
                                            rect: "□",
                                            ellipse: "○",
                                            line: "╱",
                                            text: "T",
                                            sticky: "▤",
                                            code: "</>",
                                            connector: "→",
                                            icon: "◆",
                                            image: "▧",
                                            font: "Aa",
                                            palette: "▥",
                                            snippet: "{}",
                                            asset: "▫",
                                            collection: "⊞"
                                        })[lrow.modelData.n.type] || "·"
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: lrow.modelData.n.bind && lrow.modelData.n.bind.kind ? theme.tokens.accent : theme.tokens.textMuted
                                    Layout.preferredWidth: 20
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: lrow.modelData.n.name || lrow.modelData.n.type
                                    elide: Text.ElideRight
                                    font.family: theme.uiFont
                                    font.pixelSize: 11
                                    color: lrow.modelData.n.hidden ? theme.tokens.textMuted : theme.tokens.text
                                }
                                IconImage {
                                    visible: lrow.modelData.n.locked
                                    name: "lock"
                                    px: 11
                                    tint: theme.tokens.textMuted
                                }
                            }
                            MouseArea {
                                id: lm
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: mouse => cvRoot.cb.select(lrow.modelData.n.id, (mouse.modifiers & (Qt.ShiftModifier | Qt.ControlModifier)) !== 0)
                                onDoubleClicked: cvRoot.fitTo([lrow.modelData.n])
                            }
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: layerList.count === 0
                            text: qsTr("No layers yet")
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.textMuted
                        }
                    }

                    // ---- LIBRARY: every pane's objects, drag onto the board
                    ColumnLayout {
                        spacing: 6
                        Flow {
                            Layout.fillWidth: true
                            spacing: 3
                            Repeater {
                                model: [
                                    {
                                        k: "icon",
                                        l: qsTr("Icons")
                                    },
                                    {
                                        k: "image",
                                        l: qsTr("Images")
                                    },
                                    {
                                        k: "font",
                                        l: qsTr("Fonts")
                                    },
                                    {
                                        k: "palette",
                                        l: qsTr("Colors")
                                    },
                                    {
                                        k: "snippet",
                                        l: qsTr("Code")
                                    },
                                    {
                                        k: "collection",
                                        l: qsTr("Collections")
                                    },
                                    {
                                        k: "smart",
                                        l: qsTr("Smart")
                                    },
                                    {
                                        k: "library",
                                        l: qsTr("Libraries")
                                    },
                                    {
                                        k: "doc",
                                        l: qsTr("Docs")
                                    },
                                    {
                                        k: "data",
                                        l: qsTr("Data")
                                    },
                                    {
                                        k: "video",
                                        l: qsTr("Video")
                                    },
                                    {
                                        k: "audio",
                                        l: qsTr("Audio")
                                    }
                                ]
                                Rectangle {
                                    id: kchip
                                    required property var modelData
                                    width: kt.implicitWidth + 12
                                    height: 20
                                    radius: 10
                                    color: cvRoot.libKind === modelData.k ? theme.tokens.accent : theme.tokens.surface2
                                    Text {
                                        id: kt
                                        anchors.centerIn: parent
                                        text: kchip.modelData.l
                                        font.family: theme.uiFont
                                        font.pixelSize: 10
                                        color: cvRoot.libKind === kchip.modelData.k ? theme.tokens.bg : theme.tokens.text
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            cvRoot.libKind = kchip.modelData.k;
                                            cvRoot.refreshLib();
                                        }
                                    }
                                }
                            }
                        }
                        TextField {
                            id: libSearch
                            Layout.fillWidth: true
                            Layout.preferredHeight: 26
                            placeholderText: qsTr("Search…  or paste a [[ ref ]] and press Enter")
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.text
                            background: Rectangle {
                                radius: 6
                                color: theme.tokens.surface2
                                border.color: libSearch.activeFocus ? theme.tokens.accent : theme.tokens.border
                            }
                            onTextEdited: {
                                cvRoot.libQuery = text;
                                libDebounce.restart();
                            }
                            onAccepted: {
                                var t = text.trim();
                                if (t.indexOf("[[") === 0 && cvRoot.cb) {
                                    var w = cvRoot.toWorld(viewport.width / 2, viewport.height / 2);
                                    if (cvRoot.cb.placeRef(t, cvRoot.snap(w.x), cvRoot.snap(w.y)) !== "")
                                        text = "";
                                }
                            }
                            Timer {
                                id: libDebounce
                                interval: 200
                                onTriggered: cvRoot.refreshLib()
                            }
                        }
                        GridView {
                            id: libGrid
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            readonly property bool wide: ["palette", "snippet", "collection", "smart", "library", "font", "doc", "data", "video", "audio"].indexOf(cvRoot.libKind) >= 0
                            cellWidth: wide ? width : Math.floor(width / 4)
                            cellHeight: wide ? 40 : cellWidth
                            model: cvRoot.libItems
                            ScrollBar.vertical: ScrollBar {}
                            delegate: Item {
                                id: litem
                                required property var modelData
                                width: libGrid.cellWidth
                                height: libGrid.cellHeight
                                Rectangle {
                                    anchors.fill: parent
                                    anchors.margins: 2
                                    radius: 6
                                    color: lim.containsMouse ? theme.tokens.surface2 : "transparent"
                                    border.color: lim.containsMouse ? theme.tokens.border : "transparent"
                                    Image {
                                        visible: litem.modelData.url !== undefined
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        source: litem.modelData.url || ""
                                        sourceSize.width: 96
                                        sourceSize.height: 96
                                        fillMode: Image.PreserveAspectFit
                                        asynchronous: true
                                        smooth: true
                                    }
                                    RowLayout {
                                        visible: litem.modelData.url === undefined
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 8
                                        spacing: 6
                                        Row {
                                            visible: litem.modelData.hexes !== undefined
                                            spacing: 0
                                            Repeater {
                                                model: (litem.modelData.hexes || []).slice(0, 8)
                                                Rectangle {
                                                    required property var modelData
                                                    width: 12
                                                    height: 22
                                                    color: modelData
                                                }
                                            }
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: litem.modelData.name + (litem.modelData.count !== undefined ? "  · " + litem.modelData.count : "")
                                            elide: Text.ElideRight
                                            font.family: litem.modelData.family ? litem.modelData.family : theme.uiFont
                                            font.pixelSize: 12
                                            color: theme.tokens.text
                                        }
                                        Text {
                                            visible: litem.modelData.sub !== undefined || litem.modelData.language !== undefined
                                            text: litem.modelData.sub || litem.modelData.language || ""
                                            font.family: theme.monoFont
                                            font.pixelSize: 9
                                            color: theme.tokens.textMuted
                                        }
                                    }
                                }
                                ToolTip.visible: lim.containsMouse && !lim.pressed
                                ToolTip.delay: 600
                                ToolTip.text: litem.modelData.name + qsTr(" — drag onto the board, or double-click")
                                MouseArea {
                                    id: lim
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    property point p0
                                    onPressed: mouse => {
                                        p0 = Qt.point(mouse.x, mouse.y);
                                    }
                                    onPositionChanged: mouse => {
                                        if (!pressed)
                                            return;
                                        var p = mapToItem(cvRoot, mouse.x, mouse.y);
                                        if (!ghost.visible && Math.abs(mouse.x - p0.x) + Math.abs(mouse.y - p0.y) > 6) {
                                            cvRoot.libDrag = {
                                                kind: litem.modelData.kind,
                                                id: litem.modelData.id,
                                                name: litem.modelData.name,
                                                url: litem.modelData.url || ""
                                            };
                                            ghost.visible = true;
                                        }
                                        ghost.x = p.x - ghost.width / 2;
                                        ghost.y = p.y - ghost.height / 2;
                                    }
                                    onReleased: mouse => {
                                        if (!ghost.visible)
                                            return;
                                        ghost.visible = false;
                                        var vp = mapToItem(viewport, mouse.x, mouse.y);
                                        if (vp.x >= 0 && vp.y >= 0 && vp.x <= viewport.width && vp.y <= viewport.height && cvRoot.cb) {
                                            var w = cvRoot.toWorld(vp.x, vp.y);
                                            var d = cvRoot.libDrag;
                                            Qt.callLater(function () {
                                                cvRoot.cb.placeAsset(d.kind, d.id, cvRoot.snap(w.x), cvRoot.snap(w.y));
                                            });
                                        }
                                        cvRoot.libDrag = ({});
                                    }
                                    onDoubleClicked: if (cvRoot.cb && cvRoot.cb.boardId > 0)
                                        cvRoot.placeAtCenter(litem.modelData.kind, litem.modelData.id)
                                }
                            }
                            Text {
                                anchors.centerIn: parent
                                width: parent.width - 20
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                                visible: libGrid.count === 0
                                text: qsTr("Nothing here yet — scan or import assets in the other panes and they show up in this library.")
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.textMuted
                            }
                        }
                    }
                }
            }
        }
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            color: theme.tokens.border
        }

        // ═══════════════════════════════════════════════════ CENTRE: board
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // ---- toolbar
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 40
                color: theme.tokens.surface
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 2

                    Repeater {
                        model: [
                            {
                                t: "select",
                                l: "V",
                                tip: qsTr("Select / move (V)")
                            },
                            {
                                t: "hand",
                                l: "H",
                                tip: qsTr("Pan (H, or hold Space)")
                            },
                            {
                                t: "frame",
                                l: "#",
                                tip: qsTr("Frame (F)")
                            },
                            {
                                t: "rect",
                                l: "□",
                                tip: qsTr("Rectangle (R)")
                            },
                            {
                                t: "ellipse",
                                l: "○",
                                tip: qsTr("Ellipse (O)")
                            },
                            {
                                t: "line",
                                l: "╱",
                                tip: qsTr("Line (L)")
                            },
                            {
                                t: "text",
                                l: "T",
                                tip: qsTr("Text (T)")
                            },
                            {
                                t: "sticky",
                                l: "▤",
                                tip: qsTr("Sticky note (S)")
                            },
                            {
                                t: "code",
                                l: "</>",
                                tip: qsTr("Code cell (C)")
                            },
                            {
                                t: "connect",
                                l: "→",
                                tip: qsTr("Connect two nodes (K)")
                            },
                            {
                                t: "comment",
                                l: "✎",
                                tip: qsTr("Comment (M)")
                            }
                        ]
                        ToolBtn {
                            required property var modelData
                            label: modelData.l
                            tip: modelData.tip
                            active: cvRoot.tool === modelData.t
                            onClicked: cvRoot.startTool(modelData.t)
                        }
                    }
                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 20
                        Layout.leftMargin: 6
                        Layout.rightMargin: 6
                        color: theme.tokens.border
                    }
                    ToolBtn {
                        label: "↶"
                        tip: qsTr("Undo (Ctrl+Z)")
                        opacity: cvRoot.cb && cvRoot.cb.canUndo ? 1 : 0.35
                        onClicked: if (cvRoot.cb)
                            cvRoot.cb.undo()
                    }
                    ToolBtn {
                        label: "↷"
                        tip: qsTr("Redo (Ctrl+Shift+Z)")
                        opacity: cvRoot.cb && cvRoot.cb.canRedo ? 1 : 0.35
                        onClicked: if (cvRoot.cb)
                            cvRoot.cb.redo()
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    // collaborators on this board right now
                    Row {
                        spacing: -6
                        Repeater {
                            model: cvRoot.cb ? cvRoot.cb.peers : []
                            Rectangle {
                                required property var modelData
                                width: 22
                                height: 22
                                radius: 11
                                color: modelData.color || theme.tokens.accent
                                border.color: theme.tokens.surface
                                border.width: 2
                                Text {
                                    anchors.centerIn: parent
                                    text: (parent.modelData.name || parent.modelData.actor || "?").charAt(0).toUpperCase()
                                    font.family: theme.uiFont
                                    font.pixelSize: 10
                                    font.weight: Font.Bold
                                    color: "#101418"
                                }
                                ToolTip.visible: peerMa.containsMouse
                                ToolTip.text: (modelData.name || modelData.actor) + qsTr(" is on this board")
                                MouseArea {
                                    id: peerMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                }
                            }
                        }
                    }
                    ToolBtn {
                        label: "−"
                        tip: qsTr("Zoom out (Ctrl+−)")
                        onClicked: cvRoot.setZoom(cvRoot.zoom / 1.25)
                    }
                    Text {
                        Layout.preferredWidth: 46
                        horizontalAlignment: Text.AlignHCenter
                        text: Math.round(cvRoot.zoom * 100) + "%"
                        font.family: theme.monoFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                        MouseArea {
                            anchors.fill: parent
                            onClicked: cvRoot.setZoom(1)
                        }
                    }
                    ToolBtn {
                        label: "+"
                        tip: qsTr("Zoom in (Ctrl+=)")
                        onClicked: cvRoot.setZoom(cvRoot.zoom * 1.25)
                    }
                    ToolBtn {
                        label: qsTr("Fit")
                        tip: qsTr("Zoom to fit (Shift+1)")
                        onClicked: cvRoot.fitTo(cvRoot.nodesList)
                    }
                    ToolBtn {
                        glyph: "download"
                        tip: qsTr("Export board — HTML + SVG + copied assets")
                        onClicked: if (cvRoot.cb && cvRoot.cb.boardId > 0)
                            exportDlg.open()
                    }
                }
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width
                    height: 1
                    color: theme.tokens.border
                }
            }

            // ---- the board
            Item {
                id: viewport
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                focus: true
                activeFocusOnTab: true

                Rectangle {
                    anchors.fill: parent
                    color: cvRoot.cb && cvRoot.cb.boardSettings && cvRoot.cb.boardSettings.background ? cvRoot.cb.boardSettings.background : theme.tokens.bg
                }
                // dot grid (screen space, so it stays crisp at any zoom)
                Canvas {
                    id: gridLayer
                    anchors.fill: parent
                    renderStrategy: Canvas.Cooperative
                    onPaint: {
                        var ctx = getContext("2d");
                        ctx.reset();
                        var step = cvRoot.gridSize * cvRoot.zoom;
                        while (step < 10)
                            step *= 4;
                        var ox = ((cvRoot.panX % step) + step) % step;
                        var oy = ((cvRoot.panY % step) + step) % step;
                        ctx.fillStyle = theme.isDark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.09)";
                        for (var x = ox; x < width; x += step)
                            for (var y = oy; y < height; y += step)
                                ctx.fillRect(Math.round(x), Math.round(y), 1.5, 1.5);
                    }
                }

                // background interactions: pan, marquee, draw tools,
                // wheel zoom, comments
                MouseArea {
                    id: bgMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                    property string mode: ""     // pan | marquee | draw
                    property point s0
                    property real px0: 0
                    property real py0: 0
                    cursorShape: (cvRoot.tool === "hand" || cvRoot.spaceHeld || mode === "pan") ? Qt.OpenHandCursor : (["select", "connect"].indexOf(cvRoot.tool) >= 0 ? Qt.ArrowCursor : Qt.CrossCursor)
                    onPressed: mouse => {
                        viewport.forceActiveFocus();
                        s0 = Qt.point(mouse.x, mouse.y);
                        if (mouse.button === Qt.MiddleButton || cvRoot.tool === "hand" || cvRoot.spaceHeld) {
                            mode = "pan";
                            px0 = cvRoot.panX;
                            py0 = cvRoot.panY;
                        } else if (cvRoot.tool === "select") {
                            mode = "marquee";
                            marquee.x = mouse.x;
                            marquee.y = mouse.y;
                            marquee.width = 0;
                            marquee.height = 0;
                        } else if (cvRoot.tool === "comment") {
                            mode = "";
                            var cw = cvRoot.toWorld(mouse.x, mouse.y);
                            commentPop.wx = cw.x;
                            commentPop.wy = cw.y;
                            commentPop.x = Math.min(mouse.x, viewport.width - commentPop.width - 8);
                            commentPop.y = Math.min(mouse.y, viewport.height - commentPop.height - 8);
                            commentPop.open();
                        } else if (cvRoot.tool === "connect") {
                            mode = "";
                            cvRoot.connectFrom = "";
                        } else {
                            mode = "draw";
                            drawPreview.x = mouse.x;
                            drawPreview.y = mouse.y;
                            drawPreview.width = 0;
                            drawPreview.height = 0;
                        }
                    }
                    onPositionChanged: mouse => {
                        var w = cvRoot.toWorld(mouse.x, mouse.y);
                        cvRoot.cursorWX = w.x;
                        cvRoot.cursorWY = w.y;
                        if (cvRoot.cb)
                            cvRoot.cb.setCursor(w.x, w.y);
                        if (!pressed)
                            return;
                        if (mode === "pan") {
                            cvRoot.panX = px0 + (mouse.x - s0.x);
                            cvRoot.panY = py0 + (mouse.y - s0.y);
                        } else if (mode === "marquee") {
                            marquee.x = Math.min(s0.x, mouse.x);
                            marquee.y = Math.min(s0.y, mouse.y);
                            marquee.width = Math.abs(mouse.x - s0.x);
                            marquee.height = Math.abs(mouse.y - s0.y);
                        } else if (mode === "draw") {
                            var sh = (mouse.modifiers & Qt.ShiftModifier) !== 0;
                            var dw = mouse.x - s0.x, dh = mouse.y - s0.y;
                            if (sh && cvRoot.tool !== "line") {
                                var m = Math.max(Math.abs(dw), Math.abs(dh));
                                dw = dw < 0 ? -m : m;
                                dh = dh < 0 ? -m : m;
                            }
                            drawPreview.x = Math.min(s0.x, s0.x + dw);
                            drawPreview.y = Math.min(s0.y, s0.y + dh);
                            drawPreview.width = Math.abs(dw);
                            drawPreview.height = Math.abs(dh);
                        }
                    }
                    onReleased: mouse => {
                        var m = mode;
                        mode = "";
                        if (!cvRoot.cb)
                            return;
                        if (m === "marquee") {
                            var add = (mouse.modifiers & (Qt.ShiftModifier | Qt.ControlModifier)) !== 0;
                            if (marquee.width < 3 && marquee.height < 3) {
                                if (!add)
                                    cvRoot.cb.clearSelection();
                            } else {
                                var a = cvRoot.toWorld(marquee.x, marquee.y);
                                var b = cvRoot.toWorld(marquee.x + marquee.width, marquee.y + marquee.height);
                                var inside = {};
                                var hits = [];
                                var list = cvRoot.nodesList;
                                for (var i = 0; i < list.length; ++i) {
                                    var n = list[i];
                                    if (n.locked || n.hidden || n.type === "connector")
                                        continue;
                                    if (n.x >= a.x && n.y >= a.y && n.x + n.w <= b.x && n.y + n.h <= b.y)
                                        inside[n.id] = true;
                                }
                                for (var k = 0; k < list.length; ++k)
                                    if (inside[list[k].id] && !inside[list[k].parent])
                                        hits.push(list[k].id);
                                cvRoot.cb.selectMany(hits, add);
                            }
                            marquee.width = 0;
                            marquee.height = 0;
                        } else if (m === "draw") {
                            var t = cvRoot.tool;
                            var p = cvRoot.toWorld(drawPreview.x, drawPreview.y);
                            var ww = drawPreview.width / cvRoot.zoom;
                            var hh = drawPreview.height / cvRoot.zoom;
                            var small = drawPreview.width < 4 && drawPreview.height < 4;
                            drawPreview.width = 0;
                            drawPreview.height = 0;
                            if (t === "line" && !small) {
                                // a line is stored as length + rotation about
                                // its centre (same model as the HTML/SVG
                                // exporters), so any angle round-trips
                                var o = cvRoot.toWorld(s0.x, s0.y);
                                var e = cvRoot.toWorld(mouse.x, mouse.y);
                                var len = Math.sqrt((e.x - o.x) * (e.x - o.x) + (e.y - o.y) * (e.y - o.y));
                                var lid = cvRoot.cb.addNode("line", (o.x + e.x) / 2 - len / 2, (o.y + e.y) / 2, len, 0);
                                var deg = Math.atan2(e.y - o.y, e.x - o.x) * 180 / Math.PI;
                                if (lid !== "" && Math.abs(deg) > 0.01)
                                    cvRoot.cb.setField(lid, "rot", deg);
                                cvRoot.tool = "select";
                                return;
                            }
                            var nid = cvRoot.cb.addNode(t, cvRoot.snap(p.x), cvRoot.snap(p.y), small ? 0 : ww, small ? 0 : hh);
                            if (nid !== "" && (t === "text" || t === "sticky"))
                                cvRoot.editId = nid;
                            cvRoot.tool = "select";
                        }
                    }
                    onWheel: wheel => {
                        if ((wheel.modifiers & Qt.ControlModifier) || (wheel.modifiers & Qt.MetaModifier)) {
                            cvRoot.zoomAt(wheel.x, wheel.y, Math.pow(1.0015, wheel.angleDelta.y));
                        } else if (wheel.modifiers & Qt.ShiftModifier) {
                            cvRoot.panX += wheel.angleDelta.y / 2;
                        } else {
                            cvRoot.panX += (wheel.pixelDelta.x !== 0 ? wheel.pixelDelta.x : wheel.angleDelta.x / 2);
                            cvRoot.panY += (wheel.pixelDelta.y !== 0 ? wheel.pixelDelta.y : wheel.angleDelta.y / 2);
                        }
                    }
                }

                // ---- world: nodes in board coordinates
                Item {
                    id: world
                    x: cvRoot.panX
                    y: cvRoot.panY
                    scale: cvRoot.zoom
                    transformOrigin: Item.TopLeft

                    Repeater {
                        model: cvRoot.nodesList
                        delegate: Item {
                            id: nv
                            required property var modelData
                            readonly property var n: modelData
                            readonly property var p: modelData.props || ({})
                            readonly property var v: modelData.view || ({})
                            readonly property bool bound: modelData.bind !== undefined && modelData.bind.kind !== undefined
                            readonly property bool broken: bound && v.ok === false
                            visible: !n.hidden && n.type !== "connector"
                            x: cvRoot.gx(n)
                            y: cvRoot.gy(n)
                            width: Math.max(1, cvRoot.gw(n))
                            height: n.type === "line" ? Math.max(1, cvRoot.num(p.strokeWidth, 2)) : Math.max(1, cvRoot.gh(n))
                            rotation: n.rot || 0
                            opacity: cvRoot.num(p.opacity, 1)

                            // shape body: frame / rect / ellipse / sticky / group / collection
                            Rectangle {
                                anchors.fill: parent
                                visible: ["frame", "rect", "ellipse", "sticky", "collection", "code", "snippet", "asset"].indexOf(nv.n.type) >= 0
                                radius: nv.n.type === "ellipse" ? Math.min(width, height) / 2 : cvRoot.num(nv.p.radius, nv.n.type === "sticky" ? 2 : 0)
                                color: nv.n.type === "code" || nv.n.type === "snippet" ? "#161B21" : (nv.n.type === "asset" ? theme.tokens.surface : cvRoot.col(nv.p.fill, "transparent"))
                                border.width: nv.broken ? 1.5 : (nv.n.type === "code" || nv.n.type === "snippet" || nv.n.type === "asset" ? 1 : cvRoot.num(nv.p.strokeWidth, 0))
                                border.color: nv.broken ? theme.tokens.accentCode : (nv.n.type === "code" || nv.n.type === "snippet" ? "#2A333B" : (nv.n.type === "asset" ? theme.tokens.border : cvRoot.col(nv.p.stroke, "transparent")))
                                clip: nv.n.type === "frame" && nv.p.clip !== false
                            }
                            // group: no fill, faint outline only when selected
                            Rectangle {
                                anchors.fill: parent
                                visible: nv.n.type === "group" && cvRoot.isSel(nv.n.id)
                                color: "transparent"
                                border.color: theme.tokens.accent
                                border.width: 1 / cvRoot.zoom
                            }
                            // line
                            Rectangle {
                                anchors.fill: parent
                                visible: nv.n.type === "line"
                                color: cvRoot.col(nv.p.stroke, "#6E7B86")
                                radius: height / 2
                            }
                            // text / sticky / font specimen
                            Text {
                                anchors.fill: parent
                                anchors.margins: nv.n.type === "sticky" ? 12 : 0
                                visible: ["text", "sticky", "font"].indexOf(nv.n.type) >= 0 && cvRoot.editId !== nv.n.id
                                text: nv.n.type === "font" ? (nv.p.text || nv.v.name || "") : (nv.p.text || "")
                                color: cvRoot.col(nv.p.color, "#16202B")
                                font.pixelSize: Math.max(1, cvRoot.num(nv.p.fontSize, 16))
                                font.weight: cvRoot.num(nv.p.fontWeight, 400)
                                font.family: nv.n.type === "font" ? (nv.v.family || nv.p.fontFamily || theme.uiFont) : (nv.p.fontFamily ? nv.p.fontFamily : theme.uiFont)
                                horizontalAlignment: nv.p.align === "center" ? Text.AlignHCenter : (nv.p.align === "right" ? Text.AlignRight : Text.AlignLeft)
                                wrapMode: Text.Wrap
                                elide: Text.ElideRight
                                textFormat: Text.PlainText
                            }
                            TextArea {
                                id: inlineEdit
                                anchors.fill: parent
                                anchors.margins: nv.n.type === "sticky" ? 8 : -4
                                visible: cvRoot.editId === nv.n.id
                                text: nv.p.text || ""
                                color: cvRoot.col(nv.p.color, "#16202B")
                                font.pixelSize: Math.max(1, cvRoot.num(nv.p.fontSize, 16))
                                font.family: nv.p.fontFamily ? nv.p.fontFamily : theme.uiFont
                                wrapMode: TextEdit.Wrap
                                background: Rectangle {
                                    color: "transparent"
                                    border.color: theme.tokens.accent
                                    border.width: 1 / cvRoot.zoom
                                }
                                onVisibleChanged: if (visible) {
                                    forceActiveFocus();
                                    selectAll();
                                }
                                onActiveFocusChanged: if (!activeFocus && visible)
                                    nv.commitText()
                                Keys.onEscapePressed: nv.commitText()
                            }
                            function commitText() {
                                var t = inlineEdit.text;
                                var id = n.id;
                                var old = p.text || "";
                                cvRoot.editId = "";
                                viewport.forceActiveFocus();
                                if (t !== old)
                                    Qt.callLater(function () {
                                        cvRoot.cb.setProp(id, "text", t);
                                    });
                            }
                            // icon / image
                            Image {
                                anchors.fill: parent
                                visible: (nv.n.type === "icon" || nv.n.type === "image") && !nv.broken
                                source: nv.v.url || ""
                                sourceSize.width: Math.min(2048, Math.max(32, nv.width * 2))
                                sourceSize.height: Math.min(2048, Math.max(32, nv.height * 2))
                                fillMode: nv.p.fit === "cover" ? Image.PreserveAspectCrop : (nv.p.fit === "fill" ? Image.Stretch : Image.PreserveAspectFit)
                                asynchronous: true
                                smooth: true
                                mipmap: true
                            }
                            // palette strip
                            Row {
                                anchors.fill: parent
                                visible: nv.n.type === "palette" && !nv.broken
                                Repeater {
                                    model: nv.v.hexes || []
                                    Rectangle {
                                        required property var modelData
                                        width: nv.width / Math.max(1, (nv.v.hexes || []).length)
                                        height: nv.height
                                        color: modelData
                                    }
                                }
                            }
                            // code cell / bound snippet: header + source
                            Column {
                                anchors.fill: parent
                                anchors.margins: 10
                                visible: nv.n.type === "code" || nv.n.type === "snippet"
                                spacing: 6
                                clip: true
                                Text {
                                    text: nv.n.type === "snippet" ? "{ } " + (nv.v.name || "snippet") + (nv.v.language ? "  · " + nv.v.language : "") : "</> " + (nv.n.name || "code") + "  · " + (nv.p.lang || "html")
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: nv.n.type === "snippet" ? "#39B8C4" : "#F0885C"
                                }
                                Text {
                                    width: parent.width
                                    text: nv.n.type === "snippet" ? (nv.v.code || "") : (nv.p.html || "") + ((nv.p.css || "") !== "" ? "\n\n" + nv.p.css : "")
                                    font.family: theme.monoFont
                                    font.pixelSize: 11
                                    color: "#C9D3DC"
                                    wrapMode: Text.WrapAnywhere
                                    textFormat: Text.PlainText
                                }
                            }
                            // generic media/doc/data card
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                visible: nv.n.type === "asset"
                                spacing: 8
                                Text {
                                    text: "▫"
                                    font.pixelSize: 18
                                    color: theme.tokens.accent
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: (nv.v.name || nv.n.name) + (nv.v.ext ? "  ." + nv.v.ext : "")
                                    elide: Text.ElideMiddle
                                    font.family: theme.uiFont
                                    font.pixelSize: 12
                                    color: theme.tokens.text
                                }
                            }
                            // broken binding: never drop the node — say so
                            Text {
                                anchors.centerIn: parent
                                visible: nv.broken
                                text: qsTr("missing: %1").arg(nv.v.name || nv.n.name)
                                font.family: theme.monoFont
                                font.pixelSize: 11
                                color: theme.tokens.accentCode
                            }
                            // frame / collection title, constant on-screen size
                            Text {
                                visible: nv.n.type === "frame" || nv.n.type === "collection"
                                y: -height - 4 / cvRoot.zoom
                                scale: 1 / cvRoot.zoom
                                transformOrigin: Item.BottomLeft
                                text: (nv.n.type === "collection" ? "⊞ " : "") + (nv.n.name || nv.n.type) + (nv.v.members !== undefined ? "  · " + nv.v.members : "")
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: cvRoot.isSel(nv.n.id) ? theme.tokens.accent : theme.tokens.textMuted
                                MouseArea {
                                    id: titleMouse
                                    anchors.fill: parent
                                    enabled: nodeMouse.enabled
                                    onPressed: mouse => nodeMouse.pressAt(mouse, titleMouse)
                                    onPositionChanged: mouse => nodeMouse.moveAt(mouse, titleMouse)
                                    onReleased: mouse => nodeMouse.releaseAt(mouse)
                                }
                            }

                            MouseArea {
                                id: nodeMouse
                                anchors.fill: parent
                                // frames/collections are grabbed by their title or
                                // empty area; children (higher z) win on top
                                enabled: !nv.n.locked && cvRoot.editId !== nv.n.id && (cvRoot.tool === "select" || cvRoot.tool === "connect") && !cvRoot.spaceHeld
                                acceptedButtons: Qt.LeftButton
                                property point s0
                                property bool moved: false
                                function pressAt(mouse, item) {
                                    viewport.forceActiveFocus();
                                    var add = (mouse.modifiers & (Qt.ShiftModifier | Qt.ControlModifier)) !== 0;
                                    if (cvRoot.tool === "connect") {
                                        if (cvRoot.connectFrom === "")
                                            cvRoot.connectFrom = nv.n.id;
                                        else {
                                            var a = cvRoot.connectFrom, b = nv.n.id;
                                            cvRoot.connectFrom = "";
                                            cvRoot.tool = "select";
                                            Qt.callLater(function () {
                                                cvRoot.cb.connectNodes(a, b);
                                            });
                                        }
                                        return;
                                    }
                                    if (!cvRoot.isSel(nv.n.id) || add)
                                        cvRoot.cb.select(nv.n.id, add);
                                    s0 = item.mapToItem(viewport, mouse.x, mouse.y);
                                    moved = false;
                                    cvRoot.dragSet = cvRoot.descendantsOf(cvRoot.sel);
                                }
                                function moveAt(mouse, item) {
                                    if (cvRoot.tool === "connect")
                                        return;
                                    var p = item.mapToItem(viewport, mouse.x, mouse.y);
                                    var dx = (p.x - s0.x) / cvRoot.zoom;
                                    var dy = (p.y - s0.y) / cvRoot.zoom;
                                    if (!moved && Math.abs(dx) + Math.abs(dy) < 3 / cvRoot.zoom)
                                        return;
                                    if (mouse.modifiers & Qt.ShiftModifier) {
                                        if (Math.abs(dx) > Math.abs(dy))
                                            dy = 0;
                                        else
                                            dx = 0;
                                    }
                                    moved = true;
                                    cvRoot.dragging = true;
                                    cvRoot.dragDX = (mouse.modifiers & Qt.AltModifier) ? dx : cvRoot.snap(dx);
                                    cvRoot.dragDY = (mouse.modifiers & Qt.AltModifier) ? dy : cvRoot.snap(dy);
                                }
                                function releaseAt(mouse) {
                                    if (!moved)
                                        return;
                                    var dx = cvRoot.dragDX, dy = cvRoot.dragDY;
                                    moved = false;
                                    Qt.callLater(function () {
                                        cvRoot.cb.moveSelection(dx, dy);
                                        cvRoot.dragging = false;
                                        cvRoot.dragDX = 0;
                                        cvRoot.dragDY = 0;
                                    });
                                }
                                onPressed: mouse => pressAt(mouse, nodeMouse)
                                onPositionChanged: mouse => moveAt(mouse, nodeMouse)
                                onReleased: mouse => releaseAt(mouse)
                                onDoubleClicked: {
                                    if (["text", "sticky"].indexOf(nv.n.type) >= 0)
                                        cvRoot.editId = nv.n.id;
                                    else if (nv.n.type === "frame" || nv.n.type === "collection" || nv.n.type === "group")
                                        cvRoot.fitTo([nv.n]);
                                }
                            }
                        }
                    }
                }

                // connectors (screen space; follow live drags)
                Canvas {
                    id: linkLayer
                    anchors.fill: parent
                    renderStrategy: Canvas.Cooperative
                    onPaint: {
                        var ctx = getContext("2d");
                        ctx.reset();
                        var list = cvRoot.nodesList;
                        var byId = {};
                        for (var i = 0; i < list.length; ++i)
                            byId[list[i].id] = list[i];
                        for (var k = 0; k < list.length; ++k) {
                            var c = list[k];
                            if (c.type !== "connector" || c.hidden)
                                continue;
                            var a = byId[c.props.from], b = byId[c.props.to];
                            if (!a || !b)
                                continue;
                            var ax = cvRoot.panX + (cvRoot.gx(a) + cvRoot.gw(a) / 2) * cvRoot.zoom;
                            var ay = cvRoot.panY + (cvRoot.gy(a) + cvRoot.gh(a) / 2) * cvRoot.zoom;
                            var bx = cvRoot.panX + (cvRoot.gx(b) + cvRoot.gw(b) / 2) * cvRoot.zoom;
                            var by = cvRoot.panY + (cvRoot.gy(b) + cvRoot.gh(b) / 2) * cvRoot.zoom;
                            ctx.strokeStyle = cvRoot.isSel(c.id) ? theme.tokens.accent : (c.props.stroke || "#6E7B86");
                            ctx.lineWidth = Math.max(1, (c.props.strokeWidth || 2) * Math.min(cvRoot.zoom, 2));
                            ctx.beginPath();
                            ctx.moveTo(ax, ay);
                            ctx.lineTo(bx, by);
                            ctx.stroke();
                            if (c.props.arrow !== false) {
                                var ang = Math.atan2(by - ay, bx - ax);
                                var len = 9;
                                ctx.beginPath();
                                ctx.moveTo(bx, by);
                                ctx.lineTo(bx - len * Math.cos(ang - 0.45), by - len * Math.sin(ang - 0.45));
                                ctx.lineTo(bx - len * Math.cos(ang + 0.45), by - len * Math.sin(ang + 0.45));
                                ctx.closePath();
                                ctx.fillStyle = ctx.strokeStyle;
                                ctx.fill();
                            }
                        }
                    }
                }

                // selection outlines + resize handles (screen space: crisp)
                Repeater {
                    model: cvRoot.selNodes
                    Rectangle {
                        id: selBox
                        required property var modelData
                        readonly property var n: modelData
                        visible: n.type !== "connector"
                        rotation: n.rot || 0
                        x: cvRoot.panX + cvRoot.gx(n) * cvRoot.zoom - 1
                        y: cvRoot.panY + cvRoot.gy(n) * cvRoot.zoom - 1
                        width: cvRoot.gw(n) * cvRoot.zoom + 2
                        height: Math.max(2, cvRoot.gh(n) * cvRoot.zoom) + 2
                        color: "transparent"
                        border.color: theme.tokens.accent
                        border.width: 1.5
                        // size readout
                        Rectangle {
                            visible: cvRoot.selNodes.length === 1
                            anchors.top: parent.bottom
                            anchors.topMargin: 6
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: sizeText.implicitWidth + 10
                            height: 18
                            radius: 4
                            color: theme.tokens.accent
                            Text {
                                id: sizeText
                                anchors.centerIn: parent
                                text: Math.round(cvRoot.gw(selBox.n)) + " × " + Math.round(cvRoot.gh(selBox.n))
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.bg
                            }
                        }
                        Repeater {
                            // corner + edge handles: [fx, fy] fractions
                            model: cvRoot.selNodes.length === 1 && !selBox.n.locked && !(selBox.n.rot) ? [[0, 0], [0.5, 0], [1, 0], [1, 0.5], [1, 1], [0.5, 1], [0, 1], [0, 0.5]] : []
                            Rectangle {
                                id: hdl
                                required property var modelData
                                readonly property real fx: modelData[0]
                                readonly property real fy: modelData[1]
                                width: 9
                                height: 9
                                x: fx * selBox.width - width / 2
                                y: fy * selBox.height - height / 2
                                color: theme.tokens.surface
                                border.color: theme.tokens.accent
                                border.width: 1.5
                                MouseArea {
                                    anchors.fill: parent
                                    anchors.margins: -4
                                    cursorShape: (hdl.fx === 0.5) ? Qt.SizeVerCursor : (hdl.fy === 0.5 ? Qt.SizeHorCursor : ((hdl.fx === hdl.fy) ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor))
                                    property point s0
                                    property var g0: ({})
                                    onPressed: mouse => {
                                        s0 = mapToItem(viewport, mouse.x, mouse.y);
                                        var n = selBox.n;
                                        g0 = {
                                            x: n.x,
                                            y: n.y,
                                            w: n.w,
                                            h: n.h
                                        };
                                        cvRoot.rzX = n.x;
                                        cvRoot.rzY = n.y;
                                        cvRoot.rzW = n.w;
                                        cvRoot.rzH = n.h;
                                        cvRoot.rzId = n.id;
                                    }
                                    onPositionChanged: mouse => {
                                        var p = mapToItem(viewport, mouse.x, mouse.y);
                                        var dx = (p.x - s0.x) / cvRoot.zoom;
                                        var dy = (p.y - s0.y) / cvRoot.zoom;
                                        var x = g0.x, y = g0.y, w = g0.w, h = g0.h;
                                        if (hdl.fx === 0) {
                                            x = g0.x + dx;
                                            w = g0.w - dx;
                                        } else if (hdl.fx === 1)
                                            w = g0.w + dx;
                                        if (hdl.fy === 0) {
                                            y = g0.y + dy;
                                            h = g0.h - dy;
                                        } else if (hdl.fy === 1)
                                            h = g0.h + dy;
                                        if ((mouse.modifiers & Qt.ShiftModifier) && g0.h > 0) {
                                            var r = g0.w / g0.h;
                                            if (hdl.fy === 0.5)
                                                h = w / r;
                                            else
                                                w = h * r;
                                            if (hdl.fx === 0)
                                                x = g0.x + g0.w - w;
                                            if (hdl.fy === 0)
                                                y = g0.y + g0.h - h;
                                        }
                                        if (!(mouse.modifiers & Qt.AltModifier)) {
                                            x = cvRoot.snap(x);
                                            y = cvRoot.snap(y);
                                            w = cvRoot.snap(w);
                                            h = cvRoot.snap(h);
                                        }
                                        cvRoot.rzX = x;
                                        cvRoot.rzY = y;
                                        cvRoot.rzW = Math.max(1, w);
                                        cvRoot.rzH = Math.max(selBox.n.type === "line" ? 0 : 1, h);
                                        linkLayer.requestPaint();
                                    }
                                    onReleased: {
                                        var id = cvRoot.rzId;
                                        var g = [cvRoot.rzX, cvRoot.rzY, cvRoot.rzW, cvRoot.rzH];
                                        Qt.callLater(function () {
                                            cvRoot.cb.setGeometry(id, g[0], g[1], g[2], g[3]);
                                            cvRoot.rzId = "";
                                        });
                                    }
                                }
                            }
                        }
                    }
                }

                // pending-connector hint
                Rectangle {
                    visible: cvRoot.tool === "connect"
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.topMargin: 10
                    width: hint.implicitWidth + 20
                    height: 26
                    radius: 13
                    color: theme.tokens.surface2
                    border.color: theme.tokens.border
                    Text {
                        id: hint
                        anchors.centerIn: parent
                        text: cvRoot.connectFrom === "" ? qsTr("Click the node to connect FROM") : qsTr("Now click the node to connect TO  (Esc cancels)")
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                    }
                }

                Rectangle {
                    id: marquee
                    visible: bgMouse.mode === "marquee" && width > 0
                    color: cvRoot.tint(theme.tokens.accent, 0.10)
                    border.color: theme.tokens.accent
                    border.width: 1
                }
                Rectangle {
                    id: drawPreview
                    visible: bgMouse.mode === "draw" && (width > 0 || height > 0)
                    color: "transparent"
                    radius: cvRoot.tool === "ellipse" ? Math.min(width, height) / 2 : 0
                    border.color: theme.tokens.accent
                    border.width: 1
                }

                // comment pins
                Repeater {
                    model: cvRoot.cb ? cvRoot.cb.comments : []
                    Rectangle {
                        id: pin
                        required property var modelData
                        x: cvRoot.panX + modelData.x * cvRoot.zoom - 2
                        y: cvRoot.panY + modelData.y * cvRoot.zoom - height + 2
                        width: 22
                        height: 22
                        radius: 11
                        color: theme.tokens.litPane
                        border.color: theme.tokens.bg
                        border.width: 2
                        Text {
                            anchors.centerIn: parent
                            text: "✎"
                            font.pixelSize: 10
                            color: "#101418"
                        }
                        ToolTip.visible: pinMa.containsMouse
                        ToolTip.text: modelData.body + "\n— " + modelData.author + qsTr("   (click to resolve)")
                        MouseArea {
                            id: pinMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: cvRoot.cb.resolveComment(pin.modelData.id)
                        }
                    }
                }

                // collaborators' cursors
                Repeater {
                    model: cvRoot.cb ? cvRoot.cb.peers : []
                    Item {
                        id: peerCur
                        required property var modelData
                        visible: modelData.cursor_x !== null && modelData.cursor_x !== undefined
                        x: cvRoot.panX + (modelData.cursor_x || 0) * cvRoot.zoom
                        y: cvRoot.panY + (modelData.cursor_y || 0) * cvRoot.zoom
                        Behavior on x {
                            NumberAnimation {
                                duration: 300
                            }
                        }
                        Behavior on y {
                            NumberAnimation {
                                duration: 300
                            }
                        }
                        Text {
                            text: "➤"
                            rotation: -125
                            font.pixelSize: 14
                            color: peerCur.modelData.color || theme.tokens.accent
                        }
                        Rectangle {
                            x: 12
                            y: 12
                            width: peerName.implicitWidth + 10
                            height: 16
                            radius: 4
                            color: peerCur.modelData.color || theme.tokens.accent
                            Text {
                                id: peerName
                                anchors.centerIn: parent
                                text: peerCur.modelData.name || peerCur.modelData.actor
                                font.family: theme.uiFont
                                font.pixelSize: 10
                                color: "#101418"
                            }
                        }
                    }
                }

                // empty states
                Column {
                    anchors.centerIn: parent
                    // the board column can be narrower than the copy
                    // (left + right panels on a 1280px window): wrap
                    // inside it instead of spilling past both edges
                    width: Math.min(380, parent.width - 32)
                    spacing: 12
                    visible: !cvRoot.cb || cvRoot.cb.boardId <= 0
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        text: projects !== null && projects.currentId >= 0 ? qsTr("This project has no boards yet") : qsTr("Open or create a project to start a board")
                        font.family: theme.headingFont
                        font.pixelSize: 15
                        color: theme.tokens.text
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        text: qsTr("Boards are infinite canvases for layouts, flows and code. Drag icons, images, fonts, palettes, snippets and whole collections in from the library — they stay linked to your library and update everywhere.")
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        color: theme.tokens.textMuted
                    }
                    FgButton {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: projects !== null && projects.currentId >= 0
                        text: qsTr("Create First Board")
                        onClicked: cvRoot.cb.newBoard(qsTr("Board 1"))
                    }
                }
                Text {
                    anchors.centerIn: parent
                    width: Math.min(implicitWidth, parent.width - 32)
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    visible: cvRoot.cb && cvRoot.cb.boardId > 0 && cvRoot.nodesList.length === 0
                    text: qsTr("Pick a tool above, or drag something in from the library")
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    color: theme.tokens.textMuted
                }

                // ---- keyboard
                Keys.onReleased: event => {
                    if (event.key === Qt.Key_Space && !event.isAutoRepeat) {
                        cvRoot.spaceHeld = false;
                        event.accepted = true;
                    }
                }
                Keys.onPressed: event => {
                    if (!cvRoot.cb)
                        return;
                    var ctrl = (event.modifiers & Qt.ControlModifier) || (event.modifiers & Qt.MetaModifier);
                    var shift = event.modifiers & Qt.ShiftModifier;
                    var k = event.key;
                    event.accepted = true;
                    if (k === Qt.Key_Space) {
                        cvRoot.spaceHeld = true;
                    } else if (k === Qt.Key_Delete || k === Qt.Key_Backspace) {
                        cvRoot.cb.deleteSelection();
                    } else if (ctrl && k === Qt.Key_Z) {
                        if (shift)
                            cvRoot.cb.redo();
                        else
                            cvRoot.cb.undo();
                    } else if (ctrl && k === Qt.Key_Y) {
                        cvRoot.cb.redo();
                    } else if (ctrl && k === Qt.Key_D) {
                        cvRoot.cb.duplicateSelection();
                    } else if (ctrl && k === Qt.Key_G) {
                        if (shift)
                            cvRoot.cb.ungroupSelection();
                        else
                            cvRoot.cb.groupSelection(event.modifiers & Qt.AltModifier ? true : false);
                    } else if (ctrl && k === Qt.Key_A) {
                        cvRoot.cb.selectAll();
                    } else if (ctrl && (k === Qt.Key_Equal || k === Qt.Key_Plus)) {
                        cvRoot.setZoom(cvRoot.zoom * 1.25);
                    } else if (ctrl && k === Qt.Key_Minus) {
                        cvRoot.setZoom(cvRoot.zoom / 1.25);
                    } else if (ctrl && k === Qt.Key_0) {
                        cvRoot.setZoom(1);
                    } else if (shift && (k === Qt.Key_1 || k === Qt.Key_Exclam)) {
                        cvRoot.fitTo(cvRoot.nodesList);
                    } else if (shift && (k === Qt.Key_2 || k === Qt.Key_At)) {
                        cvRoot.fitTo(cvRoot.selNodes);
                    } else if (k === Qt.Key_BracketRight) {
                        cvRoot.cb.restackSelection(ctrl ? "front" : "forward");
                    } else if (k === Qt.Key_BracketLeft) {
                        cvRoot.cb.restackSelection(ctrl ? "back" : "backward");
                    } else if (k === Qt.Key_Left || k === Qt.Key_Right || k === Qt.Key_Up || k === Qt.Key_Down) {
                        var step = shift ? 10 : 1;
                        cvRoot.cb.moveSelection(k === Qt.Key_Left ? -step : (k === Qt.Key_Right ? step : 0), k === Qt.Key_Up ? -step : (k === Qt.Key_Down ? step : 0));
                    } else if (k === Qt.Key_Escape) {
                        if (cvRoot.tool !== "select")
                            cvRoot.startTool("select");
                        else
                            cvRoot.cb.clearSelection();
                    } else if (k === Qt.Key_Return || k === Qt.Key_Enter) {
                        if (cvRoot.one && ["text", "sticky"].indexOf(cvRoot.one.type) >= 0)
                            cvRoot.editId = cvRoot.one.id;
                    } else if (!ctrl) {
                        var map = {};
                        map[Qt.Key_V] = "select";
                        map[Qt.Key_H] = "hand";
                        map[Qt.Key_F] = "frame";
                        map[Qt.Key_R] = "rect";
                        map[Qt.Key_O] = "ellipse";
                        map[Qt.Key_L] = "line";
                        map[Qt.Key_T] = "text";
                        map[Qt.Key_S] = "sticky";
                        map[Qt.Key_C] = "code";
                        map[Qt.Key_K] = "connect";
                        map[Qt.Key_M] = "comment";
                        if (map[k] !== undefined)
                            cvRoot.startTool(map[k]);
                        else
                            event.accepted = false;
                    } else {
                        event.accepted = false;
                    }
                }
                Keys.onShortcutOverride: event => {
                    // keep unmodified tool letters, Delete, arrows, Space
                    // and Esc local to the board while it has focus —
                    // modified chords (Alt+~ command bar, Ctrl+…) still
                    // reach the app's global shortcuts
                    var mods = event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier);
                    if (mods !== 0)
                        return;
                    var local = [Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Escape, Qt.Key_Space, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_BracketLeft, Qt.Key_BracketRight];
                    if (local.indexOf(event.key) >= 0 || (event.key >= Qt.Key_A && event.key <= Qt.Key_Z))
                        event.accepted = true;
                }

                // new-comment popup
                Popup {
                    id: commentPop
                    property real wx: 0
                    property real wy: 0
                    width: 260
                    padding: 10
                    modal: false
                    focus: true
                    background: Rectangle {
                        radius: 8
                        color: theme.tokens.surface
                        border.color: theme.tokens.border
                    }
                    onOpened: commentIn.forceActiveFocus()
                    contentItem: ColumnLayout {
                        spacing: 6
                        TextField {
                            id: commentIn
                            Layout.fillWidth: true
                            placeholderText: qsTr("Leave a comment…")
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: theme.tokens.text
                            background: Rectangle {
                                radius: 5
                                color: theme.tokens.surface2
                                border.color: theme.tokens.border
                            }
                            onAccepted: {
                                if (text.trim() !== "")
                                    cvRoot.cb.addComment(text, commentPop.wx, commentPop.wy, cvRoot.one ? cvRoot.one.id : "");
                                text = "";
                                commentPop.close();
                                cvRoot.startTool("select");
                            }
                        }
                    }
                }
            }

            // ---- status bar
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 24
                color: theme.tokens.surface
                Rectangle {
                    width: parent.width
                    height: 1
                    color: theme.tokens.border
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 16
                    Text {
                        text: cvRoot.cb && cvRoot.cb.boardId > 0 ? cvRoot.cb.boardName : "—"
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                    }
                    Text {
                        text: qsTr("%n node(s)", "", cvRoot.nodesList.length)
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                    Text {
                        visible: cvRoot.sel.length > 0
                        text: qsTr("%n selected", "", cvRoot.sel.length)
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.accent
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Text {
                        text: "x " + Math.round(cvRoot.cursorWX) + "   y " + Math.round(cvRoot.cursorWY)
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                    Row {
                        spacing: 5
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 7
                            height: 7
                            radius: 4
                            color: cvRoot.cb && cvRoot.cb.peers.length > 0 ? theme.tokens.success : theme.tokens.textMuted
                        }
                        Text {
                            text: cvRoot.cb && cvRoot.cb.peers.length > 0 ? qsTr("Live · %n collaborator(s)", "", cvRoot.cb.peers.length) : qsTr("Live sync ready")
                            font.family: theme.uiFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            color: theme.tokens.border
        }

        // ═════════════════════════════════════════════ RIGHT: inspector
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 264
            color: theme.tokens.surface
            Flickable {
                id: insFlick
                anchors.fill: parent
                anchors.margins: 12
                contentHeight: ins.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                ColumnLayout {
                    id: ins
                    width: insFlick.width
                    spacing: 10

                    Text {
                        text: qsTr("INSPECTOR")
                        font.family: theme.headingFont
                        font.pixelSize: 11
                        font.letterSpacing: 1.4
                        color: theme.tokens.textMuted
                    }

                    // ---------------- nothing selected → board
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: cvRoot.sel.length === 0 && cvRoot.cb !== null && cvRoot.cb.boardId > 0
                        spacing: 8
                        PanelLabel {
                            text: qsTr("BOARD")
                        }
                        TextField {
                            id: boardNameIn
                            Layout.fillWidth: true
                            Layout.preferredHeight: 28
                            text: cvRoot.cb ? cvRoot.cb.boardName : ""
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: theme.tokens.text
                            background: Rectangle {
                                radius: 6
                                color: theme.tokens.surface2
                                border.color: boardNameIn.activeFocus ? theme.tokens.accent : theme.tokens.border
                            }
                            onEditingFinished: if (text.trim() !== "" && text !== cvRoot.cb.boardName)
                                cvRoot.cb.renameBoard(text)
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            FgButton {
                                text: qsTr("Duplicate")
                                Layout.fillWidth: true
                                onClicked: cvRoot.cb.duplicateBoard()
                            }
                            FgButton {
                                text: qsTr("Delete…")
                                Layout.fillWidth: true
                                onClicked: deleteBoardDlg.open()
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: qsTr("%n node(s) on this board. Double-click a frame to zoom to it; Shift+1 fits everything.", "", cvRoot.nodesList.length)
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.textMuted
                        }
                        PanelLabel {
                            text: qsTr("COMMENTS")
                            visible: cvRoot.cb && cvRoot.cb.comments.length > 0
                        }
                        Repeater {
                            model: cvRoot.cb ? cvRoot.cb.comments : []
                            Rectangle {
                                id: cmt
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: cmtCol.implicitHeight + 12
                                radius: 6
                                color: theme.tokens.surface2
                                ColumnLayout {
                                    id: cmtCol
                                    anchors.fill: parent
                                    anchors.margins: 6
                                    spacing: 2
                                    Text {
                                        Layout.fillWidth: true
                                        text: cmt.modelData.body
                                        wrapMode: Text.Wrap
                                        font.family: theme.uiFont
                                        font.pixelSize: 11
                                        color: theme.tokens.text
                                    }
                                    RowLayout {
                                        Text {
                                            Layout.fillWidth: true
                                            text: cmt.modelData.author
                                            font.family: theme.monoFont
                                            font.pixelSize: 9
                                            color: theme.tokens.textMuted
                                        }
                                        Text {
                                            text: qsTr("Resolve")
                                            font.family: theme.uiFont
                                            font.pixelSize: 10
                                            color: theme.tokens.accent
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: cvRoot.cb.resolveComment(cmt.modelData.id)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        PanelLabel {
                            text: qsTr("SHORTCUTS")
                        }
                        Text {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: qsTr("V select · H pan (or Space) · F frame · R rect · O ellipse · L line · T text · S sticky · C code · K connect · M comment\nCtrl+D duplicate · Ctrl+G group · Ctrl+Alt+G frame · Ctrl+Shift+G ungroup · [ ] restack · arrows nudge (Shift ×10) · Alt disables snapping")
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                            lineHeight: 1.25
                        }
                    }

                    // ---------------- multi-selection
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: cvRoot.sel.length > 1
                        spacing: 8
                        PanelLabel {
                            text: qsTr("%n NODES SELECTED", "", cvRoot.sel.length)
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 4
                            columnSpacing: 4
                            rowSpacing: 4
                            Repeater {
                                model: [
                                    {
                                        h: "left",
                                        l: "⇤",
                                        t: qsTr("Align left")
                                    },
                                    {
                                        h: "hcenter",
                                        l: "↔",
                                        t: qsTr("Align centres horizontally")
                                    },
                                    {
                                        h: "right",
                                        l: "⇥",
                                        t: qsTr("Align right")
                                    },
                                    {
                                        h: "hdist",
                                        l: "⋯",
                                        t: qsTr("Distribute horizontally")
                                    },
                                    {
                                        h: "top",
                                        l: "⤒",
                                        t: qsTr("Align top")
                                    },
                                    {
                                        h: "vcenter",
                                        l: "↕",
                                        t: qsTr("Align centres vertically")
                                    },
                                    {
                                        h: "bottom",
                                        l: "⤓",
                                        t: qsTr("Align bottom")
                                    },
                                    {
                                        h: "vdist",
                                        l: "⋮",
                                        t: qsTr("Distribute vertically")
                                    }
                                ]
                                ToolBtn {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    label: modelData.l
                                    tip: modelData.t
                                    color: theme.tokens.surface2
                                    onClicked: cvRoot.cb.alignSelection(modelData.h)
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            FgButton {
                                text: qsTr("Group")
                                Layout.fillWidth: true
                                onClicked: cvRoot.cb.groupSelection(false)
                            }
                            FgButton {
                                text: qsTr("Frame")
                                Layout.fillWidth: true
                                onClicked: cvRoot.cb.groupSelection(true)
                            }
                        }
                        FgButton {
                            Layout.fillWidth: true
                            visible: cvRoot.sel.length === 2
                            text: qsTr("Connect These Two")
                            onClicked: cvRoot.cb.connectNodes(cvRoot.sel[0], cvRoot.sel[1])
                        }
                        ColorField {
                            label: qsTr("Fill")
                            value: ""
                            onCommitted: v => cvRoot.cb.setPropOnSelection("fill", v)
                        }
                    }

                    // ---------------- single selection
                    ColumnLayout {
                        id: oneCol
                        Layout.fillWidth: true
                        visible: cvRoot.one !== null
                        spacing: 8
                        readonly property var n: cvRoot.one || ({
                                id: "",
                                type: "",
                                props: {},
                                view: {},
                                bind: {}
                            })
                        readonly property var p: n.props || ({})
                        readonly property bool shape: ["frame", "rect", "ellipse", "sticky", "collection"].indexOf(n.type) >= 0
                        readonly property bool texty: ["text", "sticky", "font"].indexOf(n.type) >= 0

                        RowLayout {
                            Layout.fillWidth: true
                            PanelLabel {
                                text: (oneCol.n.type || "").toUpperCase()
                                color: theme.tokens.accent
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            IconButton {
                                icon_name: oneCol.n.locked ? "lock" : "unlock"
                                icon_px: 13
                                implicitWidth: 24
                                implicitHeight: 24
                                active: oneCol.n.locked === true
                                ToolTip.text: oneCol.n.locked ? qsTr("Unlock") : qsTr("Lock (can't be moved or picked on the board)")
                                onClicked: cvRoot.cb.setField(oneCol.n.id, "locked", !oneCol.n.locked)
                            }
                            IconButton {
                                icon_name: "eye"
                                icon_px: 13
                                implicitWidth: 24
                                implicitHeight: 24
                                active: oneCol.n.hidden === true
                                ToolTip.text: oneCol.n.hidden ? qsTr("Show") : qsTr("Hide")
                                onClicked: cvRoot.cb.setField(oneCol.n.id, "hidden", !oneCol.n.hidden)
                            }
                            IconButton {
                                icon_name: "trash"
                                icon_px: 13
                                implicitWidth: 24
                                implicitHeight: 24
                                ToolTip.text: qsTr("Delete (Del)")
                                onClicked: cvRoot.cb.deleteSelection()
                            }
                        }
                        TextField {
                            id: nameIn
                            Layout.fillWidth: true
                            Layout.preferredHeight: 28
                            text: oneCol.n.name || ""
                            placeholderText: qsTr("Layer name")
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: theme.tokens.text
                            background: Rectangle {
                                radius: 6
                                color: theme.tokens.surface2
                                border.color: nameIn.activeFocus ? theme.tokens.accent : theme.tokens.border
                            }
                            onEditingFinished: if (text !== (oneCol.n.name || ""))
                                cvRoot.cb.setField(oneCol.n.id, "name", text)
                        }

                        PanelLabel {
                            text: qsTr("LAYOUT")
                            visible: oneCol.n.type !== "connector"
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            visible: oneCol.n.type !== "connector"
                            columns: 2
                            columnSpacing: 8
                            rowSpacing: 6
                            NumField {
                                label: "X"
                                value: oneCol.n.x || 0
                                onCommitted: v => cvRoot.cb.setField(oneCol.n.id, "x", v)
                            }
                            NumField {
                                label: "Y"
                                value: oneCol.n.y || 0
                                onCommitted: v => cvRoot.cb.setField(oneCol.n.id, "y", v)
                            }
                            NumField {
                                label: "W"
                                value: oneCol.n.w || 0
                                onCommitted: v => cvRoot.cb.setField(oneCol.n.id, "w", v)
                            }
                            NumField {
                                label: "H"
                                value: oneCol.n.h || 0
                                onCommitted: v => cvRoot.cb.setField(oneCol.n.id, "h", v)
                            }
                            NumField {
                                label: qsTr("Rotation °")
                                value: oneCol.n.rot || 0
                                onCommitted: v => cvRoot.cb.setField(oneCol.n.id, "rot", v)
                            }
                            NumField {
                                label: qsTr("Opacity")
                                value: cvRoot.num(oneCol.p.opacity, 1)
                                decimals: 2
                                onCommitted: v => cvRoot.cb.setProp(oneCol.n.id, "opacity", Math.max(0, Math.min(1, v)))
                            }
                        }

                        // style
                        PanelLabel {
                            text: qsTr("STYLE")
                            visible: oneCol.shape || oneCol.n.type === "line" || oneCol.n.type === "connector"
                        }
                        ColorField {
                            visible: oneCol.shape
                            label: qsTr("Fill")
                            value: oneCol.p.fill || ""
                            onCommitted: v => cvRoot.cb.setProp(oneCol.n.id, "fill", v)
                        }
                        ColorField {
                            visible: oneCol.shape || oneCol.n.type === "line" || oneCol.n.type === "connector"
                            label: qsTr("Stroke")
                            value: oneCol.p.stroke || ""
                            onCommitted: v => cvRoot.cb.setProp(oneCol.n.id, "stroke", v)
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            visible: oneCol.shape || oneCol.n.type === "line" || oneCol.n.type === "connector"
                            columns: 2
                            columnSpacing: 8
                            NumField {
                                label: qsTr("Stroke width")
                                value: cvRoot.num(oneCol.p.strokeWidth, 0)
                                onCommitted: v => cvRoot.cb.setProp(oneCol.n.id, "strokeWidth", Math.max(0, v))
                            }
                            NumField {
                                visible: oneCol.shape && oneCol.n.type !== "ellipse"
                                label: qsTr("Radius")
                                value: cvRoot.num(oneCol.p.radius, 0)
                                onCommitted: v => cvRoot.cb.setProp(oneCol.n.id, "radius", Math.max(0, v))
                            }
                        }
                        // quick picks: colors from palettes placed on this board
                        Flow {
                            Layout.fillWidth: true
                            visible: oneCol.shape || oneCol.texty
                            spacing: 3
                            Repeater {
                                model: cvRoot.boardPalette()
                                Rectangle {
                                    required property var modelData
                                    width: 18
                                    height: 18
                                    radius: 4
                                    color: modelData
                                    border.color: theme.tokens.border
                                    ToolTip.visible: qpMa.containsMouse
                                    ToolTip.text: modelData + qsTr(" — click: fill · Shift+click: text color")
                                    MouseArea {
                                        id: qpMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        onClicked: mouse => cvRoot.cb.setProp(oneCol.n.id, ((mouse.modifiers & Qt.ShiftModifier) || oneCol.n.type === "text" || oneCol.n.type === "font") ? "color" : "fill", parent.modelData)
                                    }
                                }
                            }
                        }

                        // text
                        PanelLabel {
                            text: qsTr("TEXT")
                            visible: oneCol.texty
                        }
                        TextArea {
                            id: textIn
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(60, contentHeight + 16)
                            visible: oneCol.texty
                            text: oneCol.p.text || ""
                            wrapMode: TextEdit.Wrap
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: theme.tokens.text
                            background: Rectangle {
                                radius: 6
                                color: theme.tokens.surface2
                                border.color: textIn.activeFocus ? theme.tokens.accent : theme.tokens.border
                            }
                            onActiveFocusChanged: if (!activeFocus && text !== (oneCol.p.text || ""))
                                cvRoot.cb.setProp(oneCol.n.id, "text", text)
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            visible: oneCol.texty
                            columns: 2
                            columnSpacing: 8
                            NumField {
                                label: qsTr("Size")
                                value: cvRoot.num(oneCol.p.fontSize, 16)
                                onCommitted: v => cvRoot.cb.setProp(oneCol.n.id, "fontSize", Math.max(1, v))
                            }
                            NumField {
                                label: qsTr("Weight")
                                value: cvRoot.num(oneCol.p.fontWeight, 400)
                                onCommitted: v => cvRoot.cb.setProp(oneCol.n.id, "fontWeight", Math.max(100, Math.min(900, Math.round(v / 100) * 100)))
                            }
                        }
                        ColorField {
                            visible: oneCol.texty
                            label: qsTr("Color")
                            value: oneCol.p.color || ""
                            onCommitted: v => cvRoot.cb.setProp(oneCol.n.id, "color", v)
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: oneCol.n.type === "text" || oneCol.n.type === "sticky"
                            spacing: 4
                            Repeater {
                                model: ["left", "center", "right"]
                                ToolBtn {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    label: modelData === "left" ? "⇤" : (modelData === "center" ? "↔" : "⇥")
                                    tip: qsTr("Align %1").arg(modelData)
                                    active: (oneCol.p.align || "left") === modelData
                                    onClicked: cvRoot.cb.setProp(oneCol.n.id, "align", modelData)
                                }
                            }
                        }
                        ComboBox {
                            id: famPick
                            Layout.fillWidth: true
                            visible: oneCol.n.type === "text" || oneCol.n.type === "sticky"
                            model: [qsTr("(UI font)")].concat(projects !== null ? projects.family_options() : [])
                            displayText: oneCol.p.fontFamily ? oneCol.p.fontFamily : qsTr("(UI font)")
                            onActivated: index => cvRoot.cb.setProp(oneCol.n.id, "fontFamily", index === 0 ? "" : model[index])
                            background: Rectangle {
                                radius: 6
                                color: theme.tokens.surface2
                                border.color: theme.tokens.border
                            }
                            contentItem: Text {
                                text: famPick.displayText
                                leftPadding: 8
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                            }
                        }

                        // code cell
                        PanelLabel {
                            text: qsTr("CODE")
                            visible: oneCol.n.type === "code"
                        }
                        Repeater {
                            model: oneCol.n.type === "code" ? ["html", "css", "js"] : []
                            ColumnLayout {
                                id: codeCol
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 2
                                PanelLabel {
                                    text: codeCol.modelData.toUpperCase()
                                }
                                ScrollView {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 96
                                    TextArea {
                                        id: codeIn
                                        text: oneCol.p[codeCol.modelData] || ""
                                        font.family: theme.monoFont
                                        font.pixelSize: 11
                                        color: theme.tokens.text
                                        wrapMode: TextEdit.NoWrap
                                        selectByMouse: true
                                        background: Rectangle {
                                            radius: 6
                                            color: "#161B21"
                                            border.color: codeIn.activeFocus ? theme.tokens.accent : theme.tokens.border
                                        }
                                        onActiveFocusChanged: if (!activeFocus && text !== (oneCol.p[codeCol.modelData] || ""))
                                            cvRoot.cb.setProp(oneCol.n.id, codeCol.modelData, text)
                                    }
                                }
                            }
                        }
                        FgButton {
                            Layout.fillWidth: true
                            visible: oneCol.n.type === "code"
                            text: qsTr("Save as Snippet (Code pane)")
                            onClicked: cvRoot.cb.codeToSnippet(oneCol.n.id)
                        }

                        // library binding
                        PanelLabel {
                            text: qsTr("LINKED ASSET")
                            visible: oneCol.n.type !== "connector"
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            visible: oneCol.n.bind !== undefined && oneCol.n.bind.kind !== undefined
                            implicitHeight: bindCol.implicitHeight + 14
                            radius: 6
                            color: theme.tokens.surface2
                            border.color: oneCol.n.view && oneCol.n.view.ok === false ? theme.tokens.accentCode : theme.tokens.border
                            ColumnLayout {
                                id: bindCol
                                anchors.fill: parent
                                anchors.margins: 7
                                spacing: 3
                                Text {
                                    Layout.fillWidth: true
                                    text: (oneCol.n.view && oneCol.n.view.ok === false ? qsTr("Missing — ") : "") + ((oneCol.n.view && oneCol.n.view.name) || (oneCol.n.bind && oneCol.n.bind.name) || "")
                                    elide: Text.ElideRight
                                    font.family: theme.uiFont
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    color: oneCol.n.view && oneCol.n.view.ok === false ? theme.tokens.accentCode : theme.tokens.text
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: oneCol.n.bind ? (oneCol.n.bind.kind + "  ·  " + (oneCol.n.bind.slug ? "[[ " + oneCol.n.bind.slug + " ]]" : (oneCol.n.bind.guid || "").slice(0, 13) + "…")) : ""
                                    elide: Text.ElideRight
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    color: theme.tokens.textMuted
                                }
                                Text {
                                    Layout.fillWidth: true
                                    readonly property var uses: oneCol.n.bind && oneCol.n.bind.kind && oneCol.n.bind.id ? cvRoot.cb.usage(oneCol.n.bind.kind, oneCol.n.bind.id) : []
                                    visible: uses.length > 0
                                    wrapMode: Text.Wrap
                                    text: qsTr("Used on: ") + uses.map(function (u) {
                                        return u.name + " (" + u.uses + ")";
                                    }).join(", ")
                                    font.family: theme.uiFont
                                    font.pixelSize: 10
                                    color: theme.tokens.textMuted
                                }
                            }
                        }
                        TextField {
                            id: refIn
                            Layout.fillWidth: true
                            Layout.preferredHeight: 28
                            visible: oneCol.n.type !== "connector"
                            placeholderText: qsTr("Link to [[ slug ]], GUID or kind/…/name")
                            font.family: theme.monoFont
                            font.pixelSize: 11
                            color: theme.tokens.text
                            background: Rectangle {
                                radius: 6
                                color: theme.tokens.surface2
                                border.color: refIn.activeFocus ? theme.tokens.accent : theme.tokens.border
                            }
                            onAccepted: if (text.trim() !== "" && cvRoot.cb.bindNode(oneCol.n.id, text.trim()))
                                text = ""
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: oneCol.n.type !== "connector"
                            wrapMode: Text.Wrap
                            text: qsTr("Linked nodes render live from the library and appear in the asset's Links (role: canvas).")
                            font.family: theme.uiFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }

                        // arrange
                        PanelLabel {
                            text: qsTr("ARRANGE")
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Repeater {
                                model: [
                                    {
                                        w: "back",
                                        l: "⤓⤓",
                                        t: qsTr("Send to back (Ctrl+[)")
                                    },
                                    {
                                        w: "backward",
                                        l: "⤓",
                                        t: qsTr("Send backward ([)")
                                    },
                                    {
                                        w: "forward",
                                        l: "⤒",
                                        t: qsTr("Bring forward (])")
                                    },
                                    {
                                        w: "front",
                                        l: "⤒⤒",
                                        t: qsTr("Bring to front (Ctrl+])")
                                    }
                                ]
                                ToolBtn {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    label: modelData.l
                                    tip: modelData.t
                                    color: theme.tokens.surface2
                                    onClicked: cvRoot.cb.restackSelection(modelData.w)
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            FgButton {
                                text: qsTr("Duplicate")
                                Layout.fillWidth: true
                                onClicked: cvRoot.cb.duplicateSelection()
                            }
                            FgButton {
                                visible: ["frame", "group", "collection"].indexOf(oneCol.n.type) >= 0
                                text: qsTr("Ungroup")
                                Layout.fillWidth: true
                                onClicked: cvRoot.cb.ungroupSelection()
                            }
                        }
                    }
                }
            }
        }
    }

    // library drag ghost (follows the pointer above everything)
    Rectangle {
        id: ghost
        visible: false
        width: 56
        height: 56
        radius: 8
        z: 1000
        color: cvRoot.tint(theme.tokens.surface2, 0.92)
        border.color: theme.tokens.accent
        Image {
            anchors.fill: parent
            anchors.margins: 8
            visible: (cvRoot.libDrag.url || "") !== ""
            source: cvRoot.libDrag.url || ""
            sourceSize.width: 64
            sourceSize.height: 64
            fillMode: Image.PreserveAspectFit
        }
        Text {
            anchors.fill: parent
            anchors.margins: 4
            visible: (cvRoot.libDrag.url || "") === ""
            text: cvRoot.libDrag.name || ""
            wrapMode: Text.Wrap
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font.family: theme.uiFont
            font.pixelSize: 9
            color: theme.tokens.text
        }
    }

    Dialog {
        id: deleteBoardDlg
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: qsTr("Delete board?")
        standardButtons: Dialog.Ok | Dialog.Cancel
        background: Rectangle {
            radius: 10
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        Text {
            text: qsTr("“%1” and its %n node(s) will be removed. Library assets are not touched.", "", cvRoot.nodesList.length).arg(cvRoot.cb ? cvRoot.cb.boardName : "")
            font.family: theme.uiFont
            font.pixelSize: 12
            color: theme.tokens.text
            wrapMode: Text.Wrap
            width: 320
        }
        onAccepted: cvRoot.cb.deleteBoard()
    }
}
