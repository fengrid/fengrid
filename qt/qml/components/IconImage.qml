import QtQuick
import "."

Image {
    id: glyph
    property string name
    property color tint: "#E7EDF2"
    property int px: 16

    width: px
    height: px
    // filled Qlementine silhouettes: the tint rides in the SVG root
    // fill (see Icons.qml); no stroke/minStroke machinery anymore.
    source: Icons.url(name, tint, "none", px, Screen.devicePixelRatio || 1)
    // rasterize at the EXACT device-pixel size: the declared intrinsic
    // raster (#97 rule) is 1:1 with what the scene graph draws — no
    // resampling at any zoom or dpr.
    sourceSize.width: px * (Screen.devicePixelRatio || 1)
    sourceSize.height: px * (Screen.devicePixelRatio || 1)
    smooth: true
    mipmap: false
}
