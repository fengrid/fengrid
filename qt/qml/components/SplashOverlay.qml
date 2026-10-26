import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Launch splash: shows itself while a scan runs on a still-empty
// database (first run, post-setup relaunch, watch-folder ingestion into
// a fresh DB) — it owns the session: no gating snapshot from Main, so
// the splash opens whenever the condition is actually met, however late
// the scan is scheduled (#34). A rescan of a populated library never
// opens it, so manual rescans keep the shell quiet. Auto-hides when the
// scans go quiet. Deliberately NON-MODAL: no MouseArea, so clicks pass
// through to the shell; this informs, it does not block. Live status =
// current path under the scanner + per-scan counts against a
// pre-counted total (indeterminate until `scanTotal` arrives). QA
// `force` shows both rows with demo numbers (--dialog splash).
Item {
    id: splash
    anchors.fill: parent
    visible: shown

    property bool force: false
    // session state — opened by the Connections below, closed when the
    // scans go quiet. `shown` = session && anyScan.
    property bool session: false
    readonly property bool anyScan:
        (typeof library !== "undefined" && library !== null
         && library.scanning)
        || (typeof fonts !== "undefined" && fonts !== null && fonts.scanning)
    readonly property bool shown: force
                                  || (session && anyScan)

    Connections {
        target: library
        function onScanningChanged() {
            if (library.scanning && library.totalAssets === 0)
                splash.session = true
        }
        function onScanFinished() {
            if (!fonts.scanning)
                splash.session = false
        }
    }
    Connections {
        target: fonts
        function onScanningChanged() {
            if (fonts.scanning && fonts.totalFonts === 0)
                splash.session = true
        }
        function onScanFinished() {
            if (!library.scanning)
                splash.session = false
        }
    }

    // soft scrim — visual only, input falls through to the app
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.35)
    }

    Rectangle {   // centre card
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 460)
        height: cardCol.implicitHeight + 40
        radius: 12
        color: theme.tokens.surface
        border.color: theme.tokens.accent
        border.width: 1

        ColumnLayout {
            id: cardCol
            anchors.fill: parent
            anchors.margins: 20
            spacing: 6

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "FENGRID"
                font.family: theme.monoFont
                font.pixelSize: 13
                font.letterSpacing: 6
                color: theme.tokens.text
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 2
                text: qsTr("Preparing your library…")
                font.family: theme.uiFont
                font.pixelSize: 14
                color: theme.tokens.text
            }

            // live status line: latest file under the scanner
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 8
                visible: splash.shown
                text: splash.force
                      ? qsTr("scanning /usr/share/icons/hicolor/48x48/…")
                      : (library !== null && library.scanning
                         && library.scanPath !== ""
                         ? library.scanPath
                         : qsTr("discovering asset folders…"))
                font.family: theme.monoFont
                font.pixelSize: 10
                color: theme.tokens.textMuted
                elide: Text.ElideMiddle
                horizontalAlignment: Text.AlignHCenter
            }

            // ── icons & folders row ──
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 14
                spacing: 4
                visible: splash.force
                         || (library !== null && library.scanning)
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("Icons & folders")
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        color: theme.tokens.text
                    }
                    Text {
                        text: {
                            var done = splash.force ? 1337
                                      : (library !== null ? library.scanCount : 0)
                            var tot = splash.force ? 8000
                                      : (library !== null ? library.scanTotal : 0)
                            return tot > 0 ? qsTr("%1 / %2 files").arg(done).arg(tot)
                                           : qsTr("%1 files").arg(done)
                        }
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                }
                ProgressBar {
                    id: iconBar
                    Layout.fillWidth: true
                    Layout.preferredHeight: 6
                    from: 0
                    to: {
                        var tot = splash.force ? 8000
                                  : (library !== null ? library.scanTotal : 0)
                        return tot > 0 ? tot : 1
                    }
                    value: {
                        var done = splash.force ? 1337
                                  : (library !== null ? library.scanCount : 0)
                        return Math.min(done, to)
                    }
                    indeterminate: to <= 1
                    background: Rectangle {
                        radius: 3
                        color: theme.tokens.surface2
                    }
                    contentItem: Item {
                        clip: true
                        Rectangle {   // determinate fill
                            visible: !iconBar.indeterminate
                            height: parent.height
                            width: iconBar.visualPosition * parent.width
                            radius: 3
                            color: theme.tokens.accent
                        }
                        Rectangle {   // indeterminate sweep
                            visible: iconBar.indeterminate
                            height: parent.height
                            width: Math.max(40, parent.width * 0.3)
                            radius: 3
                            color: theme.tokens.accent
                            SequentialAnimation on x {
                                running: iconBar.indeterminate
                                         && iconBar.visible
                                loops: Animation.Infinite
                                NumberAnimation {
                                    from: -80
                                    to: iconBar.width
                                    duration: 900
                                    easing.type: Easing.InOutQuad
                                }
                                NumberAnimation {
                                    from: iconBar.width
                                    to: -80
                                    duration: 900
                                    easing.type: Easing.InOutQuad
                                }
                            }
                        }
                    }
                }
            }

            // ── fonts row ──
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 10
                spacing: 4
                visible: splash.force
                         || (fonts !== null && fonts.scanning)
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("Fonts")
                        font.family: theme.uiFont
                        font.pixelSize: 12
                        color: theme.tokens.text
                    }
                    Text {
                        text: {
                            var done = splash.force ? 274
                                      : (fonts !== null ? fonts.scanCount : 0)
                            var tot = splash.force ? 900
                                      : (fonts !== null ? fonts.scanTotal : 0)
                            return tot > 0 ? qsTr("%1 / %2 files").arg(done).arg(tot)
                                           : qsTr("%1 files").arg(done)
                        }
                        font.family: theme.monoFont
                        font.pixelSize: 10
                        color: theme.tokens.textMuted
                    }
                }
                ProgressBar {
                    id: fontBar
                    Layout.fillWidth: true
                    Layout.preferredHeight: 6
                    from: 0
                    to: {
                        var tot = splash.force ? 900
                                  : (fonts !== null ? fonts.scanTotal : 0)
                        return tot > 0 ? tot : 1
                    }
                    value: {
                        var done = splash.force ? 274
                                  : (fonts !== null ? fonts.scanCount : 0)
                        return Math.min(done, to)
                    }
                    indeterminate: to <= 1
                    background: Rectangle {
                        radius: 3
                        color: theme.tokens.surface2
                    }
                    contentItem: Item {
                        clip: true
                        Rectangle {
                            visible: !fontBar.indeterminate
                            height: parent.height
                            width: fontBar.visualPosition * parent.width
                            radius: 3
                            color: theme.tokens.accentFont
                        }
                        Rectangle {
                            visible: fontBar.indeterminate
                            height: parent.height
                            width: Math.max(40, parent.width * 0.3)
                            radius: 3
                            color: theme.tokens.accentFont
                            SequentialAnimation on x {
                                running: fontBar.indeterminate
                                         && fontBar.visible
                                loops: Animation.Infinite
                                NumberAnimation {
                                    from: -80
                                    to: fontBar.width
                                    duration: 900
                                    easing.type: Easing.InOutQuad
                                }
                                NumberAnimation {
                                    from: fontBar.width
                                    to: -80
                                    duration: 900
                                    easing.type: Easing.InOutQuad
                                }
                            }
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 14
                Layout.alignment: Qt.AlignHCenter
                text: qsTr("Assets appear as they are indexed — you can start browsing now. Next launch is instant.")
                font.family: theme.uiFont
                font.pixelSize: 11
                color: theme.tokens.textMuted
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
}