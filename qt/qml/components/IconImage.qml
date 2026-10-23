import QtQuick
import "."

Image {
    property string name
    property color tint: "#E7EDF2"
    property int px: 16

    width: px
    height: px
    source: Icons.url(name, tint)
    sourceSize.width: px * 2
    sourceSize.height: px * 2
    smooth: true
}
