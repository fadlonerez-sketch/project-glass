import QtQuick
import QtQuick.Window
import "components"
import "topbar"
import "components/Motion.js" as Motion

// The top bar window for one display: Glass mark + active app (left), markets either side of the Dynamic Glass
// (centre of the active display), status indicators and clock (right), flyouts. Only the visible shapes take input.
Window {
    id: win
    required property var targetScreen
    property bool isPrimary: true
    property string screenName: ""
    property bool suspended: false            // a full-screen app owns this display
    readonly property var s: glass.settings
    readonly property real barHeight: ({ compact: 28, regular: 32, large: 38 })[s["topbar.size"]] || 32
    property real reservedThickness: barHeight
    readonly property point backdropOrigin: Qt.point(0, 0)
    readonly property size backdropSize: Qt.size(targetScreen.geometry.width, targetScreen.geometry.height)
    property string flyout: ""                // network | battery | audio | clock | glass
    property real flyoutX: 0
    // The Dynamic Glass lives on one display at a time: the active one (where the frontmost app is), or the primary.
    readonly property bool hostsIsland: glass.islandScreen === "" ? isPrimary : glass.islandScreen === screenName
    readonly property bool overlayOpen: hostsIsland && (flyout !== "" || glass.state === "control_center") || (!hostsIsland && flyout !== "")

    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint
    color: "transparent"
    x: targetScreen.geometry.x
    y: targetScreen.geometry.y
    width: targetScreen.geometry.width
    height: Math.min(targetScreen.geometry.height, 720)
    visible: !suspended && s["topbar.visible"]
    title: "Project Glass Top Bar"

    // The desktop behind this display, for true refraction (loaded only while Liquid Glass is on).
    Image {
        id: backdrop
        visible: false
        source: glass.material.intensity > 0 ? (glass.backdrops[win.screenName] || "") : ""
        mipmap: true; asynchronous: true; cache: false
        sourceSize: Qt.size(win.targetScreen.geometry.width * Screen.devicePixelRatio, win.targetScreen.geometry.height * Screen.devicePixelRatio)
    }

    Connections {
        target: glass
        function onCloseOverlays() { win.flyout = "" }
        function onStateChanged() { if (glass.state === "control_center") win.flyout = ""; win.regionSoon() }
    }
    onFlyoutChanged: { glass.setControlsOpen(flyout !== ""); regionSoon() }
    onHostsIslandChanged: regionSoon()

    // Click anywhere outside an open flyout / control center closes it (the click is not passed through).
    MouseArea {
        anchors.fill: parent
        enabled: win.overlayOpen
        onPressed: { win.flyout = ""; glass.closeAll() }
    }

    // ---- the bar strip -----------------------------------------------------------------------------
    GlassSurface {
        id: strip
        visible: s["topbar.background"] === "bar"
        x: -margin; y: -margin
        width: win.width + 2 * margin
        height: win.barHeight + margin   // shape extends above the screen so only the bottom edge shows
        margin: 18
        radius: 0
        elevation: 0          // a bar has a hairline, not a shadow
        backdropItem: backdrop
        shapeRect: Qt.vector4d(margin - 4, 0, win.width + 8, win.barHeight + margin)
    }

    // ---- left: Glass mark + frontmost application ----------------------------------------------------
    Row {
        id: left
        x: 14; height: win.barHeight
        spacing: 12
        Item {
            width: 22; height: win.barHeight
            Rectangle {
                anchors.centerIn: parent; width: 18; height: 18; radius: 9
                gradient: Gradient { GradientStop { position: 0; color: Qt.lighter(glass.theme.accent, 1.35) }
                                     GradientStop { position: 1; color: glass.theme.accent } }
                scale: markArea.pressed ? 0.9 : markArea.containsMouse ? 1.08 : 1
                Behavior on scale { NumberAnimation { duration: 140 } }
                Rectangle { x: 4; y: 3.5; width: 6; height: 3; radius: 1.5; color: "white"; opacity: 0.55; rotation: -28 }
            }
            MouseArea { id: markArea; anchors.fill: parent; hoverEnabled: true
                        onClicked: win.toggleFlyout("glass", 14)
                        Accessible.role: Accessible.Button; Accessible.name: "Project Glass menu" }
        }
        Label {
            visible: s["topbar.show_app_name"]
            anchors.verticalCenter: parent.verticalCenter
            role: "callout"; font.weight: Font.DemiBold
            text: dock.foregroundName
            width: Math.min(implicitWidth, win.width * 0.25)
        }
    }

    // ---- centre: Dynamic Glass ---------------------------------------------------------------------
    DynamicGlass {
        id: pill
        barHeight: win.barHeight
        backdropSource: backdrop
        x: Math.round((win.width - width) / 2)
        y: 3 - margin
        opacity: win.hostsIsland ? 1 : 0
        scale: win.hostsIsland ? 1 : 0.85
        transformOrigin: Item.Top
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: Motion.ms(glass.theme, 260); easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: Motion.ms(glass.theme, 320); easing.type: Easing.OutCubic } }
        onTargetChanged: win.regionSoon()
    }

    // ---- markets: indices to the left of the Dynamic Glass, the watchlist to the right ----------------------------
    readonly property var mk: markets ? markets.data : ({})
    readonly property bool marketsOn: hostsIsland && !!mk.enabled && s["topbar.visible"]
    readonly property real pillHalf: pill.shapeW / 2
    readonly property real centerX: width / 2
    MarketStrip {
        id: leftMarkets
        visible: win.marketsOn && opacity > 0.01
        opacity: win.marketsOn && glass.state !== "control_center" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
        alignRight: true
        entries: win.mk.indices || []
        sparklines: !!win.mk.sparklines
        barHeight: win.barHeight
        maxWidth: Math.max(0, win.centerX - win.pillHalf - 18 - (left.x + left.width + 28))
        x: win.centerX - win.pillHalf - 18 - width
        onHoveredEntry: (e, item) => quote.showFor(e, item)
        onUnhovered: quote.hideSoon()
    }
    MarketStrip {
        id: rightMarkets
        visible: win.marketsOn && opacity > 0.01
        opacity: win.marketsOn && glass.state !== "control_center" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
        entries: win.mk.watchlist || []
        sparklines: !!win.mk.sparklines
        barHeight: win.barHeight
        showStatus: true
        statusKind: win.mk.status || ""
        statusText: win.mk.label || ""
        maxWidth: Math.max(0, status.x - 28 - (win.centerX + win.pillHalf + 18))
        x: win.centerX + win.pillHalf + 18
        onHoveredEntry: (e, item) => quote.showFor(e, item)
        onUnhovered: quote.hideSoon()
    }
    // quote details on hover (after a short intent delay)
    GlassPanel {
        id: quote
        property var e: ({})
        property Item anchorItem: null
        property bool wanted: false
        tone: "elevated"; backdropItem: backdrop; margin: 22; radius: 16; padding: 12
        tintOverride: glass.material.intensity > 0 ? -1 : 1
        width: 236 + 2 * (margin + padding)
        height: qcol.implicitHeight + 2 * (margin + padding)
        x: anchorItem ? Math.max(4 - margin, Math.min(win.width - width + margin - 4, anchorItem.mapToItem(win.contentItem, anchorItem.width / 2, 0).x - width / 2)) : 0
        y: win.barHeight + 4 - margin
        opacity: wanted && win.marketsOn ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 140 } }
        onOpacityChanged: win.regionSoon()
        function showFor(entry, item) { e = entry; anchorItem = item; hideT.stop(); if (!wanted) showT.restart() }
        function hideSoon() { showT.stop(); hideT.restart() }
        Timer { id: showT; interval: 320; onTriggered: { quote.wanted = true; win.regionSoon() } }
        Timer { id: hideT; interval: 160; onTriggered: quote.wanted = false }
        Column {
            id: qcol
            width: 236
            spacing: 6
            Label { width: parent.width; role: "callout"; font.weight: Font.DemiBold; text: quote.e.name || "" }
            Row {
                spacing: 8
                Label { role: "title"; font.features: { "tnum": 1 }; text: quote.e.price !== null && quote.e.price !== undefined ? leftMarkets.fmt(quote.e.price) : "—" }
                Label { anchors.baseline: parent.children[0].baseline; role: "caption"; font.features: { "tnum": 1 }
                        color: (quote.e.change || 0) >= 0 ? glass.theme.success : glass.theme.danger
                        text: quote.e.change !== null && quote.e.change !== undefined ? ((quote.e.change >= 0 ? "+" : "") + quote.e.change.toFixed(2) + "  (" + (quote.e.changePct >= 0 ? "+" : "") + quote.e.changePct.toFixed(2) + "%)") : "" }
            }
            Label { role: "micro"; tertiary: true; visible: !!quote.e.currency; text: (quote.e.exchange || "") + (quote.e.currency ? " · " + quote.e.currency : "") }
            Rectangle { width: parent.width; height: 1; color: glass.theme.separator }
            Row {
                spacing: 18
                Column { Label { role: "micro"; tertiary: true; text: "Day range" }
                         Label { role: "caption"; font.features: { "tnum": 1 }
                                 text: quote.e.dayLow !== null && quote.e.dayLow !== undefined ? leftMarkets.fmt(quote.e.dayLow) + " – " + leftMarkets.fmt(quote.e.dayHigh) : "—" } }
                Column { Label { role: "micro"; tertiary: true; text: "Prev. close" }
                         Label { role: "caption"; font.features: { "tnum": 1 }; text: leftMarkets.fmt(quote.e.previousClose) } }
            }
            Row {
                spacing: 6
                Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 6; height: 6; radius: 3
                            color: quote.e.live ? glass.theme.success : quote.e.status === "closed" ? glass.theme.text3 : glass.theme.warning }
                Label { role: "caption"; secondary: true; text: quote.e.error ? quote.e.error : (quote.e.statusLabel || "") }
            }
            Label { width: parent.width; role: "micro"; tertiary: true; wrapMode: Text.Wrap
                    text: (win.mk.updated ? win.mk.updated + " · " : "") + "Source: " + (win.mk.source || "") + ". Click to open the quote." }
        }
    }

    // ---- right: status area ------------------------------------------------------------------------
    Row {
        id: status
        anchors.right: parent.right; anchors.rightMargin: 12
        height: win.barHeight
        spacing: 2

        component Indicator: Item {
            id: ind
            property string kind
            default property alias content: box.data
            width: box.childrenRect.width + 16; height: win.barHeight
            Rectangle {
                anchors.centerIn: parent; width: parent.width; height: win.barHeight - 6; radius: height / 2
                color: win.flyout === ind.kind ? glass.theme.control_pressed : ia.containsMouse ? glass.theme.control_hover : "transparent"
                Behavior on color { ColorAnimation { duration: 120 } }
            }
            Row { id: box; anchors.centerIn: parent; spacing: 5 }
            MouseArea { id: ia; anchors.fill: parent; hoverEnabled: true
                        onClicked: ind.kind === "tray" ? glass.revealTray() : win.toggleFlyout(ind.kind, ind.mapToItem(null, 0, 0).x + ind.width)
                        Accessible.role: Accessible.Button; Accessible.name: ind.kind }
        }

        Indicator { kind: "power"; visible: true
            Icon { name: "power"; size: 14; color: glass.theme.text2; anchors.verticalCenter: parent.verticalCenter } }
        Indicator { kind: "tray"; visible: s["topbar.indicators.tray"]
            Icon { name: "chevron-down"; size: 14; color: glass.theme.text2; anchors.verticalCenter: parent.verticalCenter } }
        Indicator { kind: "network"; visible: s["topbar.indicators.network"]
            WifiIcon { size: 16; kind: glass.network.kind || "none"; bars: glass.network.bars || 0; internet: !!glass.network.internet
                       anchors.verticalCenter: parent.verticalCenter } }
        Indicator { kind: "audio"; visible: s["topbar.indicators.audio"]
            SpeakerIcon { size: 16; level: glass.audio.volume || 0; muted: !!glass.audio.muted; anchors.verticalCenter: parent.verticalCenter } }
        Indicator { kind: "battery"; visible: s["topbar.indicators.battery"] && !!glass.power.present
            Label { role: "callout"; text: (glass.power.percent || 0) + "%"; visible: s["topbar.indicators.battery_percent"]
                    anchors.verticalCenter: parent.verticalCenter; font.features: { "tnum": 1 } }
            BatteryIcon { size: 14; percent: glass.power.percent || 0; charging: !!glass.power.charging
                          plugged: !!glass.power.plugged; saver: !!glass.power.saver; anchors.verticalCenter: parent.verticalCenter } }
        Indicator { kind: "clock"; visible: s["topbar.indicators.clock"]
            Label {
                id: clock
                role: "callout"; font.weight: Font.Medium; font.features: { "tnum": 1 }
                anchors.verticalCenter: parent.verticalCenter
                property date now: new Date()
                text: (s["topbar.clock.show_date"] ? Qt.formatDate(now, "ddd d MMM") + "   " : "")
                      + Qt.formatTime(now, s["topbar.clock.format"] === "12h"
                                      ? (s["topbar.clock.show_seconds"] ? "h:mm:ss AP" : "h:mm AP")
                                      : (s["topbar.clock.show_seconds"] ? "HH:mm:ss" : "HH:mm"))
                Timer { interval: s["topbar.clock.show_seconds"] ? 1000 : 1000 * (60 - new Date().getSeconds()) + 50
                        running: true; repeat: true; triggeredOnStart: true
                        onTriggered: { clock.now = new Date(); interval = s["topbar.clock.show_seconds"] ? 1000 : 60000 } }
            }
        }
    }

    // ---- flyout ------------------------------------------------------------------------------------
    function toggleFlyout(kind, anchorRight) {
        if (flyout === kind) { flyout = ""; return }
        if (glass.state === "control_center") glass.closeAll()
        flyoutX = anchorRight
        flyout = kind
    }

    GlassPanel {
        id: flyPanel
        tone: "elevated"
        backdropItem: backdrop
        margin: 26
        radius: 22
        padding: 14
        width: 320 + 2 * (margin + padding)
        height: flyContent.implicitHeight + 2 * (margin + padding)
        x: win.flyout === "glass" ? 6 - margin : Math.max(8, Math.min(win.width - width + margin - 8, win.flyoutX - width + margin))
        y: win.barHeight + 4 - margin
        visible: opacity > 0.01
        opacity: win.flyout !== "" ? 1 : 0
        scale: win.flyout !== "" ? 1 : 0.96
        transformOrigin: win.flyout === "glass" ? Item.TopLeft : Item.TopRight
        Behavior on opacity { OpacityAnimator { duration: Motion.ms(glass.theme, 160) } }
        Behavior on scale { ScaleAnimator { duration: Motion.ms(glass.theme, 220); easing.type: Easing.OutCubic } }

        MouseArea { anchors.fill: parent }   // swallow clicks inside the panel
        Flyouts {
            id: flyContent
            width: 320
            kind: win.flyout
            hostWindow: win
        }
    }

    // ---- input region: only visible shapes take the mouse ---------------------------------------------
    // A window region also clips drawing, so the region is computed from where shapes are *going* (the pill's target
    // size) and applied at once, before the animation starts. It shrinks only after the shape has settled. (Computing
    // it from the animated size, after the animation, is what used to clip the media player and make it pop in late.)
    function regionSoon() { Qt.callLater(updateRegion); settleT.restart() }
    Timer { id: settleT; interval: 700; onTriggered: win.updateRegion() }
    Connections { target: flyPanel; function onHeightChanged() { win.regionSoon() } }
    Component.onCompleted: updateRegion()
    function updateRegion() {
        if (overlayOpen) {
            glass.setInteractiveRegion(win, [{ x: 0, y: 0, width: win.width, height: win.height }])
            return
        }
        var r = [{ x: 0, y: 0, width: win.width, height: win.barHeight + 8 }]
        if (pill.visible || hostsIsland) {
            var t = pill.target
            var compact = ["idle", "media"].indexOf(pill.st) < 0 ? false : true
            var pad = compact ? 8 : pill.margin - 4
            // the larger of where the pill is and where it is going, with room for the spring's overshoot
            var w = Math.max(t.width * 1.06 + 12, pill.shapeW), h = Math.max(t.height * 1.06 + 8, pill.shapeH)
            r.push({ x: win.width / 2 - w / 2 - pad, y: 0, width: w + 2 * pad, height: 3 + h + pad })
        }
        if (quote.visible || quote.wanted)
            r.push({ x: quote.x + quote.margin - 8, y: quote.y + quote.margin - 8, width: quote.width - 2 * quote.margin + 16,
                     height: quote.height - 2 * quote.margin + 16 })
        glass.setInteractiveRegion(win, r)
    }
}
