import QtQuick
import "../components"

// A thin slider row bound to a numeric setting, with a value readout.
Row_ {
    id: r
    property string key: ""
    property real from: 0
    property real to: 1
    property real step: 0.01
    property bool percent: true
    property string unit: ""
    property real sliderWidth: 220
    readonly property real v: cc.settings[key] !== undefined ? cc.settings[key] : from
    Row {
        spacing: 12
        Item {
            id: track
            width: r.sliderWidth; height: 24
            readonly property real t: (r.v - r.from) / (r.to - r.from)
            Accessible.role: Accessible.Slider
            Accessible.name: r.title
            Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 4; radius: 2; color: glass.theme.track
                Rectangle { width: parent.width * track.t; height: 4; radius: 2; color: glass.theme.accent } }
            Rectangle {
                x: track.t * (track.width - width); anchors.verticalCenter: parent.verticalCenter
                width: 20; height: 20; radius: 10; color: "white"
                border.width: 1; border.color: glass.theme.dark ? "transparent" : "#22000000"
                Rectangle { anchors.fill: parent; anchors.margins: -3; radius: 13; color: "transparent"; border.width: 3
                            border.color: Qt.rgba(glass.theme.accent.r, glass.theme.accent.g, glass.theme.accent.b, ma.pressed ? 0.35 : 0) }
            }
            MouseArea {
                id: ma; anchors.fill: parent; preventStealing: true
                function val(mx) {
                    var t = Math.max(0, Math.min(1, (mx - 10) / (track.width - 20)))
                    var raw = r.from + t * (r.to - r.from)
                    return Math.round(raw / r.step) * r.step
                }
                onPressed: (e) => cc.set(r.key, val(e.x))
                onPositionChanged: (e) => { if (pressed) cc.set(r.key, val(e.x)) }
                onWheel: (w) => cc.set(r.key, Math.max(r.from, Math.min(r.to, r.v + (w.angleDelta.y > 0 ? r.step : -r.step) * (r.percent ? 5 : 1))))
            }
        }
        Label {
            width: 52; anchors.verticalCenter: parent.verticalCenter; horizontalAlignment: Text.AlignRight
            role: "callout"; secondary: true; font.features: { "tnum": 1 }
            text: r.percent ? Math.round(r.v * 100) + "%" : (r.step < 1 ? r.v.toFixed(2) : Math.round(r.v)) + r.unit
        }
    }
}
