import QtQuick
import "."

Image {
    id: glyph
    property string name
    property color tint: "#E7EDF2"
    property int px: 16

    width: px
    height: px
    source: Icons.url(name, tint, "none", px)
    // rasterize at the EXACT device-pixel size. The old px*2 raster +
    // bilinear downscale halved the hairline stroke into sub-pixel
    // fuzz (the "fuzzy plus icon" report). Screen.devicePixelRatio is
    // 1 on standard desktops, 2 on hidpi — either way the raster
    // matches what the scene graph draws 1:1, no resampling.
    sourceSize.width: px * (Screen.devicePixelRatio || 1)
    sourceSize.height: px * (Screen.devicePixelRatio || 1)
    smooth: true
    mipmap: false
}
