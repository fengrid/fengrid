import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// FONTS · CSS/webfont export — shows the fonts.css boilerplate
// (editable, syntax highlighted) for every selected family, with the
// @font-face URLs pointing at RELATIVE paths (fonts/<Family>/<file>).
// Two save modes:
//   «Save to folder»  — fonts.css + fonts/<Name>.<flavor> laid out
//                       exactly as the CSS references them
//   «Save as ZIP…»    — the same package as one archive (fonts.css at
//                       the root, fonts/ beside it)
// Formats: WOFF2 / WOFF / TTF / OTF — the CSS src() lines follow the
// selection, and files are converted on save (fontTools).
Dialog {
    id: cssRoot

    component Chip: AbstractButton {
        id: chipRoot
        property string chipText: ""
        property bool active: false
        property color activeColor: theme.tokens.accent
        implicitWidth: chipLbl.implicitWidth + 20
        implicitHeight: 24
        background: Rectangle {
            radius: 12
            color: chipRoot.active ? chipRoot.activeColor
                                   : theme.tokens.surface2
            border.color: chipRoot.active ? chipRoot.activeColor
                                          : theme.tokens.border
        }
        contentItem: Text {
            id: chipLbl
            text: chipRoot.chipText
            font.family: theme.monoFont; font.pixelSize: 10
            color: chipRoot.active ? theme.tokens.bg : theme.tokens.text
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    property var chosen: []              // families passed in by the caller
    property var flavors: ["woff2", "woff"]
    property bool includeOriginal: false
    property bool userEdited: false      // stop regenerating once edited
    property string dest: ""
    property string previewError: ""
    readonly property bool canSave: chosen.length > 0
                                    && destField.text.trim() !== ""

    width: 580
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    padding: 16
    background: Rectangle {
        radius: 12
        color: theme.tokens.surface
        border.color: theme.tokens.border
    }

    // open FIRST, fill SECOND: a failed preview can never swallow the
    // click (the "Export CSS button does nothing" class of bug — the
    // dialog always appears, and any error shows inside it).
    // #52: the family-selection portion is REMOVED — the caller passes
    // the checked families (grid checkboxes / Ctrl/Shift multi-select)
    // or the currently selected family.
    function openWith(families) {
        userEdited = false
        // QVariantList from Python is NOT an Array in QML (typeof
        // "object", Array.isArray false) — copy it element-wise
        var arr = []
        try {
            if (typeof families === "string") {
                if (families !== "")
                    arr.push(families)
            } else if (families) {
                for (var i = 0; i < families.length; i++)
                    arr.push(families[i])
            }
        } catch (e) {
            arr = []
        }
        // ONE assignment — mutating in place would never notify canSave
        chosen = arr
        dest = library !== null && library.lastExportDir !== ""
               ? library.lastExportDir : ""
        open()
        regenerate()
    }
    function regenerate() {
        previewError = ""
        if (fonts === null || !chosen.length) {
            cssEdit.text = "/* fengrid webfont package */\n" +
                           "/* select at least one family */"
            return
        }
        var css = fonts.css_preview(chosen, flavors)
        if (typeof css === "string" && css !== "") {
            cssEdit.text = css
        } else {
            previewError = qsTr("could not build the stylesheet — the " +
                                "reason is shown in the toast")
            cssEdit.text = "/* preview unavailable */"
        }
        userEdited = false
    }
    function toggleFlavor(f) {
        var sel = flavors.slice()
        var i = sel.indexOf(f)
        if (i >= 0) {
            if (sel.length === 1)
                return                       // keep at least one format
            sel.splice(i, 1)
        } else {
            sel.push(f)
        }
        flavors = sel
        regenerate()
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
                       "by a RELATIVE path (fonts/<file>.woff2|.woff) so " +
                       "the folder works anywhere unchanged. Saving " +
                       "converts the files to the selected formats.")
        }

        // #52: the family-selection chips are GONE — families are picked
        // in the grid (checkboxes / Ctrl / Shift) and passed in here
        Text {
            Layout.fillWidth: true
            wrapMode: Text.WrapAnywhere
            font.family: theme.monoFont; font.pixelSize: 10
            color: theme.tokens.text
            text: chosen.length === 0
                  ? qsTr("no families — check families in the grid first")
                  : (chosen.length === 1
                     ? qsTr("family: %1").arg(chosen[0])
                     : qsTr("%1 families: %2")
                           .arg(chosen.length).arg(chosen.join(", ")))
        }

        // conversion formats
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: qsTr("convert to")
                font.family: theme.monoFont; font.pixelSize: 9
                font.letterSpacing: 1.2
                font.capitalization: Font.AllUppercase
                color: theme.tokens.textMuted
            }
            Flow {
                Layout.fillWidth: true
                spacing: 5
                Repeater {
                    model: ["woff2", "woff", "ttf", "otf"]
                    delegate: Chip {
                        required property var modelData
                        required property int index
                        chipText: modelData
                        active: cssRoot.flavors.indexOf(modelData) >= 0
                        activeColor: theme.tokens.accent
                        onClicked: cssRoot.toggleFlavor(modelData)
                    }
                }
            }
            FormCheck {
                checkLabel: qsTr("also include original files")
                checked: cssRoot.includeOriginal
                onToggled: cssRoot.includeOriginal = checked
            }
        }

        // editable, syntax-highlighted CSS
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 220
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
                    onTextChanged: if (activeFocus) cssRoot.userEdited = true
                    Component.onCompleted: {
                        if (typeof cssHl !== "undefined" && cssHl !== null)
                            cssHl.attach(cssEdit.textDocument, "css")
                    }
                }
            }
            Text {
                anchors { right: parent.right; bottom: parent.bottom
                          margins: 6 }
                visible: cssRoot.userEdited
                text: qsTr("edited — family/format changes regenerate it")
                font.family: theme.uiFont; font.pixelSize: 9
                color: theme.tokens.litPane
            }
        }
        Text {
            Layout.fillWidth: true
            visible: cssRoot.previewError !== ""
            text: cssRoot.previewError
            wrapMode: Text.Wrap
            font.family: theme.uiFont; font.pixelSize: 10
            color: theme.tokens.litPane
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

    footer: ColumnLayout {
        spacing: 8
        // #47: the footer spans the dialog edge-to-edge — without insets
        // the buttons sat flush against the bottom-right corner (the
        // shared FgDialogFooter carries the same 16px insets)
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            Layout.rightMargin: 16
            Layout.bottomMargin: 16
            spacing: 8
            Item { Layout.fillWidth: true }
            Button {
                text: qsTr("Cancel")
                onClicked: cssRoot.reject()
                background: Rectangle {
                    radius: 6; color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
            }
            Button {
                text: qsTr("Save as ZIP…")
                enabled: cssRoot.canSave
                ToolTip.visible: hovered
                ToolTip.text: qsTr("fonts.css at the root + fonts/ " +
                                   "beside it — one archive")
                onClicked: {
                    cssRoot.dest = destField.text.trim()
                    fonts.export_zip_pkg(cssRoot.chosen, cssRoot.dest,
                                         cssRoot.flavors,
                                         cssRoot.includeOriginal,
                                         cssEdit.text)
                    cssRoot.accept()
                }
                background: Rectangle {
                    radius: 6; color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
            }
            Button {
                text: qsTr("Save to folder")
                enabled: cssRoot.canSave
                onClicked: {
                    cssRoot.dest = destField.text.trim()
                    fonts.export_css_package(cssRoot.dest, cssEdit.text,
                                             cssRoot.chosen,
                                             cssRoot.flavors)
                    cssRoot.accept()
                }
                background: Rectangle {
                    radius: 6; color: theme.tokens.accent
                }
                contentItem: Text {
                    text: qsTr("Save to folder")
                    color: theme.tokens.bg
                    font.family: theme.uiFont; font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }

    Loader {
        id: cssDestLoader
        active: false
        sourceComponent: FolderDialog {
            id: cssFolderDialog
            currentFolder: prefs !== null && prefs.lastDialogDir !== ""
                           ? encodeURI("file://" + prefs.lastDialogDir) : ""
            onAccepted: {
                cssRoot.dest = Icons.toLocalPath(selectedFolder)
                destField.text = cssRoot.dest
                if (prefs !== null)
                    prefs.rememberDialogDir(cssFolderDialog.currentFolder)
                cssDestLoader.active = false
            }
            onRejected: {
                if (prefs !== null)
                    prefs.rememberDialogDir(cssFolderDialog.currentFolder)
                cssDestLoader.active = false
            }
        }
        function open() { active = true; item.open() }
    }
}
