import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// Shared export interface: pick one or more formats, a destination
// folder, and (per pane, injected below the formats) type-specific
// options. Fires doExport(selectedFormats, destination) on Export.
Dialog {
    id: exportRoot

    default property alias options: optionsCol.data

    property string headline: qsTr("Export")
    property var formats: []             // [{id, label}]
    property var selectedFormats: []
    property string dest: ""
    property string lastDestPref: ""     // per-pane remembered path
    // multi-select: allow checking several formats at once
    property bool multi: true
    signal doExport(var formats, string dest)

    width: 420
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    padding: 16
    background: Rectangle {
        radius: 12
        color: theme.tokens.surface
        border.color: theme.tokens.border
    }

    function openWith(formats, preferredDest) {
        exportRoot.formats = formats
        selectedFormats = formats.length === 1 ? [formats[0].id] : []
        dest = preferredDest || ""
        open()
    }
    function toggle(id) {
        var sel = selectedFormats.slice()
        var i = sel.indexOf(id)
        if (i >= 0)
            sel.splice(i, 1)
        else if (multi)
            sel.push(id)
        else
            sel = [id]
        selectedFormats = sel
    }

    contentItem: ColumnLayout {
        spacing: 10

        Text {
            text: exportRoot.headline
            font.family: theme.headingFont
            font.pixelSize: 14
            font.letterSpacing: 1.2
            font.capitalization: Font.AllUppercase
            color: theme.tokens.text
        }

        // format chips — multi-select
        Flow {
            Layout.fillWidth: true
            spacing: 5
            Repeater {
                model: exportRoot.formats
                Button {
                    id: fmtChip
                    required property var modelData
                    required property int index
                    readonly property bool on: exportRoot.selectedFormats
                                               .indexOf(modelData.id) >= 0
                    implicitWidth: fmtLbl.implicitWidth + 20
                    implicitHeight: 24
                    onClicked: exportRoot.toggle(modelData.id)
                    background: Rectangle {
                        radius: 12
                        color: fmtChip.on ? theme.tokens.accent
                                          : theme.tokens.surface2
                        border.color: fmtChip.on ? theme.tokens.accent
                                                 : theme.tokens.border
                    }
                    contentItem: Text {
                        id: fmtLbl
                        text: fmtChip.modelData.label
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: fmtChip.on ? theme.tokens.bg
                                          : theme.tokens.text
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        // destination
        Text {
            text: qsTr("Destination folder")
            font.family: theme.monoFont; font.pixelSize: 9
            font.letterSpacing: 1.2; font.capitalization: Font.AllUppercase
            color: theme.tokens.textMuted
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            FormInput {
                id: destField
                Layout.fillWidth: true
                label: ""
                text: exportRoot.dest
                onEditingFinished: exportRoot.dest = text
            }
            FgButton {
                text: qsTr("Browse…")
                onClicked: exportDestLoader.open()
            }
        }

        // per-type options (injected by the calling pane)
        ColumnLayout {
            id: optionsCol
            Layout.fillWidth: true
            spacing: 8
        }
    }

    footer: FgDialogFooter {
        acceptLabel: qsTr("Export")
        acceptEnabled: exportRoot.selectedFormats.length > 0
                       && destField.text.trim() !== ""
        onCancelClicked: exportRoot.reject()
        onAcceptClicked: {
            exportRoot.dest = destField.text.trim()
            exportRoot.doExport(exportRoot.selectedFormats,
                                exportRoot.dest)
            exportRoot.accept()
        }
    }

    // lazy native folder dialog (portal-safe — never instantiated
    // until Browse is clicked)
    Loader {
        id: exportDestLoader
        active: false
        sourceComponent: FolderDialog {
            id: exportFolderDialog
            currentFolder: prefs !== null && prefs.lastDialogDir !== ""
                           ? encodeURI("file://" + prefs.lastDialogDir) : ""
            onAccepted: {
                exportRoot.dest = Icons.toLocalPath(selectedFolder)
                destField.text = exportRoot.dest
                if (prefs !== null)
                    prefs.rememberDialogDir(exportFolderDialog.currentFolder)
                exportDestLoader.active = false
            }
            onRejected: {
                if (prefs !== null)
                    prefs.rememberDialogDir(exportFolderDialog.currentFolder)
                exportDestLoader.active = false
            }
        }
        // #81 dead-attempt recycle guard (same class as the settings
        // dialog loaders): a native dialog that never maps leaves the
        // Loader active forever, and every later click re-opens the
        // same dead item — recycle the Loader and retry instead.
        function open() {
            if (prefs !== null)
                prefs.noteDialogEvent(
                    "exportBrowse", active ? "retry-click" : "click", 0)
            if (active)
                active = false
            active = true
            item.open()
        }
    }
}
