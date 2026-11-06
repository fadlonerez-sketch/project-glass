import QtQuick
import QtQuick.Window
import "components"
import "dock"
import "components/Motion.js" as Motion

// The Dock: a thin glass bar spanning the display.
//   [ widgets ]            [ search · Open apps | Recently Used ]            [ widgets ]
// Geometry comes from glass.core.docklayout (Python) and never depends on the pointer: magnification, lift and
// highlights are transforms on top of fixed slots, so nothing shifts while you move across the icons. What is
// shown above the bar (tooltips, window previews) follows the hover state machine (glass.core.dockhover).
Window {
    id: win
    required property var targetScreen
    property bool isPrimary: true
    property string screenName: ""
    property bool suspended: false
    readonly property var s: glass.settings
    readonly property var hover: dock.hoverState
    readonly property string pos: s["dock.position"]
    readonly property bool vertical: pos !== "bottom"

    // ---- proportions --------------------------------------------------------------------------------
    readonly property real iconBase: s["dock.icon_size"]
    readonly property real gapBase: s["dock.spacing"]
    readonly property real vpad: Math.round(iconBase * 0.21)            // icon to bar edge, across
    readonly property real barT: iconBase + 2 * vpad                    // the bar's thickness
    readonly property real hpad: Math.round(iconBase * 0.32)            // first/last item to the bar's ends
    readonly property real edgeGap: 6
    readonly property real sideMargin: 10
    readonly property real topInset: 56                                 // vertical docks start below the top bar
    readonly property real magScale: s["dock.magnification"] ? s["dock.magnification_scale"] : 1.0
    readonly property real headroom: iconBase * (magScale - 1) + 56     // magnified icons and the tooltip
    readonly property real popSpace: vertical ? 600 : 380
    property real reservedThickness: s["dock.autohide"] ? 0 : barT + edgeGap + 2
    readonly property real winThick: barT + edgeGap + headroom + popSpace

    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint
    color: "transparent"
    title: "Project Glass Dock"
    readonly property rect sg: targetScreen.geometry
    readonly property point backdropOrigin: Qt.point(pos === "right" ? sg.width - winThick : 0, pos === "bottom" ? sg.height - winThick : 0)
    readonly property size backdropSize: Qt.size(sg.width, sg.height)
    x: pos === "right" ? sg.x + sg.width - winThick : sg.x
    y: pos === "bottom" ? sg.y + sg.height - winThick : sg.y
    width: vertical ? winThick : sg.width
    height: vertical ? sg.height : winThick
    visible: !suspended && s["dock.visible"]

    Image {
        id: backdrop
        visible: false
        source: glass.material.intensity > 0 ? (glass.backdrops[win.screenName] || "") : ""
        mipmap: true; asynchronous: true; cache: false
        sourceSize: Qt.size(win.sg.width * Screen.devicePixelRatio, win.sg.height * Screen.devicePixelRatio)
    }

    // ---- the bar's place in the window ----------------------------------------------------------------
    property bool dragging: false
    property bool revealed: !s["dock.autohide"] || zoneHover.hovered || edgeTrigger.hovered || kbActive || popOpen
                            || hover.preview !== "" || dragging
    property real hideShift: revealed ? 0 : barT + edgeGap + 8
    Behavior on hideShift { NumberAnimation { duration: Motion.ms(glass.theme, 280); easing.type: Easing.OutCubic } }
    readonly property real barLen: vertical ? sg.height - topInset - sideMargin : sg.width - 2 * sideMargin
    readonly property real barX: pos === "left" ? edgeGap - hideShift : pos === "right" ? width - edgeGap - barT + hideShift : sideMargin
    readonly property real barY: vertical ? topInset : height - edgeGap - barT + hideShift
    readonly property real barW: vertical ? barT : barLen
    readonly property real barH: vertical ? barLen : barT
    readonly property real innerLen: barLen - 2 * hpad
    readonly property var lay: { dock.layoutRevision; return dock.layoutFor(innerLen, iconBase, gapBase, !vertical) }
    readonly property real icon: lay.icon || iconBase
    // along-axis coordinate (bar inner origin) -> window coordinate
    function alongToWin(a) { return (vertical ? barY : barX) + hpad + a }
    // the direction away from the screen edge (where magnified icons grow, previews open)
    readonly property real outward: pos === "left" ? 1 : -1

    // ---- glass bar ----------------------------------------------------------------------------------------
    GlassSurface {
        id: bar
        backdropItem: backdrop
        margin: 34
        radius: Math.round(win.barT * 0.38)
        elevation: 1.0
        x: win.barX - margin; y: win.barY - margin
        width: win.barW + 2 * margin; height: win.barH + 2 * margin
        lightPoint: win.pointer >= 0 ? (win.vertical ? Qt.point(win.barT / 2, win.pointer - win.barY)
                                                     : Qt.point(win.pointer - win.barX, win.barT * 0.2)) : Qt.point(-1, -1)
        lightStrength: win.magAmount * 0.9
        Accessible.role: Accessible.ToolBar
        Accessible.name: "Dock"
    }

    // ---- pointer zone: the bar, plus room above the apps while they are magnified --------------------------
    property real pointer: -1          // pointer position along the axis, window coords (-1 = away)
    property real magAmount: zoneHover.hovered && !dragging && hover.state !== "menu" ? 1 : 0
    Behavior on magAmount { NumberAnimation { duration: Motion.ms(glass.theme, 170); easing.type: Easing.OutCubic } }
    readonly property bool zoneOpen: zoneHover.hovered || magAmount > 0.01
    readonly property real clusterA: alongToWin(lay.cluster ? lay.cluster[0] : 0) - icon
    readonly property real clusterB: alongToWin(lay.cluster ? lay.cluster[1] : 0) + icon
    Item {
        id: zone
        readonly property real extra: win.zoneOpen ? win.headroom * 0.62 : 0
        x: win.vertical ? (win.pos === "left" ? win.barX : win.barX - extra) : win.barX
        y: win.vertical ? win.barY : win.barY - extra
        width: win.vertical ? win.barT + extra : win.barW
        height: win.vertical ? win.barH : win.barT + extra
        HoverHandler {
            id: zoneHover
            onPointChanged: win.pointer = win.vertical ? point.position.y + zone.y : point.position.x + zone.x
            onHoveredChanged: { if (!hovered) win.pointer = -1; win.regionSoon() }
        }
    }
    onZoneOpenChanged: regionSoon()
    // Auto-hide: a thin trigger strip on the screen edge brings the Dock back.
    Item {
        id: edge
        visible: s["dock.autohide"]
        x: win.pos === "right" ? win.width - 3 : 0
        y: win.pos === "bottom" ? win.height - 3 : 0
        width: win.vertical ? 3 : win.width
        height: win.vertical ? win.height : 3
        HoverHandler { id: edgeTrigger }
    }

    function magnify(center) {
        if (magScale <= 1.001 || magAmount <= 0.001 || pointer < 0) return 1
        var d = center - pointer, sigma = icon * 1.1
        return 1 + (magScale - 1) * magAmount * Math.exp(-(d * d) / (2 * sigma * sigma))
    }

    // ---- drag-and-drop reordering (pinned apps, within their section) ----------------------------------------
    property string dragUid: ""
    property real dragCenter: 0              // dragged icon's centre along the axis, window coords
    property var dragPeers: []               // [{uid, center}] other pinned apps in the same section
    readonly property int dropIndex: {
        var n = 0
        for (var i = 0; i < dragPeers.length; i++) if (dragPeers[i].center < dragCenter) n++
        return n
    }
    function beginDrag(uid, section) {
        var peers = []
        for (var i = 0; i < slots.count; i++) {
            var it = slots.itemAt(i)
            if (it && it.uid !== uid && it.kind === "app" && it.pinned && it.section === section && !it.leaving)
                peers.push({ uid: it.uid, center: it.centerWin, appId: it.appId })
        }
        peers.sort(function (a, b) { return a.center - b.center })
        dragPeers = peers
        dragUid = uid
        dragging = true
        hover.dragStart()
    }
    function endDrag(item, removing) {
        var uid = dragUid, peers = dragPeers, k = dropIndex
        dragUid = ""; dragPeers = []; dragging = false
        hover.dragEnd()
        if (removing) { if (item.running) dock.unpin(item.appId); else dock.removeFromDock(item.appId); return }
        var order = []
        for (var i = 0; i < peers.length; i++) { if (i === k) order.push(item.appId); order.push(peers[i].appId) }
        if (k >= peers.length) order.push(item.appId)
        dock.reorderPinned(order)
    }
    function dragShift(uid) {           // how far a peer moves aside to show where the dragged icon will land
        if (dragUid === "" || uid === dragUid) return 0
        var j = -1, orig = -1
        for (var i = 0; i < dragPeers.length; i++) if (dragPeers[i].uid === uid) j = i
        if (j < 0) return 0
        var dragItem = itemFor(dragUid)
        var before = dragItem ? dragPeers.filter(function (p) { return p.center < dragItem.centerWin }).length : 0
        var step = icon + lay.gap
        if (j >= dropIndex && j < before) return step
        if (j < dropIndex && j >= before) return -step
        return 0
    }

    // ---- items --------------------------------------------------------------------------------------------------
    Repeater {
        id: slots
        model: dock.model
        delegate: DockItem {
            dockWindow: win
            onOpenMenu: (item, appId) => { hover.menuOpen(); menu.openFor(item, appId) }
            onOpenWidget: (item, wtype) => win.openWidget(item, wtype)
        }
    }
    function itemFor(uid) {
        for (var i = 0; i < slots.count; i++) { var it = slots.itemAt(i); if (it && it.uid === uid) return it }
        return null
    }
    function openWidget(item, wtype) {
        if (wtype === "weather") weatherPop.openFor(item)
        else if (wtype === "garvis") garvisApp.activate()
        else if (wtype === "calendar" || wtype === "clock") glass.openSettingsPage("ms-settings:dateandtime")
        else if (wtype === "system") glass.openSettingsPage("ms-settings:about")
    }

    // ---- tooltip (closed apps, the launcher; open apps when previews are off) ------------------------------------
    readonly property var tipItem: hover.tooltip !== "" ? itemFor(hover.tooltip) : null
    property var tipHeld: null              // the last item with a tooltip: it fades out where it was
    property string tipText: ""
    property string tipSub: ""
    onTipItemChanged: if (tipItem) { tipHeld = tipItem; tipText = tipItem.title; tipSub = tipItem.subtitle }
    GlassPanel {
        id: tip
        tone: "elevated"; margin: 18; radius: 11; padding: 0; elevation: 0.55
        backdropItem: backdrop
        tintOverride: glass.material.intensity > 0 ? -1 : 1
        readonly property bool shown: win.tipItem !== null && !win.dragging
        width: Math.max(tipCol.implicitWidth, 40) + 26 + 2 * margin
        height: tipCol.implicitHeight + 14 + 2 * margin
        readonly property real tx: win.tipHeld ? (win.vertical ? (win.pos === "left" ? win.barX + win.barT + 14 - margin : win.barX - width - 14 + margin)
                                                               : win.tipHeld.centerWin - width / 2) : 0
        readonly property real ty: win.tipHeld ? (win.vertical ? win.tipHeld.centerWin - height / 2
                                                               : win.barY - win.icon * (win.magScale - 1) - 14 - height + margin) : 0
        x: Math.max(4 - margin, Math.min(win.width - width + margin - 4, tx))
        y: ty
        Behavior on x { enabled: tip.opacity > 0.5; NumberAnimation { duration: Motion.ms(glass.theme, 180); easing.type: Easing.OutCubic } }
        opacity: shown ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { OpacityAnimator { duration: Motion.ms(glass.theme, tip.shown ? 140 : 110) } }
        Column {
            id: tipCol
            anchors.centerIn: parent
            Label { anchors.horizontalCenter: parent.horizontalCenter; role: "callout"; font.weight: Font.DemiBold; text: win.tipText }
            Label { anchors.horizontalCenter: parent.horizontalCenter; role: "micro"; tertiary: true; text: win.tipSub; visible: text !== "" }
        }
    }

    // ---- window previews ----------------------------------------------------------------------------------------
    WindowPreview {
        id: preview
        dockWindow: win
        backdropSource: backdrop
        appUid: win.dragging ? "" : hover.preview
        z: 40
        onTargetChanged: win.regionSoon()
    }

    // ---- popovers (click outside closes) ---------------------------------------------------------------------------
    readonly property bool popOpen: menu.visible || weatherPop.visible
    onPopOpenChanged: { if (!menu.visible) hover.menuClose(); regionSoon() }
    MouseArea {
        anchors.fill: parent
        z: 50
        enabled: win.popOpen
        onPressed: { menu.close(); weatherPop.close() }
    }
    DockMenu { id: menu; z: 60; dockWindow: win; backdropSource: backdrop }
    WeatherPopover { id: weatherPop; z: 60; dockWindow: win; backdropSource: backdrop }
    QtObject {
        id: garvisApp
        function activate() { garvisLink ? garvisLink.activate() : glass.openControlCenter("garvis") }
    }
    Connections {
        target: glass
        function onCloseOverlays() { menu.close(); weatherPop.close(); if (hover.state !== "in_preview") hover.dismiss() }
    }

    // ---- keyboard navigation (Ctrl+Alt+Shift+D) ---------------------------------------------------------------------
    property bool kbActive: false
    property int kbIndex: 0
    property int kbCard: -1
    function focusables() {
        var out = []
        for (var i = 0; i < slots.count; i++) {
            var it = slots.itemAt(i)
            if (it && (it.kind === "app" || it.kind === "launcher" || it.kind === "widget") && !it.leaving && !it.hiddenSlot) out.push(it)
        }
        out.sort(function (a, b) { return a.centerWin - b.centerWin })
        return out
    }
    readonly property string kbUid: { if (!kbActive) return ""; var f = focusables(); return f.length ? f[Math.max(0, Math.min(kbIndex, f.length - 1))].uid : "" }
    Connections {
        target: dock
        function onKeyboardRequested() {
            var f = win.focusables(), start = 0
            for (var i = 0; i < f.length; i++) if (f[i].focused) start = i
            win.kbIndex = start; win.kbCard = -1; win.kbActive = true
            glass.requestKeyboard(win, true)
            keys.forceActiveFocus()
        }
    }
    onActiveChanged: if (!active && kbActive) endKeyboard(false)
    function endKeyboard(giveBack) {
        kbActive = false; kbCard = -1
        hover.dismiss()
        glass.requestKeyboard(win, false)
        if (giveBack) dock.returnFocus()
    }
    Item {
        id: keys
        focus: win.kbActive
        Keys.onPressed: (e) => {
            var f = win.focusables(), cur = f[Math.max(0, Math.min(win.kbIndex, f.length - 1))]
            var next = win.vertical ? Qt.Key_Down : Qt.Key_Right, prev = win.vertical ? Qt.Key_Up : Qt.Key_Left
            var open = win.vertical ? (win.pos === "left" ? Qt.Key_Right : Qt.Key_Left) : Qt.Key_Up
            var shut = win.vertical ? (win.pos === "left" ? Qt.Key_Left : Qt.Key_Right) : Qt.Key_Down
            e.accepted = true
            if (win.kbCard >= 0) {                       // inside a preview: choose a window
                var n = preview.count
                if (e.key === next) win.kbCard = Math.min(n - 1, win.kbCard + 1)
                else if (e.key === prev) win.kbCard = Math.max(0, win.kbCard - 1)
                else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space) { preview.activateCard(win.kbCard); win.endKeyboard(false) }
                else if (e.key === shut || e.key === Qt.Key_Escape) { win.kbCard = -1; hover.dismiss() }
                else e.accepted = false
                return
            }
            if (e.key === next) { win.kbIndex = Math.min(f.length - 1, win.kbIndex + 1); hover.dismiss() }
            else if (e.key === prev) { win.kbIndex = Math.max(0, win.kbIndex - 1); hover.dismiss() }
            else if (e.key === Qt.Key_Home) win.kbIndex = 0
            else if (e.key === Qt.Key_End) win.kbIndex = f.length - 1
            else if ((e.key === open || e.key === Qt.Key_Space) && cur && cur.kind === "app") {
                hover.showNow(cur.uid, cur.hasWindows)
                if (cur.hasWindows) win.kbCard = 0
            }
            else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { if (cur) { cur.primaryAction(); win.endKeyboard(false) } }
            else if (e.key === Qt.Key_Menu || (e.key === Qt.Key_F10 && (e.modifiers & Qt.ShiftModifier))) { if (cur && cur.kind === "app") { hover.menuOpen(); menu.openFor(cur, cur.appId) } }
            else if (e.key === Qt.Key_Escape) win.endKeyboard(true)
            else e.accepted = false
        }
    }

    // ---- input region: only what is visible takes the mouse; everything else clicks through ---------------------------
    // Regions also clip drawing, so they grow *before* anything opens (computed from targets, not from animated values)
    // and shrink only after closing animations have finished.
    function regionSoon() { Qt.callLater(updateRegion) }
    Timer { id: shrink; interval: 320; onTriggered: win.updateRegion() }
    onRevealedChanged: { regionSoon(); shrink.restart() }
    onDraggingChanged: regionSoon()
    onKbActiveChanged: regionSoon()
    Connections { target: hover; function onChanged() { win.regionSoon(); shrink.restart() } }
    onLayChanged: regionSoon()
    Component.onCompleted: updateRegion()
    function updateRegion() {
        if (popOpen) { glass.setInteractiveRegion(win, [{ x: 0, y: 0, width: win.width, height: win.height }]); return }
        var r = []
        if (s["dock.autohide"]) r.push({ x: edge.x, y: edge.y, width: edge.width, height: edge.height })
        var shownAbove = zoneOpen || dragging || kbActive || tip.shown || tip.visible || preview.shown || preview.visible
        if (revealed || shownAbove) {
            // the bar, with a little room for its shadow
            r.push({ x: barX - 6, y: barY - 6, width: barW + 12, height: barH + 12 })
        }
        if (shownAbove) {
            var lo = clusterA, hi = clusterB
            if (vertical) {
                var depth = headroom + 10
                r.push({ x: pos === "left" ? barX + barT : barX - depth, y: lo, width: depth, height: hi - lo })
            } else {
                r.push({ x: lo, y: barY - headroom - 10, width: hi - lo, height: headroom + 10 })
            }
            if (tip.shown || tip.visible) r.push({ x: Math.min(tip.x, tip.tx) + tip.margin - 6, y: tip.ty + tip.margin - 6,
                                                   width: tip.width - 2 * tip.margin + 12 + Math.abs(tip.x - tip.tx), height: tip.height - 2 * tip.margin + 12 })
            if (preview.shown || preview.visible) {
                var a = preview.target, b = Qt.rect(preview.x, preview.y, preview.width, preview.height)
                var x0 = Math.min(a.x, b.x) + preview.margin - 14, y0 = Math.min(a.y, b.y) + preview.margin - 14
                var x1 = Math.max(a.x + a.width, b.x + b.width) - preview.margin + 14, y1 = Math.max(a.y + a.height, b.y + b.height) - preview.margin + 20
                r.push({ x: x0, y: y0, width: x1 - x0, height: y1 - y0 })
                // the gap between the icon and its preview stays inside the Dock while moving across it
                if (!vertical) r.push({ x: Math.max(x0, lo), y: y1 - 20, width: Math.min(x1, hi) - Math.max(x0, lo), height: barY - y1 + 20 })
            }
        }
        glass.setInteractiveRegion(win, r)
    }
}
