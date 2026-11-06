import QtQuick
import "../components"
import "../components/Motion.js" as Motion

// Hovering an open app shows its windows: a live thumbnail of each (DWM draws it; no pixels reach Glass), its
// title and the app's identity. Click a card to bring that window forward; minimise/restore and close (with a
// confirming second click) sit in the card's title row. Windows that can't show a live thumbnail (minimised, on
// another desktop) get a calm fallback card with the app icon.
GlassPanel {
    id: pv
    property var dockWindow
    property Item backdropSource: null
    property string appUid: ""
    readonly property string appId: appUid.indexOf("app:") === 0 ? appUid.slice(4) : ""
    readonly property bool shown: appId !== ""
    property string shownApp: ""                 // the app whose cards are on screen (lags appId during a crossfade)
    property var wins: []
    property var status: ({})                    // hwnd -> "" (live thumbnail) | reason
    readonly property int count: wins.length
    readonly property var anchorItem: shownApp !== "" ? dockWindow.itemFor("app:" + shownApp) : null
    readonly property string appName: anchorItem ? anchorItem.title : ""
    readonly property string appIcon: anchorItem ? (anchorItem.model_icon || "") : ""

    tone: "elevated"; margin: 30; radius: 22; padding: 10
    backdropItem: backdropSource
    tintOverride: glass.material.intensity > 0 ? -1 : 1
    elevation: 1.2

    // ---- card grid ------------------------------------------------------------------------------------------
    readonly property real headerH: 26
    readonly property real titleH: 32
    readonly property real cardPad: 7
    readonly property real cardGap: 8
    readonly property real maxW: dockWindow.vertical ? 560 : Math.min(dockWindow.width - 40, 1500)
    readonly property var grid: {
        var n = wins.length
        if (n === 0) return { thumbH: 120, cards: [], w: 220, h: 160 }
        var thumbH = 136, cards, rowW, rows
        for (var attempt = 0; attempt < 8; attempt++) {
            cards = []; rows = [[]]; rowW = 0
            var maxRow = 0
            for (var i = 0; i < n; i++) {
                var cw = Math.max(150, Math.min(300, thumbH * wins[i].aspect)) + 2 * cardPad
                if (rows[rows.length - 1].length && rowW + cardGap + cw > maxW - 2 * padding) { rows.push([]); rowW = 0 }
                rowW += (rows[rows.length - 1].length ? cardGap : 0) + cw
                rows[rows.length - 1].push({ i: i, w: cw })
                maxRow = Math.max(maxRow, rowW)
            }
            if (rows.length <= 2 || thumbH <= 88) break
            thumbH -= 12
        }
        var cardH = thumbH + 2 * cardPad + titleH, y = headerH, out = []
        for (var r = 0; r < rows.length; r++) {
            var x = 0
            for (var c = 0; c < rows[r].length; c++) { out[rows[r][c].i] = { x: x, y: y, w: rows[r][c].w, h: cardH }; x += rows[r][c].w + cardGap }
            y += cardH + cardGap
        }
        return { thumbH: thumbH, cards: out, w: Math.max(maxRow, 200), h: y - cardGap }
    }

    // ---- target placement: centred over the icon, kept on the display, above the magnified icons -------------------
    readonly property rect target: {
        var w = grid.w + 2 * (margin + padding), h = grid.h + 2 * (margin + padding)
        var a = anchorItem ? anchorItem.centerWin : dockWindow.width / 2
        var d = dockWindow
        if (d.vertical) {
            var tx = d.pos === "left" ? d.barX + d.barT + 18 - margin : d.barX - w - 18 + margin
            return Qt.rect(tx, Math.max(8 - margin, Math.min(d.height - h + margin - 8, a - h / 2)), w, h)
        }
        return Qt.rect(Math.max(8 - margin, Math.min(d.width - w + margin - 8, a - w / 2)),
                       d.barY - d.icon * (d.magScale - 1) - 18 - h + margin, w, h)
    }
    onTargetChanged: { settle.restart(); if (opacity > 0.5) dock.thumbnails.hide(dockWindow) }
    property bool moving: false
    x: target.x; y: target.y; width: target.width; height: target.height
    Behavior on x { enabled: pv.moving; NumberAnimation { duration: Motion.ms(glass.theme, 230); easing.type: Easing.OutCubic } }
    Behavior on y { enabled: pv.moving; NumberAnimation { duration: Motion.ms(glass.theme, 230); easing.type: Easing.OutCubic } }
    Behavior on width { enabled: pv.moving; NumberAnimation { duration: Motion.ms(glass.theme, 230); easing.type: Easing.OutCubic } }
    Behavior on height { enabled: pv.moving; NumberAnimation { duration: Motion.ms(glass.theme, 230); easing.type: Easing.OutCubic } }

    opacity: shown ? 1 : 0
    scale: shown ? 1 : 0.95
    transformOrigin: dockWindow.vertical ? (dockWindow.pos === "left" ? Item.Left : Item.Right) : Item.Bottom
    visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: Motion.ms(glass.theme, pv.shown ? 170 : 130); easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: Motion.ms(glass.theme, 220); easing.type: Easing.OutCubic } }

    // ---- switching apps: slide to the new icon while the cards crossfade ---------------------------------------------
    property real contentOpacity: 1
    onAppIdChanged: {
        if (appId === "") { dock.thumbnails.hide(dockWindow); closeT.restart(); return }
        closeT.stop()
        if (shownApp === "" || opacity < 0.05) {        // opening: appear in place
            moving = false
            shownApp = appId; reload()
            Qt.callLater(function () { pv.moving = true })
        } else if (appId !== shownApp) {               // switching: glide and crossfade
            dock.thumbnails.hide(dockWindow)
            swap.restart()
        }
    }
    SequentialAnimation {
        id: swap
        NumberAnimation { target: pv; property: "contentOpacity"; to: 0; duration: Motion.ms(glass.theme, 70) }
        ScriptAction { script: { pv.shownApp = pv.appId; pv.reload() } }
        NumberAnimation { target: pv; property: "contentOpacity"; to: 1; duration: Motion.ms(glass.theme, 150); easing.type: Easing.OutCubic }
    }
    Timer { id: closeT; interval: 160; onTriggered: { dock.thumbnails.clear(pv.dockWindow); pv.shownApp = ""; pv.wins = []; pv.moving = false } }
    function reload() { wins = shownApp ? dock.previewWindows(shownApp) : []; status = ({}); settle.restart() }
    Connections {
        target: dock
        function onPinnedChanged() { if (pv.shownApp !== "") { var before = JSON.stringify(pv.wins); pv.wins = dock.previewWindows(pv.shownApp); if (JSON.stringify(pv.wins) !== before) settle.restart() } }
    }

    // ---- live thumbnails, once the panel has come to rest ------------------------------------------------------------
    Timer {
        id: settle
        interval: Motion.ms(glass.theme, 240)
        onTriggered: pv.placeThumbnails()
    }
    function placeThumbnails() {
        if (!shown || shownApp === "" || cardRep.count === 0) return
        var items = []
        for (var i = 0; i < cardRep.count; i++) {
            var c = cardRep.itemAt(i)
            if (!c) continue
            var p = c.thumbBox.mapToItem(null, 0, 0)
            items.push({ hwnd: c.hwnd, x: p.x, y: p.y, w: c.thumbBox.width, h: c.thumbBox.height })
        }
        status = dock.thumbnails.show(dockWindow, items)
    }

    // ---- pointer ---------------------------------------------------------------------------------------------------
    HoverHandler { id: inside; onHoveredChanged: hovered ? dockWindow.hover.previewEnter() : dockWindow.hover.previewLeave() }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }      // the panel itself never clicks through

    function activateCard(i) {
        if (i < 0 || i >= wins.length) return
        dock.focusWindow(wins[i].hwnd)
        dockWindow.hover.chooseWindow()
    }

    Item {
        width: pv.grid.w; height: pv.grid.h
        opacity: pv.contentOpacity
        Row {
            height: pv.headerH - 6
            spacing: 7
            Image { width: 16; height: 16; anchors.verticalCenter: parent.verticalCenter; source: pv.appIcon
                    sourceSize: Qt.size(32, 32); smooth: true; asynchronous: true }
            Label { anchors.verticalCenter: parent.verticalCenter; role: "caption"; font.weight: Font.DemiBold; text: pv.appName }
            Label { anchors.verticalCenter: parent.verticalCenter; role: "caption"; secondary: true
                    text: pv.count > 1 ? pv.count + " windows" : "" }
        }
        Repeater {
            id: cardRep
            model: pv.wins
            Item {
                id: card
                readonly property var geo: pv.grid.cards[index] || { x: 0, y: 0, w: 0, h: 0 }
                readonly property int hwnd: modelData.hwnd
                readonly property string reason: pv.status[String(modelData.hwnd)] !== undefined ? pv.status[String(modelData.hwnd)]
                                                 : (modelData.minimized ? "minimized" : "pending")
                readonly property bool selected: cardHover.hovered || pv.dockWindow.kbCard === index
                property alias thumbBox: tbox
                property bool confirmClose: false
                x: geo.x; y: geo.y; width: geo.w; height: geo.h
                Accessible.role: Accessible.Button
                Accessible.name: modelData.title + (modelData.minimized ? ", minimized" : "") + (modelData.active ? ", current window" : "")
                Accessible.onPressAction: pv.activateCard(index)

                Rectangle {
                    anchors.fill: parent; radius: 14
                    color: card.selected ? glass.theme.control_hover : "transparent"
                    border.width: card.selected ? 1.5 : 0
                    border.color: Qt.rgba(glass.theme.accent.r, glass.theme.accent.g, glass.theme.accent.b, 0.85)
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
                // thumbnail box: DWM paints the live window here (aspect-fitted); the fallback shows otherwise
                Rectangle {
                    id: tbox
                    x: pv.cardPad; y: pv.cardPad
                    width: card.width - 2 * pv.cardPad; height: pv.grid.thumbH
                    radius: 9
                    color: card.reason === "" ? "transparent" : glass.theme.control
                    clip: true
                    Rectangle {
                        anchors.fill: parent; radius: parent.radius
                        visible: card.reason !== "" && card.reason !== "pending"
                        gradient: Gradient {
                            GradientStop { position: 0; color: Qt.rgba(glass.theme.accent.r, glass.theme.accent.g, glass.theme.accent.b, glass.theme.dark ? 0.16 : 0.10) }
                            GradientStop { position: 1; color: "transparent" }
                        }
                        Column {
                            anchors.centerIn: parent
                            spacing: 6
                            Image { anchors.horizontalCenter: parent.horizontalCenter; width: 40; height: 40; source: pv.appIcon
                                    sourceSize: Qt.size(80, 80); smooth: true; asynchronous: true }
                            Label { anchors.horizontalCenter: parent.horizontalCenter; role: "micro"; secondary: true
                                    text: card.reason === "minimized" ? "Minimized" : card.reason === "elsewhere" ? "On another desktop"
                                          : card.reason === "gone" ? "Closed" : "Preview unavailable" }
                        }
                    }
                }
                // title row: identity, title, window actions
                Item {
                    x: pv.cardPad; y: pv.cardPad + pv.grid.thumbH
                    width: card.width - 2 * pv.cardPad; height: pv.titleH
                    Rectangle { id: activeDot; visible: modelData.active; x: 2; anchors.verticalCenter: parent.verticalCenter
                                width: 6; height: 6; radius: 3; color: glass.theme.accent }
                    Label {
                        x: modelData.active ? 14 : 2
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - x - (actions.visible ? actions.width + 4 : 0)
                        role: "caption"; font.weight: modelData.active ? Font.DemiBold : Font.Medium
                        text: modelData.title
                    }
                    Row {
                        id: actions
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        visible: card.selected
                        IconButton { icon: modelData.minimized ? "restore" : "minus"; size: 24; iconSize: 12; color: glass.theme.text2
                                     tooltip: modelData.minimized ? "Restore window" : "Minimize window"
                                     onClicked: { if (modelData.minimized) pv.activateCard(index); else { dock.minimizeWindow(card.hwnd); refreshT.restart() } } }
                        Item {
                            width: card.confirmClose ? 58 : 24; height: 24
                            Behavior on width { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                            Rectangle { anchors.fill: parent; radius: 12; visible: card.confirmClose; color: glass.theme.danger }
                            Label { anchors.centerIn: parent; visible: card.confirmClose; role: "micro"; color: "white"; font.weight: Font.DemiBold; text: "Close" }
                            IconButton { visible: !card.confirmClose; icon: "close"; size: 24; iconSize: 11; color: glass.theme.text2; tooltip: "Close window"
                                         onClicked: { card.confirmClose = true; confirmT.restart() } }
                            MouseArea { anchors.fill: parent; enabled: card.confirmClose
                                        onClicked: { dock.closeWindow(card.hwnd); card.confirmClose = false; refreshT.restart() }
                                        Accessible.role: Accessible.Button; Accessible.name: "Confirm close window" }
                            Timer { id: confirmT; interval: 2600; onTriggered: card.confirmClose = false }
                        }
                    }
                }
                HoverHandler { id: cardHover; onHoveredChanged: if (!hovered) card.confirmClose = false }
                TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: (pt) => {
                    var p = card.mapFromItem(null, pt.scenePosition.x, pt.scenePosition.y)
                    if (p.y < pv.cardPad + pv.grid.thumbH || p.x < card.width - 64) pv.activateCard(index) } }
            }
        }
    }
    Timer { id: refreshT; interval: 350; onTriggered: { if (pv.shownApp !== "") { pv.wins = dock.previewWindows(pv.shownApp); settle.restart() } } }
}
