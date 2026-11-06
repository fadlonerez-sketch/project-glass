import QtQuick

Item {
    id: root
    property bool checked: false
    property bool enabled: true
    property string accessibleName: "Toggle"
    signal toggled(bool checked)
    width: 40; height: 24
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.CheckBox
    Accessible.name: accessibleName
    Accessible.checkable: true
    Accessible.checked: checked
    Accessible.onToggleAction: if (enabled) root.toggled(!checked)

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.checked ? glass.theme.accent : glass.theme.track
        Behavior on color { ColorAnimation { duration: 160 } }
        Rectangle {
            width: parent.height - 4; height: width; radius: width / 2
            y: 2
            x: root.checked ? parent.width - width - 2 : 2
            color: "white"
            Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutBack; easing.overshoot: 1.2 } }
        }
    }
    MouseArea { anchors.fill: parent; enabled: root.enabled; onClicked: root.toggled(!root.checked) }
}
