import QtQuick
import QtQuick.Window

Image {
    id: root
    property real level: 0.5
    property bool muted: false
    property color color: glass.theme.text
    property real size: 18
    width: size; height: size
    readonly property int px: Math.ceil(size * Screen.devicePixelRatio)
    sourceSize: Qt.size(px, px)
    // Quantise the level so the glyph only re-renders when its wave count changes.
    source: "image://glyph/speaker/" + (level > 0.5 ? 1 : level > 0.01 ? 0.3 : 0) + "/" + (muted ? 1 : 0) + "/" + encodeURIComponent(color.toString())
    smooth: true
}
