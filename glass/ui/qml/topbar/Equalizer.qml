import QtQuick

// Four accent bars moving while media plays (still when paused or with reduced motion). The bars are driven by
// render-thread animators, so playing music never keeps the UI thread busy.
Row {
    id: root
    property bool playing: true
    property color color: glass.theme.accent
    property real barHeight: 12
    spacing: 2
    height: barHeight
    Repeater {
        model: 4
        Item {
            width: 2.6; height: root.barHeight
            clip: true
            Rectangle {
                id: bar
                width: parent.width; height: root.barHeight; radius: 1.3
                color: root.color
                y: root.barHeight * 0.65
                readonly property var lows: [0.62, 0.30, 0.55, 0.40]
                readonly property var highs: [0.08, 0.22, 0.04, 0.18]
                SequentialAnimation {
                    running: root.playing && !glass.theme.reduce_motion && root.visible
                    loops: Animation.Infinite
                    YAnimator { target: bar; to: root.barHeight * bar.highs[index]; duration: [380, 300, 420, 340][index]; easing.type: Easing.InOutSine }
                    YAnimator { target: bar; to: root.barHeight * bar.lows[index]; duration: [320, 360, 280, 400][index]; easing.type: Easing.InOutSine }
                    YAnimator { target: bar; to: root.barHeight * [0.25, 0.5, 0.12, 0.55][index]; duration: [300, 420, 360, 300][index]; easing.type: Easing.InOutSine }
                    onRunningChanged: if (!running) bar.y = root.barHeight * 0.65
                }
            }
        }
    }
}
