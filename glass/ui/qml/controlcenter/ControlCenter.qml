import QtQuick
import QtQuick.Window
import "../components"

Window {
    id: root_
    width: 1060; height: 760
    minimumWidth: 860; minimumHeight: 560
    visible: !previewMode
    title: "Control Center"
    color: glass.theme.bg
    property string page: initialPage
    readonly property var pages: [
        ["appearance", "Appearance", "palette"], ["glass", "Liquid Glass", "glass"], ["topbar", "Top Bar & Dynamic Glass", "island"],
        ["dock", "Dock", "dock"], ["markets", "Markets", "cpu"], ["notifications", "Notifications", "bell"], ["applications", "Applications", "apps"],
        ["system", "System", "display"], ["garvis", "Garvis", "sparkle"], ["about", "About", "info"]
    ]
    Connections { target: cc; function onPageRequested(p) { root_.page = p } function onMessage(m) { toast.show(m) } }

    // ---- sidebar --------------------------------------------------------------------------------------
    Rectangle {
        id: sidebar
        width: 260; height: root_.height
        color: glass.theme.dark ? Qt.darker(glass.theme.bg, 1.15) : "#EBEBF0"
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: glass.theme.separator }
        Column {
            x: 14; y: 18; width: parent.width - 28
            spacing: 2
            Row {
                spacing: 10; height: 52; leftPadding: 6
                Rectangle { width: 32; height: 32; radius: 9; anchors.verticalCenter: parent.verticalCenter
                            gradient: Gradient { GradientStop { position: 0; color: Qt.lighter(glass.theme.accent, 1.3) }
                                                 GradientStop { position: 1; color: glass.theme.accent } }
                            Icon { anchors.centerIn: parent; name: "glass"; size: 17; color: "white" } }
                Column { anchors.verticalCenter: parent.verticalCenter
                    Label { role: "headline"; text: "Control Center" }
                    Label { role: "caption"; secondary: true; text: "Project Glass" } }
            }
            // The master power switch. It shows Glass's real state, as the Shell reports it.
            Rectangle {
                width: parent.width; height: 58; radius: 14
                color: glass.theme.dark ? glass.theme.surface : "#FFFFFF"
                border.width: 1; border.color: glass.theme.hairline
                Rectangle {
                    id: pIcon
                    x: 12; anchors.verticalCenter: parent.verticalCenter
                    width: 34; height: 34; radius: 17
                    color: cc.powered ? glass.theme.accent : glass.theme.control
                    Behavior on color { ColorAnimation { duration: 200 } }
                    Icon { anchors.centerIn: parent; name: "power"; size: 16; strokeWidth: 2.2
                           color: cc.powered ? glass.theme.on_accent : glass.theme.text2 }
                }
                Column {
                    anchors.left: pIcon.right; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter
                    Label { role: "callout"; font.weight: Font.DemiBold; text: "Project Glass" }
                    Label { role: "caption"; secondary: true
                            text: cc.powerBusy ? "Switching…" : !cc.shellConnected ? "Not running" : cc.powered ? "On" : "Off — Windows desktop" }
                }
                Toggle {
                    anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                    checked: cc.powered
                    enabled: !cc.powerBusy
                    accessibleName: "Project Glass on or off"
                    onToggled: (c) => cc.setPower(c)
                }
            }
            Item { width: 1; height: 10 }
            Repeater {
                model: root_.pages
                Item {
                    width: parent.width; height: 36
                    readonly property bool current: root_.page === modelData[0]
                    Rectangle { anchors.fill: parent; radius: 9
                                color: parent.current ? glass.theme.accent : na.containsMouse ? glass.theme.control_hover : "transparent"
                                Behavior on color { ColorAnimation { duration: 120 } } }
                    Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 24; height: 24; radius: 7
                                color: parent.current ? Qt.rgba(1, 1, 1, 0.22) : glass.theme.control
                                Icon { anchors.centerIn: parent; name: modelData[2]; size: 14
                                       color: parent.parent.current ? glass.theme.on_accent : glass.theme.text } }
                    Label { x: 42; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 50; role: "body"
                            text: modelData[1]; color: parent.current ? glass.theme.on_accent : glass.theme.text }
                    MouseArea { id: na; anchors.fill: parent; hoverEnabled: true; onClicked: root_.page = modelData[0]
                                Accessible.role: Accessible.PageTab; Accessible.name: modelData[1] }
                }
            }
        }
    }

    // ---- content ----------------------------------------------------------------------------------------
    Item {
        x: sidebar.width
        width: root_.width - sidebar.width
        height: root_.height
        Label {
            id: heading
            x: 36; y: 26; role: "display"
            text: (root_.pages.find(p => p[0] === root_.page) || ["", ""])[1]
        }
        Rectangle {
            visible: !cc.shellConnected
            anchors.right: parent.right; anchors.rightMargin: 36; y: 30
            width: offline.implicitWidth + 24; height: 28; radius: 14; color: glass.theme.control
            Label { id: offline; anchors.centerIn: parent; role: "caption"; secondary: true
                    text: "Offline — changes apply when Glass starts" }
        }
        Flickable {
            id: flick
            anchors.fill: parent; anchors.topMargin: 84
            contentHeight: pageLoader.height + 60
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickDeceleration: 4000
            Loader {
                id: pageLoader
                objectName: "pageLoader"
                x: 36; width: Math.min(760, flick.width - 72)
                source: root_.page + ".qml" === ".qml" ? "" : ({
                    appearance: "AppearancePage.qml", glass: "GlassPage.qml", topbar: "TopBarPage.qml", dock: "DockPage.qml",
                    notifications: "NotificationsPage.qml", applications: "ApplicationsPage.qml", system: "SystemPage.qml", markets: "MarketsPage.qml",
                    garvis: "GarvisPage.qml", about: "AboutPage.qml" })[root_.page]
                onLoaded: { flick.contentY = 0; item.width = Qt.binding(() => pageLoader.width); fade.restart() }
                NumberAnimation { id: fade; target: pageLoader; property: "opacity"; from: 0; to: 1; duration: 180 }
            }
            WheelHandler { onWheel: (e) => flick.flick(0, e.angleDelta.y * 6) }
        }
    }

    // ---- toast ---------------------------------------------------------------------------------------------
    Rectangle {
        id: toast
        property string text: ""
        function show(t) { text = t; opacity = 1; hide.restart() }
        x: (root_.width - width) / 2; y: root_.height - height - 24
        width: tl.implicitWidth + 32; height: 36; radius: 18
        color: glass.theme.dark ? "#F4F4F7" : "#1B1B20"
        opacity: 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Label { id: tl; anchors.centerIn: parent; role: "callout"; text: toast.text; color: glass.theme.dark ? "#16161A" : "white" }
        Timer { id: hide; interval: 2600; onTriggered: toast.opacity = 0 }
    }
}
