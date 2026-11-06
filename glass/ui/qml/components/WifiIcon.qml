import QtQuick
import QtQuick.Window

// Wi-Fi strength (0-5 bars from Windows mapped onto 3 arcs), ethernet, or offline.
Item {
    id: root
    property int bars: 4
    property string kind: "wifi"       // wifi | ethernet | cellular | none
    property bool internet: true
    property color color: glass.theme.text
    property real size: 18
    width: size; height: size
    readonly property int level: bars >= 4 ? 3 : bars >= 2 ? 2 : bars >= 1 ? 1 : 0
    readonly property int px: Math.ceil(size * Screen.devicePixelRatio)

    Image {
        visible: root.kind === "wifi" || root.kind === "none"
        anchors.fill: parent
        sourceSize: Qt.size(root.px, root.px)
        source: "image://glyph/wifi/" + root.level + "/" + root.kind + "/" + encodeURIComponent(root.color.toString())
        smooth: true
    }
    Icon {
        visible: root.kind === "ethernet" || root.kind === "cellular"
        anchors.centerIn: parent
        name: root.kind === "ethernet" ? "ethernet" : "globe"
        size: root.size
        color: root.color
    }
    Rectangle {
        visible: root.kind !== "none" && !root.internet
        width: root.size * 0.42; height: width; radius: width / 2
        anchors.right: parent.right; anchors.bottom: parent.bottom
        color: glass.theme.warning
        Text { anchors.centerIn: parent; text: "!"; color: "white"; font.pixelSize: parent.width * 0.8; font.bold: true }
    }
}
