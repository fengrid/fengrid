import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// DESIGN screen — the block canvas of the Projects studio.
// Top: page tabs. Below: insert palette (compact chips) + block rows
// (click selects, arrows reorder, trash removes) + the selected
// block's inspector at the bottom. The live preview sits beside this
// column (owned by Projects.qml, shared with Run) and renders the
// SAME page — tokens + [[ asset ]] refs resolved.
Item {
    id: designRoot
    component SectionLabel: Text {
        font.family: theme.monoFont
        font.pixelSize: 9
        font.letterSpacing: 1.4
        color: theme.tokens.accent
    }

    property var st: null               // Studio bridge (injected)
    property var prj: null              // Projects bridge (pickers)
    property var sel: ({})
    // flattened visible rows — rebuilt imperatively on pageChanged
    // (bindings cannot see inside flatBlocks())
    property var canvasRows: []
    Connections {
        target: st
        function onPageChanged() {
            rebuild();
        }
        function onSelectionChanged() {
            sel = st.selectedBlock;
            rebuild();
        }
    }
    Component.onCompleted: if (st)
        rebuild()
    function rebuild() {
        if (!st)
            return;
        canvasRows = flatBlocks();
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 6

        // page tabs ------------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            Repeater {
                model: designRoot.st ? designRoot.st.pages : []
                Button {
                    id: pageTab
                    required property var modelData
                    required property int index
                    Layout.preferredHeight: 24
                    text: modelData.name + (modelData.kind === "component" ? " ⌗" : "")
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    onClicked: designRoot.st.setPage(modelData.id)
                    background: Rectangle {
                        radius: 5
                        color: designRoot.st && designRoot.st.currentPageId === pageTab.modelData.id ? theme.tokens.accentCode : theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        text: pageTab.text
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: pageTab.modelData.id === designRoot.st.currentPageId ? theme.tokens.bg : theme.tokens.text
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
            IconButton {
                icon_name: "plus"
                ToolTip.text: qsTr("New page")
                onClicked: newPageDialog.open()
            }
            Item {
                Layout.fillWidth: true
            }
            IconButton {
                icon_name: "trash"
                visible: designRoot.st && designRoot.st.pages.length > 1
                ToolTip.text: qsTr("Delete the current page")
                onClicked: designRoot.st.deletePage(designRoot.st.currentPageId)
            }
        }

        // insert palette — compact chips in a wrapping flow ---------------
        Flow {
            Layout.fillWidth: true
            spacing: 4
            Repeater {
                model: [
                    {
                        t: "section",
                        l: "Section"
                    },
                    {
                        t: "grid",
                        l: "Grid"
                    },
                    {
                        t: "heading",
                        l: "Heading"
                    },
                    {
                        t: "text",
                        l: "Text"
                    },
                    {
                        t: "image",
                        l: "Image"
                    },
                    {
                        t: "icon",
                        l: "Icon"
                    },
                    {
                        t: "button",
                        l: "Button"
                    },
                    {
                        t: "palette",
                        l: "Pal"
                    },
                    {
                        t: "font",
                        l: "Font"
                    },
                    {
                        t: "snippet",
                        l: "Snippet"
                    },
                    {
                        t: "html",
                        l: "HTML"
                    },
                    {
                        t: "spacer",
                        l: "Spacer"
                    }
                ]
                Button {
                    id: insBtn
                    required property var modelData
                    required property int index
                    property bool intoSel: designRoot.sel.type === "section" || designRoot.sel.type === "grid"
                    implicitWidth: insLbl.implicitWidth + 16
                    implicitHeight: 22
                    onClicked: {
                        designRoot.st.addBlock(modelData.t);
                        designRoot.sel = designRoot.st.selectedBlock;
                    }
                    background: Rectangle {
                        radius: 10
                        color: insBtn.intoSel ? theme.tokens.accentIcon : theme.tokens.surface2
                        border.color: theme.tokens.border
                    }
                    contentItem: Text {
                        id: insLbl
                        text: (insBtn.intoSel ? "↳ " : "+ ") + insBtn.modelData.l
                        font.family: theme.uiFont
                        font.pixelSize: 10
                        color: insBtn.intoSel ? theme.tokens.bg : theme.tokens.text
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: intoSel ? qsTr("Insert %1 inside the selected %2").arg(modelData.l).arg(designRoot.sel.type) : qsTr("Insert %1 at page root").arg(modelData.l)
                }
            }
        }

        // block canvas ----------------------------------------------------
        Flickable {
            id: canvas
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentHeight: canvasCol.implicitHeight + 8
            ScrollBar.vertical: ScrollBar {}

            ColumnLayout {
                id: canvasCol
                width: canvas.width - 8
                x: 4
                spacing: 3

                Repeater {
                    model: canvasRows
                    delegate: BlockRow {
                        entry: modelData
                    }
                }
                Text {
                    visible: designRoot.st && designRoot.canvasRows.length === 0
                    text: qsTr("Empty Page — Insert Blocks Above")
                    color: theme.tokens.textMuted
                    font.family: theme.uiFont
                    font.pixelSize: 10
                }
            }
        }

        // inspector for the selected block ---------------------------------
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: inspCol.visible ? inspCol.implicitHeight + 12 : 0
            visible: inspCol.visible
            radius: 6
            color: theme.tokens.surface
            border.color: theme.tokens.border
            ColumnLayout {
                id: inspCol
                x: 6
                y: 6
                width: parent.width - 12
                spacing: 4
                visible: designRoot.sel.id !== undefined && designRoot.sel.id !== ""
                Text {
                    text: designRoot.sel.id ? designRoot.sel.type + " · " + designRoot.sel.id : ""
                    font.family: theme.monoFont
                    font.pixelSize: 10
                    color: theme.tokens.accent
                }
                Repeater {
                    model: designRoot.sel.id ? designRoot.propFields(designRoot.sel.type) : []
                    FormInput {
                        required property var modelData
                        property string key: modelData.key
                        Layout.fillWidth: true
                        label: modelData.label
                        text: designRoot.sel.props ? (designRoot.sel.props[modelData.key] ?? "") : ""
                        onEditingFinished: {
                            var p = Object.assign({}, designRoot.sel.props || {});
                            p[modelData.key] = text;
                            designRoot.st.selectBlock(designRoot.sel.id);
                            designRoot.st.setProps(JSON.stringify(p));
                            designRoot.sel = designRoot.st.selectedBlock;
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    IconButton {
                        icon_name: "chevron-up"
                        ToolTip.text: qsTr("Move up")
                        onClicked: designRoot.st.moveBlock(-1)
                    }
                    IconButton {
                        icon_name: "chevron-down"
                        ToolTip.text: qsTr("Move down")
                        onClicked: designRoot.st.moveBlock(1)
                    }
                    IconButton {
                        icon_name: "copy"
                        ToolTip.text: qsTr("Duplicate")
                        onClicked: designRoot.st.duplicateBlock()
                    }
                    IconButton {
                        icon_name: "trash"
                        ToolTip.text: qsTr("Remove block")
                        onClicked: {
                            designRoot.st.removeBlock();
                            designRoot.sel = {};
                        }
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Text {
                        text: designRoot.sel.type === "section" || designRoot.sel.type === "grid" ? qsTr("↳ inserts nest inside") : qsTr("Selected")
                        font.family: theme.uiFont
                        font.pixelSize: 9
                        color: theme.tokens.textMuted
                    }
                }
            }
        }
    }

    // flatten the block tree into visible rows (QML cannot instantiate
    // components recursively — a flat list with indent depth renders
    // the same structure and keeps the ListView happy)
    function flatBlocks() {
        var out = [];
        function walk(tree, depth) {
            for (var i = 0; i < tree.length; i++) {
                out.push({
                    b: tree[i],
                    depth: depth
                });
                if (tree[i].children && tree[i].children.length && depth < 1)
                    walk(tree[i].children, depth + 1);
            }
        }
        if (designRoot.st)
            walk(designRoot.st.pagePayload, 0);
        return out;
    }

    component BlockRow: Rectangle {
        id: rowCard
        property var entry
        readonly property var block: entry.b
        readonly property int depth: entry.depth
        Layout.fillWidth: true
        implicitHeight: 26
        radius: 5
        color: designRoot.sel.id === block.id ? theme.tokens.surface2 : "transparent"
        border.color: designRoot.sel.id === block.id ? theme.tokens.accentCode : "transparent"
        border.width: 1
        MouseArea {
            anchors.fill: parent
            onClicked: {
                designRoot.st.selectBlock(rowCard.block.id);
                designRoot.sel = designRoot.st.selectedBlock;
            }
        }
        RowLayout {
            x: 8 + rowCard.depth * 16
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 16 - rowCard.depth * 16
            spacing: 6
            Text {
                text: rowCard.depth > 0 ? "↳" : "·"
                color: theme.tokens.textMuted
                font.pixelSize: 10
            }
            Text {
                text: rowCard.block.type
                font.family: theme.monoFont
                font.pixelSize: 10
                font.bold: designRoot.sel.id === rowCard.block.id
                color: designRoot.sel.id === rowCard.block.id ? theme.tokens.accentCode : theme.tokens.text
            }
            Text {
                Layout.fillWidth: true
                text: designRoot.previewLabel(rowCard.block)
                font.family: theme.uiFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
                elide: Text.ElideRight
            }
        }
    }

    // helpers -------------------------------------------------------------
    function previewLabel(b) {
        var p = b.props || {};
        if (b.type === "heading" || b.type === "text")
            return p.text || "";
        if (b.type === "button")
            return p.text || "button";
        if (b.type === "image")
            return p.ref ? "[[ " + p.ref + " ]]" : "image";
        if (b.type === "icon")
            return p.ref ? "[[ " + p.ref + " ]]" : "icon";
        if (b.type === "palette")
            return p.ref ? "palette " + p.ref : "palette";
        if (b.type === "font")
            return p.family || "font";
        if (b.type === "snippet")
            return p.ref ? "snippet " + p.ref : "snippet";
        if (b.type === "grid")
            return (p.columns || 3) + " columns";
        if (b.type === "spacer")
            return (p.height || 24) + "px";
        if (b.type === "html")
            return "<html>";
        return p.class || "";
    }
    function propFields(t) {
        var F = {
            heading: [
                {
                    key: "text",
                    label: "text"
                },
                {
                    key: "level",
                    label: "level 1-4"
                },
                {
                    key: "class",
                    label: "class"
                }
            ],
            text: [
                {
                    key: "text",
                    label: "text"
                },
                {
                    key: "class",
                    label: "class"
                }
            ],
            button: [
                {
                    key: "text",
                    label: "label"
                },
                {
                    key: "href",
                    label: "href"
                }
            ],
            image: [
                {
                    key: "ref",
                    label: "[[ ref ]] (slug/GUID)"
                },
                {
                    key: "alt",
                    label: "alt"
                }
            ],
            icon: [
                {
                    key: "ref",
                    label: "[[ ref ]]"
                },
                {
                    key: "size",
                    label: "size px"
                }
            ],
            palette: [
                {
                    key: "ref",
                    label: "[[ ref ]] / palette id"
                }
            ],
            font: [
                {
                    key: "family",
                    label: "family"
                }
            ],
            snippet: [
                {
                    key: "ref",
                    label: "[[ ref ]] / snippet id"
                }
            ],
            html: [
                {
                    key: "html",
                    label: "raw HTML"
                }
            ],
            spacer: [
                {
                    key: "height",
                    label: "height px"
                }
            ],
            grid: [
                {
                    key: "columns",
                    label: "columns"
                }
            ],
            section: [
                {
                    key: "class",
                    label: "class"
                }
            ]
        };
        return F[t] || [];
    }

    FormDialog {
        id: newPageDialog
        heading: qsTr("New page")
        acceptEnabled: newPageName.text.trim() !== ""
        fields: [
            FormInput {
                id: newPageName
                label: qsTr("Page Name")
            }
        ]
        onOpened: {
            newPageName.text = "";
            newPageName.forceActiveFocus();
        }
        onApply: designRoot.st.addPage(newPageName.text)
    }
}
