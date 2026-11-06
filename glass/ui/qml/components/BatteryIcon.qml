import QtQuick

// Battery outline with a live fill; green while charging, red when low, a bolt when charging.
Item {
    id: root
    property int percent: 100
    property bool charging: false
    property bool plugged: false
    property bool saver: false
    property color color: glass.theme.text
    property real size: 18
    width: size * 1.45; height: size * 0.72
    readonly property color fillColor: charging ? glass.theme.success
                                       : percent <= 10 ? glass.theme.danger
                                       : saver ? glass.theme.warning : color

    Rectangle {
        id: body
        width: parent.width - root.size * 0.12; height: parent.height
        radius: height * 0.3
        color: "transparent"
        border.width: Math.max(1, root.size * 0.07)
        border.color: Qt.rgba(root.color.r, root.color.g, root.color.b, 0.45)
        Rectangle {
            x: body.border.width + 1.2; y: body.border.width + 1.2
            height: parent.height - 2 * y
            width: Math.max(1.5, (parent.width - 2 * x) * Math.max(0, Math.min(100, root.percent)) / 100)
            radius: height * 0.28
            color: root.fillColor
            Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
        }
    }
    Rectangle {
        anchors.left: body.right; anchors.leftMargin: root.size * 0.03
        anchors.verticalCenter: body.verticalCenter
        width: root.size * 0.08; height: body.height * 0.36; radius: width / 2
        color: Qt.rgba(root.color.r, root.color.g, root.color.b, 0.45)
    }
    Icon {
        visible: root.charging || root.plugged
        anchors.centerIn: body
        name: root.charging ? "bolt" : "plug"
        size: root.size * 0.78
        color: glass.theme.dark ? "white" : "#111114"
    }
}
