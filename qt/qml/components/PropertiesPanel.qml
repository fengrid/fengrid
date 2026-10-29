import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Universal Properties panel — the right-hand configuration surface for
// EVERY asset kind (icon, font, palette, snippet). Driven entirely by
// taxonomy.item_properties(kind, id): tags, custom field values, and
// typed links, so each pane only needs to supply a kind + id.
//
// Two tabs (VS Code panel-style): INFO carries the taxonomy surface
// (tags / custom fields / links); DETAILS carries kind-specific rich
// content — the font specimen view (replacing the old FontDetail popup),
// the palette's color list, or a snippet's metadata card.
Rectangle {
    id: panel
    color: theme.tokens.bg

    property string itemKind: "icon"
    property int itemId: -1
    property var props: null
    property int activeTab: 0
    // Projects and saved Libraries carry their own repo tree — the
    // Docs / License / Sources tabs exist only for them
    readonly property bool isEntity: itemKind === "project"
                                     || itemKind === "library"
    property var related: []          // cross-kind tag neighbours
    property var srcSum: null         // Sources tab snapshot
    function refreshSources() {
        srcSum = (taxonomy !== null && isEntity && itemId >= 0)
                 ? taxonomy.git_summary(itemKind, itemId) : null
    }
    // fonts default to Details (the specimen is the money view — this
    // preserves the old click-opens-details behavior); others to Info
    function defaultTab() { return itemKind === "font" ? 1 : 0 }

    // specimen controls (Details tab, font kind)
    property real previewPx: 30
    property bool darkBg: true
    property string sample: "The quick brown fox jumps over the lazy dog"
    // auto preview text: one curated passage per size bucket (haiku /
    // poems / speeches from resources/preview_text.json), swapped at
    // THREE breakpoints only; disabled the moment the user types
    property bool sampleCustom: false
    property string autoSample: fonts !== null
                                ? fonts.preview_text(previewPx) : ""
    onAutoSampleChanged: if (!sampleCustom) sample = autoSample
    function resetSample() {
        sampleCustom = false
        if (fonts !== null)
            fonts.set_sample_custom(false)
        sample = autoSample
    }

    onItemIdChanged: reload()
    onItemKindChanged: {
        reload()
        activeTab = defaultTab()
    }
    visible: itemId >= 0
    Component.onCompleted: {
        reload()
        if (!sampleCustom && autoSample !== "")
            sample = autoSample
    }

    function reload() {
        props = (taxonomy !== null && itemId >= 0)
                ? taxonomy.item_properties(itemKind, itemId) : null
        related = (taxonomy !== null && itemId >= 0)
                  ? taxonomy.related_by_tags(itemKind, itemId) : []
        refreshSources()
    }

    // 100..900 CSS weights → Qt font weights
    function weightEnum(w) {
        var map = {}
        map[100] = Font.Thin; map[200] = Font.ExtraLight
        map[300] = Font.Light; map[400] = Font.Normal
        map[500] = Font.Medium; map[600] = Font.DemiBold
        map[700] = Font.Bold; map[800] = Font.ExtraBold
        map[900] = Font.Black
        return map[w] !== undefined ? map[w] : Font.Normal
    }

    Connections {
        target: taxonomy
        function onFieldsChanged() { panel.reload() }
        function onLinksChanged() { panel.reload() }
        function onGitUpdated() { panel.refreshSources() }
    }

    component SectionHeader: Text {
        topPadding: 12
        bottomPadding: 4
        font.family: theme.headingFont
        font.pixelSize: 12
        font.letterSpacing: 1.4
        font.capitalization: Font.AllUppercase
        color: theme.tokens.textMuted
    }

    component PanelTab: AbstractButton {
        id: ptab
        property string label
        property int tabIdx
        checked: panel.activeTab === tabIdx
        hoverEnabled: true
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        onClicked: panel.activeTab = tabIdx
        // tighter padding so five tabs (entity kinds) fit a 300px dock
        implicitWidth: ptabLabel.implicitWidth
                       + (panel.isEntity ? 12 : 24)
        implicitHeight: 26

        background: Rectangle {
            implicitWidth: ptab.implicitWidth
            implicitHeight: ptab.implicitHeight
            color: "transparent"
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 2
                radius: 1
                color: theme.tokens.accent
                opacity: ptab.checked ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 140 } }
            }
        }
        contentItem: Text {
            id: ptabLabel
            text: ptab.label
            font.family: theme.headingFont
            font.pixelSize: 10
            font.letterSpacing: 1.2
            font.capitalization: Font.AllUppercase
            color: ptab.checked ? theme.tokens.text
                  : theme.tokens.textMuted
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Item { Layout.fillWidth: true; Layout.preferredHeight: 8 }

        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 12
            text: panel.itemKind.toUpperCase()
            font.family: theme.headingFont
            font.pixelSize: 12
            font.letterSpacing: 1.6
            color: theme.tokens.accent
        }

        // tab row + hairline (VS Code panel-tab look)
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 6
            Layout.topMargin: 4
            spacing: 2
            PanelTab { label: qsTr("Info"); tabIdx: 0 }
            PanelTab { label: qsTr("Details"); tabIdx: 1 }
            PanelTab {
                label: qsTr("Docs"); tabIdx: 2
                visible: panel.isEntity
            }
            PanelTab {
                label: qsTr("License"); tabIdx: 3
                visible: panel.isEntity
            }
            PanelTab {
                label: qsTr("Sources"); tabIdx: 4
                visible: panel.isEntity
            }
            Item { Layout.fillWidth: true }
        }
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: theme.tokens.border
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: panel.activeTab

            // ================================================== INFO PAGE
            Flickable {
                contentHeight: infoCol.implicitHeight + 24
                clip: true
                ScrollBar.vertical: ScrollBar { }

                ColumnLayout {
                    id: infoCol
                    width: panel.width - 24
                    x: 12
                    spacing: 8

                    Item { Layout.fillWidth: true; Layout.preferredHeight: 2 }

                    // ------------------------------------------------------ TAGS
                    SectionHeader { text: qsTr("Tags") }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 5
                        Repeater {
                            model: panel.props ? panel.props.tags : []
                            Rectangle {
                                required property var modelData
                                radius: 9
                                height: 20
                                width: tagText.implicitWidth + 26
                                color: theme.tokens.surface2
                                Row {
                                    anchors.centerIn: parent
                                    spacing: 4
                                    Text {
                                        id: tagText
                                        text: "#" + modelData
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.text
                                    }
                                    Text {
                                        text: "✕"
                                        font.pixelSize: 9
                                        color: theme.tokens.textMuted
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: taxonomy !== null
                                                && taxonomy.remove_tag(
                                                    panel.itemKind,
                                                    panel.itemId, modelData)
                                        }
                                    }
                                }
                            }
                        }
                        Text {
                            visible: !panel.props
                                     || panel.props.tags.length === 0
                            text: qsTr("no tags yet")
                            font.family: theme.uiFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }
                    }
                    RowLayout {
                        spacing: 6
                        Layout.fillWidth: true
                        Rectangle {
                            Layout.fillWidth: true
                            height: 26
                            radius: 6
                            color: theme.tokens.surface2
                            border.color: tagAddInput.activeFocus
                                          ? theme.tokens.accent
                                          : theme.tokens.border
                            TextInput {
                                id: tagAddInput
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                verticalAlignment: TextInput.AlignVCenter
                                font.family: theme.monoFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                clip: true
                                onAccepted: {
                                    if (text.trim() !== ""
                                            && taxonomy !== null) {
                                        taxonomy.add_tag(panel.itemKind,
                                                         panel.itemId,
                                                         text.trim())
                                        text = ""
                                    }
                                }
                            }
                            Text {
                                visible: tagAddInput.text === ""
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                verticalAlignment: Text.AlignVCenter
                                text: qsTr("add tag…")
                                font.family: theme.uiFont
                                font.pixelSize: 10
                                color: theme.tokens.textMuted
                            }
                        }
                        IconButton {
                            icon_name: "plus"
                            implicitWidth: 24
                            implicitHeight: 24
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (tagAddInput.text.trim() !== ""
                                            && taxonomy !== null) {
                                        taxonomy.add_tag(panel.itemKind,
                                                         panel.itemId,
                                                         tagAddInput.text
                                                         .trim())
                                        tagAddInput.text = ""
                                    }
                                }
                            }
                        }
                    }

                    // ------------------------------------------------ FIELDS
                    SectionHeader { text: qsTr("Custom fields") }
                    Repeater {
                        model: panel.props ? panel.props.fields : []
                        RowLayout {
                            id: propRow
                            required property var modelData
                            spacing: 6
                            Layout.fillWidth: true
                            Text {
                                text: propRow.modelData.name
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.textMuted
                                Layout.preferredWidth: 82
                                elide: Text.ElideRight
                            }
                            Loader {
                                Layout.fillWidth: true
                                sourceComponent:
                                    propRow.modelData.type === "bool"
                                    ? boolEd
                                    : (propRow.modelData.type === "select"
                                       ? selectEd : textEd)
                            }
                            Component {
                                id: textEd
                                Rectangle {
                                    implicitHeight: 24
                                    radius: 5
                                    color: theme.tokens.surface2
                                    border.color: pvInput.activeFocus
                                                  ? theme.tokens.accent
                                                  : theme.tokens.border
                                    TextInput {
                                        id: pvInput
                                        anchors.fill: parent
                                        anchors.leftMargin: 6
                                        anchors.rightMargin: 6
                                        verticalAlignment:
                                            TextInput.AlignVCenter
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.text
                                        clip: true
                                        text: propRow.modelData.value
                                        onEditingFinished: taxonomy !== null
                                            && taxonomy.set_field_value(
                                                panel.itemId,
                                                propRow.modelData.id,
                                                text, panel.itemKind)
                                    }
                                }
                            }
                            Component {
                                id: boolEd
                                // #102: shared compact checkbox (raw
                                // default-style CheckBox was ~26px next
                                // to 10px row text)
                                FormCheck {
                                    font.family: theme.monoFont
                                    font.pixelSize: 10
                                    checked:
                                        propRow.modelData.value === "1"
                                    onClicked: taxonomy !== null
                                        && taxonomy.set_field_value(
                                            panel.itemId,
                                            propRow.modelData.id,
                                            checked ? "1" : "0",
                                            panel.itemKind)
                                }
                            }
                            Component {
                                id: selectEd
                                ComboBox {
                                    implicitHeight: 24
                                    model:
                                        propRow.modelData.options.choices
                                        || []
                                    currentIndex: {
                                        var ch =
                                            propRow.modelData.options
                                            .choices || []
                                        return Math.max(0, ch.indexOf(
                                            propRow.modelData.value))
                                    }
                                    onActivated: function (idx) {
                                        taxonomy !== null
                                            && taxonomy.set_field_value(
                                                panel.itemId,
                                                propRow.modelData.id,
                                                model[idx],
                                                panel.itemKind)
                                    }
                                    background: Rectangle {
                                        radius: 5
                                        color: theme.tokens.surface2
                                        border.color: theme.tokens.border
                                    }
                                    contentItem: Text {
                                        text: parent.displayText
                                        font.family: theme.monoFont
                                        font.pixelSize: 10
                                        color: theme.tokens.text
                                        verticalAlignment:
                                            Text.AlignVCenter
                                        leftPadding: 6
                                    }
                                }
                            }
                            IconButton {
                                visible:
                                    propRow.modelData.type === "id"
                                icon_name: "zap"
                                icon_px: 10
                                implicitWidth: 20
                                implicitHeight: 20
                                ToolTip.text: qsTr("Generate next ID")
                                onClicked: taxonomy !== null
                                    && taxonomy.generate_id(
                                        panel.itemId,
                                        propRow.modelData.id,
                                        panel.itemKind)
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: !panel.props
                                 || panel.props.fields.length === 0
                        text: qsTr("No custom fields defined yet")
                        font.family: theme.uiFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                        wrapMode: Text.Wrap
                    }
                    // create fields from ANY pane's inspector
                    AbstractButton {
                        id: newFieldBtn
                        Layout.fillWidth: true
                        Layout.preferredHeight: 26
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        background: Rectangle {
                            radius: 6
                            color: newFieldMa.containsMouse
                                   ? theme.tokens.surface2 : "transparent"
                            border.color: theme.tokens.border
                        }
                        contentItem: Row {
                            spacing: 6
                            IconImage {
                                name: "plus"; px: 12
                                tint: theme.tokens.textMuted
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: qsTr("New field…")
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        MouseArea {
                            id: newFieldMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: panelFieldDialog.open()
                        }
                    }

                    // ------------------------------------------------- LINKS
                    SectionHeader { text: qsTr("Links") }
                    Repeater {
                        model: panel.props ? panel.props.links : []
                        RowLayout {
                            id: linkRow
                            required property var modelData
                            spacing: 6
                            Layout.fillWidth: true
                            Text {
                                Layout.fillWidth: true
                                text: (linkRow.modelData.direction === "out"
                                       ? "→ " : "← ")
                                      + linkRow.modelData.label
                                      + (linkRow.modelData.role !== ""
                                         ? "  (" + linkRow.modelData.role
                                           + ")" : "")
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: theme.tokens.textMuted
                                elide: Text.ElideRight
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: taxonomy !== null
                                        && taxonomy.remove_link(
                                            linkRow.modelData.id)
                                }
                                ToolTip.visible: containsMouse
                                ToolTip.text: qsTr("click to remove this"
                                                   + " link")
                                HoverHandler {
                                    cursorShape: Qt.PointingHandCursor
                                }
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: !panel.props
                                 || panel.props.links.length === 0
                        text: qsTr("No links — use an asset's"
                                   + " right-click menu to link"
                                   + " collections, libraries or"
                                   + " projects")
                        font.family: theme.uiFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                        wrapMode: Text.Wrap
                    }

                    // -------------------------------- RELATED BY TAG
                    // taxonomic links across asset types: entities of
                    // OTHER kinds carrying at least one of this item's
                    // tags (tags are the cross-kind link fabric)
                    SectionHeader {
                        text: qsTr("Related by tag")
                        visible: panel.related.length > 0
                    }
                    Repeater {
                        model: panel.related
                        delegate: RowLayout {
                            required property var modelData
                            width: panel.width - 24
                            spacing: 6
                            Rectangle {
                                width: Math.min(kindLbl.implicitWidth + 16, 64)
                                height: 18
                                radius: 4
                                color: theme.tokens.surface2
                                Text {
                                    id: kindLbl
                                    anchors.centerIn: parent
                                    text: modelData.kind
                                    font.family: theme.monoFont
                                    font.pixelSize: 9
                                    font.capitalization: Font.AllUppercase
                                    color: theme.tokens.accent
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.name
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                                elide: Text.ElideRight
                            }
                            Text {
                                text: modelData.shared.join(" ")
                                font.family: theme.monoFont
                                font.pixelSize: 9
                                color: theme.tokens.textMuted
                                elide: Text.ElideRight
                                Layout.maximumWidth: 110
                            }
                        }
                    }

                    Item { Layout.fillHeight: true
                           Layout.minimumHeight: 12 }
                }
            }

            // ================================================ DETAILS PAGE
            Loader {
                Layout.fillWidth: true
                Layout.fillHeight: true
                sourceComponent: panel.itemKind === "font" ? fontDetailPage
                                 : panel.itemKind === "palette"
                                   ? paletteDetailPage
                                   : panel.itemKind === "icon"
                                     ? iconDetailPage : snippetDetailPage
            }

            // ================================================ DOCS PAGE
            // (project / library kinds only) — renders the entity's
            // README.md straight out of its repository tree
            Flickable {
                contentHeight: docsCol.implicitHeight + 24
                clip: true
                ScrollBar.vertical: ScrollBar { }

                ColumnLayout {
                    id: docsCol
                    width: panel.width - 24
                    x: 12
                    spacing: 8

                    Item { Layout.fillWidth: true; Layout.preferredHeight: 2 }

                    Text {
                        Layout.fillWidth: true
                        visible: !panel.props
                                 || !panel.props.meta.readme
                                 || !panel.props.meta.readme.exists
                        text: qsTr("No README.md in this repository yet."
                                   + " Add one to the repository folder and"
                                   + " it will show up here — it is the"
                                   + " Documentation tab's source.")
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.textMuted
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: panel.props && panel.props.meta.readme
                                 && panel.props.meta.readme.path !== ""
                        text: panel.props && panel.props.meta.readme
                              ? panel.props.meta.readme.path : ""
                        font.family: theme.monoFont
                        font.pixelSize: 9
                        color: theme.tokens.textMuted
                        elide: Text.ElideMiddle
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: panel.props && panel.props.meta.readme
                                 && panel.props.meta.readme.exists
                        text: panel.props && panel.props.meta.readme
                              ? panel.props.meta.readme.text : ""
                        font.family: theme.monoFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                        wrapMode: Text.WrapAnywhere
                        textFormat: Text.PlainText
                    }
                    Item { Layout.fillHeight: true
                           Layout.minimumHeight: 12 }
                }
            }

            // ============================================== LICENSE PAGE
            Flickable {
                contentHeight: licCol.implicitHeight + 24
                clip: true
                ScrollBar.vertical: ScrollBar { }

                ColumnLayout {
                    id: licCol
                    width: panel.width - 24
                    x: 12
                    spacing: 8

                    Item { Layout.fillWidth: true; Layout.preferredHeight: 2 }

                    Text {
                        Layout.fillWidth: true
                        visible: !panel.props
                                 || !panel.props.meta.license
                                 || !panel.props.meta.license.exists
                        text: qsTr("No LICENSE file in this repository."
                                   + " Drop a LICENSE.md into the repository"
                                   + " folder — standard open-source licenses"
                                   + " are recognized and summarized here.")
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.textMuted
                        wrapMode: Text.Wrap
                    }

                    // recognized standard license → summarized terms
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        visible: panel.props && panel.props.meta.license
                                 && panel.props.meta.license.exists
                                 && panel.props.meta.license.standard

                        Text {
                            Layout.fillWidth: true
                            text: panel.props && panel.props.meta.license
                                  && panel.props.meta.license.standard
                                  ? panel.props.meta.license.standard.name : ""
                            font.family: theme.headingFont
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                            color: theme.tokens.text
                        }
                        Text {
                            Layout.fillWidth: true
                            text: panel.props && panel.props.meta.license
                                  && panel.props.meta.license.standard
                                  ? panel.props.meta.license.standard.spdx
                                    + "  ·  " + "full text: "
                                    + panel.props.meta.license.standard.url
                                  : ""
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.accent
                        }
                        Repeater {
                            model: panel.props && panel.props.meta.license
                                   && panel.props.meta.license.standard
                                   ? panel.props.meta.license.standard.permissions : []
                            Text {
                                required property var modelData
                                Layout.fillWidth: true
                                text: "✓ " + modelData
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                            }
                        }
                        Repeater {
                            model: panel.props && panel.props.meta.license
                                   && panel.props.meta.license.standard
                                   ? panel.props.meta.license.standard.conditions : []
                            Text {
                                required property var modelData
                                Layout.fillWidth: true
                                text: "• " + modelData
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.text
                            }
                        }
                        Repeater {
                            model: panel.props && panel.props.meta.license
                                   && panel.props.meta.license.standard
                                   ? panel.props.meta.license.standard.limitations : []
                            Text {
                                required property var modelData
                                Layout.fillWidth: true
                                text: "✕ " + modelData
                                font.family: theme.uiFont
                                font.pixelSize: 11
                                color: theme.tokens.textMuted
                            }
                        }
                    }

                    // the actual file: path, open, and a raw-text preview
                    RowLayout {
                        Layout.fillWidth: true
                        visible: panel.props && panel.props.meta.license
                                 && panel.props.meta.license.exists
                        spacing: 8
                        Text {
                            Layout.fillWidth: true
                            text: panel.props && panel.props.meta.license
                                  ? panel.props.meta.license.path : ""
                            font.family: theme.monoFont
                            font.pixelSize: 9
                            color: theme.tokens.textMuted
                            elide: Text.ElideMiddle
                        }
                        FgButton {
                            text: qsTr("Open file")
                            onClicked: {
                                if (panel.props && panel.props.meta.license
                                        && panel.props.meta.license.path)
                                    Qt.openUrlExternally(
                                        Icons.fileUrl(
                                            panel.props.meta.license.path))
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: panel.props && panel.props.meta.license
                                 && panel.props.meta.license.exists
                                 && !panel.props.meta.license.standard
                        text: qsTr("Non-standard license — read the full"
                                   + " text before redistributing.")
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.text
                        wrapMode: Text.Wrap
                    }
                    Item { Layout.fillHeight: true
                           Layout.minimumHeight: 12 }
                }
            }

            // ============================================= SOURCES PAGE
            Flickable {
                contentHeight: srcCol.implicitHeight + 24
                clip: true
                ScrollBar.vertical: ScrollBar { }

                ColumnLayout {
                    id: srcCol
                    width: panel.width - 24
                    x: 12
                    spacing: 8

                    Item { Layout.fillWidth: true; Layout.preferredHeight: 2 }

                    Text {
                        Layout.fillWidth: true
                        visible: !panel.srcSum || !panel.srcSum.exists
                        text: qsTr("No git repository for this item yet —"
                                   + " initialize one to track changes,"
                                   + " commit snapshots and sync with a"
                                   + " remote.")
                        font.family: theme.uiFont
                        font.pixelSize: 11
                        color: theme.tokens.textMuted
                        wrapMode: Text.Wrap
                    }
                    FgButton {
                        visible: panel.srcSum && !panel.srcSum.exists
                        text: qsTr("Initialize repository")
                        onClicked: taxonomy.git_init(panel.itemKind,
                                                     panel.itemId)
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        visible: panel.srcSum && panel.srcSum.exists

                        Text {
                            Layout.fillWidth: true
                            text: ((panel.srcSum && panel.srcSum.branch
                                    ? "#" + panel.srcSum.branch
                                    : "no branch"))
                                  + (panel.srcSum && panel.srcSum.clean
                                     ? "  ·  clean" : "  ·  changes pending")
                            font.family: theme.monoFont
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                            color: theme.tokens.text
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: panel.srcSum && panel.srcSum.remote !== ""
                            text: (panel.srcSum ? panel.srcSum.remote : "")
                                  || ""
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                            elide: Text.ElideMiddle
                        }
                        Text {
                            Layout.fillWidth: true
                            text: ((panel.srcSum && panel.srcSum.staged)
                                   ? panel.srcSum.staged.length : 0)
                                  + " staged · "
                                  + ((panel.srcSum && panel.srcSum.unstaged)
                                     ? panel.srcSum.unstaged.length : 0)
                                  + " unstaged · "
                                  + ((panel.srcSum && panel.srcSum.untracked)
                                     ? panel.srcSum.untracked.length : 0)
                                  + " untracked"
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: panel.srcSum
                                     && !!panel.srcSum.last_commit
                            text: panel.srcSum && panel.srcSum.last_commit
                                  ? panel.srcSum.last_commit.sha.slice(0, 10)
                                    + "  " + panel.srcSum.last_commit.subject
                                  : ""
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.text
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: (panel.srcSum ? panel.srcSum.path : "") || ""
                            font.family: theme.monoFont
                            font.pixelSize: 9
                            color: theme.tokens.textMuted
                            elide: Text.ElideMiddle
                        }
                    }

                    TextField {
                        id: srcMsg
                        Layout.fillWidth: true
                        visible: panel.srcSum && panel.srcSum.exists
                        placeholderText: qsTr("commit message…")
                        font.family: theme.uiFont
                        font.pixelSize: 11
                    }
                    Flow {
                        Layout.fillWidth: true
                        visible: panel.srcSum && panel.srcSum.exists
                        spacing: 6
                        FgButton {
                            text: qsTr("Commit")
                            enabled: srcMsg.text.trim() !== ""
                            onClicked: {
                                taxonomy.git_commit(panel.itemKind,
                                                    panel.itemId,
                                                    srcMsg.text)
                                srcMsg.text = ""
                            }
                        }
                        FgButton {
                            text: qsTr("Push")
                            onClicked: taxonomy.git_push(panel.itemKind,
                                                         panel.itemId)
                        }
                        FgButton {
                            text: qsTr("Pull")
                            onClicked: taxonomy.git_pull(panel.itemKind,
                                                         panel.itemId)
                        }
                        FgButton {
                            text: qsTr("Save & Push")
                            enabled: srcMsg.text.trim() !== ""
                            onClicked: {
                                taxonomy.git_commit_push(panel.itemKind,
                                                         panel.itemId,
                                                         srcMsg.text, true)
                                srcMsg.text = ""
                            }
                        }
                        FgButton {
                            id: discardBtn
                            property bool armed: false
                            text: qsTr("Discard changes")
                            enabled: panel.srcSum && panel.srcSum.exists
                                     && !panel.srcSum.clean
                            onClicked: {
                                if (!armed) {
                                    armed = true
                                    discardTimer.restart()
                                    return
                                }
                                armed = false
                                taxonomy.git_discard(panel.itemKind,
                                                     panel.itemId)
                            }
                            Timer {
                                id: discardTimer
                                interval: 3000
                                onTriggered: discardBtn.armed = false
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: panel.srcSum && panel.srcSum.exists
                        text: qsTr("Command line: git -C “"
                                   + (panel.srcSum ? panel.srcSum.path : "")
                                   + "” status | log | diff")
                        font.family: theme.monoFont
                        font.pixelSize: 9
                        color: theme.tokens.textMuted
                        wrapMode: Text.WrapAnywhere
                    }
                    Item { Layout.fillHeight: true
                           Layout.minimumHeight: 12 }
                }
            }
        }
    }

    // ------------------------------------------------------- font details
    Component {
        id: fontDetailPage
        Flickable {
            contentHeight: fontCol.implicitHeight + 24
            clip: true
            ScrollBar.vertical: ScrollBar { }

            ColumnLayout {
                id: fontCol
                width: panel.width - 24
                x: 12
                // one even rhythm for header, controls and every variant
                // card — 27-weight families read as distinct blocks
                spacing: 14

                Item { Layout.fillWidth: true; Layout.preferredHeight: 4 }

                // family rendered in its own face
                Text {
                    Layout.fillWidth: true
                    text: panel.props ? panel.props.meta.family : ""
                    font.family: panel.props ? panel.props.meta.family : ""
                    font.pixelSize: 22
                    color: theme.tokens.text
                    elide: Text.ElideRight
                }

                // controls: preview size, sample text, preview background
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Text {
                        text: qsTr("size")
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                    FgSlider {
                        id: sizeSlider
                        Layout.preferredWidth: 120
                        from: 10; to: 96; stepSize: 1
                        value: panel.previewPx
                        onMoved: panel.previewPx = value
                    }
                    Text {
                        text: Math.round(panel.previewPx) + "px"
                        font.family: theme.monoFont; font.pixelSize: 10
                        color: theme.tokens.text
                        Layout.preferredWidth: 30
                    }
                    Button {
                        checkable: true
                        checked: panel.darkBg
                        implicitHeight: 24
                        onClicked: panel.darkBg = !panel.darkBg
                        background: Rectangle {
                            radius: 6
                            color: parent.checked ? "#101418" : "#FFFFFF"
                            border.color: theme.tokens.border
                        }
                        contentItem: Text {
                            text: parent.checked ? qsTr("dark bg")
                                                  : qsTr("light bg")
                            color: parent.checked ? "#F5C25C" : "#16202B"
                            font.family: theme.monoFont; font.pixelSize: 10
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
                TextField {
                    id: sampleField
                    Layout.fillWidth: true
                    text: panel.sample
                    onTextEdited: {
                        panel.sampleCustom = true
                        if (fonts !== null)
                            fonts.set_sample_custom(true)
                        panel.sample = text
                    }
                    placeholderText: qsTr("type your own sample…")
                    font.family: theme.monoFont; font.pixelSize: 11
                    color: theme.tokens.text
                    background: Rectangle {
                        radius: 6; color: theme.tokens.surface2
                        border.color: sampleField.activeFocus
                                      ? theme.tokens.accent
                                      : theme.tokens.border
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: panel.sampleCustom
                    spacing: 6
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("custom preview text — curated "
                                   + "passages disabled")
                        font.family: theme.monoFont
                        font.pixelSize: 9
                        color: theme.tokens.textMuted
                        elide: Text.ElideRight
                    }
                    FgButton {
                        text: qsTr("Reset")
                        onClicked: {
                            panel.resetSample()
                            sampleField.text = panel.sample
                        }
                    }
                }

                readonly property var variants:
                    fonts !== null && panel.props
                    ? fonts.family_files(panel.props.meta.family) : []

                Text {
                    Layout.fillWidth: true
                    text: fontCol.variants.length + " variant"
                          + (fontCol.variants.length === 1 ? "" : "s")
                          + " · preview at " + Math.round(panel.previewPx)
                          + "px"
                    font.family: theme.monoFont; font.pixelSize: 10
                    color: theme.tokens.textMuted
                }

                // glyph sentence
                Rectangle {
                    Layout.fillWidth: true
                    // implicitHeight (not height): the layout owns the
                    // geometry — a hand-bound `height` raced the layout's
                    // own sizing pass and could freeze a stale, too-small
                    // measurement (the clipped specimen line)
                    implicitHeight: glCol.implicitHeight + 20
                    radius: 8
                    color: panel.darkBg ? "#101418" : "#FFFFFF"
                    border.color: theme.tokens.border
                    clip: true
                    Column {
                        id: glCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 10
                        spacing: 4
                        Text {
                            width: parent.width
                            text: panel.sample
                            font.family: panel.props
                                         ? panel.props.meta.family : ""
                            font.pixelSize: Math.min(panel.previewPx, 46)
                            color: panel.darkBg ? "#E7EDF2" : "#16202B"
                            wrapMode: Text.Wrap
                        }
                        Text {
                            width: parent.width
                            text: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
                                  + "ghijklmnopqrstuvwxyz0123456789"
                                  + " &!?%()[]{}@#*"
                            font.family: panel.props
                                         ? panel.props.meta.family : ""
                            font.pixelSize: Math.min(panel.previewPx * 0.6, 22)
                            color: panel.darkBg ? "#8DA0AF" : "#6B7A88"
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }

                // every indexed variant, rendered in its own style
                Repeater {
                    model: fontCol.variants
                    Rectangle {
                        id: varRow
                        required property var modelData
                        Layout.fillWidth: true
                        // implicitHeight, NOT height: the ColumnLayout
                        // queries implicitHeight whenever the wrapped
                        // sample, face weight or panel width changes and
                        // re-lays out — a direct `height` binding could
                        // keep a stale one-line measurement, slicing the
                        // specimen mid-glyph (seen on 27-weight families)
                        implicitHeight: vrCol.implicitHeight + 24
                        radius: 8
                        color: panel.darkBg ? "#101418" : "#FFFFFF"
                        border.color: theme.tokens.border
                        clip: true
                        Column {
                            id: vrCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 8
                            Text {
                                width: parent.width
                                text: (varRow.modelData.style || "Regular")
                                      + " · weight "
                                      + (varRow.modelData.weight || 400)
                                      + (varRow.modelData.italic
                                         ? " · italic" : "")
                                font.family: theme.monoFont
                                font.pixelSize: 10
                                color: panel.darkBg ? "#F5C25C" : "#A16207"
                            }
                            Text {
                                width: parent.width
                                text: String(varRow.modelData.path)
                                      .split("/").pop()
                                font.family: theme.monoFont
                                font.pixelSize: 9
                                color: panel.darkBg ? "#8DA0AF" : "#6B7A88"
                                elide: Text.ElideMiddle
                            }
                            Text {
                                width: parent.width
                                text: panel.sample
                                wrapMode: Text.Wrap
                                font.family: panel.props
                                             ? panel.props.meta.family : ""
                                font.pixelSize: panel.previewPx
                                font.weight: panel.weightEnum(
                                                 varRow.modelData.weight
                                                 || 400)
                                font.italic: !!varRow.modelData.italic
                                color: panel.darkBg ? "#E7EDF2" : "#16202B"
                            }
                        }
                    }
                }

                Text {
                    visible: fontCol.variants.length === 0
                    text: qsTr("No indexed files for this family")
                    font.family: theme.uiFont; font.pixelSize: 11
                    color: theme.tokens.textMuted
                }

                Item { Layout.fillHeight: true; Layout.minimumHeight: 12 }
            }
        }
    }

    // ---------------------------------------------------- palette details
    Component {
        id: paletteDetailPage
        Flickable {
            contentHeight: palCol.implicitHeight + 24
            clip: true
            ScrollBar.vertical: ScrollBar { }

            ColumnLayout {
                id: palCol
                width: panel.width - 24
                x: 12
                spacing: 8

                Item { Layout.fillWidth: true; Layout.preferredHeight: 4 }

                Text {
                    Layout.fillWidth: true
                    text: panel.props ? panel.props.meta.name : ""
                    font.family: theme.headingFont
                    font.pixelSize: 16
                    color: theme.tokens.text
                    elide: Text.ElideRight
                }

                Repeater {
                    model: panel.props ? panel.props.meta.colors : []
                    RowLayout {
                        id: colorRow
                        required property var modelData
                        spacing: 8
                        Layout.fillWidth: true
                        Rectangle {
                            width: 34; height: 24; radius: 5
                            color: colorRow.modelData.hex
                            border.color: theme.tokens.border
                        }
                        Text {
                            text: colorRow.modelData.hex.toUpperCase()
                            font.family: theme.monoFont
                            font.pixelSize: 11
                            color: theme.tokens.text
                        }
                        Text {
                            text: colorRow.modelData.locked
                                  ? "· locked" : ""
                            font.family: theme.monoFont
                            font.pixelSize: 9
                            color: theme.tokens.textMuted
                        }
                        Item { Layout.fillWidth: true }
                    }
                }

                Text {
                    visible: !panel.props
                             || panel.props.meta.colors.length === 0
                    text: qsTr("Save the working palette to see its"
                               + " colors here")
                    font.family: theme.uiFont; font.pixelSize: 10
                    color: theme.tokens.textMuted
                    wrapMode: Text.Wrap
                }

                Item { Layout.fillHeight: true; Layout.minimumHeight: 12 }
            }
        }
    }

    // ---------------------------------------------------- snippet details
    Component {
        id: snippetDetailPage
        Flickable {
            contentHeight: snipCol.implicitHeight + 24
            clip: true
            ScrollBar.vertical: ScrollBar { }

            ColumnLayout {
                id: snipCol
                width: panel.width - 24
                x: 12
                spacing: 8

                Item { Layout.fillWidth: true; Layout.preferredHeight: 4 }

                Text {
                    Layout.fillWidth: true
                    text: panel.props ? panel.props.meta.title : ""
                    font.family: theme.headingFont
                    font.pixelSize: 16
                    color: theme.tokens.text
                    elide: Text.ElideRight
                }

                Repeater {
                    model: [
                        { k: "language", v: snipCol.snipMeta("language") },
                        { k: "description", v: snipCol.snipMeta("description") },
                        { k: "created", v: snipCol.snipMeta("created") },
                        { k: "updated", v: snipCol.snipMeta("updated") }
                    ]
                    RowLayout {
                        id: metaRow
                        required property var modelData
                        spacing: 8
                        Layout.fillWidth: true
                        visible: modelData.v !== ""
                        Text {
                            text: metaRow.modelData.k
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                            Layout.preferredWidth: 82
                        }
                        Text {
                            text: metaRow.modelData.v
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.text
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                        }
                    }
                }

                function snipMeta(key) {
                    return panel.props && panel.props.meta[key]
                           ? String(panel.props.meta[key]) : ""
                }

                Item { Layout.fillHeight: true; Layout.minimumHeight: 12 }
            }
        }
    }

    // ------------------------------------------------------ icon details
    Component {
        id: iconDetailPage
        Flickable {
            contentHeight: iconCol.implicitHeight + 24
            clip: true
            ScrollBar.vertical: ScrollBar { }

            ColumnLayout {
                id: iconCol
                width: panel.width - 24
                x: 12
                spacing: 8

                Item { Layout.fillWidth: true; Layout.preferredHeight: 4 }

                // the glyph itself, rendered large
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 96
                    Rectangle {
                        anchors.centerIn: parent
                        width: 88; height: 88; radius: 10
                        color: theme.tokens.surface2
                        border.color: theme.tokens.border
                        IconImage {
                            anchors.centerIn: parent
                            px: 48
                            name: panel.props ? panel.props.meta.name : ""
                            tint: theme.tokens.text
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: panel.props ? panel.props.meta.name : ""
                    font.family: theme.headingFont
                    font.pixelSize: 16
                    color: theme.tokens.text
                    elide: Text.ElideRight
                }

                Repeater {
                    model: [
                        { k: "file", v: panel.props
                          ? String(panel.props.meta.path || "")
                            .split("/").pop() : "" },
                        { k: "folder", v: panel.props
                          ? String(panel.props.meta.path || "")
                            .split("/").slice(0, -1).join("/") : "" }
                    ]
                    RowLayout {
                        id: iconMetaRow
                        required property var modelData
                        spacing: 8
                        Layout.fillWidth: true
                        Text {
                            text: iconMetaRow.modelData.k
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.textMuted
                            Layout.preferredWidth: 82
                        }
                        Text {
                            text: iconMetaRow.modelData.v
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            color: theme.tokens.text
                            Layout.fillWidth: true
                            elide: Text.ElideMiddle
                        }
                    }
                }

                Item { Layout.fillHeight: true; Layout.minimumHeight: 12 }
            }
        }
    }

    // ── new custom field — available from ANY pane's inspector ──
    Dialog {
        id: panelFieldDialog
        objectName: "panelFieldDialog"
        width: 300
        padding: 16
        modal: true
        dim: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        background: Rectangle {
            radius: 12; color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        contentItem: ColumnLayout {
            spacing: 10
            Text {
                text: qsTr("New field")
                font.family: theme.headingFont; font.pixelSize: 15
                font.letterSpacing: 1.4
                font.capitalization: Font.AllUppercase
                color: theme.tokens.text
                Layout.bottomMargin: 2
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 30
                radius: 6
                color: theme.tokens.surface2
                border.color: pfName.activeFocus ? theme.tokens.accent
                                                 : theme.tokens.border
                TextInput {
                    id: pfName
                    anchors.fill: parent
                    anchors.leftMargin: 9; anchors.rightMargin: 9
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.monoFont; font.pixelSize: 12
                    color: theme.tokens.text
                    clip: true
                    selectByMouse: true
                }
            }
            ComboBox {
                id: pfKind
                Layout.fillWidth: true
                implicitHeight: 30
                textRole: "label"
                valueRole: "kind"
                // #105: default the scope to the panel's asset class
                model: [
                    { label: qsTr("Icons"), kind: "icon" },
                    { label: qsTr("Fonts"), kind: "font" },
                    { label: qsTr("Images"), kind: "image" },
                    { label: qsTr("Palettes"), kind: "palette" },
                    { label: qsTr("Snippets"), kind: "snippet" },
                    { label: qsTr("Projects"), kind: "project" },
                    { label: qsTr("All Asset Types"), kind: "" }
                ]
                currentIndex: {
                    var k = ["icon", "font", "image", "palette",
                             "snippet", "project"].indexOf(
                                 panel.itemKind || "icon")
                    return k >= 0 ? k : 6
                }
                background: Rectangle {
                    radius: 6; color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
                contentItem: Text {
                    text: pfKind.displayText
                    font.family: theme.monoFont; font.pixelSize: 12
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 9
                }
            }
            ComboBox {
                id: pfType
                Layout.fillWidth: true
                implicitHeight: 30
                model: ["text", "number", "bool", "date", "select", "id"]
                background: Rectangle {
                    radius: 6; color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
                contentItem: Text {
                    text: pfType.displayText
                    font.family: theme.monoFont; font.pixelSize: 12
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 9
                }
            }
            Rectangle {
                visible: pfType.currentIndex === 4
                Layout.fillWidth: true
                implicitHeight: 30
                radius: 6
                color: theme.tokens.surface2
                border.color: pfChoices.activeFocus ? theme.tokens.accent
                                                    : theme.tokens.border
                TextInput {
                    id: pfChoices
                    anchors.fill: parent
                    anchors.leftMargin: 9; anchors.rightMargin: 9
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.monoFont; font.pixelSize: 12
                    color: theme.tokens.text
                    clip: true
                    selectByMouse: true
                }
            }
            Text {
                visible: pfType.currentIndex === 4
                text: qsTr("choices (comma-separated)")
                font.family: theme.monoFont; font.pixelSize: 9
                color: theme.tokens.textMuted
            }
        }
        footer: FgDialogFooter {
            acceptLabel: qsTr("Create")
            acceptEnabled: pfName.text.trim() !== ""
            onCancelClicked: panelFieldDialog.reject()
            onAcceptClicked: {
                var opts = {}
                if (pfType.currentIndex === 4)
                    opts.choices = pfChoices.text.split(",").map(
                        function (s) { return s.trim() }).filter(
                        function (s) { return s !== "" })
                taxonomy.create_field(pfName.text.trim(),
                                      pfType.currentText,
                                      JSON.stringify(opts),
                                      pfKind.currentValue || "")
                pfName.text = ""
                pfChoices.text = ""
                panelFieldDialog.accept()
            }
        }
        onClosed: panel.reload()
    }
}
