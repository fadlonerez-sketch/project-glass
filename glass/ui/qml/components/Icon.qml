import QtQuick
import QtQuick.Window

// A glyph from the Project Glass icon set (vector paths in Glyphs.js), rasterised by the glyph provider at
// the exact device pixel size so it stays crisp at any DPI and recolours reliably on theme changes.
Image {
    id: root
    property string name: ""
    property color color: glass.theme.text
    property real size: 18
    property real strokeWidth: 1.7
    width: size
    height: size
    visible: name !== ""
    readonly property int px: Math.ceil(size * Screen.devicePixelRatio)
    sourceSize: Qt.size(px, px)
    source: name === "" ? "" : "image://glyph/icon/" + name + "/" + encodeURIComponent(color.toString()) + "/" + strokeWidth
    smooth: true
    cache: true
    asynchronous: false
}
