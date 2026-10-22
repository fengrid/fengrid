import QtQuick
import QtQuick.Controls
import "."

// Keyboard-shortcut capture box (KeySequenceEdit replacement — that
// Control is not present in our Qt 6.9.3 build). Click to arm, press
// the combination: modifiers assemble as Ctrl/Alt/Shift/Meta+KEY,
// printable keys use their character (Alt+/), non-printables their Qt
// name (F5, Right). Escape cancels; a modifier (Ctrl/Alt/Meta) or an
// F-key is required so letters stay typeable app-wide. Writes through
// sequenceEdited → prefs.set_command_shortcut.
Rectangle {
    id: box
    width: 170
    height: 30
    radius: 6
    color: theme.tokens.surface2
    border.color: capturing ? theme.tokens.accent
                 : (tap.containsMouse || activeFocus
                    ? theme.tokens.text : theme.tokens.border)
    border.width: capturing ? 2 : 1

    property bool capturing: false
    property string seqRaw: ""       // QKeySequence text, e.g. "Alt+/"
    property string invalidHint: ""
    signal sequenceEdited(string seq)

    // live-follow prefs (Reset from the sibling button must update us)
    function syncFromPrefs() {
        if (!capturing)
            seqRaw = prefs !== null ? prefs.commandShortcut : "Alt+/"
    }
    Component.onCompleted: syncFromPrefs()
    onCapturingChanged: {
        Shell.capturing = capturing
        if (!capturing)
            invalidHint = ""
    }
    Connections {
        target: prefs
        function onCommandShortcutChanged() { box.syncFromPrefs() }
    }

    // human display: "Alt+/" → "Alt + /"
    readonly property string display:
        seqRaw !== "" ? seqRaw.split("+").join(" + ") : ""

    Text {
        anchors.centerIn: parent
        visible: !box.capturing
        text: box.display
        font.family: theme.monoFont
        font.pixelSize: 11
        color: theme.tokens.text
    }
    Text {
        anchors.centerIn: parent
        visible: box.capturing
        text: box.invalidHint !== "" ? box.invalidHint
              : qsTr("press shortcut…")
        font.family: theme.uiFont
        font.pixelSize: 11
        font.italic: box.invalidHint === ""
        color: box.invalidHint !== "" ? theme.tokens.litPane
               : theme.tokens.textMuted
    }

    MouseArea {
        id: tap
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            box.forceActiveFocus()
            box.capturing = true
            box.invalidHint = ""
        }
    }

    onActiveFocusChanged: {
        if (!activeFocus && capturing) {
            capturing = false        // click-away disarms cleanly
            Shell.capturing = false
        }
    }

    Keys.onPressed: function (event) {
        if (!box.capturing) {
            return
        }
        event.accepted = true
        var k = event.key
        if (k === Qt.Key_Escape) {
            box.capturing = false    // cancel — keep the old sequence
            Shell.capturing = false
            return
        }
        // pure modifier presses: keep waiting for the real key
        if (k === Qt.Key_Control || k === Qt.Key_Alt
                || k === Qt.Key_Shift || k === Qt.Key_Meta)
            return

        var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
        var alt = (event.modifiers & Qt.AltModifier) !== 0
        var shift = (event.modifiers & Qt.ShiftModifier) !== 0
        var meta = (event.modifiers & Qt.MetaModifier) !== 0
        var isFunctionKey = k >= Qt.Key_F1 && k <= Qt.Key_F24
        if (!ctrl && !alt && !meta && !isFunctionKey) {
            // bare letters would hijack typing app-wide (the reason "/"
            // and friends gate on focus) — demand a real modifier
            box.invalidHint = qsTr("needs Ctrl / Alt / Meta or F-key")
            return
        }

        var seq = ""
        if (ctrl) seq += "Ctrl+"
        if (alt) seq += "Alt+"
        if (shift) seq += "Shift+"
        if (meta) seq += "Meta+"

        var keyName = ""
        var text = event.text
        if (text && text.length === 1 && text >= " ")
            keyName = /[a-z0-9]/i.test(text) ? text.toUpperCase() : text
        else
            keyName = Qt.keyToString(k)
        if (keyName === "")
            return
        seq += keyName

        box.capturing = false
        Shell.capturing = false
        box.sequenceEdited(seq)      // caller persists via prefs
    }
}
