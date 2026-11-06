import QtQuick
import "../components"

// Playback progress, interpolated locally between timeline events (no polling of the player).
// Only repaints every quarter second while playing -- never a 120 Hz animation at idle.
Item {
    id: root
    property var media: glass.media
    property bool light: true          // on the deep pill
    property real now: Date.now() / 1000
    readonly property real duration: media.duration || 0
    readonly property real position: {
        now
        if (!duration) return 0
        var p = media.position || 0
        if (media.playing && media.position_updated)
            p += (Date.now() / 1000 - media.position_updated) * (media.rate || 1)
        return Math.max(0, Math.min(duration, p))
    }
    implicitHeight: 24
    Timer { interval: 250; repeat: true; running: root.visible && root.media.playing && root.duration > 0
            onTriggered: root.now = Date.now() / 1000 }

    Rectangle {
        id: track
        y: 2
        width: parent.width; height: 4; radius: 2
        color: root.light ? Qt.rgba(1, 1, 1, 0.18) : glass.theme.track
        Rectangle {
            width: root.duration > 0 ? parent.width * root.position / root.duration : 0
            height: parent.height; radius: 2
            color: root.light ? "white" : glass.theme.accent
        }
        MouseArea {
            anchors.fill: parent; anchors.margins: -6
            enabled: !!root.media.can_seek && root.duration > 0
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: (e) => glass.seek(Math.max(0, Math.min(1, (e.x - 6) / track.width)) * root.duration)
        }
    }
    Label { anchors.left: parent.left; y: 10; role: "micro"; color: root.light ? Qt.rgba(1, 1, 1, 0.6) : glass.theme.text3
            text: glass.formatDuration(root.position); visible: root.duration > 0 }
    Label { anchors.right: parent.right; y: 10; role: "micro"; color: root.light ? Qt.rgba(1, 1, 1, 0.6) : glass.theme.text3
            text: "-" + glass.formatDuration(root.duration - root.position); visible: root.duration > 0 }
}
