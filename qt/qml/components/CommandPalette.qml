import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Slash menu — the cross between VS Code's command palette, macOS
// Spotlight and Dash/Alfred: one input over commands, assets, snippets
// and databases, opened with the configured hotkey (Alt+/ by default)
// or the header's magnifier. Activation SIGNALS OUT to the shell, which
// owns every action (this file can't see Main's ids). Groups render as
// ListView sections; typing never mutates the grid's own search state —
// picking an asset reveals it instead.
Item {
    id: pal
    anchors.fill: parent

    property bool open: false
    property alias query: field.text
    property int resultCount: 0
    signal opened()
    signal closed()
    // kind: command | asset | snippet | db | fallback — payload is JSON
    signal activated(string kind, string payload)

    function show(initial) {
        query = initial !== undefined ? initial : ""
        open = true
        rebuild()
        opened()
        field.forceActiveFocus()
        field.selectAll()
    }
    function hide() {
        if (open) {
            open = false
            closed()
        }
    }

    // ---- command registry (id is what Main.paletteAction dispatches) ----
    readonly property var settingsCats: ["general", "appearance", "library",
                                         "storage", "editor", "colors",
                                         "updates", "about"]
    readonly property var commands: {
        var list = [
            { id: "go-icons", t: qsTr("Go to Icons pane"), g: qsTr("Navigate"), k: "pane switch grid assets icons" },
            { id: "go-fonts", t: qsTr("Go to Fonts pane"), g: qsTr("Navigate"), k: "pane switch families ttf otf" },
            { id: "go-colors", t: qsTr("Go to Colors pane"), g: qsTr("Navigate"), k: "pane switch palette harmonies" },
            { id: "go-code", t: qsTr("Go to Code pane"), g: qsTr("Navigate"), k: "pane switch snippets editor" },
            { id: "go-projects", t: qsTr("Go to Projects pane"), g: qsTr("Navigate"), k: "pane switch configurator css" },
            { id: "rescan-library", t: qsTr("Rescan library"), g: qsTr("Actions"), k: "scan refresh index rebuild assets" },
            { id: "rescan-fonts", t: qsTr("Rescan fonts"), g: qsTr("Actions"), k: "scan refresh index rebuild font" },
            { id: "toggle-theme", t: qsTr("Toggle dark / light theme"), g: qsTr("Actions"), k: "theme dark light appearance mode color" },
            { id: "generate-palette", t: qsTr("Generate a color palette"), g: qsTr("Actions"), k: "colors palette generate harmony random" },
            { id: "new-snippet", t: qsTr("New snippet"), g: qsTr("Actions"), k: "snippet create new code editor language slash command markdown python" },
            { id: "check-updates", t: qsTr("Check for updates"), g: qsTr("Actions"), k: "update release version upgrade" },
            { id: "open-settings", t: qsTr("Open settings"), g: qsTr("Preferences"), k: "settings preferences config options" },
            { id: "run-setup", t: qsTr("Run first-time setup again"), g: qsTr("Preferences"), k: "setup first-run wizard configure paths folders" },
            { id: "command-shortcut", t: qsTr("Change slash menu shortcut"), g: qsTr("Preferences"), k: "hotkey keyboard shortcut keybinding slash menu" },
            { id: "new-db", t: qsTr("New database…"), g: qsTr("Databases"), k: "database new create file" },
            { id: "open-db", t: qsTr("Open database…"), g: qsTr("Databases"), k: "database open file load" },
            { id: "star-db", t: qsTr("Star / unstar current database"), g: qsTr("Databases"), k: "star favorite quick access pin" },
            { id: "clear-recent", t: qsTr("Clear recent databases"), g: qsTr("Databases"), k: "recent clear forget history" }
        ]
        var titles = { general: qsTr("General"), appearance: qsTr("Appearance"),
                       library: qsTr("Library"), storage: qsTr("Storage"),
                       editor: qsTr("Editor"), colors: qsTr("Colors"),
                       updates: qsTr("Updates"), about: qsTr("About") }
        for (var i = 0; i < settingsCats.length; i++) {
            var c = settingsCats[i]
            list.push({ id: "settings-" + c,
                        t: qsTr("Settings: %1").arg(titles[c]),
                        g: qsTr("Preferences"),
                        k: "settings preferences " + c })
        }
        return list
    }

    // ---- model ----
    ListModel { id: resultsModel }

    function rebuild() {
        resultsModel.clear()
        var q = field.text.trim().toLowerCase()

        for (var i = 0; i < commands.length; i++) {
            var c = commands[i]
            if (q === "" || c.t.toLowerCase().indexOf(q) >= 0
                    || c.k.indexOf(q) >= 0) {
                resultsModel.append({ group: c.g, title: c.t, sub: "",
                                       kind: "command",
                                       value: JSON.stringify({ id: c.id }) })
            }
        }
        if (dbs !== null) {
            var rec = dbs.recent
            for (var d = 0; d < rec.length; d++) {
                var r = rec[d]
                if (q !== "" && r.label.toLowerCase().indexOf(q) < 0)
                    continue
                resultsModel.append({
                    group: qsTr("Databases"), title: r.label,
                    sub: r.exists ? r.when : qsTr("Missing"),
                    kind: "db",
                    value: JSON.stringify({ path: r.path }) })
            }
        }
        if (q !== "") {
            var assets = library !== null ? library.palette_search(field.text, 10) : []
            for (var a = 0; a < assets.length; a++) {
                var as_ = assets[a]
                resultsModel.append({
                    group: qsTr("Assets"), title: as_.name, sub: as_.path,
                    kind: "asset",
                    value: JSON.stringify({ path: as_.path, kind: as_.kind,
                                            family: as_.family }) })
            }
            var snips = code !== null ? code.palette_search(field.text, 6) : []
            for (var s = 0; s < snips.length; s++) {
                var sn = snips[s]
                resultsModel.append({
                    group: qsTr("Snippets"), title: sn.title,
                    sub: sn.language, kind: "snippet",
                    value: JSON.stringify({ id: sn.id }) })
            }
        }
        resultCount = resultsModel.count
        results.currentIndex = resultsModel.count > 0 ? 0 : -1
    }

    function activate(i) {
        var m = resultsModel.get(i)
        if (!m)
            return
        activated(m.kind, m.value)
        hide()
    }
    function activateCurrent() {
        var q = field.text.trim()
        if (resultsModel.count === 0) {
            // nothing matched — hand the query to the grid's quick
            // search (the pre-existing flow, verbatim)
            if (q !== "")
                activated("fallback", JSON.stringify({ query: q }))
            hide()
            return
        }
        activate(results.currentIndex < 0 ? 0 : results.currentIndex)
    }

    // ---- backdrop ----
    Rectangle {
        anchors.fill: parent
        visible: pal.open
        color: Qt.rgba(0, 0, 0, 0.32)
        MouseArea {
            anchors.fill: parent
            onClicked: pal.hide()
        }
    }

    // ---- top-centre panel ----
    Rectangle {
        id: panel
        visible: pal.open
        anchors.top: parent.top
        anchors.topMargin: 24
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width - 80, 660)
        height: panelCol.implicitHeight + 14
        radius: 10
        color: theme.tokens.surface
        border.color: theme.tokens.accent
        border.width: 1

        ColumnLayout {
            id: panelCol
            anchors.fill: parent
            anchors.margins: 7
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                spacing: 9
                IconImage {
                    name: "search"
                    px: 16
                    tint: theme.tokens.textMuted
                }
                TextField {
                    id: field
                    Layout.fillWidth: true
                    background: null
                    color: theme.tokens.text
                    placeholderTextColor: theme.tokens.textMuted
                    font.family: theme.uiFont
                    font.pixelSize: 14
                    selectByMouse: true
                    // the tip for the (re)opening hotkey lives in the
                    // placeholder — it follows the configured sequence
                    placeholderText: prefs !== null
                        ? qsTr("Search or run a command — %1")
                              .arg(prefs.formattedShortcut)
                        : qsTr("Search or run a command")
                    onTextChanged: debounce.restart()
                    Keys.onPressed: function (event) {
                        if (event.key === Qt.Key_Down) {
                            results.incrementCurrentIndex()
                            event.accepted = true
                        } else if (event.key === Qt.Key_Up) {
                            results.decrementCurrentIndex()
                            event.accepted = true
                        } else if (event.key === Qt.Key_Return
                                   || event.key === Qt.Key_Enter) {
                            pal.activateCurrent()
                            event.accepted = true
                        } else if (event.key === Qt.Key_Escape) {
                            pal.hide()
                            event.accepted = true
                        }
                    }
                }
                Rectangle {   // current-shortcut chip in the bar
                    visible: prefs !== null
                    Layout.preferredHeight: 18
                    Layout.preferredWidth: shortcutHint.implicitWidth + 12
                    radius: 4
                    color: theme.tokens.surface2
                    border.color: theme.tokens.border
                    Text {
                        id: shortcutHint
                        anchors.centerIn: parent
                        text: prefs !== null ? prefs.formattedShortcut : ""
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                visible: resultsModel.count > 0
                color: theme.tokens.border
                Layout.topMargin: 6
            }

            ListView {
                id: results
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(contentHeight, 420)
                visible: resultsModel.count > 0
                clip: true
                model: resultsModel
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}

                section.property: "group"
                section.delegate: Rectangle {
                    width: results.width
                    height: 26
                    color: theme.tokens.bg
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: section
                        font.family: theme.monoFont
                        font.pixelSize: 9
                        font.letterSpacing: 1.4
                        font.capitalization: Font.AllUppercase
                        color: theme.tokens.textMuted
                    }
                }

                delegate: Rectangle {
                    id: rowRect
                    required property int index
                    required property string title
                    required property string sub
                    width: results.width
                    height: 36
                    color: ListView.isCurrentItem ? theme.tokens.accent
                          : (rowMa.containsMouse ? theme.tokens.surface2
                                                 : "transparent")
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 12
                        Text {
                            Layout.fillWidth: true
                            text: rowRect.title
                            font.family: theme.uiFont
                            font.pixelSize: 13
                            color: ListView.isCurrentItem ? theme.tokens.bg
                                  : theme.tokens.text
                            elide: Text.ElideRight
                        }
                        Text {
                            text: rowRect.sub
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: ListView.isCurrentItem
                                   ? Qt.rgba(theme.tokens.bg.r,
                                             theme.tokens.bg.g,
                                             theme.tokens.bg.b, 0.75)
                                   : theme.tokens.textMuted
                            elide: Text.ElideRight
                            Layout.maximumWidth: 260
                            horizontalAlignment: Text.AlignRight
                        }
                    }
                    MouseArea {
                        id: rowMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            results.currentIndex = rowRect.index
                            pal.activate(rowRect.index)
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 10
                Layout.bottomMargin: 6
                visible: resultsModel.count === 0
                text: qsTr("No matches for '%1'").arg(field.text)
                font.family: theme.uiFont
                font.pixelSize: 12
                color: theme.tokens.textMuted
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }

    Timer {
        id: debounce
        interval: 120
        onTriggered: pal.rebuild()
    }
}