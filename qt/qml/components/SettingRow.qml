import QtQuick
import QtQuick.Layouts

// One settings row: label + description on the left, the control
// appended as a child on the right (VS Code-style). The owning screen
// sets `visible` from its category/search filter — this component has
// no view of the owner's state (ids don't cross file scopes).
RowLayout {
    id: row
    property string section: ""  // category key — also drives the
                                 // section's any-row-visible filter
    property string label: ""
    property string desc: ""
    property string keys: ""     // extra search synonyms
    // filter result as PLAIN DATA: SettingsSection reads this instead of
    // `visible`, because `visible` reads are effectively-visibility — a
    // hidden section would hide its rows, then never see them match
    // again (parent/child visibility deadlock)
    property bool rowMatches: true
    visible: rowMatches

    Layout.fillWidth: true
    Layout.topMargin: 14
    spacing: 20

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        Text {
            text: row.label
            font.family: theme.uiFont
            font.pixelSize: 13
            color: theme.tokens.text
            Layout.fillWidth: true
            wrapMode: Text.Wrap
        }
        Text {
            text: row.desc
            font.family: theme.uiFont
            font.pixelSize: 11
            color: theme.tokens.textMuted
            Layout.fillWidth: true
            wrapMode: Text.Wrap
        }
    }
}