import QtQuick

// A thick, rounded slider (Control Center style): the fill carries an optional icon, dragging is direct.
Item {
    id: root
    property real value: 0.5          // 0..1
    property string icon: ""
    property Component iconComponent: null
    property real thickness: 28
    property bool enabled: true
    property bool live: true          // emit moved continuously while dragging
    property string accessibleName: "Slider"
    signal moved(real value)
    implicitWidth: 220
    implicitHeight: thickness
    height: thickness
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.Slider
    Accessible.name: accessibleName
    property real _shown: area.pressed ? _drag : value
    property real _drag: value

    Rectangle {
        id: track
        anchors.fill: parent
        radius: height / 2
        color: glass.theme.track
        clip: true
        Rectangle {
            width: Math.max(track.height, track.width * root._shown)
            height: parent.height
            radius: track.radius
            color: glass.theme.dark ? "#F2F2F5" : "#FFFFFF"
            border.width: glass.theme.dark ? 0 : 1
            border.color: glass.theme.hairline
            Behavior on width { enabled: !area.pressed; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        }
    }
    Icon {
        visible: root.icon !== ""
        x: (track.height - size) / 2
        anchors.verticalCenter: parent.verticalCenter
        name: root.icon
        size: root.thickness * 0.55
        color: "#5A5A64"
    }
    Loader {
        active: root.iconComponent !== null
        sourceComponent: root.iconComponent
        x: (track.height - (item ? item.width : 0)) / 2
        anchors.verticalCenter: parent.verticalCenter
    }
    MouseArea {
        id: area
        anchors.fill: parent
        enabled: root.enabled
        preventStealing: true
        function at(mx) { return Math.max(0, Math.min(1, mx / width)) }
        onPressed: (e) => { root._drag = at(e.x); if (root.live) root.moved(root._drag) }
        onPositionChanged: (e) => { if (pressed) { root._drag = at(e.x); if (root.live) root.moved(root._drag) } }
        onReleased: (e) => { root._drag = at(e.x); root.moved(root._drag) }
        onWheel: (w) => { root.moved(Math.max(0, Math.min(1, root.value + (w.angleDelta.y > 0 ? 0.04 : -0.04)))) }
    }
}
