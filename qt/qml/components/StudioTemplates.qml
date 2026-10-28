import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// TEMPLATES screen — generalize a project across tenants/implementations:
// template variables ({{name}} in any text prop), instance creation with
// per-tenant overrides, and the instance registry.
Item {
    id: tplRoot
    component SectionLabel: Text {
        font.family: theme.monoFont
        font.pixelSize: 9
        font.letterSpacing: 1.4
        color: theme.tokens.accent
    }


    property var st: null               // Studio bridge

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 10

        SectionLabel { text: qsTr("Template variables") }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font.family: theme.uiFont; font.pixelSize: 10
            color: theme.tokens.textMuted
            text: qsTr("Use {{name}} in any block text — instances " +
                       "substitute their own values when created. " +
                       "Exports can bake a chosen value in.")
        }

        Repeater {
            model: tplRoot.st ? tplRoot.st.templateVars : []
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 6
                Text {
                    text: modelData.name
                    font.family: theme.monoFont; font.pixelSize: 11
                    color: theme.tokens.accent
                    Layout.preferredWidth: 120
                    elide: Text.ElideRight
                }
                FormInput {
                    id: varVal
                    Layout.fillWidth: true
                    text: modelData.value
                    onEditingFinished: {
                        if (text !== modelData.value)
                            tplRoot.st.setVar(modelData.name, text)
                    }
                }
                IconButton {
                    icon_name: "trash"
                    ToolTip.text: qsTr("Delete variable")
                    onClicked: tplRoot.st.setVar(modelData.name, "")
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            FormInput {
                id: newName
                Layout.preferredWidth: 150
                label: qsTr("new variable")
            }
            Button {
                text: qsTr("Add")
                enabled: newName.text.trim() !== ""
                onClicked: {
                    tplRoot.st.setVar(newName.text.trim(), "")
                    newName.text = ""
                }
            }
        }

        SectionLabel { text: qsTr("Create instance") }
        FormDialog {
            id: instDialog
            heading: qsTr("New instance")
            acceptEnabled: instName.text.trim() !== ""
            property var stashVars: ({})
            fields: [
                FormInput { id: instName; label: qsTr("instance name") },
                FormInput {
                    id: instOverrides
                    label: qsTr("overrides — name=value, comma-separated")
                }
            ]
            onOpened: {
                instName.text = ""
                var parts = []
                var vars = tplRoot.st.templateVars
                for (var i = 0; i < vars.length; i++)
                    parts.push(vars[i].name + "=" + vars[i].value)
                instOverrides.text = parts.join(", ")
                instName.forceActiveFocus()
            }
            onApply: {
                var overrides = {}
                var bits = instOverrides.text.split(",")
                for (var i = 0; i < bits.length; i++) {
                    var kv = bits[i].split("=")
                    if (kv.length === 2 && kv[0].trim())
                        overrides[kv[0].trim()] = kv[1].trim()
                }
                var newId = tplRoot.st.instantiate(
                    instName.text, JSON.stringify(overrides))
                if (newId > 0 && projects !== null)
                    projects.open(newId)
            }
        }
        RowLayout {
            Button {
                text: qsTr("Create instance…")
                onClicked: instDialog.open()
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Copies pages + settings into a new " +
                                   "project with {{vars}} applied")
            }
        }

        SectionLabel { text: qsTr("Instances of this project") }
        Repeater {
            model: st ? st.instancesList : []
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                Button {
                    text: qsTr("Open") + " · " + modelData.name
                    onClicked: if (projects !== null)
                                   projects.open(modelData.id)
                }
            }
        }
        Text {
            visible: !st || st.instancesList.length === 0
            text: qsTr("No instances yet — this project is not used " +
                       "as a template (that's fine; the variables " +
                       "are still usable in exports)")
            font.family: theme.uiFont; font.pixelSize: 10
            color: theme.tokens.textMuted
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
        Item { Layout.fillHeight: true }
    }

    Connections {
        target: st
        function onPagesChanged() { st.refreshInstances() }
    }
}
