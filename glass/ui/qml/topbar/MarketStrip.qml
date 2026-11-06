import QtQuick
import "../components"

// A quiet row of tickers beside the Dynamic Glass. Each ticker has a fixed width so changing prices never nudge
// the layout. Tickers that don't fit are left out from the outer end. Stale or failed quotes are dimmed and never
// styled as live; the status chip says exactly how fresh the numbers are.
Item {
    id: strip
    property var entries: []
    property bool alignRight: false          // true: grows leftwards from its right edge (the left side of the pill)
    property real maxWidth: 400
    property bool sparklines: true
    property bool showStatus: false
    property string statusKind: ""
    property string statusText: ""
    property real barHeight: 32
    signal hoveredEntry(var entry, Item item)
    signal unhovered()
    readonly property real tickW: sparklines ? 156 : 118
    readonly property real gap: 6
    readonly property real chipW: showStatus && statusText !== "" ? chip.implicitWidth + 18 : 0
    readonly property int fit: Math.max(0, Math.min(entries.length, Math.floor((maxWidth - chipW + gap) / (tickW + gap))))
    width: fit * (tickW + gap) - (fit ? gap : 0) + (chipW ? chipW + gap : 0)
    height: barHeight

    Row {
        id: row
        layoutDirection: strip.alignRight ? Qt.RightToLeft : Qt.LeftToRight
        anchors.fill: parent
        spacing: strip.gap
        Repeater {
            model: strip.entries.slice(0, strip.fit)
            Item {
                id: tick
                readonly property var e: modelData
                readonly property bool has: e.price !== null && e.price !== undefined
                readonly property bool up: (e.change || 0) >= 0
                readonly property bool weak: e.status === "stale" || e.status === "error" || !has
                readonly property color moveColor: !has || e.change === null ? glass.theme.text3
                                                  : up ? glass.theme.success : glass.theme.danger
                width: strip.tickW; height: strip.barHeight
                opacity: weak ? 0.55 : 1
                Behavior on opacity { NumberAnimation { duration: 300 } }
                Accessible.role: Accessible.StaticText
                Accessible.name: e.name + (has ? ", " + e.price.toFixed(2) + ", " + (up ? "up " : "down ") + Math.abs(e.changePct || 0).toFixed(2) + " percent, " + e.statusLabel : ", unavailable")

                Rectangle {
                    anchors.fill: parent; anchors.topMargin: 4; anchors.bottomMargin: 4
                    radius: height / 2
                    color: th.hovered ? glass.theme.control_hover : "transparent"
                    Behavior on color { ColorAnimation { duration: 140 } }
                }
                Label {
                    id: sym
                    x: 8; anchors.verticalCenter: parent.verticalCenter
                    width: strip.sparklines ? 44 : 40
                    role: "caption"; font.weight: Font.DemiBold; secondary: true
                    text: e.label
                }
                Column {
                    anchors.left: sym.right; anchors.leftMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    width: 54
                    spacing: -3
                    Label { width: parent.width; role: "caption"; font.weight: Font.Medium; font.features: { "tnum": 1 }
                            text: tick.has ? strip.fmt(e.price) : "—" }
                    Label { width: parent.width; role: "micro"; font.features: { "tnum": 1 }; color: tick.moveColor
                            text: tick.has && e.changePct !== null ? (tick.up ? "▲ " : "▼ ") + Math.abs(e.changePct).toFixed(2) + "%" : "" }
                }
                Canvas {
                    id: spark
                    visible: strip.sparklines
                    anchors.right: parent.right; anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    width: 36; height: strip.barHeight * 0.42
                    renderStrategy: Canvas.Cooperative
                    property var pts: e.spark || []
                    property color stroke: tick.moveColor
                    onPtsChanged: requestPaint()
                    onStrokeChanged: requestPaint()
                    onPaint: {
                        var c = getContext("2d"); c.reset()
                        if (pts.length < 2) return
                        var lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts)
                        if (e.previousClose !== null && e.previousClose !== undefined) { lo = Math.min(lo, e.previousClose); hi = Math.max(hi, e.previousClose) }
                        var span = Math.max(hi - lo, 1e-9), w = width, h = height - 2
                        function Y(v) { return 1 + h - (v - lo) / span * h }
                        if (e.previousClose !== null && e.previousClose !== undefined) {
                            c.strokeStyle = Qt.rgba(glass.theme.text3.r, glass.theme.text3.g, glass.theme.text3.b, 0.5)
                            c.lineWidth = 1; c.setLineDash([1.5, 2])
                            c.beginPath(); c.moveTo(0, Y(e.previousClose)); c.lineTo(w, Y(e.previousClose)); c.stroke()
                            c.setLineDash([])
                        }
                        c.beginPath()
                        for (var i = 0; i < pts.length; i++) {
                            var x = i / (pts.length - 1) * w
                            if (i === 0) c.moveTo(x, Y(pts[i])); else c.lineTo(x, Y(pts[i]))
                        }
                        c.lineWidth = 1.4; c.lineJoin = "round"; c.strokeStyle = stroke; c.stroke()
                    }
                }
                HoverHandler { id: th; onHoveredChanged: hovered ? strip.hoveredEntry(tick.e, tick) : strip.unhovered() }
                TapHandler { onTapped: markets.openQuote(tick.e.symbol) }
            }
        }
        // freshness: exactly how current the numbers are
        Item {
            visible: strip.chipW > 0
            width: strip.chipW; height: strip.barHeight
            Row {
                id: chip
                anchors.centerIn: parent
                spacing: 5
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 6; height: 6; radius: 3
                    color: strip.statusKind === "live" ? glass.theme.success
                         : strip.statusKind === "delayed" || strip.statusKind === "stale" ? glass.theme.warning
                         : strip.statusKind === "error" ? glass.theme.danger : glass.theme.text3
                }
                Label { anchors.verticalCenter: parent.verticalCenter; role: "micro"; secondary: true; text: strip.statusText }
            }
        }
    }

    function fmt(v) {
        if (v === null || v === undefined) return "—"
        var a = Math.abs(v)
        return a >= 10000 ? Math.round(v).toLocaleString(Qt.locale("en_US"), "f", 0) : v.toFixed(a >= 1000 ? 1 : 2)
    }
}
