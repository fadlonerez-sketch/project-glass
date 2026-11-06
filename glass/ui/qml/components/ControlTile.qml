import QtQuick

// A rounded tile in the expanded control panel. `active` paints it with the accent (like an "on" toggle).
Item {
    id: root
    property string icon: ""
    property string title: ""
    property string subtitle: ""
    property bool active: false
    property bool showChevron: false
    property bool enabled: true
    signal clicked()
    signal chevronClicked()
    implicitHeight: 54
    opacity: enabled ? 1 : 0.5
    Accessible.role: Accessible.Button
    Accessible.name: title + (subtitle ? ", " + subtitle : "")
    Accessible.onPressAction: root.clicked()

    Rectangle {
        anchors.fill: parent
        radius: 16
        color: area.pressed ? glass.theme.control_pressed : area.containsMouse ? glass.theme.control_hover : glass.theme.control
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    Rectangle {
        id: badge
        x: 10; anchors.verticalCenter: parent.verticalCenter
        width: 32; height: 32; radius: 16
        color: root.active ? glass.theme.accent : glass.theme.track
        Behavior on color { ColorAnimation { duration: 160 } }
        Icon { anchors.centerIn: parent; name: root.icon; size: 17; color: root.active ? glass.theme.on_accent : glass.theme.text }
    }
    Column {
        anchors.left: badge.right; anchors.leftMargin: 10
        anchors.right: chev.left; anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        spacing: 1
        Label { width: parent.width; role: "callout"; font.weight: Font.DemiBold; text: root.title }
        Label { width: parent.width; role: "caption"; secondary: true; text: root.subtitle; visible: text !== "" }
    }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; enabled: root.enabled; onClicked: root.clicked() }
    IconButton {
        id: chev
        visible: root.showChevron
        width: visible ? 28 : 0
        anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
        icon: "chevron-right"; iconSize: 14; size: 28; color: glass.theme.text2
        onClicked: root.chevronClicked()
    }
}
