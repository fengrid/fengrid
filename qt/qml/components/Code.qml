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
    // editor language suite: "web" = HTML/CSS/JS fiddle; "markdown" gets
    // a live GitHub-styled preview; everything else is a single-body
    // language editing the field code.body_field() returns
    property string snipLang: "web"
    readonly property string bodyField:
        code !== null ? code.body_field(snipLang) : ""
    readonly property bool isWeb: snipLang === "web"
    readonly property bool isMarkdown: snipLang === "markdown"
    // markdown preview document — regenerated while typing
    property string markdownDoc: ""
    property string previewDoc: ""
    property bool previewActive: false

    // IDE command layer state (0.x port) — emacs bindings always on for
    // plain editing; the vim toggle adds modal normal/insert/visual
    property bool vimEnabled: false
    property string vimMode: "normal"     // normal | insert | visual
    property string pendingOp: ""         // d/c/y operator or ':' ex prefix
    property string pendingCount: ""      // count digits before a motion
    property bool pendingG: false         // 'g' seen, awaiting second 'g'
    property int vimAnchor: -1            // visual-mode anchor
    property int colGoal: -1              // j/k column memory
    property var killRing: []
    property bool emacsChord: false       // Ctrl-X seen, awaiting second key
    // vim 'u' undo: programmatic .text writes do NOT feed Qt's undo stack
    // (the 0.x leaned on execCommand('undo'), which had the same hole), so
    // the command layer keeps its own snapshots
    property var undoStack: []

    // keybinding scheme: vscode (native) | emacs | vim | readline.
    // The VIM button/shortcut can overlay vim mode temporarily on any
    // scheme; scheme "vim" just STARTS in vim mode.
    property string keymap: code !== null ? code.keymap : "vscode"
    readonly property var keymapIndex: ({ "vscode": 0, "emacs": 1,
                                          "vim": 2, "readline": 3 })

    function applyKeymapVim() {
        if (keymap === "vim" && !vimEnabled) {
            vimEnabled = true
            vimMode = "normal"
        }
    }
    Component.onCompleted: {
        applyKeymapVim()
        // attach the real highlighter to the TextArea's own document —
        // one layout for glyphs, cursor and selection (no overlay drift).
        // Colors are theme-driven inside the snipHl bridge.
        snipHl.attach(edTa.textDocument, currentPane)
    }
    onCurrentPaneChanged: snipHl.set_language(currentPane)

    function setPane(lang) {
        if (code === null)
            return
        editors[currentPane] = edTa.text
        currentPane = lang
        edTa.text = editors[lang]
        vimAnchor = -1
        colGoal = -1
        dirty = true
    }

    // switch the editor language (dropdown / / command): park the body
    // text in its field, then focus the new language's body field
    function setLanguage(lang) {
        if (code === null)
            return
        editors[currentPane] = edTa.text
        snipLang = lang
        var f = code.body_field(lang)
        currentPane = f || "html"
        edTa.text = editors[currentPane]
        vimAnchor = -1
        colGoal = -1
        dirty = true
        updateMarkdown()   // pane switch: refresh immediately (no debounce)
    }

    // live markdown preview — regenerated ≤1x per 150 ms while typing
    // (PERF-3: markdown_html over a big document on every keystroke
    // stalls the editor; the debounce keeps the preview "live" without
    // the per-keystroke re-parse)
    Timer {
        id: mdDebounce
        interval: 150
        onTriggered: updateMarkdown()
    }
    function updateMarkdown() {
        if (isMarkdown && code !== null)
            markdownDoc = code.markdown_html(editors[currentPane],
                                             theme.isDark)
    }

    function cursorStatus() {
        if (edTa === null || edTa.text === undefined)
            return "1:1"
        var t = edTa.text, pos = edTa.cursorPosition, line = 1, i
        for (i = 0; i < pos && i < t.length; i++)
            if (t[i] === "\n")
                line++
        var col = pos - t.lastIndexOf("\n", pos - 1) - 1
        if (!vimEnabled)
            return line + ":" + col
        var s = "-- " + vimMode.toUpperCase() + " --  " + line + ":" + col
        if (pendingOp !== "")
            s = (pendingOp + pendingCount) + "  " + s
        else if (pendingCount !== "")
            s = pendingCount + "  " + s
        else if (pendingG)
            s = "g  " + s
        return s
    }

    // ---- IDE command layer (0.x code.html port). Two 0.x bugs are fixed
    // here: 'gg' works (separate pendingG state — 0.x reused pendingOp, so
    // the generic operator path ate the second 'g'), and ':' actually
    // reaches the ex handler (0.x had no case that set it).
    function lineBounds(v, pos) {
        var ls = v.lastIndexOf("\n", pos - 1) + 1
        var le = v.indexOf("\n", pos)
        if (le === -1) le = v.length
        return [ls, le]
    }
    function wCls(ch) {
        return /\s/.test(ch) ? 0 : /[A-Za-z0-9_]/.test(ch) ? 1 : 2
    }
    function nextWordStart(v, pos) {
        var i = pos, n = v.length
        if (i >= n) return n
        var cur = wCls(v[i])
        while (i < n && wCls(v[i]) === cur) i++
        while (i < n && /\s/.test(v[i])) i++
        return i
    }
    function prevWordStart(v, pos) {
        var i = pos - 1
        while (i > 0 && /\s/.test(v[i])) i--
        if (i <= 0) return 0
        var cur = wCls(v[i])
        while (i > 0 && wCls(v[i - 1]) === cur) i--
        return i
    }
    function nextWordEnd(v, pos) {
        var i = pos + 1, n = v.length
        while (i < n && /\s/.test(v[i])) i++
        if (i >= n) return n
        var cur = wCls(v[i])
        while (i + 1 < n && wCls(v[i + 1]) === cur) i++
        return i
    }
    function lineStarts(v) {
        var arr = [0]
        for (var i = 0; i < v.length; i++)
            if (v[i] === "\n") arr.push(i + 1)
        return arr
    }
    function taSet(start, end, val) {
        if (val !== undefined) edTa.text = val
        if (start > end) { var t = start; start = end; end = t }
        if (start === end) edTa.cursorPosition = start
        else edTa.select(start, end)
    }
    function pushUndo() {
        undoStack.push({ t: edTa.text, p: edTa.cursorPosition })
        if (undoStack.length > 200)
            undoStack.shift()
    }
    function deleteRange(a, b, yank) {
        var v = edTa.text
        if (a > b) { var t = a; a = b; b = t }
        if (a === b) return
        pushUndo()
        if (yank) killRing.push(v.slice(a, b))
        edTa.text = v.slice(0, a) + v.slice(b)
        edTa.cursorPosition = a
    }
    function deleteSelection(yank) {
        var a = edTa.selectionStart, b = edTa.selectionEnd
        vimMode = "normal"
        vimAnchor = -1
        if (a === b) return
        pushUndo()
        if (yank) killRing.push(edTa.text.slice(a, b))
        edTa.text = edTa.text.slice(0, a) + edTa.text.slice(b)
        edTa.cursorPosition = a
    }
    function yankSelection() {
        var a = edTa.selectionStart, b = edTa.selectionEnd
        if (a !== b) killRing.push(edTa.text.slice(a, b))
        vimMode = "normal"
        vimAnchor = -1
        edTa.cursorPosition = a
    }
    function moveVert(dir, selecting) {
        var v = edTa.text, pos = edTa.cursorPosition
        var starts = lineStarts(v), li = 0
        while (li + 1 < starts.length && starts[li + 1] <= pos) li++
        var col = pos - starts[li]
        if (colGoal >= 0 && colGoal > col) col = Math.min(colGoal, col)
        var nl = li + dir
        if (nl < 0 || nl >= starts.length) {
            colGoal = -1
            var end = dir > 0 ? v.length : 0
            taSet(selecting ? Math.min(end, vimAnchor) : end,
                  selecting ? Math.max(end, vimAnchor) : end)
            return
        }
        colGoal = col
        var le = nl + 1 < starts.length ? starts[nl + 1] - 1 : v.length
        var p = starts[nl] + Math.min(col, le - starts[nl])
        taSet(selecting ? Math.min(p, vimAnchor) : p,
              selecting ? Math.max(p, vimAnchor) : p)
    }
    function opTarget(op, motion) {
        // [start, end, linewise] for operator+motion, or null
        var v = edTa.text, pos = edTa.cursorPosition
        var lb = lineBounds(v, pos)
        var linewise = false, end = pos, start = pos
        if (motion === "w") { start = pos; end = nextWordStart(v, pos) }
        else if (motion === "b") { start = prevWordStart(v, pos); end = pos }
        else if (motion === "e") { start = pos; end = Math.min(nextWordEnd(v, pos) + 1, v.length) }
        else if (motion === "0") { start = lb[0]; end = pos }
        else if (motion === "$") { start = pos; end = lb[1] }
        else if (motion === "j" || motion === "k") {
            linewise = true
            var starts = lineStarts(v), li = 0
            while (li + 1 < starts.length && starts[li + 1] <= pos) li++
            var nl = li + (motion === "j" ? 1 : -1)
            if (nl < 0) nl = 0
            if (nl >= starts.length) nl = starts.length - 1
            start = starts[li]
            end = nl + 1 < starts.length ? starts[nl + 1] : v.length
        } else if (motion === "d") {
            linewise = true
            start = lb[0]; end = lb[1] + 1
            if (end > v.length) end = v.length
        } else return null
        return [Math.min(start, end), Math.max(start, end), linewise]
    }
    function vimDo(op, motion) {
        var t = opTarget(op, motion)
        if (!t) return
        if (op === "d") deleteRange(t[0], t[1], true)
        else if (op === "y") {
            killRing.push(edTa.text.slice(t[0], t[1]))
            edTa.cursorPosition = t[0]
        } else if (op === "c") {
            deleteRange(t[0], t[1], true)
            vimMode = "insert"
        }
    }
    function pasteLine(before) {
        var v = edTa.text, pos = edTa.cursorPosition
        if (killRing.length === 0) return
        pushUndo()
        var last = killRing[killRing.length - 1]
        var lb = lineBounds(v, pos)
        var text = last.slice(-1) === "\n" || last.indexOf("\n") !== -1
                   ? last : last + "\n"
        var at = before ? lb[0] : Math.min(lb[1] + 1, v.length)
        edTa.text = v.slice(0, at) + text + v.slice(at)
        edTa.cursorPosition = at + text.length
    }
    function tabIndent() {
        var s = edTa.selectionStart, e = edTa.selectionEnd
        edTa.text = edTa.text.slice(0, s) + "  " + edTa.text.slice(e)
        edTa.cursorPosition = s + 2
    }
    function tabDedent() {
        // Shift+Tab: remove two spaces from the cursor line's start
        var s = edTa.selectionStart
        var ls = edTa.text.lastIndexOf("\n", s - 1) + 1
        if (edTa.text.slice(ls, ls + 2) === "  ") {
            pushUndo()
            edTa.text = edTa.text.slice(0, ls) + edTa.text.slice(ls + 2)
            edTa.cursorPosition = Math.max(ls, s - 2)
        }
    }
    function toggleVim() {
        vimEnabled = !vimEnabled
        vimMode = vimEnabled ? "normal" : "insert"
        pendingOp = ""; pendingCount = ""; pendingG = false
        vimAnchor = -1; colGoal = -1
    }

    function runPreview() {
        // [[ asset ]] references expand via the bridge (slug / GUID /
        // type/…/name forms → fengrid-asset:// urls)
        var doc = code !== null
                  ? code.fiddle_doc(editors.html, editors.css, editors.js)
                  : ("<!DOCTYPE html><html><head><style>" + editors.css +
                     "</style></head><body>" + editors.html +
                     "<script>" + editors.js + "</" + "script></body></html>")
        previewDoc = doc
        previewActive = true
    }

    function saveSnippet() {
        if (code === null)
            return
        code.save(titleField.text, code.current.description || "",
                  snipLang,
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
            snipLang = code.current.language || "web"
            currentPane = bodyField || "html"
            edTa.text = editors[currentPane]
            titleField.text = code.current.title || ""
            tagsField.text = code.current.tags || ""
            dirty = false
        }
        function onMessage(msg) { toast.show(msg) }
        function onImportFailed(err) { toast.show(qsTr("Import failed: %1").arg(err)) }
        function onImportDone(n) { toast.show(qsTr("Imported %1 snippets").arg(n)) }
        function onKeymapChanged() {
            if (keymap === "vim") {
                vimEnabled = true
                vimMode = "normal"
            } else if (vimEnabled) {
                toggleVim()                   // leaving the vim scheme → off
            }
        }
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
                    // filter list = the editor language suite (the pane
                    // filter matches the snippet's language column)
                    model: code !== null
                           ? [qsTr("All langs")].concat(code.languages)
                           : [qsTr("All langs")]
                    currentIndex: 0
                    onActivated: function (idx) {
                        code !== null && code.set_lang(
                            idx === 0 ? "" : code.languages[idx - 1])
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
                    // menus outside the delegate read the row via currentItem
                    readonly property var row: modelData
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
                        id: snipMa
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            code !== null && code.open_snippet(snipItem.modelData.id)
                            if (mouse.button === Qt.RightButton)
                                snipMenu.popup()
                        }
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

            // snippet context menu
            Menu {
                id: snipMenu
                width: 190
                padding: 4
                background: Rectangle {
                    radius: 8; color: theme.tokens.surface
                    border.color: theme.tokens.border
                }
                FgMenuItem {
                    text: qsTr("Open in editor")
                    height: 28
                    onTriggered: code !== null && code.open_snippet(
                        snipList.currentItem ? snipList.currentItem.row.id : -1)
                }
                FgMenuItem {
                    text: qsTr("Copy title")
                    height: 28
                    onTriggered: {
                        var it = snipList.currentItem
                        if (it)
                            titleField.text = it.row.title
                    }
                }
                FgMenuSeparator {
                    topPadding: 3; bottomPadding: 3
                    contentItem: Rectangle { implicitHeight: 1; color: theme.tokens.border }
                }
                FgMenuItem {
                    text: qsTr("Add to collection")
                    height: 28
                    enabled: library !== null && library.collections.length > 0
                    Menu {
                        id: snipCollSub
                        Repeater {
                            model: library !== null ? library.collections : []
                            MenuItem {
                                id: snipCollItem
                                required property var modelData
                                text: snipCollItem.modelData.name
                                onTriggered: {
                                    var it = snipList.currentItem
                                    if (it && code !== null)
                                        library.add_ref(
                                            snipCollItem.modelData.id,
                                            "snippet", it.row.id, it.row.title)
                                }
                            }
                        }
                    }
                    onHoveredChanged: if (hovered) snipCollSub.popup(
                                          parent, parent.width, 0)
                    onClicked: snipCollSub.popup(parent, parent.width, 0)
                }
                FgMenuItem {
                    text: qsTr("Delete snippet")
                    height: 28
                    onTriggered: {
                        var it = snipList.currentItem
                        if (it && code !== null)
                            code.remove(it.row.id)
                    }
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
                        // web fiddle → three tabs; any other editor
                        // language → a single tab bound to its body field
                        model: isWeb ? ["html", "css", "js"]
                                     : [bodyField || "html"]
                        Button {
                            id: paneTab
                            required property string modelData
                            text: isWeb ? modelData.toUpperCase()
                                        : snipLang.toUpperCase()
                            Layout.preferredHeight: 22
                            onClicked: codeRoot.setPane(modelData)
                            background: Rectangle {
                                radius: 4
                                color: codeRoot.currentPane === paneTab.modelData
                                       ? theme.tokens.accentCode : "transparent"
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
                    // cursor line:col + vim mode — a function binding, so it
                    // re-evaluates whenever any property it reads changes
                    // (cursor, text, vim state)
                    Text {
                        id: posStatus
                        text: codeRoot.cursorStatus()
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: codeRoot.vimEnabled && codeRoot.vimMode !== "insert"
                               ? theme.tokens.accent : theme.tokens.textMuted
                        ToolTip.visible: posMouse.containsMouse
                        ToolTip.delay: 400
                        ToolTip.text: qsTr("Cursor position — line : column" +
                                           (codeRoot.vimEnabled
                                            ? " · vim mode" : ""))
                        MouseArea {
                            id: posMouse
                            anchors.fill: parent
                            hoverEnabled: true
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
                    // language suite dropdown — also how the / command
                    // lands ("New snippet" opens the editor; pick here)
                    ComboBox {
                        id: langPick
                        Layout.preferredHeight: 26
                        Layout.preferredWidth: 116
                        model: code !== null ? code.languages : []
                        currentIndex: code !== null
                                      ? code.languages.indexOf(snipLang)
                                      : 0
                        onActivated: function (idx) {
                            var lang = code !== null
                                       ? code.languages[idx] : "web"
                            if (lang !== snipLang)
                                setLanguage(lang)
                        }
                        ToolTip.visible: hovered
                        ToolTip.text: qsTr("Snippet language — markdown renders a live preview")
                        background: Rectangle {
                            radius: 6
                            color: theme.tokens.surface2
                            border.color: theme.tokens.border
                        }
                        contentItem: Text {
                            text: langPick.displayText
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.text
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 6
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
                        ToolTip.visible: hovered
                        ToolTip.delay: 350
                        ToolTip.text: qsTr("Save the snippet (Ctrl+S)")
                        Layout.preferredHeight: 26
                        onClicked: codeRoot.saveSnippet()
                        background: Rectangle {
                            radius: 6
                            color: theme.tokens.accentCode
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
                        enabled: previewProfile !== null && isWeb
                        ToolTip.visible: !enabled && hovered
                        ToolTip.text: isWeb
                                      ? qsTr("Preview unavailable (no WebEngine)")
                                      : qsTr("Only the web fiddle runs — markdown previews live")
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
                    Button {
                        id: vimBtn
                        text: qsTr("VIM")
                        Layout.preferredHeight: 26
                        onClicked: codeRoot.toggleVim()
                        ToolTip.text: qsTr("Vim modal editing (Ctrl+Alt+V)")
                        ToolTip.visible: hovered
                        background: Rectangle {
                            radius: 6
                            color: codeRoot.vimEnabled ? theme.tokens.accent
                                                       : theme.tokens.surface2
                            border.color: codeRoot.vimEnabled
                                          ? theme.tokens.accent
                                          : theme.tokens.border
                        }
                        contentItem: Text {
                            text: vimBtn.text
                            color: codeRoot.vimEnabled ? theme.tokens.bg
                                                       : theme.tokens.textMuted
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 8; rightPadding: 8
                        }
                    }
                    ComboBox {
                        id: keymapBox
                        Layout.preferredHeight: 26
                        Layout.preferredWidth: 92
                        model: [qsTr("VS Code"), qsTr("Emacs"), qsTr("Vim"),
                                qsTr("Readline")]
                        currentIndex: code !== null
                                      ? (codeRoot.keymapIndex[code.keymap] || 0) : 0
                        onActivated: function (idx) {
                            code !== null && code.set_keymap(
                                ["vscode", "emacs", "vim", "readline"][idx])
                        }
                        ToolTip.visible: hovered
                        ToolTip.text: qsTr("Editor keybindings — applies to all three tabs")
                        background: Rectangle {
                            radius: 6
                            color: theme.tokens.surface2
                            border.color: theme.tokens.border
                        }
                        contentItem: Text {
                            text: keymapBox.displayText
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.text
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 6
                        }
                    }
                }
            }
        }

        // two-row editor layout: upper row = snippet editor;
        // lower row = preview spanning the right two-thirds
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            // ---- row 1 (40%): editor + snippet property inspector.
            // Plain anchors: Layout.fillHeight is a bool in Qt6 (no
            // stretch weights) and child preferredHeight bindings on
            // parent.height are circular — fractions of the fixed-band
            // item are the honest 40/60 split.
            RowLayout {
                id: editorRow
                anchors { top: parent.top; left: parent.left
                         right: parent.right }
                height: parent.height * 0.4 - 0.5
                spacing: 0

                Rectangle {
                    id: editorPane
                    Layout.fillWidth: true
                    Layout.fillHeight: true
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
                        // glyphs render natively (QSyntaxHighlighter
                        // attached via snipHl) — no transparent-text
                        // overlay, so cursor and selection can't drift
                        color: theme.tokens.text
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
                        placeholderText: qsTr("write %1 here…").arg(currentPane)
                        placeholderTextColor: theme.tokens.inkFaint
                        onTextChanged: {
                            editors[currentPane] = text
                            dirty = true
                            mdDebounce.restart()
                        }
                        Keys.onPressed: function (event) {
                            var v = text, pos = cursorPosition
                            var mod = event.modifiers
                                      & (Qt.ControlModifier | Qt.MetaModifier)
                            var shift = event.modifiers & Qt.ShiftModifier
                            var alt = event.modifiers & Qt.AltModifier
                            var root = codeRoot

                            // NOTE: the Ctrl+Alt+V vim toggle lives in the
                            // pane-level Shortcut ONLY — a Keys-level branch
                            // here would fire in ADDITION to the shortcut
                            // (both see the same event) and double-toggle.

                            var scheme = root.keymap
                            if (!root.vimEnabled
                                    && (scheme === "emacs"
                                        || scheme === "readline")) {
                                // ---- emacs-style bindings (0.x port)
                                if (mod && !shift && event.key === Qt.Key_X) {
                                    root.emacsChord = true
                                    event.accepted = true
                                    return
                                }
                                if (root.emacsChord) {
                                    root.emacsChord = false
                                    if (mod && event.key === Qt.Key_S) {
                                        event.accepted = true
                                        root.saveSnippet()
                                    }
                                    return
                                }
                                if (mod && !shift && event.key === Qt.Key_A) {
                                    event.accepted = true
                                    cursorPosition = root.lineBounds(v, pos)[0]
                                    return
                                }
                                if (mod && !shift && event.key === Qt.Key_E) {
                                    event.accepted = true
                                    cursorPosition = root.lineBounds(v, pos)[1]
                                    return
                                }
                                if (mod && !shift && event.key === Qt.Key_K) {
                                    event.accepted = true
                                    var lbK = root.lineBounds(v, pos)
                                    root.deleteRange(pos, lbK[1], true)
                                    return
                                }
                                if (mod && !shift && event.key === Qt.Key_Y) {
                                    event.accepted = true
                                    if (root.killRing.length > 0) {
                                        var y = root.killRing[
                                            root.killRing.length - 1]
                                        text = v.slice(0, pos) + y + v.slice(pos)
                                        cursorPosition = pos + y.length
                                    }
                                    return
                                }
                                if (mod && !shift && event.key === Qt.Key_D) {
                                    event.accepted = true
                                    root.deleteRange(pos, Math.min(pos + 1, v.length), false)
                                    return
                                }
                                // readline-only extras (Ctrl+U is
                                // universal-argument in emacs, so these
                                // stay out of the emacs scheme)
                                if (scheme === "readline"
                                        && mod && !shift
                                        && event.key === Qt.Key_U) {
                                    event.accepted = true
                                    var lbU = root.lineBounds(v, pos)
                                    root.deleteRange(lbU[0], pos, true)
                                    return
                                }
                                if (scheme === "readline"
                                        && mod && !shift
                                        && event.key === Qt.Key_W) {
                                    event.accepted = true
                                    root.deleteRange(root.prevWordStart(v, pos), pos, true)
                                    return
                                }
                                if (alt && event.key === Qt.Key_B) {
                                    event.accepted = true
                                    cursorPosition = root.prevWordStart(v, pos)
                                    return
                                }
                                if (alt && event.key === Qt.Key_F) {
                                    event.accepted = true
                                    cursorPosition = root.nextWordStart(v, pos)
                                    return
                                }
                                if (alt && event.key === Qt.Key_D) {
                                    event.accepted = true
                                    root.deleteRange(pos, root.nextWordStart(v, pos), true)
                                    return
                                }
                                if (alt && event.key === Qt.Key_Backspace) {
                                    event.accepted = true
                                    root.deleteRange(root.prevWordStart(v, pos), pos, true)
                                    return
                                }
                                if (event.key === Qt.Key_Tab) {
                                    event.accepted = true
                                    root.tabIndent()
                                    return
                                }
                                if (event.key === Qt.Key_Backtab) {
                                    event.accepted = true
                                    root.tabDedent()
                                }
                                return
                            }
                            if (!root.vimEnabled) {
                                // ---- vscode (default): native editing —
                                // only the indent keys are handled here
                                if (event.key === Qt.Key_Tab) {
                                    event.accepted = true
                                    root.tabIndent()
                                    return
                                }
                                if (event.key === Qt.Key_Backtab) {
                                    event.accepted = true
                                    root.tabDedent()
                                }
                                return
                            }

                            // ---- vim modal editing
                            if (event.key === Qt.Key_Escape) {
                                event.accepted = true
                                root.vimMode = "normal"
                                root.pendingOp = ""; root.pendingCount = ""
                                root.pendingG = false; root.colGoal = -1
                                if (cursorPosition > 0 && selectionStart === selectionEnd)
                                    cursorPosition = cursorPosition - 1
                                else {
                                    root.vimAnchor = -1
                                    select(selectionStart, selectionStart)
                                }
                                return
                            }
                            if (mod && event.key === Qt.Key_R) {
                                event.accepted = true
                                return
                            }
                            if (root.vimMode === "insert") {
                                if (event.key === Qt.Key_Tab) {
                                    event.accepted = true
                                    root.tabIndent()
                                    return
                                }
                                if (event.key === Qt.Key_Backtab) {
                                    event.accepted = true
                                    root.tabDedent()
                                }
                                return  // default typing
                            }

                            // NORMAL / VISUAL — nothing types
                            if (event.text.length === 1
                                    && event.text.charCodeAt(0) >= 32)
                                event.accepted = true
                            var key = event.text
                            var count = parseInt(root.pendingCount, 10) || 1
                            var visual = root.vimMode === "visual"

                            function keepSel(fn) {
                                if (visual) {
                                    if (root.vimAnchor < 0) root.vimAnchor = pos
                                    fn()
                                    var a = root.vimAnchor, b = edTa.cursorPosition
                                    if (b < a) { var tt = a; a = b; b = tt }
                                    edTa.select(a, b)
                                } else fn()
                            }
                            function n(fn) {
                                for (var i2 = 0; i2 < count; i2++) fn()
                                root.pendingCount = ""
                            }

                            // digits: count prefix ('0' only continues a count)
                            if (/^[1-9]$/.test(key)
                                    || (root.pendingCount !== "" && key === "0")) {
                                root.pendingCount = root.pendingCount + key
                                return
                            }
                            // ex command — only :w (save) is supported
                            if (root.pendingOp === ":") {
                                if (key === "w") {
                                    root.pendingOp = ""; root.pendingCount = ""
                                    root.saveSnippet()
                                } else { root.pendingOp = ""; root.pendingCount = "" }
                                return
                            }
                            if (root.pendingG) {
                                root.pendingG = false
                                if (key === "g") keepSel(function () { root.taSet(0, 0) })
                                return
                            }
                            if (root.pendingOp) {
                                var op = root.pendingOp, mot = key
                                root.pendingOp = ""
                                var pc = root.pendingCount
                                root.pendingCount = ""
                                for (var rep = 0; rep < (parseInt(pc, 10) || 1); rep++)
                                    root.vimDo(op, mot)
                                return
                            }
                            if (event.key === Qt.Key_Backspace) {
                                event.accepted = true
                                keepSel(function () {
                                    var p = Math.max(0, edTa.cursorPosition - 1)
                                    root.taSet(p, p) })
                                return
                            }
                            if (event.key === Qt.Key_Return
                                    || event.key === Qt.Key_Enter) {
                                event.accepted = true
                                keepSel(function () { root.moveVert(1, visual) })
                                return
                            }

                            switch (key) {
                            case "h":
                                keepSel(function () { n(function () {
                                    var p = Math.max(0, edTa.cursorPosition - 1)
                                    root.taSet(p, p) }) })
                                break
                            case "l":
                                keepSel(function () { n(function () {
                                    var p = Math.min(edTa.text.length,
                                                     edTa.cursorPosition + 1)
                                    root.taSet(p, p) }) })
                                break
                            case "j":
                                root.colGoal = -1
                                keepSel(function () { n(function () {
                                    root.moveVert(1, visual) }) })
                                break
                            case "k":
                                root.colGoal = -1
                                keepSel(function () { n(function () {
                                    root.moveVert(-1, visual) }) })
                                break
                            case "w":
                                keepSel(function () { n(function () {
                                    var p = root.nextWordStart(edTa.text, edTa.cursorPosition)
                                    root.taSet(p, p) }) })
                                break
                            case "b":
                                keepSel(function () { n(function () {
                                    var p = root.prevWordStart(edTa.text, edTa.cursorPosition)
                                    root.taSet(p, p) }) })
                                break
                            case "e":
                                keepSel(function () { n(function () {
                                    var p = Math.min(root.nextWordEnd(edTa.text, edTa.cursorPosition),
                                                     edTa.text.length - 1)
                                    root.taSet(p, p) }) })
                                break
                            case "0":
                                keepSel(function () {
                                    var lb0 = root.lineBounds(edTa.text, edTa.cursorPosition)
                                    root.taSet(lb0[0], lb0[0]) })
                                break
                            case "$":
                                keepSel(function () {
                                    var lb1 = root.lineBounds(edTa.text, edTa.cursorPosition)
                                    root.taSet(lb1[1], lb1[1]) })
                                break
                            case "g":
                                root.pendingG = true
                                break
                            case "G":
                                keepSel(function () {
                                    root.taSet(edTa.text.length, edTa.text.length) })
                                break
                            case "x":
                                if (visual) root.deleteSelection(true)
                                else n(function () {
                                    var p = edTa.cursorPosition
                                    root.deleteRange(p, Math.min(p + 1, edTa.text.length), true) })
                                break
                            case "D":
                                root.deleteRange(edTa.cursorPosition,
                                                 root.lineBounds(edTa.text, edTa.cursorPosition)[1],
                                                 true)
                                break
                            case "C":
                                root.deleteRange(edTa.cursorPosition,
                                                 root.lineBounds(edTa.text, edTa.cursorPosition)[1],
                                                 true)
                                root.vimMode = "insert"
                                break
                            case "d":
                                if (visual) root.deleteSelection(true)
                                else root.pendingOp = "d"
                                break
                            case "c":
                                if (visual) { root.deleteSelection(true); root.vimMode = "insert" }
                                else root.pendingOp = "c"
                                break
                            case "y":
                                if (visual) root.yankSelection()
                                else root.pendingOp = "y"
                                break
                            case "p": root.pasteLine(false); break
                            case "P": root.pasteLine(true); break
                            case "i": root.vimMode = "insert"; break
                            case "a":
                                root.vimMode = "insert"
                                root.taSet(Math.min(pos + 1, edTa.text.length),
                                           Math.min(pos + 1, edTa.text.length))
                                break
                            case "A":
                                root.vimMode = "insert"
                                var lbA = root.lineBounds(edTa.text, edTa.cursorPosition)
                                root.taSet(lbA[1], lbA[1])
                                break
                            case "I":
                                root.vimMode = "insert"
                                var lbI = root.lineBounds(edTa.text, edTa.cursorPosition)
                                root.taSet(lbI[0], lbI[0])
                                break
                            case "o": {
                                var lbO = root.lineBounds(edTa.text, edTa.cursorPosition)
                                root.vimMode = "insert"
                                var at2 = lbO[1] + 1
                                root.taSet(at2, at2,
                                           edTa.text.slice(0, lbO[1]) + "\n"
                                           + edTa.text.slice(lbO[1]))
                                break
                            }
                            case "O": {
                                var lbO2 = root.lineBounds(edTa.text, edTa.cursorPosition)
                                root.vimMode = "insert"
                                root.taSet(lbO2[0], lbO2[0],
                                           edTa.text.slice(0, lbO2[0]) + "\n"
                                           + edTa.text.slice(lbO2[0]))
                                break
                            }
                            case "v":
                                root.vimMode = "visual"
                                root.vimAnchor = pos
                                break
                            case "u":
                                if (root.undoStack.length > 0) {
                                    var snap = root.undoStack.pop()
                                    edTa.text = snap.t
                                    edTa.cursorPosition = snap.p
                                }
                                root.vimAnchor = -1
                                break
                            case ":":
                                root.pendingOp = ":"
                                break
                            }
                        }
                    }
                }
            }

                PropertiesPanel {
                    id: snipInspector
                    Layout.preferredWidth: 300
                    Layout.fillHeight: true
                    itemKind: "snippet"
                    itemId: code !== null ? code.currentId : -1
                    visible: itemId >= 0
                }
            }

            Rectangle {
                anchors { top: editorRow.bottom; left: parent.left
                         right: parent.right }
                height: 1
                color: theme.tokens.border
            }

            // ---- row 2 (60%): preview across the full band — the
            // inspector lives in row 1, so nothing squeezes it now
            Item {
                anchors { top: editorRow.bottom; left: parent.left
                         right: parent.right; bottom: parent.bottom }
                clip: true

                Rectangle {   // live preview
                    anchors.fill: parent
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
                        // markdown: live GitHub-styled preview while typing
                        Loader {
                            anchors.fill: parent
                            anchors.margins: 1
                            active: isMarkdown && !previewActive
                            sourceComponent: PreviewPane {
                                profile: previewProfile
                                document: markdownDoc
                            }
                        }
                        Column {
                            anchors.centerIn: parent
                            visible: !codeRoot.previewActive
                                     && !isMarkdown
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
                        + "Languages: the dropdown next to the title picks "
                        + "the snippet language — Web keeps the three-tab "
                        + "HTML/CSS/JS fiddle, Markdown renders a live "
                        + "GitHub-styled preview while you type, and every "
                        + "other language (Python, Go, Rust, SQL, YAML…) "
                        + "edits a single body field. Pick a language from "
                        + "the slash menu with New snippet.\n\n"
                        + "Import: read snippets from other tools — VSCode "
                        + ".code-snippets / .json files (comments and trailing "
                        + "commas allowed) or a massCode db.sqlite. Unmapped "
                        + "languages keep their code in the JS pane with a "
                        + "lang:<name> tag.\n\n"
                        + "Keybindings: the Keymap combo switches the editor "
                        + "between VS Code (native — default), Emacs "
                        + "(Ctrl+A/E line home/end, Ctrl+K kill, Ctrl+Y "
                        + "yank, Ctrl+D delete, Alt+B/F word motion, Alt+D "
                        + "kill word, Ctrl+X Ctrl+S save), Vim (modal — "
                        + "starts enabled: h j k l w b e 0 $ gg G, d c y "
                        + "operators, p P, u undo, v visual, :w save) and "
                        + "Readline (Emacs set plus Ctrl+U kill-to-line-start "
                        + "and Ctrl+W kill-word-back). The VIM toggle "
                        + "(Ctrl+Alt+V) overlays vim mode on any scheme.\n\n"
                        + "Tab indents two spaces · Shift+Tab dedents · "
                        + "Ctrl+S save · Ctrl+Enter run · Esc closes dialogs "
                        + "or leaves vim insert.")
                }
            }
        }
    }

    Shortcut {
        sequence: "Ctrl+S"
        enabled: codeRoot.visible && !Shell.overlayOpen
        onActivated: codeRoot.saveSnippet()
    }
    Shortcut {
        sequence: "Ctrl+Return"
        enabled: codeRoot.visible && previewProfile !== null
                 && !Shell.overlayOpen
        onActivated: codeRoot.runPreview()
    }
    Shortcut {
        sequence: "Ctrl+Alt+V"
        enabled: codeRoot.visible && !Shell.overlayOpen
        onActivated: codeRoot.toggleVim()
    }
}
