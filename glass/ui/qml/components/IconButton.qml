import QtQuick

// Circular icon button with a soft hover/press fill. Fully keyboard/UIA accessible.
Item {
    id: root
    property string icon: ""
    property real size: 30
    property real iconSize: 16
    property color color: glass.theme.text
    property color hoverFill: glass.theme.control_hover
    property bool filled: false
    property color fill: glass.theme.control
    property string tooltip: ""
    signal clicked()
    width: size; height: size
    Accessible.role: Accessible.Button
    Accessible.name: tooltip || icon
    Accessible.onPressAction: root.clicked()

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: area.pressed ? glass.theme.control_pressed : area.containsMouse ? root.hoverFill : (root.filled ? root.fill : "transparent")
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    Icon {
        anchors.centerIn: parent
        name: root.icon
        size: root.iconSize
        color: root.color
        scale: area.pressed ? 0.88 : 1.0
        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        onClicked: root.clicked()
    }
}
