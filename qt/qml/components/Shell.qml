pragma Singleton
import QtQuick

// Shared shell state for components that cannot reach Main.qml's ids:
// true while a full-surface overlay (Settings or first-run setup) is
// open. Pane shortcuts are window-scoped, so `Space`/`Ctrl+S` in the
// Colors/Code panes would otherwise keep firing while the user types
// in an overlay's search field (regenerating a palette mid-word).
QtObject {
    property bool overlayOpen: false
    property bool paletteOpen: false
    property bool capturing: false
}
