import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// Colors pane (M3): harmony generator, HSL/hex editor, WCAG readouts,
// saved palettes (library SQLite), CSS/JSON/SVG/PNG board exports.
// Ported from the 0.x colors.html; the math lives in core/colors.py.
Item {
    id: colorsRoot

    // false = harmony generator (the 0.x port), true = terminal designer;
    // --term (QA) opens straight into the designer
    property bool termMode: typeof initialTerm !== "undefined" ? initialTerm : false

    // `colors !== null` guards: context properties are nulled during app
    // teardown while lingering bindings re-evaluate (same as SideRail)
    Rectangle {
        id: genBar
        height: 44
        color: theme.tokens.surface
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        z: 1

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 10
            spacing: 10

            // sub-tab toggle: harmony generator vs terminal theme designer
            RowLayout {
                spacing: 2
                Repeater {
                    model: [qsTr("Harmonies"), qsTr("Terminal")]
                    delegate: Button {
                        id: modeBtn
                        required property int index
                        required property string modelData
                        Layout.preferredHeight: 26
                        onClicked: colorsRoot.termMode = index === 1
                        background: Rectangle {
                            radius: 5
                            color: (colorsRoot.termMode === modeBtn.index) ? theme.tokens.accentColor : "transparent"
                            border.color: theme.tokens.border
                        }
                        contentItem: Text {
                            text: modeBtn.modelData
                            color: (colorsRoot.termMode === modeBtn.index) ? "#101418" : theme.tokens.textMuted
                            font.family: theme.monoFont
                            font.pixelSize: 10
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }
            }
            Rectangle {
                width: 1
                height: 18
                color: theme.tokens.border
            }

            // ── HARMONY MODE: rule picker + generator + palette naming ──
            // (hidden in Terminal mode — the top bar switches contexts and
            // shows the terminal theme's own name/save/export controls)
            ComboBox {
                id: ruleBox
                visible: !colorsRoot.termMode
                Layout.preferredWidth: 160
                Layout.preferredHeight: 28
                model: [qsTr("Pleasing mix"), qsTr("Analogous"), qsTr("Complementary"), qsTr("Triadic"), qsTr("Monochrome"), qsTr("Random")]
                currentIndex: {
                    var rules = ["pleasing", "analogous", "complementary", "triadic", "monochrome", "random"];
                    return colors !== null ? Math.max(0, rules.indexOf(colors.rule)) : 0;
                }
                onActivated: function (idx) {
                    var rules = ["pleasing", "analogous", "complementary", "triadic", "monochrome", "random"];
                    if (colors !== null)
                        colors.set_rule(rules[idx]);
                }
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.surface2
                    border.color: theme.tokens.border
                }
                contentItem: Text {
                    text: ruleBox.displayText
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8
                }
            }

            Button {
                id: genBtn
                visible: !colorsRoot.termMode
                text: qsTr("Generate")
                ToolTip.visible: hovered
                ToolTip.delay: 350
                ToolTip.text: qsTr("Use the space bar to generate new color combinations!")
                onClicked: colors !== null && colors.generate()
                background: Rectangle {
                    radius: 6
                    color: theme.tokens.accent
                }
                contentItem: Text {
                    text: genBtn.text
                    color: theme.tokens.bg
                    font.family: theme.uiFont
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 12
                    rightPadding: 12
                }
            }

            Rectangle {
                id: nameBox
                visible: !colorsRoot.termMode
                Layout.preferredWidth: 170
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: nameField.activeFocus ? theme.tokens.accent : theme.tokens.border
                TextInput {
                    id: nameField
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                    text: colors !== null ? colors.paletteName : ""
                    onTextEdited: colors !== null && colors.set_name(text)
                }
                Text {
                    visible: nameField.text === ""
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Palette Name…")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }

            Rectangle {
                visible: !colorsRoot.termMode
                Layout.preferredWidth: 150
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: tagsField.activeFocus ? theme.tokens.accent : theme.tokens.border
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
                }
                Text {
                    visible: tagsField.text === ""
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Tags (Comma-Separated)")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }

            // ── TERMINAL MODE: theme name + save/export for the theme ──
            Rectangle {
                id: termNameBox
                visible: colorsRoot.termMode
                Layout.preferredWidth: 200
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: termNameField.activeFocus ? theme.tokens.accent : theme.tokens.border
                TextInput {
                    id: termNameField
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                    text: terms !== null && terms.theme ? (terms.theme.name || "") : ""
                    onEditingFinished: terms !== null && terms.set_name(text)
                }
                Text {
                    visible: termNameField.text === ""
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Theme Name…")
                    font.family: theme.uiFont
                    font.pixelSize: 11
                    color: theme.tokens.textMuted
                }
            }
            // ── ONE save/export drop-down for both interfaces ──
            // (per user request: every individual save/export button is
            // folded into this single menu; the items follow the mode)
            GenButton {
                id: saveExportBtn
                label: qsTr("Save / Export ▾")
                onClicked: saveExportMenu.popup(saveExportBtn, 0, saveExportBtn.height + 2)
            }
        }
    }
    component GenButton: AbstractButton {
        id: genB
        property string label
        implicitHeight: 26
        contentItem: Text {
            text: genB.label
            color: genB.hovered ? theme.tokens.text : theme.tokens.textMuted
            font.family: theme.uiFont
            font.pixelSize: 11
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            leftPadding: 8
            rightPadding: 8
        }
        background: Rectangle {
            radius: 6
            color: genB.pressed ? theme.tokens.surface2 : (genB.hovered ? theme.tokens.surface2 : "transparent")
            border.color: genB.hovered ? theme.tokens.accentColor : theme.tokens.border
        }
    }

    // single save/export menu — harmony mode items (save scheme, CSS/
    // JSON/SVG/PNG board) vs terminal mode items (save to snippets,
    // iTerm2/Windows Terminal/kitty/… formats)
    Menu {
        id: saveExportMenu
        width: 220
        padding: 4
        background: Rectangle {
            radius: 8
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        // ── harmony generator mode ──
        FgMenuItem {
            text: qsTr("Save scheme…")
            height: 28
            visible: !colorsRoot.termMode
            onTriggered: colors !== null && colors.save(tagsField.text)
        }
        FgMenuSeparator {
            visible: !colorsRoot.termMode
            topPadding: 3
            bottomPadding: 3
            contentItem: Rectangle {
                implicitHeight: 1
                color: theme.tokens.border
            }
        }
        Repeater {
            model: !colorsRoot.termMode ? [
                {
                    label: qsTr("Export CSS…"),
                    kind: "css"
                },
                {
                    label: qsTr("Export JSON…"),
                    kind: "json"
                },
                {
                    label: qsTr("Export SVG board…"),
                    kind: "svg"
                },
                {
                    label: qsTr("Export PNG board…"),
                    kind: "png"
                }
            ] : []
            FgMenuItem {
                required property var modelData
                text: modelData.label
                height: 28
                onTriggered: {
                    colorExport.openWith([
                        {
                            id: "css",
                            label: "CSS"
                        },
                        {
                            id: "json",
                            label: "JSON"
                        },
                        {
                            id: "svg",
                            label: "SVG board"
                        },
                        {
                            id: "png",
                            label: "PNG board"
                        }
                    ], colorsRoot.exportDest);
                    // preselect the kind that opened the dialog
                    colorExport.selectedFormats = [modelData.kind];
                }
            }
        }
        // ── terminal theme mode ──
        FgMenuItem {
            text: qsTr("Save theme to snippets")
            height: 28
            visible: colorsRoot.termMode
            onTriggered: terms !== null && terms.save_as_snippet()
        }
        Repeater {
            model: colorsRoot.termMode && terms !== null ? terms.formats() : []
            FgMenuItem {
                required property var modelData
                text: qsTr("Export %1…").arg(String(modelData.label || modelData))
                height: 28
                onTriggered: {
                    if (terms === null)
                        return;
                    colorsRoot.termExportKind = String(modelData.key || modelData);
                    termExportDialog.open();
                }
            }
        }
    }
    property string termExportKind: "json"
    FolderDialog {
        id: termExportDialog
        onAccepted: terms !== null && terms.export(Icons.toLocalPath(selectedFolder), colorsRoot.termExportKind)
    }

    // editor sync: dragged sliders lose their `val` bindings, so values are
    // assigned imperatively; the hex field only follows selection changes —
    // rebuilding it on every swatch change would fight the user mid-typing
    // (the 0.x editor kept the field intact while typing, colors.html:429-431)
    function syncSliders() {
        if (colors === null || colors.selectedIdx < 0)
            return;
        var s = colors.swatches[colors.selectedIdx];
        hSlider.val = s.h;
        sSlider.val = s.s;
        lSlider.val = s.l;
    }
    function syncEditor() {
        syncSliders();
        if (colors !== null && colors.selectedIdx >= 0)
            hexField.text = colors.swatches[colors.selectedIdx].hex;
    }
    function openColorPicker() {
        if (colors === null || colors.selectedIdx < 0)
            colors.select(0);
        colorPickerDialog.openWith(colors.swatches[colors.selectedIdx].hex);
    }
    function applyHsl() {
        if (colors === null || colors.selectedIdx < 0)
            return;
        colors.set_hsl(colors.selectedIdx, hSlider.val, sSlider.val, lSlider.val);
    }
    Connections {
        target: colors
        function onSelectionChanged() {
            syncEditor();
        }
        function onSwatchesChanged() {
            if (hSlider.pressed || sSlider.pressed || lSlider.pressed)
                // mid-drag: keep the user's values
                return;
            syncSliders();
        }
    }

    // shared export interface: multi-format, destination, one export run
    property string exportDest: ""
    ExportDialog {
        id: colorExport
        headline: qsTr("Export palette")
        onDoExport: function (formats, dest) {
            colorsRoot.exportDest = dest;
            if (colors === null)
                return;
            for (var i = 0; i < formats.length; i++)
                colors.export(formats[i], dest);
        }
    }

    ColorPickerDialog {
        id: colorPickerDialog
        onAcceptedHex: function (hex) {
            if (colors !== null && colors.selectedIdx >= 0)
                colors.set_hex(colors.selectedIdx, hex)
        }
    }

    ListView {
        id: savedStrip
        orientation: ListView.Horizontal
        height: colors !== null && colors.palettes.length > 0 ? 92 : 0
        visible: height > 0
        anchors.bottom: editorStrip.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 8
        clip: true
        spacing: 8
        model: colors !== null ? colors.palettes : []

        delegate: Rectangle {
            id: palCard
            required property var modelData
            required property int index

            width: 150
            height: 84
            radius: 8
            color: theme.tokens.surface
            border.color: theme.tokens.border

            Row {
                id: strip
                anchors.top: parent.top
                anchors.topMargin: 8
                anchors.left: parent.left
                anchors.leftMargin: 8
                // stop before the delete button — the chip run used to slide
                // under the trash and clip flush at the card edge
                anchors.right: delBtn.left
                anchors.rightMargin: 2
                height: 20
                spacing: 2
                Repeater {
                    // modelData would be shadowed by this Repeater's int
                    // model inside the delegate — read it off palCard
                    model: palCard.modelData.colors.length
                    Rectangle {
                        required property int index
                        // chip run sized to the ACTUAL color count — 5 is
                        // the default but schemes may hold up to 7
                        width: palCard.modelData.colors.length > 0 ? (strip.width - (palCard.modelData.colors.length - 1) * 2) / palCard.modelData.colors.length : strip.width
                        height: parent.height
                        radius: 3
                        color: palCard.modelData.colors[index]
                    }
                }
            }
            Text {
                anchors.top: strip.bottom
                anchors.topMargin: 4
                anchors.left: parent.left
                anchors.leftMargin: 8
                anchors.right: delBtn.left
                text: modelData.name
                font.family: theme.monoFont
                font.pixelSize: 11
                color: theme.tokens.text
                elide: Text.ElideRight
            }
            Text {
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 6
                anchors.left: parent.left
                anchors.leftMargin: 8
                text: modelData.colors.length + qsTr(" colors · ") + (modelData.tags || "")
                font.family: theme.monoFont
                font.pixelSize: 9
                color: theme.tokens.textMuted
                elide: Text.ElideRight
                width: parent.width - 16
            }
            IconButton {
                id: delBtn
                anchors.top: parent.top
                anchors.topMargin: 6
                anchors.right: parent.right
                anchors.rightMargin: 6
                icon_name: "trash"
                icon_px: 12
                // stroke uses the app-wide hairline cadence (no
                // opt-in) to match every other glyph
                implicitWidth: 22
                implicitHeight: 22
                ToolTip.text: qsTr("Delete palette")
                onClicked: colors !== null && colors.delete_palette(modelData.id)
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: Qt.PointingHandCursor
                onClicked: function (mouse) {
                    // left-click opens (inspector follows); right-click
                    // opens the menu for the CURRENTLY OPEN palette —
                    // the generator and inspector stay untouched
                    if (mouse.button !== Qt.LeftButton)
                        palMenu.popup();
                }
                z: -1
            }
        }
        Text {
            anchors.centerIn: parent
            visible: savedStrip.height > 0 && savedStrip.count === 0
            text: qsTr("No palettes yet")
            font.family: theme.uiFont
            font.pixelSize: 11
            color: theme.tokens.textMuted
        }
    }

    // editor strip for the selected swatch
    Rectangle {
        id: editorStrip
        height: colors !== null && colors.selectedIdx >= 0 ? 56 : 0
        visible: height > 0
        color: theme.tokens.surface
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 10
            visible: editorStrip.height > 0

            IconButton {
                icon_name: "chevron-left"
                ToolTip.text: qsTr("Move left")
                onClicked: colors !== null && colors.move_swatch(colors.selectedIdx, colors.selectedIdx - 1)
            }
            IconButton {
                icon_name: "chevron-right"
                ToolTip.text: qsTr("Move right")
                onClicked: colors !== null && colors.move_swatch(colors.selectedIdx, colors.selectedIdx + 1)
            }
            EditSlider {
                id: hSlider
                label: "H"
                maxVal: 360
                tip: qsTr("Hue — 0–360° around the color wheel")
                onEdited: val => applyHsl()
            }
            EditSlider {
                id: sSlider
                label: "S"
                maxVal: 100
                tip: qsTr("Saturation — 0 = gray, 100 = fully saturated")
                onEdited: val => applyHsl()
            }
            EditSlider {
                id: lSlider
                label: "L"
                maxVal: 100
                tip: qsTr("Lightness — 0 = black, 100 = white")
                onEdited: val => applyHsl()
            }

            Rectangle {
                Layout.preferredWidth: 90
                Layout.preferredHeight: 28
                radius: 6
                color: theme.tokens.surface2
                border.color: hexField.activeFocus ? theme.tokens.accent : theme.tokens.border
                TextInput {
                    id: hexField
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: theme.monoFont
                    font.pixelSize: 11
                    color: theme.tokens.text
                    clip: true
                    onAccepted: colors !== null && colors.selectedIdx >= 0 && colors.set_hex(colors.selectedIdx, text)
                }
            }
            IconButton {
                icon_name: "paint-drop"
                icon_px: 16
                ToolTip.text: qsTr("Open color picker")
                onClicked: {
                    if (colors === null || colors.selectedIdx < 0)
                        return
                    colorPickerDialog.openWith(colors.swatches[colors.selectedIdx].hex)
                }
            }
            Item {
                Layout.fillWidth: true
            }
            IconButton {
                icon_name: "x"
                ToolTip.text: qsTr("Close editor")
                onClicked: colors !== null && colors.select(colors.selectedIdx)
            }
        }
    }

    component EditSlider: RowLayout {
        property string label
        property string tip: ""
        property real val
        property real maxVal
        signal edited(real v)
        Text {
            text: parent.label
            font.family: theme.monoFont
            font.pixelSize: 10
            color: theme.tokens.textMuted
            MouseArea {
                id: hslTipArea
                anchors.fill: parent
                hoverEnabled: true
            }
            ToolTip.visible: parent.tip !== "" && hslTipArea.containsMouse
            ToolTip.delay: 350
            ToolTip.text: parent.tip
        }
        FgSlider {
            id: es
            Layout.preferredWidth: 140
            from: 0
            to: parent.maxVal
            value: parent.val
            // dragging breaks the value: parent.val binding (Qt
            // slider gotcha) — without this imperative assign,
            // applyHsl kept reading the STALE pre-drag val and the
            // swatch never changed: "the HSL sliders don't work"
            onMoved: {
                parent.val = value;
                parent.edited(value);
            }
        }
        Text {
            text: Math.round(parent.val)
            font.family: theme.monoFont
            font.pixelSize: 10
            color: theme.tokens.text
            Layout.preferredWidth: 26
        }
    }

    // the palette row: five swatch cards
    RowLayout {
        id: paletteRow
        spacing: 8
        anchors.top: genBar.bottom
        anchors.bottom: savedStrip.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 10

        Repeater {
            model: colors !== null ? colors.swatches : []

            Rectangle {
                id: swCard
                required property var modelData
                required property int index
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 10
                color: modelData.hex
                // DRAG-TO-REORDER: the card body is grabbable — open-hand
                // cursor on hover is the standard "can drag" indicator,
                // closed-hand while dragging; the card lifts (z + translate)
                // and snaps to the slot under the drop point on release.
                transform: Translate {
                    x: swMa.dragging ? swMa.dragDX : 0
                    Behavior on x {
                        NumberAnimation {
                            duration: 40
                        }
                    }
                }
                z: swMa.dragging ? 3 : 0
                border.color: swMa.dragging ? theme.tokens.accent : (colors !== null && colors.selectedIdx === swCard.index ? theme.tokens.litPane : "transparent")
                border.width: 2

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 12
                    spacing: 2
                    Text {
                        text: modelData.hex.toUpperCase()
                        font.family: theme.monoFont
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        color: modelData.ink
                    }
                    Text {
                        text: modelData.name
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: modelData.ink
                        opacity: 0.75
                    }
                    Text {
                        text: "C/W " + modelData.cw.toFixed(1) + " " + modelData.wcagW + " · C/B " + modelData.cb.toFixed(1) + " " + modelData.wcagB
                        font.family: theme.monoFont
                        font.pixelSize: 9
                        color: modelData.ink
                        opacity: 0.7
                    }
                }

                Row {
                    id: tools
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    spacing: 4
                    // z ABOVE the card's selection MouseArea (declared after
                    // it in sibling order, swMa would otherwise eat every
                    // click aimed at the lock/remove buttons).
                    //
                    // ALWAYS visible: per the interaction rule, anything
                    // rendered and interactive performs its primary function
                    // on engagement — the lock/✕ chips must not depend on
                    // hover or prior swatch selection (hover-only reveal
                    // proved fragile in QT6 and hid the affordance).
                    z: 2
                    SwTool {
                        icon_name: swCard.modelData.locked ? "lock" : "unlock"
                        // locked state is tinted amber so it reads even at
                        // a glance — but only when amber contrasts with the
                        // swatch (#25: amber on Wheat was ~1.1:1); the tint
                        // falls back to the swatch's best ink. The other
                        // tool glyphs use best ink too (hardcoded white was
                        // invisible on pale swatches)
                        tint: swCard.modelData.locked ? swCard.modelData.lock_ink : swCard.modelData.ink
                        ToolTip.visible: hovered
                        ToolTip.delay: 350
                        ToolTip.text: swCard.modelData.locked ? qsTr("Locked — this color stays fixed when Generate runs (click to unlock)") : qsTr("Lock this color so it stays fixed when Generate runs")
                        onClicked: colors !== null && colors.toggle_lock(swCard.index)
                    }
                    SwTool {
                        icon_name: "x"
                        tint: swCard.modelData.ink
                        ToolTip.visible: hovered
                        ToolTip.delay: 350
                        ToolTip.text: qsTr("Remove this swatch from the palette")
                        onClicked: colors !== null && colors.remove_swatch(swCard.index)
                    }
                }

                MouseArea {
                    id: swMa
                    anchors.fill: parent
                    hoverEnabled: true
                    // standard drag indicators: open hand = grabbable,
                    // closed hand = dragging
                    cursorShape: swMa.dragging ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                    property bool dragging: false
                    property real pressX: 0
                    property real dragDX: 0
                    onPressed: function (mouse) {
                        pressX = mouse.x;
                        dragDX = 0;
                        dragging = false;
                    }
                    onPositionChanged: function (mouse) {
                        if (!pressed)
                            return;
                        dragDX = mouse.x - pressX;
                        if (!dragging && Math.abs(dragDX) > 8)
                            dragging = true;
                    }
                    onReleased: {
                        // one reorder per gesture, on release — calling
                        // move_swatch mid-drag would recreate the delegates
                        // and drop the mouse grab
                        if (dragging && colors !== null) {
                            var n = colors.swatches.length;
                            var slot = (paletteRow.width - 8 * (n - 1)) / n;
                            var target = swCard.index + Math.round(dragDX / (slot + 8));
                            target = Math.max(0, Math.min(n - 1, target));
                            if (target !== swCard.index)
                                colors.move_swatch(swCard.index, target);
                        }
                        dragging = false;
                        dragDX = 0;
                    }
                    onClicked: colors !== null && colors.select(swCard.index)
                }
            }
        }

        // add-swatch tile — schemes default to 5 colors and accept up to 7;
        // disabled (invisible) once the scheme is full
        Rectangle {
            id: addSwatchTile
            visible: colors !== null && colors.swatches.length < 7
            Layout.preferredWidth: 44
            Layout.fillHeight: true
            radius: 10
            color: addSwatchMa.containsMouse ? theme.tokens.surface2 : theme.tokens.surface
            border.color: addSwatchMa.containsMouse ? theme.tokens.accentColor : theme.tokens.border
            border.width: 1
            IconImage {
                name: "plus"
                px: 18
                anchors.centerIn: parent
                tint: theme.tokens.textMuted
            }
            Text {
                anchors.top: parent.verticalCenter
                anchors.topMargin: 8
                anchors.horizontalCenter: parent.horizontalCenter
                text: (colors !== null ? colors.swatches.length : 0) + "/7"
                font.family: theme.monoFont
                font.pixelSize: 9
                color: theme.tokens.textMuted
            }
            MouseArea {
                id: addSwatchMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: colors !== null && colors.add_swatch()
            }
        }
    }

    component SwTool: AbstractButton {
        id: st
        property string icon_name
        property color tint: "#FFFFFF"
        width: 20
        height: 20
        contentItem: IconImage {
            name: st.icon_name
            // #97: glyph stays at its native 16px render
            // (no scaling either way); the chip shrinks
            // to 20px — 2px breathing room per side.
            // Stroke uses the app-wide hairline cadence
            // (no opt-in) to match every other
            // interface glyph.
            px: 16
            tint: st.tint
            anchors.centerIn: parent
        }
        background: Rectangle {
            radius: 6
            // theme-token scrims (hardcoded overlays broke
            // light-theme parity)
            color: st.hovered ? theme.tokens.scrim : theme.tokens.scrimSoft
        }
    }

    // space = reroll (only when this pane is visible and no field is in edit)
    Shortcut {
        sequence: "Space"
        enabled: colorsRoot.visible && !nameField.activeFocus && !tagsField.activeFocus && !hexField.activeFocus && !Shell.overlayOpen
        onActivated: colors !== null && colors.generate()
    }

    // saved-palette context menu
    Menu {
        id: palMenu
        property var target: null
        width: 190
        padding: 4
        background: Rectangle {
            radius: 8
            color: theme.tokens.surface
            border.color: theme.tokens.border
        }
        FgMenuItem {
            // acts on the CURRENTLY OPEN palette (left-click loads a
            // palette into the generator — right-click never does)
            text: qsTr("Export…")
            height: 28
            enabled: colors !== null && colors.paletteId > 0
            onTriggered: {
                colorExport.openWith([
                    {
                        id: "css",
                        label: "CSS"
                    },
                    {
                        id: "json",
                        label: "JSON"
                    },
                    {
                        id: "svg",
                        label: "SVG board"
                    },
                    {
                        id: "png",
                        label: "PNG board"
                    }
                ], colorsRoot.exportDest);
                colorExport.selectedFormats = ["css"];
            }
        }
        FgMenuItem {
            text: qsTr("Star / Unstar")
            height: 28
            enabled: colors !== null && colors.paletteId > 0 && library !== null
            onTriggered: library.star_item("palette", colors.paletteId, !library.is_item_starred("palette", colors.paletteId))
        }
        FgMenuItem {
            text: qsTr("Add to collection…")
            height: 28
            enabled: colors !== null && colors.paletteId > 0 && library !== null && library.collections.length > 0
            Menu {
                id: palCollSub
                cascade: true
                width: 220
                padding: 4
                background: Rectangle {
                    radius: 8
                    color: theme.tokens.surface
                    border.color: theme.tokens.border
                }
                Repeater {
                    model: library !== null ? library.collections : []
                    FgMenuItem {
                        id: palCollTarget
                        required property var modelData
                        height: 28
                        onTriggered: library !== null && colors !== null && library.add_item_to_collection(modelData.id, "palette", colors.paletteId, colors.paletteName)
                        contentItem: Text {
                            text: palCollTarget.modelData.name
                            font.family: theme.uiFont
                            font.pixelSize: 11
                            color: theme.tokens.text
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 10
                        }
                        background: Rectangle {
                            color: palCollTarget.hovered ? theme.tokens.surface2 : "transparent"
                            radius: 5
                        }
                    }
                }
            }
        }
        FgMenuSeparator {
            topPadding: 3
            bottomPadding: 3
            contentItem: Rectangle {
                implicitHeight: 1
                color: theme.tokens.border
            }
        }
        FgMenuItem {
            text: qsTr("Delete palette")
            height: 28
            // acts on the OPEN palette (per the shared rule: the menu
            // targets the current selection); each row also has its own
            // delete button for direct deletion
            enabled: colors !== null && colors.paletteId > 0
            onTriggered: colors.delete_palette(colors.paletteId)
        }
    }

    // Terminal designer overlay — covers everything below the toolbar when
    // the Terminal sub-tab is active (the harmony UI stays mounted beneath)
    TerminalTab {
        anchors.top: genBar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        visible: colorsRoot.termMode
        z: 2

        // opaque backdrop so the harmony generator never bleeds through
        Rectangle {
            anchors.fill: parent
            color: theme.tokens.bg
            z: -1
        }
    }
}
