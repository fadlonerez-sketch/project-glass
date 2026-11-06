import QtQuick
import QtQuick.Window

// Colour weather glyphs (original artwork): clear, partly, cloudy, fog, drizzle, rain, heavy_rain, sleet,
// snow, thunder -- with night variants for clear/partly.
Image {
    id: root
    property string kind: "clear"
    property bool day: true
    property real size: 32
    width: size; height: size
    readonly property int px: Math.ceil(size * Screen.devicePixelRatio)
    sourceSize: Qt.size(px, px)
    source: "image://glyph/weather/" + (kind || "cloudy") + "/" + (day ? 1 : 0) + "/" + (glass.theme.dark ? 1 : 0)
    smooth: true
}
