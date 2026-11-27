import QtQuick
import QtQuick.Layouts

// A titled settings group. Hides itself entirely when none of its
// SettingRow children match the owner's filter: rows expose a
// `section` property, the header Text below does not, so the loop
// only ever counts real rows.
ColumnLayout {
    id: sec
    property string section: ""
    property string title: ""
    // false = never auto-hide (setup screens with no category/search
    // filter, or sections whose rows live inside Repeaters — Repeaters
    // are not Items, so they never appear in `children` below)
    property bool filterRows: true

    Layout.fillWidth: true
    spacing: 0
    visible: {
        if (!filterRows)
            return true;
        for (var i = 0; i < children.length; i++) {
            var c = children[i];
            // rowMatches, NOT visible: visible reads are effective, and
            // this section's own flag gates its rows' — that deadlocks
            if (c.rowMatches !== undefined && c.rowMatches)
                return true;
        }
        return false;
    }

    Text {
        text: sec.title
        font.family: theme.headingFont
        font.pixelSize: 15
        font.letterSpacing: 0.6
        color: theme.tokens.text
        Layout.fillWidth: true
        Layout.topMargin: 22
        Layout.bottomMargin: 2
    }
    Rectangle {
        Layout.fillWidth: true
        height: 1
        color: theme.tokens.border
    }
    // the owner's SettingRow children are appended here
}
