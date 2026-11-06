import QtQuick
import "../components"
import "../components/Motion.js" as Motion

// Right-click menu for a Dock app: its windows, new window, keep in Dock, remove, quit.
GlassPanel {
    id: menu
    property var dockWindow
    property Item backdropSource: null
    property string appId: ""
    property var windows: []
    property bool running: false
    property bool pinned: false
    property string appName: ""
    tone: "elevated"; margin: 24; radius: 16; padding: 6
    backdropItem: backdropSource
    tintOverride: glass.material.intensity > 0 ? -1 : 1
    width: 248 + 2 * (margin + padding)
    height: col.implicitHeight + 2 * (margin + padding)
    visible: opacity > 0.01
    opacity: 0
    scale: 0.96
    Behavior on opacity { OpacityAnimator { duration: Motion.ms(glass.theme, 140) } }
    Behavior on scale { ScaleAnimator { duration: Motion.ms(glass.theme, 180); easing.type: Easing.OutCubic } }
    MouseArea { anchors.fill: parent }

    function openFor(item, id) {
        appId = id
        var data = item
        windows = dock.windowsFor(id)
        running = windows.length > 0
        pinned = dock.isPinned(id)
        appName = item.Accessible.name.split(",")[0]
        var p = item.mapToItem(dockWindow.contentItem, item.width / 2, 0)
        if (dockWindow.vertical) {
            x = dockWindow.pos === "left" ? p.x + item.width / 2 + 16 - margin : p.x - item.width / 2 - width - 16 + margin
            y = Math.max(8, Math.min(dockWindow.height - height - 8, p.y + item.height / 2 - height / 2))
        } else {
            x = Math.max(8, Math.min(dockWindow.width - width - 8, p.x - width / 2))
            y = p.y - height - 4 + margin
        }
        opacity = 1; scale = 1
    }
    function close() { opacity = 0; scale = 0.96 }

    component Item_: Item {
        property string text; property string icon: ""; property bool destructive: false; property bool bold: false
        signal activated()
        width: col.width; height: 32
        Rectangle { anchors.fill: parent; radius: 9; color: ma.containsMouse ? glass.theme.accent : "transparent" }
        Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; name: parent.icon; size: 15; visible: parent.icon !== ""
               color: ma.containsMouse ? glass.theme.on_accent : (parent.destructive ? glass.theme.danger : glass.theme.text2) }
        Label { x: parent.icon !== "" ? 34 : 10; width: parent.width - x - 8; anchors.verticalCenter: parent.verticalCenter
                role: "callout"; text: parent.text; font.weight: parent.bold ? Font.DemiBold : Font.Normal
                color: ma.containsMouse ? glass.theme.on_accent : (parent.destructive ? glass.theme.danger : glass.theme.text) }
        MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: { parent.activated(); menu.close() }
                    Accessible.role: Accessible.MenuItem; Accessible.name: parent.text }
    }

    Column {
        id: col
        width: 248
        spacing: 1
        Label { width: parent.width; leftPadding: 10; height: 26; role: "caption"; tertiary: true; text: menu.appName }
        Repeater {
            model: menu.windows
            Item_ { text: modelData.title; icon: "window"; onActivated: dock.focusWindow(modelData.hwnd) }
        }
        Rectangle { width: parent.width; height: 1; color: glass.theme.separator; visible: menu.windows.length > 0 }
        Item_ { text: menu.running ? "New Window" : "Open"; icon: "plus"; onActivated: dock.launchApp(menu.appId) }
        Item_ { text: menu.pinned ? "Unpin from Dock" : "Keep in Dock"; icon: "pin"
                onActivated: menu.pinned ? dock.unpin(menu.appId) : dock.pin(menu.appId) }
        Item_ { visible: !menu.running; text: "Remove from Dock"; icon: "trash"; onActivated: dock.removeFromDock(menu.appId) }
        Rectangle { width: parent.width; height: 1; color: glass.theme.separator; visible: menu.running }
        Item_ { visible: menu.running; text: menu.windows.length > 1 ? "Close All Windows" : "Quit"; icon: "close"; destructive: true
                onActivated: dock.quitApp(menu.appId) }
    }
}
