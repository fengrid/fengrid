import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// PRESET LIBRARIES — curated remote catalogues (open-source fonts,
// icon sets, site templates). Entries are browsable WITHOUT
// downloading: every preview square carries a remote placeholder
// (dashed frame + download glyph) until the project is cloned, then
// shows a generated 1280x640 (GitHub social-image size) preview
// derived from the repo's README.md / social imagery. Downloading
// clones the entry's git remote via Fengrid's built-in git wrapper.
Dialog {
    id: presetsRoot

    property int currentLib: -1
    property var entryRows: []
    property string filterText: ""
    // #141: live download state per entry id — {phase: "clone"|"update"|
    // "ingest"|"working", pct: 0-100 or -1 (pulse)}. Drives the loading
    // bars on the cards; survives delegate rebuilds (it lives on the
    // dialog, not on the cards).
    property var progressMap: ({})

    width: 1000
    height: 660
    modal: true
    anchors.centerIn: parent
    background: Rectangle {
        radius: 10
        color: theme.tokens.surface
        border.color: theme.tokens.border
    }
    footer: Rectangle {
        color: theme.tokens.surface
        height: 50
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.topMargin: 8
            anchors.bottomMargin: 8
            spacing: 10
            Text {
                Layout.fillWidth: true
                text: presets !== null ? (presets.libraries.length + " preset libraries · " + "nothing downloads until you ask") : ""
                font.family: theme.monoFont
                font.pixelSize: 9
                color: theme.tokens.textMuted
            }
            Button {
                id: closeBtn
                text: qsTr("Close")
                font.family: theme.uiFont
                font.pixelSize: 12
                leftPadding: 18
                rightPadding: 18
                topPadding: 6
                bottomPadding: 6
                hoverEnabled: true
                contentItem: Text {
                    text: closeBtn.text
                    font: closeBtn.font
                    color: closeBtn.hovered ? theme.tokens.bg : theme.tokens.text
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    radius: 6
                    color: closeBtn.hovered || closeBtn.pressed ? theme.tokens.accent : theme.tokens.surface2
                    border.color: closeBtn.hovered ? theme.tokens.accent : theme.tokens.border
                }
                onClicked: presetsRoot.close()
            }
        }
    }

    function openLibrary(libId, paneKind) {
        if (libId >= 0) {
            currentLib = libId;
        } else {
            // no explicit pack: open the library matching the ACTIVE
            // pane's asset kind (Fonts pane → Open Fonts, Colors pane
            // → Color Harmonies, etc.)
            var packs = presets !== null ? presets.libraries : [];
            var want = paneKind === "font" ? "font" : paneKind === "icon" ? "icon" : paneKind === "template" ? "template" : paneKind === "palette" ? "palette" : "";
            currentLib = -1;
            for (var i = 0; i < packs.length; i++)
                if (want !== "" && packs[i].kind === want)
                    currentLib = packs[i].id;
            if (currentLib < 0 && packs.length > 0)
                currentLib = packs[0].id;
        }
        filterText = "";
        refresh();
        open();
    }

    function refresh() {
        entryRows = (presets !== null && currentLib >= 0) ? presets.entries(currentLib) : [];
        // #141: seed live progress for entries the map doesn't know yet
        // (dialog reopened mid-download) — never clobber live ticks
        var m = progressMap;
        for (var i = 0; i < entryRows.length; i++) {
            var r = entryRows[i];
            if (m[r.id] !== undefined)
                continue;
            if (r.ingesting)
                m[r.id] = { phase: "ingest", pct: -1 };
            else if (r.busy)
                m[r.id] = r.progressPct !== null
                          ? { phase: "clone", pct: r.progressPct }
                          : { phase: "working", pct: -1 };
        }
        progressMap = m;
    }

    onCurrentLibChanged: refresh()

    Connections {
        target: presets
        function onEntriesChanged() {
            presetsRoot.refresh();
        }
        function onLibrariesChanged() {
            presetsRoot.refresh();
        }
        // #141: live clone/update percent (pct -1 = indeterminate pulse)
        function onDownloadProgress(entryId, phase, pct) {
            var m = progressMap;
            m[entryId] = { phase: phase, pct: pct };
            progressMap = m;
        }
        // #141: "ingest" → pulse while the fresh clone's assets are
        // indexed; "done" → drop the bar
        function onDownloadState(entryId, state) {
            var m = progressMap;
            if (state === "done")
                delete m[entryId];
            else
                m[entryId] = { phase: state, pct: -1 };
            progressMap = m;
        }
        function onMessage(msg) {
        }
    }

    // 2:1 preview cards — GitHub social-image proportions (1280x640)
    readonly property int cardW: 300
    readonly property int cardH: 150

    contentItem: ColumnLayout {
        spacing: 10

        // ── header: title + library picker + search ──
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            Layout.rightMargin: 16
            Layout.topMargin: 14
            spacing: 10
            Text {
                text: qsTr("PRESET LIBRARIES")
                font.family: theme.headingFont
                font.pixelSize: 13
                font.letterSpacing: 1.6
                color: theme.tokens.accent
            }
            Item {
                Layout.fillWidth: true
            }
            TextField {
                id: searchField
                Layout.preferredWidth: 220
                placeholderText: qsTr("Filter Entries…")
                font.family: theme.uiFont
                font.pixelSize: 11
                color: theme.tokens.text
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.bg
                    border.color: searchField.activeFocus ? theme.tokens.accent : theme.tokens.border
                }
                onTextChanged: presetsRoot.filterText = text
            }
        }

        // ── library tabs ──
        // #36: a Flow (not a row) — packs wrap instead of running flush
        // off the dialog edge, and every card carries real inner padding
        // so the "N entries" line never touches the card border
        Flow {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            Layout.rightMargin: 16
            spacing: 8
            Repeater {
                model: presets !== null ? presets.libraries : []
                delegate: AbstractButton {
                    id: libTab
                    required property var modelData
                    implicitWidth: 200
                    padding: 10
                    HoverHandler {
                        cursorShape: Qt.PointingHandCursor
                    }
                    background: Rectangle {
                        radius: 8
                        color: presetsRoot.currentLib === libTab.modelData.id ? theme.tokens.surface2 : "transparent"
                        border.color: presetsRoot.currentLib === libTab.modelData.id ? theme.tokens.accent : theme.tokens.border
                    }
                    contentItem: ColumnLayout {
                        spacing: 2
                        Text {
                            text: libTab.modelData.name + (libTab.modelData.downloaded > 0 ? "  ·  " + libTab.modelData.downloaded + " local" : "")
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            color: presetsRoot.currentLib === libTab.modelData.id ? theme.tokens.accent : theme.tokens.text
                        }
                        Text {
                            text: libTab.modelData.entries + " entries"
                            font.family: theme.monoFont
                            font.pixelSize: 9
                            color: theme.tokens.textMuted
                        }
                    }
                    onClicked: presetsRoot.currentLib = libTab.modelData.id
                }
            }
            Item {
                Layout.fillWidth: true
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            text: {
                var l = (presets !== null && presetsRoot.currentLib >= 0) ? presets.libraries : [];
                for (var i = 0; i < l.length; i++)
                    if (l[i].id === presetsRoot.currentLib)
                        return l[i].summary;
                return "";
            }
            font.family: theme.uiFont
            font.pixelSize: 11
            color: theme.tokens.textMuted
            wrapMode: Text.Wrap
        }

        // ── entries grid: 2:1 social-image cards ──
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: gridFlow.implicitHeight + 24
            clip: true
            ScrollBar.vertical: ScrollBar {}

            Flow {
                id: gridFlow
                x: 16
                y: 8
                width: presetsRoot.width - 32
                spacing: 12

                Repeater {
                    model: {
                        var f = presetsRoot.filterText.toLowerCase();
                        var rows = presetsRoot.entryRows;
                        if (!f)
                            return rows;
                        var out = [];
                        for (var i = 0; i < rows.length; i++) {
                            var hay = (rows[i].name + " " + rows[i].repo + " " + rows[i].description + " " + rows[i].tags).toLowerCase();
                            if (hay.indexOf(f) >= 0)
                                out.push(rows[i]);
                        }
                        return out;
                    }
                    delegate: Rectangle {
                        id: entryCard
                        required property var modelData
                        // #141: a clone or index scan is in flight — the
                        // bridge's busy flag or live progress in the map
                        readonly property bool progActive:
                            (modelData.busy === true)
                            || presetsRoot.progressMap[modelData.id] !== undefined
                        width: presetsRoot.cardW
                        height: presetsRoot.cardH + 108
                        radius: 8
                        color: theme.tokens.surface2
                        border.color: cardMa.containsMouse ? theme.tokens.accent : theme.tokens.border
                        clip: true

                        // ── preview square (2:1, social-image size) ──
                        Rectangle {
                            id: previewBox
                            anchors.top: parent.top
                            anchors.left: parent.left
                            anchors.right: parent.right
                            height: presetsRoot.cardH
                            radius: 8
                            clip: true
                            color: theme.tokens.bg

                            // downloaded → generated preview image
                            Image {
                                anchors.fill: parent
                                visible: entryCard.modelData.downloaded && entryCard.modelData.preview !== ""
                                source: entryCard.modelData.downloaded && entryCard.modelData.preview !== "" ? Icons.fileUrl(entryCard.modelData.preview) : ""
                                fillMode: Image.PreserveAspectCrop
                                smooth: true
                            }

                            // palette-kind entry: show color swatches
                            Row {
                                anchors.fill: parent
                                visible: entryCard.modelData.libraryKind === "palette"
                                spacing: 2
                                Repeater {
                                    model: {
                                        var raw = entryCard.modelData.colors || "";
                                        if (!raw) return [];
                                        try { return JSON.parse(raw); }
                                        catch(e) { return []; }
                                    }
                                    Rectangle {
                                        required property var modelData
                                        width: (previewBox.width - 10) / 5
                                        height: previewBox.height
                                        color: modelData
                                    }
                                }
                            }

                            // license badge over the preview square
                            Rectangle {
                                anchors.top: parent.top
                                anchors.right: parent.right
                                anchors.margins: 6
                                visible: entryCard.modelData.license !== ""
                                width: licLbl.implicitWidth + 10
                                height: 16
                                radius: 8
                                color: theme.tokens.surface
                                border.color: theme.tokens.border
                                Text {
                                    id: licLbl
                                    anchors.centerIn: parent
                                    text: entryCard.modelData.license
                                    font.family: theme.monoFont
                                    font.pixelSize: 8
                                    color: theme.tokens.textMuted
                                }
                            }

                            // local badge when present
                            Rectangle {
                                anchors.top: parent.top
                                anchors.left: parent.left
                                anchors.margins: 6
                                visible: entryCard.modelData.downloaded
                                width: 20
                                height: 20
                                radius: 10
                                color: theme.tokens.accent
                                IconImage {
                                    anchors.centerIn: parent
                                    name: "check"
                                    px: 12
                                    tint: theme.tokens.bg
                                }
                            }

                            // ── download / ingestion progress (#141) ──
                            // a clone or index scan in flight dims the
                            // preview and pins a chip + bar strip to the
                            // square's bottom edge, padded clear of the
                            // border so it never touches the rounded edge
                            Rectangle {
                                id: progDim
                                anchors.fill: parent
                                radius: 8
                                color: theme.tokens.bg
                                opacity: progCol.visible ? 0.45 : 0
                                visible: opacity > 0
                                Behavior on opacity {
                                    NumberAnimation { duration: 160 }
                                }
                            }

                            Column {
                                id: progCol
                                objectName: "presetProgressOverlay"
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.margins: 10
                                spacing: 6
                                visible: entryCard.progActive

                                readonly property real pct: {
                                    var st = presetsRoot.progressMap[entryCard.modelData.id];
                                    return st !== undefined ? st.pct : -1;
                                }
                                readonly property string phase: {
                                    var st = presetsRoot.progressMap[entryCard.modelData.id];
                                    return st !== undefined ? st.phase : "working";
                                }

                                Rectangle {   // status chip
                                    width: progChipLbl.implicitWidth + 14
                                    height: progChipLbl.implicitHeight + 8
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    radius: 7
                                    color: theme.tokens.surface
                                    opacity: 0.94
                                    Text {
                                        id: progChipLbl
                                        objectName: "presetProgressLabel"
                                        anchors.centerIn: parent
                                        text: progCol.pct >= 0
                                              ? "Cloning  " + Math.round(progCol.pct) + "%"
                                              : (progCol.phase === "ingest" ? "Indexing…"
                                                     : progCol.phase === "update" ? "Updating…"
                                                     : "Preparing…")
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.text
                                    }
                                }

                                Rectangle {   // track
                                    id: progTrack
                                    objectName: "presetProgressTrack"
                                    width: parent.width
                                    height: 5
                                    radius: 2.5
                                    color: theme.tokens.surface
                                    border.color: theme.tokens.border

                                    Rectangle {   // determinate fill
                                        objectName: "presetProgressFill"
                                        anchors.top: parent.top
                                        anchors.bottom: parent.bottom
                                        anchors.left: parent.left
                                        anchors.margins: 1
                                        width: progCol.pct >= 0
                                               ? Math.max(4, (progTrack.width - 2) * progCol.pct / 100)
                                               : 0
                                        radius: 1.5
                                        color: theme.tokens.accent
                                        visible: progCol.pct >= 0
                                    }

                                    Rectangle {   // indeterminate pulse
                                        id: progPulse
                                        objectName: "presetProgressPulse"
                                        anchors.top: parent.top
                                        anchors.bottom: parent.bottom
                                        anchors.margins: 1
                                        width: progTrack.width / 3
                                        radius: 1.5
                                        color: theme.tokens.accent
                                        visible: progCol.pct < 0
                                        NumberAnimation on x {
                                            running: progCol.visible && progCol.pct < 0
                                            loops: Animation.Infinite
                                            from: 1
                                            to: progTrack.width - progPulse.width - 1
                                            duration: 1300
                                        }
                                    }
                                }
                            }
                        }

                        // ── meta: name, repo, description, tags ──
                        ColumnLayout {
                            anchors.top: previewBox.bottom
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.margins: 8
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                text: entryCard.modelData.name
                                font.family: theme.uiFont
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                                color: theme.tokens.text
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: entryCard.modelData.repo
                                font.family: theme.monoFont
                                font.pixelSize: 9
                                color: theme.tokens.textMuted
                                elide: Text.ElideMiddle
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                text: entryCard.modelData.description
                                font.family: theme.uiFont
                                font.pixelSize: 10
                                color: theme.tokens.text
                                wrapMode: Text.Wrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "#" + String(entryCard.modelData.tags).split(",").join(" #")
                                font.family: theme.monoFont
                                font.pixelSize: 9
                                color: theme.tokens.accent
                                elide: Text.ElideRight
                            }
                        }

                        MouseArea {
                            id: cardMa
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            cursorShape: Qt.PointingHandCursor
                            onClicked: function (mouse) {
                                if (mouse.button === Qt.RightButton) {
                                    entryMenu.popup();
                                    return;
                                }
                                // #141: a download/index in flight must
                                // not be re-triggered by a click
                                if (entryCard.progActive)
                                    return;
                                if (entryCard.modelData.libraryKind === "palette") {
                                    presets.apply_preset(entryCard.modelData.id);
                                } else if (entryCard.modelData.downloaded) {
                                    presets.open_folder(entryCard.modelData.id);
                                } else {
                                    presets.download(entryCard.modelData.id);
                                }
                            }
                        }
                        Menu {
                            id: entryMenu
                            width: 210
                            padding: 4
                            background: Rectangle {
                                radius: 8
                                color: theme.tokens.surface
                                border.color: theme.tokens.border
                            }
                            FgMenuItem {
                                visible: entryCard.modelData.libraryKind !== "palette"
                                text: entryCard.modelData.downloaded ? qsTr("Update (git pull)") : qsTr("Download (git clone)")
                                enabled: entryCard.progActive !== true
                                height: 28
                                onTriggered: presets.download(entryCard.modelData.id)
                            }
                            FgMenuItem {
                                visible: entryCard.modelData.libraryKind !== "palette"
                                text: qsTr("Open folder")
                                height: 28
                                enabled: entryCard.modelData.downloaded
                                onTriggered: presets.open_folder(entryCard.modelData.id)
                            }
                            FgMenuItem {
                                visible: entryCard.modelData.libraryKind !== "palette"
                                text: qsTr("Open on GitHub")
                                height: 28
                                onTriggered: Qt.openUrlExternally("https://github.com/" + entryCard.modelData.repo)
                            }
                            FgMenuItem {
                                visible: entryCard.modelData.libraryKind !== "palette"
                                text: qsTr("Remove local copy")
                                height: 28
                                enabled: entryCard.modelData.downloaded
                                onTriggered: presets.forget(entryCard.modelData.id)
                            }
                        }
                    }
                }
            }
        }

        // ── footer hint ──
        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            Layout.bottomMargin: 10
            text: qsTr("Entries stay remote until downloaded — clicking a " + "remote card clones its repository with Fengrid's " + "git (source URL and branch from the entry's " + "properties). Previews are generated at GitHub " + "social-image size (1280×640) from the repo's " + "README/social imagery once downloaded.")
            font.family: theme.uiFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
            wrapMode: Text.Wrap
        }
    }
}
