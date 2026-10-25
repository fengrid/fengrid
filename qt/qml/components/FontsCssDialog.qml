import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// FONTS · CSS export — shows the fonts.css boilerplate (editable,
// syntax highlighted) for every selected family, with the @font-face
// URLs pointing at RELATIVE paths (fonts/<Family>/<file>.woff2|woff).
// «Save…» writes the CSS exactly as shown plus the font files
// converted to WOFF2/WOFF, laid out exactly as the CSS references them.
Dialog {
    id: cssRoot

    property var fams: []                // all family names
    property var chosen: []              // checked families
    property bool userEdited: false      // stop regenerating once edited
    property string dest: ""
    readonly property bool canSave: chosen.length > 0
                                    && destField.text.trim() !== ""

    width: 560
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    padding: 16
    background: Rectangle {
        radius: 12
        color: theme.tokens.surface
        border.color: theme.tokens.border
    }

    function openWith(selectedFamily) {
        userEdited = false
        fams = fonts !== null ? fonts.family_names() : []
        chosen = selectedFamily && fams.indexOf(selectedFamily) >= 0
                 ? [selectedFamily] : (fams.length ? [fams[0]] : [])
        dest = library !== null && library.lastExportDir !== ""
               ? library.lastExportDir : ""
        regenerate()
        open()
    }
    function regenerate() {
        if (fonts !== null)
            cssEdit.text = fonts.css_preview(chosen, ["woff2", "woff"])
        userEdited = false
    }

    contentItem: ColumnLayout {
        spacing: 10

        Text {
            text: qsTr("Export fonts as CSS + webfonts")
            font.family: theme.headingFont
            font.pixelSize: 14
            font.letterSpacing: 1.2
            font.capitalization: Font.AllUppercase
            color: theme.tokens.text
        }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font.family: theme.uiFont; font.pixelSize: 10
            color: theme.tokens.textMuted
            text: qsTr("The stylesheet references every checked family " +
                       "by a RELATIVE path (fonts/<Family>/<file>.woff2 " +
                       "+ .woff). Saving writes this CSS as fonts.css " +
                       "alongside the converted font files, so the " +
                       "folder works anywhere unchanged.")
        }

        // family selection
        Flow {
            Layout.fillWidth: true
            spacing: 5
            Repeater {
                model: cssRoot.fams
                Button {
                    id: famChip
                    required property var modelData
                    required property int index
                    readonly property bool on: cssRoot.chosen
                                               .indexOf(modelData) >= 0
                    implicitWidth: famLbl.implicitWidth + 20
                    implicitHeight: 24
                    onClicked: {
                        var sel = cssRoot.chosen.slice()
                        var i = sel.indexOf(famChip.modelData)
                        if (i >= 0) sel.splice(i, 1); else sel.push(famChip.modelData)
                        cssRoot.chosen = sel
                        cssRoot.regenerate()
                    }
                    background: Rectangle {
                        radius: 12
                        color: famChip.on ? theme.tokens.accentFont
                                          : theme.tokens.surface2
                        border.color: famChip.on ? theme.tokens.accentFont
                                                 : theme.tokens.border
                    }
                    contentItem: Text {
                        id: famLbl
                        text: famChip.modelData
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: famChip.on ? theme.tokens.bg
                                          : theme.tokens.text
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        // editable, syntax-highlighted CSS
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 240
            radius: 8
            color: theme.tokens.bg
            border.color: theme.tokens.border
            Flickable {
                id: cssFlick
                anchors.fill: parent
                clip: true
                contentWidth: width
                contentHeight: cssEdit.implicitHeight
                ScrollBar.vertical: ScrollBar { }
                TextArea.flickable: TextArea {
                    id: cssEdit
                    wrapMode: TextArea.NoWrap
                    font.family: theme.monoFont; font.pixelSize: 11
                    color: theme.tokens.text
                    selectionColor: theme.tokens.accent
                    selectedTextColor: theme.tokens.bg
                    padding: 10
                    background: null
                    text: ""
                    onTextChanged: if (activeFocus) cssRoot.userEdited = true
                    Component.onCompleted: cssHl !== undefined
                                           && cssHl !== null
                                           && cssHl.attach(cssEdit.textDocument,
                                                           "css")
                }
            }
            Text {
                anchors { right: parent.right; bottom: parent.bottom
                          margins: 6 }
                visible: cssRoot.userEdited
                text: qsTr("edited — family changes regenerate it")
                font.family: theme.uiFont; font.pixelSize: 9
                color: theme.tokens.litPane
            }
        }

        // destination
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            FormInput {
                id: destField
                Layout.fillWidth: true
                label: qsTr("destination folder")
                text: cssRoot.dest
                onEditingFinished: cssRoot.dest = text
            }
            Button {
                text: qsTr("Browse…")
                onClicked: cssDestLoader.open()
            }
        }
    }

    footer: FgDialogFooter {
        acceptLabel: qsTr("Save CSS + fonts")
        acceptEnabled: cssRoot.canSave
        onCancelClicked: cssRoot.reject()
        onAcceptClicked: {
            cssRoot.dest = destField.text.trim()
            fonts.export_css_package(cssRoot.dest, cssEdit.text,
                                     cssRoot.chosen, ["woff2", "woff"])
            cssRoot.accept()
        }
    }

    Loader {
        id: cssDestLoader
        active: false
        sourceComponent: FolderDialog {
            onAccepted: {
                cssRoot.dest = Icons.toLocalPath(selectedFolder)
                destField.text = cssRoot.dest
                cssDestLoader.active = false
            }
            onRejected: cssDestLoader.active = false
        }
        function open() { active = true; item.open() }
    }
}
