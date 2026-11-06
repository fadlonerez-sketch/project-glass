import QtQuick
import "../components"
import "../components/Motion.js" as Motion

// One Dock slot: an application, the launcher, a separator or a widget.
// The slot (and so the hit area) is fixed by the layout; magnification, lift, bounce and drag are transforms
// on the visual only, so neighbours never move because of the pointer.
Item {
    id: root
    property var dockWindow
    signal openMenu(Item item, string appId)
    signal openWidget(Item item, string widgetType)

    readonly property var w: dockWindow
    readonly property string uid: model.uid
    readonly property string kind: model.kind
    readonly property string appId: model.appId
    readonly property string section: model.section
    readonly property bool pinned: model.pinned
    readonly property bool running: model.running
    readonly property bool focused: model.focused
    readonly property bool leaving: !!model.leaving
    readonly property bool hasWindows: model.running && model.windowCount > 0
    readonly property string title: kind === "launcher" ? "Search" : (model.name || "")
    readonly property string subtitle: kind === "launcher" ? "Find an app" : (kind === "app" && !running ? "Not running · click to open" : "")
    readonly property var slot: w.lay.slots ? (w.lay.slots[uid] || null) : null
    readonly property bool hiddenSlot: !slot || slot.hidden

    // ---- slot geometry: animated only when the layout itself changes (apps open/close, settings) ----------------
    property real along: slot ? slot.pos : 0
    property real span: slot ? slot.len : 0
    property bool settled: false
    Behavior on along { enabled: root.settled; NumberAnimation { duration: Motion.ms(glass.theme, 320); easing.type: Easing.OutCubic } }
    Behavior on span { enabled: root.settled; NumberAnimation { duration: Motion.ms(glass.theme, 320); easing.type: Easing.OutCubic } }
    Component.onCompleted: { settled = true; appear = 1 }
    readonly property real centerWin: w.alongToWin(along + span / 2)
    x: w.vertical ? w.barX : w.alongToWin(along)
    y: w.vertical ? w.alongToWin(along) : w.barY
    width: w.vertical ? w.barT : Math.max(span, 0)
    height: w.vertical ? Math.max(span, 0) : w.barT
    z: dragH.active ? 30 : hoverH.hovered ? 10 : 1
    visible: !hiddenSlot || leaving || opacity > 0.01

    Accessible.role: Accessible.Button
    Accessible.name: kind === "app" ? model.name + (running ? ", running" : "") + (pinned ? ", pinned" : "")
                    : kind === "launcher" ? "Search applications" : (model.name || "")
    Accessible.onPressAction: root.primaryAction()

    // ---- appearance / departure -------------------------------------------------------------------------------------
    property real appear: 0
    Behavior on appear { NumberAnimation { duration: Motion.ms(glass.theme, 360); easing.type: Easing.OutBack; easing.overshoot: 1.2 } }
    readonly property real presence: leaving || hiddenSlot ? 0 : appear

    // ---- magnification & lift (visual only) -----------------------------------------------------------------------
    readonly property bool magnifies: kind === "app" || kind === "launcher"
    readonly property real mag: magnifies && !leaving ? w.magnify(centerWin) : 1
    readonly property bool isHover: w.hover.hovered === uid
    readonly property real lift: (mag - 1) * w.icon * 0.22 + (isHover ? 2 : 0) + bounce
    readonly property real dragAlong: dragH.active ? (w.vertical ? dragH.activeTranslation.y : dragH.activeTranslation.x) : 0
    readonly property real dragOut: dragH.active ? (w.vertical ? (w.pos === "left" ? dragH.activeTranslation.x : -dragH.activeTranslation.x) : -dragH.activeTranslation.y) : 0
    readonly property bool removing: dragH.active && dragOut > w.icon * 1.6
    property real peerShift: w.dragShift(uid)
    Behavior on peerShift { NumberAnimation { duration: Motion.ms(glass.theme, 200); easing.type: Easing.OutCubic } }

    Item {
        id: visual
        readonly property real sz: root.kind === "widget" ? 0 : w.icon
        width: root.kind === "widget" ? root.width : sz
        height: root.kind === "widget" ? root.height : sz
        x: root.kind === "widget" ? 0 : (root.width - width) / 2
        y: root.kind === "widget" ? 0 : (root.height - height) / 2
        opacity: root.presence * (root.removing ? 0.35 : 1)
        Behavior on opacity { NumberAnimation { duration: 160 } }
        transformOrigin: w.vertical ? (w.pos === "left" ? Item.Left : Item.Right) : Item.Bottom
        scale: root.mag * (0.55 + 0.45 * root.presence) * (dragH.active ? 1.08 : 1)
        transform: Translate {
            x: w.vertical ? (w.outward * root.lift) + (dragH.active ? dragH.activeTranslation.x : 0) : root.dragAlong + root.peerShift
            y: w.vertical ? root.dragAlong + root.peerShift : -root.lift + (dragH.active ? Math.min(0, dragH.activeTranslation.y) : 0)
        }

        // launcher: a refined glass search tile in the accent colour
        Rectangle {
            visible: root.kind === "launcher"
            anchors.fill: parent; radius: width * 0.26
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.lighter(glass.theme.accent, 1.38) }
                GradientStop { position: 1; color: Qt.darker(glass.theme.accent, 1.15) }
            }
            Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.28) }
            Rectangle { x: parent.width * 0.12; y: 2; width: parent.width * 0.76; height: parent.height * 0.42; radius: parent.radius * 0.8
                        gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.30) } GradientStop { position: 1; color: Qt.rgba(1, 1, 1, 0) } } }
            Icon { anchors.centerIn: parent; name: "search"; size: parent.width * 0.46; color: "white"; strokeWidth: 2.2 }
        }
        Image {
            id: appIcon
            visible: root.kind === "app"
            anchors.fill: parent
            source: root.kind === "app" ? (model.icon || "") : ""
            sourceSize: Qt.size(128, 128)
            fillMode: Image.PreserveAspectFit
            smooth: true; mipmap: true; asynchronous: true
            opacity: status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 180 } }
        }
        Rectangle {    // placeholder while the icon loads, or if the app has none
            visible: root.kind === "app" && appIcon.status !== Image.Ready
            anchors.fill: parent; radius: width * 0.26; color: glass.theme.control
            Label { anchors.centerIn: parent; role: "headline"; text: (model.name || "?").charAt(0) }
        }
        Loader {
            active: root.kind === "widget"
            anchors.fill: parent
            sourceComponent: Widgets {
                type: model.widgetType
                iconSize: root.w.icon
                wide: !root.w.vertical
                onActivated: (it) => root.openWidget(root, model.widgetType)
            }
        }
    }

    // keyboard focus ring
    Rectangle {
        visible: w.kbUid === root.uid
        anchors.centerIn: visual
        width: (root.kind === "widget" ? visual.width : w.icon) + 8; height: (root.kind === "widget" ? visual.height : w.icon) + 8
        radius: (root.kind === "widget" ? 12 : w.icon * 0.3) + 4
        color: "transparent"; border.width: 2; border.color: glass.theme.accent
    }

    // separator: a hairline with breathing room
    Rectangle {
        visible: root.kind === "separator" && !root.hiddenSlot
        width: w.vertical ? w.barT * 0.5 : 1
        height: w.vertical ? 1 : w.barT * 0.5
        anchors.centerIn: parent
        color: glass.theme.separator
        opacity: root.presence
    }

    // running indicator: one dot per window (up to three); accent when frontmost, a ring on another desktop
    Row {
        visible: root.kind === "app" && root.running && glass.settings["dock.indicators"] && !root.leaving
        spacing: 3
        rotation: w.vertical ? 90 : 0
        x: w.vertical ? (w.pos === "left" ? 2 : root.width - width / 2 - height / 2 - 2) : (root.width - width) / 2 + root.dragAlong + root.peerShift
        y: w.vertical ? (root.height - height) / 2 : root.height - 6
        Repeater {
            model: Math.max(1, Math.min(3, root.model_windowCount))
            Rectangle {
                width: 4; height: 4; radius: 2
                color: model_otherDesktop ? "transparent" : root.focused ? glass.theme.accent : glass.theme.text2
                border.width: model_otherDesktop ? 1 : 0
                border.color: glass.theme.text2
                Behavior on color { ColorAnimation { duration: 180 } }
                readonly property bool model_otherDesktop: root.model_otherDesktop
            }
        }
    }
    readonly property int model_windowCount: model.windowCount
    readonly property string model_icon: model.icon || ""
    readonly property bool model_otherDesktop: model.otherDesktop

    // ---- launch bounce (only while launching, at most ~10 s) ------------------------------------------------------
    property real bounce: 0
    SequentialAnimation on bounce {
        running: !!model.launching && glass.settings["dock.launch_bounce"] && !glass.theme.reduce_motion
        loops: Animation.Infinite
        NumberAnimation { to: w.icon * 0.32; duration: 280; easing.type: Easing.OutQuad }
        NumberAnimation { to: 0; duration: 300; easing.type: Easing.InQuad }
        PauseAnimation { duration: 160 }
        onRunningChanged: if (!running) root.bounce = 0
    }

    // ---- interaction ---------------------------------------------------------------------------------------------------
    HoverHandler {
        id: hoverH
        enabled: root.kind === "app" || root.kind === "launcher"
        onHoveredChanged: hovered ? w.hover.iconEnter(root.uid, root.hasWindows) : w.hover.iconLeave(root.uid)
    }
    function primaryAction() {
        if (kind === "launcher") { glass.openLauncher(); return }
        if (kind === "widget") { root.openWidget(root, model.widgetType); return }
        if (kind !== "app") return
        if (running) dock.activate(appId)
        else dock.launchApp(appId)
    }
    MouseArea {
        anchors.fill: parent
        enabled: (root.kind === "app" || root.kind === "launcher") && !root.leaving
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        cursorShape: Qt.PointingHandCursor
        onClicked: (e) => {
            if (e.button === Qt.RightButton && root.kind === "app") root.openMenu(root, root.appId)
            else if (e.button === Qt.MiddleButton && root.kind === "app") { w.hover.press(root.uid); dock.launchApp(root.appId) }
            else if (e.button === Qt.LeftButton) { w.hover.press(root.uid); root.primaryAction() }
        }
    }

    // ---- drag: reorder pinned apps within their section, or drag out to remove -------------------------------------
    DragHandler {
        id: dragH
        enabled: root.kind === "app" && root.pinned && !root.leaving
        target: null
        dragThreshold: 8
        onActiveChanged: active ? w.beginDrag(root.uid, root.section) : w.endDrag(root, root.removingAtRelease)
        onActiveTranslationChanged: if (active) { w.dragCenter = root.centerWin + root.dragAlong; root.removingAtRelease = root.removing }
    }
    property bool removingAtRelease: false
}
