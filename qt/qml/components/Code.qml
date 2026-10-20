import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// Code pane (M3): tabbed HTML/CSS/JS editors with regex syntax highlighting,
// live preview in the hardened WebEngine profile, and a SQLite-backed
// snippet library with VSCode/massCode import. Port of the 0.x code.html.
//
// Editor structure: a TextArea with TRANSPARENT text over a highlight Text
// (the 0.x textarea-over-pre technique) — the overlay supplies the token
// colors, the TextArea owns editing, caret and selection. Both live in the
// Flickable's contentItem so they scroll as one.
Item {
    id: codeRoot

    property var editors: ({ html: "", css: "", js: "" })
    property string currentPane: "html"
    property bool dirty: false
    property string previewDoc: ""
    property bool previewActive: false

    // syntax token colors — same roles as the 0.x .tk-* classes
    readonly property var tkColors: ({
        "t": theme.tokens.accent,     // tags
        "k": theme.tokens.accent,     // JS keywords
        "a": theme.tokens.hlInk,      // attribute names / CSS props
        "s": "#98C379",               // strings (theme-independent, 0.x)
        "c": theme.tokens.inkFaint,   // comments
        "n": theme.tokens.hlInk,      // numbers
        "f": theme.tokens.text        // CSS selectors / JS functions
    })

    function highlight(code, lang) {
        var s = code.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
        var tokens = []
        function wrap(cls, m) {
            tokens.push('<span style="color: ' + tkColors[cls] + '">'
                        + m + '</span>')
            return "\uE000" + String.fromCharCode(0xE001 + tokens.length - 1)
                   + "\uE000"
        }
        if (lang === "html") {
            s = s.replace(/&lt;!--[\s\S]*?--&gt;/g, function (m) { return wrap("c", m) })
            s = s.replace(/&lt;!DOCTYPE[^&]*&gt;/g, function (m) { return wrap("k", m) })
            s = s.replace(/&lt;\/?[\w-]+/g, function (m) { return wrap("t", m) })
            s = s.replace(/[\w-]+(?==)/g, function (m) { return wrap("a", m) })
            s = s.replace(/&quot;[^&]*?&quot;/g, function (m) { return wrap("s", m) })
        } else if (lang === "css") {
            s = s.replace(/\/\*[\s\S]*?\*\//g, function (m) { return wrap("c", m) })
            s = s.replace(/@[\w-]+/g, function (m) { return wrap("k", m) })
            s = s.replace(/[.#][\w-]+(?=[\s,{:.])/g, function (m) { return wrap("f", m) })
            s = s.replace(/:{1,2}[\w-]+(?=[\s,{)])/g, function (m) { return wrap("f", m) })
            s = s.replace(/\b[\w-]+(?=\()/g, function (m) { return wrap("f", m) })
            s = s.replace(/[\w-]+(?=\s*:)/g, function (m) { return wrap("a", m) })
            s = s.replace(/#[0-9a-fA-F]{3,8}\b|\b\d+\.?\d*(?:px|em|rem|%|vh|vw|s|ms|deg|fr)?\b/g, function (m) { return wrap("n", m) })
        } else {  // js
            s = s.replace(/\/\/[^\n]*|\/\*[\s\S]*?\*\//g, function (m) { return wrap("c", m) })
            s = s.replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`/g, function (m) { return wrap("s", m) })
            s = s.replace(/\b(var|let|const|function|return|if|else|for|while|do|switch|case|break|continue|new|this|typeof|instanceof|null|undefined|true|false|class|extends|import|export|from|async|await|try|catch|finally|throw|delete|in|of)\b/g, function (m) { return wrap("k", m) })
            s = s.replace(/\b[\w$]+(?=\s*\()/g, function (m) { return wrap("f", m) })
            s = s.replace(/\b\d+\.?\d*\b/g, function (m) { return wrap("n", m) })
        }
        return s.replace(/\uE000(.)\uE000/g, function (_, c) {
            return tokens[c.charCodeAt(0) - 0xE001] || ""
        })
    }

    function setPane(lang) {
        if (code === null)
            return
        editors[currentPane] = edTa.text
        currentPane = lang
        edTa.text = editors[lang]
        refreshHighlight()
        dirty = true
    }

    function cursorStatus() {
        if (edTa === null || edTa.text === undefined)
            return "1:1"
        var t = edTa.text, pos = edTa.cursorPosition, line = 1, i
        for (i = 0; i < pos && i < t.length; i++)
            if (t[i] === "\n")
                line++
        return line + ":" + (pos - t.lastIndexOf("\n", pos - 1))
    }

    function refreshHighlight() {
        edHl.text = highlight(edTa.text, currentPane) + "\n"
    }

    function runPreview() {
        var doc = "<!DOCTYPE html><html><head><style>" + editors.css +
                  "</style></head><body>" + editors.html +
                  "<script>" + editors.js + "</" + "script></body></html>"
        previewDoc = doc
        previewActive = true
    }

    function saveSnippet() {
        if (code === null)
            return
        code.save(titleField.text, code.current.description || "",
                  code.current.language || "web",
                  editors.html, editors.css, editors.js,
                  tagsField.text)
        dirty = false
    }

    // populate the editors whenever a snippet is loaded (open/new/save)
    Connections {
        target: code
        function onCurrentChanged() {
            if (code === null)
                return
            editors.html = code.current.html || ""
            editors.css = code.current.css || ""
            editors.js = code.current.js || ""
            currentPane = "html"
            edTa.text = editors.html
            titleField.text = code.current.title || ""
            tagsField.text = code.current.tags || ""
            refreshHighlight()
            dirty = false
        }
        function onMessage(msg) { toast.show(msg) }
        function onImportFailed(err) { toast.show(qsTr("Import failed: %1").arg(err)) }
        function onImportDone(n) { toast.show(qsTr("Imported %1 snippets").arg(n)) }
    }
    Connections {
        target: theme
        function onTokensChanged() { refreshHighlight() }
    }

    Toast { id: toast }

    // ------------------------------------------------------------- sidebar
    Rectangle {
        id: sidebar
        width: 240
        color: theme.tokens.surface
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 6

            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Button {
                    id: newBtn
                    Layout.fillWidth: true
                    text: qsTr("+ New")
                    onClicked: code !== null && code.new_snippet()
                    background: Rectangle {
                        radius: 6
                        color: newBtn.enabled ? theme.tokens.accent
                                              : theme.tokens.border
                    }
                    contentItem: Text {
                        text: newBtn.text
                        color: theme.tokens.bg
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                IconButton {
                    icon_name: "upload"
                    ToolTip.text: qsTr("Import snippets (VSCode / massCode)")
                    onClicked: importDialog.open()
                }
                ComboBox {
                    id: importKind
                    Layout.preferredWidth: 92
                    model: ["vscode", "masscode"]
                    background: Rectangle {
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: importKind.displayText
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.text
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 6
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: snipSearch.activeFocus ? theme.tokens.accent
                                                     : theme.tokens.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 6
                    spacing: 4
                    IconImage { name: "search"; px: 13; tint: theme.tokens.textMuted }
                    TextInput {
                        id: snipSearch
                        Layout.fillWidth: true
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                        clip: true
                        onTextChanged: snipDebounce.restart()
                    }
                }
                Timer {
                    id: snipDebounce
                    interval: 200
                    onTriggered: code !== null && code.set_search(snipSearch.text)
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 4
                ComboBox {
                    id: sortBox
                    Layout.fillWidth: true
                    model: [qsTr("Recent"), qsTr("Created"), qsTr("Title")]
                    currentIndex: 0
                    onActivated: function (idx) {
                        code !== null && code.set_sort(
                            ["updated", "created", "title"][idx])
                    }
                    background: Rectangle { radius: 6; color: theme.tokens.surface2; border.color: theme.tokens.border }
                    contentItem: Text { text: sortBox.displayText; font.family: theme.monoFont; font.pixelSize: 10; color: theme.tokens.text; verticalAlignment: Text.AlignVCenter; leftPadding: 6 }
                }
                ComboBox {
                    id: langBox
                    Layout.fillWidth: true
                    model: [qsTr("All langs"), qsTr("Web"), qsTr("Markdown")]
                    currentIndex: 0
                    onActivated: function (idx) {
                        code !== null && code.set_lang(
                            ["", "web", "markdown"][idx])
                    }
                    background: Rectangle { radius: 6; color: theme.tokens.surface2; border.color: theme.tokens.border }
                    contentItem: Text { text: langBox.displayText; font.family: theme.monoFont; font.pixelSize: 10; color: theme.tokens.text; verticalAlignment: Text.AlignVCenter; leftPadding: 6 }
                }
            }

            ListView {
                id: snipList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 4
                model: code !== null ? code.snippets : []
                ScrollBar.vertical: ScrollBar { }

                delegate: Rectangle {
                    id: snipItem
                    required property var modelData
                    required property int index
                    width: snipList.width
                    height: itemCol.implicitHeight + 12
                    radius: 7
                    color: code !== null && code.currentId === modelData.id
                           ? theme.tokens.surface2 : "transparent"
                    border.color: code !== null && code.currentId === modelData.id
                                  ? theme.tokens.accent : "transparent"

                    ColumnLayout {
                        id: itemCol
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 2

                        Text {
                            text: snipItem.modelData.title
                            font.family: theme.monoFont
                            font.pixelSize: 12
                            color: theme.tokens.text
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Text {
                            text: snipItem.modelData.language + " · "
                                  + String(snipItem.modelData.updated).slice(0, 10)
                            font.family: theme.monoFont
                            font.pixelSize: 9
                            color: theme.tokens.textMuted
                            Layout.fillWidth: true
                        }
                        Flow {
                            visible: snipItem.modelData.tags !== ""
                            spacing: 3
                            Repeater {
                                model: snipItem.modelData.tags.split(",").filter(function (t) { return t.trim() !== "" })
                                Rectangle {
                                    required property string modelData
                                    radius: 99
                                    height: 14
                                    width: tagText.implicitWidth + 10
                                    color: theme.tokens.surface2
                                    Text {
                                        id: tagText
                                        anchors.centerIn: parent
                                        text: parent.modelData.trim()
                                        font.family: theme.monoFont
                                        font.pixelSize: 8
                                        color: theme.tokens.accent
                                    }
                                }
                            }
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: code !== null && code.open_snippet(snipItem.modelData.id)
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: code !== null && code.snippetCount === 0
                             && snipList.count === 0
                    text: qsTr("No snippets yet — create one!")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }

            // tag cloud — click to filter
            Flow {
                visible: code !== null && code.tags.length > 0
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: code !== null ? code.tags : []
                    Rectangle {
                        id: cloudChip
                        required property var modelData
                        radius: 99
                        height: 18
                        width: cloudText.implicitWidth + 14
                        color: theme.tokens.surface2
                        border.color: snipSearch.text === cloudChip.modelData.name
                                      ? theme.tokens.accent : "transparent"
                        Text {
                            id: cloudText
                            anchors.centerIn: parent
                            text: cloudChip.modelData.name + " ("
                                  + cloudChip.modelData.count + ")"
                            font.family: theme.monoFont
                            font.pixelSize: 9
                            color: theme.tokens.accent
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: snipSearch.text =
                                snipSearch.text === cloudChip.modelData.name
                                ? "" : cloudChip.modelData.name
                        }
                    }
                }
            }
        }

        FileDialog {
            id: importDialog
            nameFilters: importKind.currentIndex === 0
                         ? [qsTr("Snippets (*.json *.code-snippets)")]
                         : [qsTr("Databases (*.sqlite *.db)")]
            onAccepted: code !== null && code.import_snippets(
                importKind.currentText, Icons.toLocalPath(selectedFile))
        }
    }
    Rectangle { width: 1; anchors.top: parent.top; anchors.bottom: parent.bottom
                anchors.left: sidebar.right; color: theme.tokens.border }

    // ----------------------------------------------------------- main area
    ColumnLayout {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: sidebar.right
        anchors.right: parent.right
        spacing: 0

        // toolbar: tabs, title, tags, actions
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 64
            color: theme.tokens.surface
            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 8
                spacing: 2

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Repeater {
                        model: ["html", "css", "js"]
                        Button {
                            id: paneTab
                            required property string modelData
                            text: modelData.toUpperCase()
                            Layout.preferredHeight: 22
                            onClicked: codeRoot.setPane(modelData)
                            background: Rectangle {
                                radius: 4
                                color: codeRoot.currentPane === paneTab.modelData
                                       ? theme.tokens.accent : "transparent"
                                border.color: theme.tokens.border
                            }
                            contentItem: Text {
                                text: paneTab.text
                                color: codeRoot.currentPane === paneTab.modelData
                                       ? theme.tokens.bg : theme.tokens.textMuted
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }
                    }
                    Rectangle { width: 1; height: 16; color: theme.tokens.border }
                    // cursor line:col status (vim mode lands in a follow-up)
                     Text {
                        id: posStatus
                        text: codeRoot.cursorStatus()
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                        Connections {
                            target: edTa
                            function onCursorPositionChanged() {
                                posStatus.text = codeRoot.cursorStatus()
                            }
                            function onTextChanged() {
                                posStatus.text = codeRoot.cursorStatus()
                            }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    IconButton {
                        icon_name: "trash"
                        enabled: code !== null && code.currentId >= 0
                        ToolTip.text: qsTr("Delete snippet")
                        onClicked: {
                            if (code !== null && code.currentId >= 0)
                                code.remove(code.currentId)
                        }
                    }
                    IconButton {
                        icon_name: "help"
                        ToolTip.text: qsTr("Help & guide")
                        onClicked: helpPopup.open()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 26
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: titleField.activeFocus ? theme.tokens.accent
                                                             : theme.tokens.border
                        TextInput {
                            id: titleField
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: TextInput.AlignVCenter
                            font.family: theme.monoFont
                            font.pixelSize: 11
                            color: theme.tokens.text
                            clip: true
                            onTextEdited: codeRoot.dirty = true
                        }
                        Text {
                            visible: titleField.text === ""
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            verticalAlignment: Text.AlignVCenter
                            text: qsTr("snippet title…")
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.textMuted
                        }
                    }
                    Rectangle {
                        Layout.preferredWidth: 160
                        Layout.preferredHeight: 26
                        radius: 6
                        color: theme.tokens.surface2
                        border.color: tagsField.activeFocus ? theme.tokens.accent
                                                            : theme.tokens.border
                        TextInput {
                            id: tagsField
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: TextInput.AlignVCenter
                            font.family: theme.monoFont
                            font.pixelSize: 11
                            color: theme.tokens.text
                            clip: true
                            onTextEdited: codeRoot.dirty = true
                        }
                        Text {
                            visible: tagsField.text === ""
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            verticalAlignment: Text.AlignVCenter
                            text: qsTr("tags (comma-separated)")
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.textMuted
                        }
                    }
                    Button {
                        id: saveBtn
                        text: dirty ? qsTr("Save •") : qsTr("Save")
                        Layout.preferredHeight: 26
                        onClicked: codeRoot.saveSnippet()
                        background: Rectangle {
                            radius: 6
                            color: theme.tokens.accent
                        }
                        contentItem: Text {
                            text: saveBtn.text
                            color: theme.tokens.bg
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 10; rightPadding: 10
                        }
                    }
                    Button {
                        id: runBtn
                        text: qsTr("Run ▸")
                        Layout.preferredHeight: 26
                        enabled: previewProfile !== null
                        ToolTip.visible: !enabled && hovered
                        ToolTip.text: qsTr("Preview unavailable (no WebEngine)")
                        onClicked: codeRoot.runPreview()
                        background: Rectangle {
                            radius: 6
                            color: runBtn.enabled ? theme.tokens.accent
                                                  : theme.tokens.border
                        }
                        contentItem: Text {
                            text: runBtn.text
                            color: runBtn.enabled ? theme.tokens.bg
                                                  : theme.tokens.textMuted
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 10; rightPadding: 10
                        }
                    }
                }
            }
        }

        // editor + preview split
        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            handle: Rectangle {
                color: SplitView.hovered ? theme.tokens.accent
                                         : theme.tokens.border
                width: SplitView.pressed ? 3 : 1
                Behavior on width { NumberAnimation { duration: 80 } }
            }

            // ---- editor
            Rectangle {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 240
                color: theme.tokens.bg
                Flickable {
                    id: edFlick
                    anchors.fill: parent
                    anchors.margins: 0
                    clip: true
                    contentWidth: Math.max(width, edTa.contentWidth + 16)
                    contentHeight: Math.max(height, edTa.contentHeight + 16)

                    ScrollBar.vertical: ScrollBar { }
                    ScrollBar.horizontal: ScrollBar { }

                    TextArea.flickable: TextArea {
                        id: edTa
                        width: Math.max(edFlick.width, contentWidth)
                        color: "transparent"     // glyphs come from edHl
                        selectionColor: theme.tokens.accent
                        selectedTextColor: theme.tokens.bg
                        cursorDelegate: Rectangle {
                            width: 2
                            color: theme.tokens.text
                        }
                        font.family: theme.monoFont
                        font.pixelSize: 12
                        wrapMode: TextArea.NoWrap
                        padding: 8
                        background: null
                        // the glyph layer is edHl; this field only edits
                        placeholderText: qsTr("write %1 here…").arg(currentPane)
                        placeholderTextColor: theme.tokens.inkFaint
                        onTextChanged: {
                            editors[currentPane] = text
                            dirty = true
                            refreshHighlight()
                        }
                        Keys.onTabPressed: function (event) {
                            // two-space indent, 0.x behaviour
                            var s = selectionStart, e = selectionEnd
                            text = text.slice(0, s) + "  " + text.slice(e)
                            cursorPosition = s + 2
                            event.accepted = true
                        }
                    }

                    Text {
                        id: edHl
                        x: 0
                        y: 0
                        width: Math.max(edFlick.width, implicitWidth)
                        enabled: false                // clicks fall through
                        font.family: theme.monoFont
                        font.pixelSize: 12
                        textFormat: Text.StyledText
                        text: ""
                        leftPadding: 8
                        topPadding: 8
                        color: theme.tokens.text
                    }
                }
            }

            Rectangle {
                width: 1
                color: theme.tokens.border
            }

            // ---- preview
            Rectangle {
                SplitView.preferredWidth: parent.width * 0.42
                SplitView.minimumWidth: 120
                color: theme.tokens.surface

                Item {
                    anchors.fill: parent
                    Loader {
                        id: previewLoader
                        anchors.fill: parent
                        anchors.margins: 1
                        active: codeRoot.previewActive
                        sourceComponent: PreviewPane {
                            profile: previewProfile
                            document: codeRoot.previewDoc
                        }
                    }
                    Column {
                        anchors.centerIn: parent
                        visible: !codeRoot.previewActive
                        spacing: 10
                        IconImage {
                            anchors.horizontalCenter: parent.horizontalCenter
                            name: "play"
                            px: 28
                            tint: theme.tokens.textMuted
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: qsTr("Press Run ▸ or Ctrl+Enter")
                            font.family: theme.uiFont
                            font.pixelSize: 12
                            color: theme.tokens.textMuted
                        }
                    }
                }
            }
        }
    }

    Popup {
        id: helpPopup
        modal: true
        anchors.centerIn: parent
        width: Math.min(460, codeRoot.width - 40)
        height: Math.min(420, codeRoot.height - 40)
        background: Rectangle {
            radius: 12
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        contentItem: Flickable {
            clip: true
            contentHeight: helpCol.implicitHeight
            ScrollBar.vertical: ScrollBar { }
            ColumnLayout {
                id: helpCol
                width: helpPopup.width - 32
                spacing: 6
                Text {
                    text: qsTr("Code guide")
                    font.family: theme.headingFont
                    font.pixelSize: 14
                    color: theme.tokens.accent
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                    text: qsTr(
                        "Write HTML, CSS and JS in the three tabs, then press "
                        + "Run ▸ (or Ctrl+Enter) to render them together in "
                        + "the sandboxed preview — no network, no file access. "
                        + "\n\nSaving: give the snippet a title (tags "
                        + "optional) and press Save; the first save creates "
                        + "it, later saves update in place. The sidebar lists "
                        + "snippets with search, sort, and a tag cloud.\n\n"
                        + "Import: read snippets from other tools — VSCode "
                        + ".code-snippets / .json files (comments and trailing "
                        + "commas allowed) or a massCode db.sqlite. Unmapped "
                        + "languages keep their code in the JS pane with a "
                        + "lang:<name> tag.\n\n"
                        + "Keyboard: Ctrl+S save · Ctrl+Enter run · Esc close "
                        + "dialogs · Tab indents two spaces.")
                }
            }
        }
    }

    Shortcut {
        sequence: "Ctrl+S"
        enabled: codeRoot.visible
        onActivated: codeRoot.saveSnippet()
    }
    Shortcut {
        sequence: "Ctrl+Return"
        enabled: codeRoot.visible && previewProfile !== null
        onActivated: codeRoot.runPreview()
    }
}
