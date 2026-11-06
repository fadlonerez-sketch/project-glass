import QtQuick
import "../components"

// Content of the status flyouts. `kind`: network | battery | audio | clock | glass | power
Item {
    id: root
    property string kind: ""
    property var hostWindow: null
    signal close()
    implicitWidth: 320
    implicitHeight: loader.item ? loader.item.implicitHeight : 0

    Loader {
        id: loader
        width: parent.width
        sourceComponent: ({ network: networkC, battery: batteryC, audio: audioC, clock: clockC, glass: glassC, power: powerC })[root.kind] || null
    }

    component Header: Row {
        property string title
        property alias trailing: trail.data
        width: parent ? parent.width : 0
        height: 30
        Label { role: "headline"; text: parent.title; width: parent.width - trail.width; anchors.verticalCenter: parent.verticalCenter }
        Item { id: trail; width: childrenRect.width; height: parent.height }
    }
    component Row2: Item {
        property string label; property string value
        width: parent ? parent.width : 0; height: 22
        Label { role: "callout"; secondary: true; text: parent.label; anchors.verticalCenter: parent.verticalCenter }
        Label { role: "callout"; text: parent.value; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter }
    }
    component LinkRow: Item {
        property string text; property string icon: "external"
        signal activated()
        width: parent ? parent.width : 0; height: 34
        Rectangle { anchors.fill: parent; radius: 10; color: la.containsMouse ? glass.theme.control_hover : "transparent" }
        Label { x: 10; role: "callout"; text: parent.text; anchors.verticalCenter: parent.verticalCenter }
        Icon { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
               name: parent.icon; size: 14; color: glass.theme.text3 }
        MouseArea { id: la; anchors.fill: parent; hoverEnabled: true; onClicked: parent.activated()
                    Accessible.role: Accessible.Link; Accessible.name: parent.text }
    }
    component Sep: Rectangle { width: parent ? parent.width : 0; height: 1; color: glass.theme.separator }

    // ------------------------------------------------------------------ network
    Component {
        id: networkC
        Column {
            spacing: 8
            property string pwFor: ""
            Component.onCompleted: glass.scanWifi()
            Header {
                title: "Network"
                trailing: [
                    Toggle { anchors.verticalCenter: parent.verticalCenter; accessibleName: "Wi-Fi"
                             checked: glass.network.kind === "wifi"; onToggled: (c) => glass.setWifiEnabled(c) }
                ]
            }
            Rectangle {
                width: parent.width; height: 52; radius: 12; color: glass.theme.control
                WifiIcon { x: 12; anchors.verticalCenter: parent.verticalCenter; size: 20; kind: glass.network.kind || "none"
                           bars: glass.network.bars || 0; internet: !!glass.network.internet; color: glass.theme.accent }
                Column {
                    x: 44; anchors.verticalCenter: parent.verticalCenter
                    Label { role: "callout"; font.weight: Font.DemiBold; text: glass.network.ssid || glass.network.name || "Not connected" }
                    Label { role: "caption"; secondary: true
                            text: glass.network.internet ? "Connected" : glass.network.level === "local" ? "No internet" : "Disconnected" }
                }
            }
            Label { role: "caption"; tertiary: true; text: glass.wifiStatus.scanning ? "Looking for networks…" : "Other networks" }
            Label { role: "caption"; color: glass.theme.warning; width: parent.width; wrapMode: Text.Wrap
                    visible: !!glass.wifiStatus.error; text: glass.wifiStatus.error || "" }
            Label { role: "caption"; width: parent.width; wrapMode: Text.Wrap
                    visible: !!(glass.wifiStatus.result && !glass.wifiStatus.result.ok)
                    color: glass.theme.danger; text: glass.wifiStatus.result ? (glass.wifiStatus.result.error || "") : "" }
            ListView {
                width: parent.width; height: Math.min(contentHeight, 220); clip: true
                model: glass.wifiNetworks
                spacing: 2
                delegate: Item {
                    width: ListView.view.width; height: rowPw.visible ? 76 : 36
                    Rectangle { anchors.fill: parent; radius: 10; color: na.containsMouse ? glass.theme.control_hover : "transparent" }
                    WifiIcon { x: 10; y: 9; size: 17; bars: modelData.bars; color: glass.theme.text }
                    Label { x: 38; y: 9; role: "callout"; text: modelData.ssid; width: parent.width - 90
                            font.weight: modelData.connected ? Font.DemiBold : Font.Normal }
                    Icon { anchors.right: parent.right; anchors.rightMargin: 12; y: 10; name: modelData.connected ? "check" : (modelData.secured ? "lock" : "")
                           size: 14; color: modelData.connected ? glass.theme.accent : glass.theme.text3 }
                    MouseArea {
                        id: na; anchors.fill: parent; anchors.bottomMargin: rowPw.visible ? 40 : 0; hoverEnabled: true
                        onClicked: {
                            if (modelData.connected) return
                            if (modelData.secured) { col.pwFor = modelData.ssid; glass.requestKeyboard(root.hostWindow, true); pw.forceActiveFocus() }
                            else glass.connectWifi(modelData.ssid, "")
                        }
                    }
                    Row {
                        id: rowPw
                        visible: col.pwFor === modelData.ssid
                        x: 10; y: 38; spacing: 6
                        Rectangle {
                            width: 200; height: 30; radius: 8; color: glass.theme.surface; border.color: glass.theme.accent; border.width: 1
                            TextInput { id: pw; anchors.fill: parent; anchors.margins: 7; echoMode: TextInput.Password
                                        color: glass.theme.text; font.pixelSize: 13; clip: true
                                        onAccepted: { glass.connectWifi(modelData.ssid, text); glass.requestKeyboard(root.hostWindow, false); col.pwFor = "" } }
                        }
                        IconButton { icon: "check"; size: 30; filled: true; onClicked: pw.accepted() }
                    }
                }
            }
            Sep {}
            LinkRow { text: "Network & Internet settings"; onActivated: glass.openSettingsPage("network") }
            id: col
        }
    }

    // ------------------------------------------------------------------ battery
    Component {
        id: batteryC
        Column {
            spacing: 8
            readonly property var pw: glass.power
            Header { title: "Battery" }
            Row {
                spacing: 14
                BatteryIcon { size: 30; percent: pw.percent || 0; charging: !!pw.charging; plugged: !!pw.plugged; saver: !!pw.saver
                              anchors.verticalCenter: parent.verticalCenter }
                Column {
                    Label { role: "title"; text: (pw.percent || 0) + "%" }
                    Label { role: "caption"; secondary: true
                            text: pw.charging ? "Charging" : pw.plugged ? "Plugged in, not charging"
                                : pw.remaining_min ? Math.floor(pw.remaining_min / 60) + " h " + (pw.remaining_min % 60) + " min remaining" : "On battery" }
                }
            }
            Sep {}
            Row2 { label: "Battery saver"; value: pw.saver ? "On" : "Off" }
            Row2 { label: "Battery health"; value: pw.health ? pw.health + "%" : "—"; visible: !!pw.health }
            Row2 { label: pw.charging ? "Charging rate" : "Power draw"; value: pw.rate_w !== null && pw.rate_w !== undefined ? Math.abs(pw.rate_w) + " W" : "—" }
            Sep {}
            LinkRow { text: "Battery saver settings"; onActivated: glass.openSettingsPage("battery") }
            LinkRow { text: "Power & sleep settings"; onActivated: glass.openSettingsPage("power") }
        }
    }

    // ------------------------------------------------------------------ audio
    Component {
        id: audioC
        Column {
            spacing: 10
            Header {
                title: "Sound"
                trailing: [
                    Toggle { anchors.verticalCenter: parent.verticalCenter; accessibleName: "Sound on"
                             checked: !glass.audio.muted; enabled: !!glass.audio.available; onToggled: (c) => glass.setMuted(!c) }
                ]
            }
            GlassSlider {
                width: parent.width; accessibleName: "Volume"; enabled: !!glass.audio.available
                value: glass.audio.muted ? 0 : (glass.audio.volume || 0)
                iconComponent: Component { SpeakerIcon { size: 15; color: "#5A5A64"; level: glass.audio.volume || 0; muted: !!glass.audio.muted } }
                onMoved: (v) => { if (glass.audio.muted && v > 0) glass.setMuted(false); glass.setVolume(v) }
            }
            Rectangle {
                width: parent.width; height: 44; radius: 12; color: glass.theme.control
                Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "speaker"; size: 16; color: glass.theme.accent }
                Label { x: 38; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 50; role: "callout"
                        text: glass.audio.device || "No output device" }
            }
            Label { role: "caption"; tertiary: true; width: parent.width; wrapMode: Text.Wrap
                    text: "Windows has no supported API for switching output devices, so that happens in Sound settings." }
            Sep {}
            LinkRow { text: "Output device & sound settings"; onActivated: glass.openSettingsPage("sound") }
            LinkRow { text: "Volume mixer"; onActivated: glass.openSettingsPage("volume_mixer") }
        }
    }

    // ------------------------------------------------------------------ clock: calendar + notifications
    Component {
        id: clockC
        Column {
            spacing: 10
            property date today: new Date()
            Label { role: "title"; text: Qt.formatDate(today, "dddd, d MMMM") }
            Grid {
                id: cal
                columns: 7; columnSpacing: 0; rowSpacing: 2
                property date first: new Date(today.getFullYear(), today.getMonth(), 1)
                property int offset: (first.getDay() + 6) % 7
                property int days: new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate()
                Repeater {
                    model: ["M", "T", "W", "T", "F", "S", "S"]
                    Label { width: 44; horizontalAlignment: Text.AlignHCenter; role: "micro"; tertiary: true; text: modelData }
                }
                Repeater {
                    model: 42
                    Item {
                        width: 44; height: 28
                        property int day: index - cal.offset + 1
                        visible: day >= 1 && day <= cal.days || index < 35
                        Rectangle { anchors.centerIn: parent; width: 26; height: 26; radius: 13; color: glass.theme.accent
                                    visible: parent.day === today.getDate() }
                        Label { anchors.centerIn: parent; role: "callout"; text: parent.day >= 1 && parent.day <= cal.days ? parent.day : ""
                                color: parent.day === today.getDate() ? glass.theme.on_accent : glass.theme.text }
                    }
                }
            }
            Sep {}
            Item {
                width: parent.width; height: 24
                Label { role: "headline"; text: "Notifications"; anchors.verticalCenter: parent.verticalCenter }
                Label { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; role: "caption"
                        color: glass.theme.accent_text; text: "Clear"; visible: glass.notifications.length > 0
                        MouseArea { anchors.fill: parent; onClicked: glass.clearNotifications() } }
            }
            Label { visible: glass.notifications.length === 0; role: "callout"; tertiary: true; text: "No notifications" }
            ListView {
                width: parent.width; height: Math.min(contentHeight, 240); clip: true; spacing: 6
                model: glass.notifications
                delegate: Rectangle {
                    width: ListView.view.width; height: nc.implicitHeight + 16; radius: 12; color: glass.theme.control
                    Column { id: nc; x: 12; y: 8; width: parent.width - 24; spacing: 1
                        Label { width: parent.width; role: "caption"; tertiary: true
                                text: (modelData.app || "") + " · " + Qt.formatTime(new Date(modelData.time * 1000), "HH:mm") }
                        Label { width: parent.width; role: "callout"; font.weight: Font.DemiBold; text: modelData.title || "" }
                        Label { width: parent.width; role: "caption"; secondary: true; text: modelData.body || ""; visible: text !== ""
                                wrapMode: Text.Wrap; maximumLineCount: 3 } }
                }
            }
            Label {
                width: parent.width; wrapMode: Text.Wrap; role: "caption"; tertiary: true
                visible: glass.mirrorStatus === "needs_identity"
                text: "Showing Glass and Garvis notifications. To mirror all Windows notifications, run scripts\\install-identity.ps1 (see docs)."
            }
        }
    }

    // ------------------------------------------------------------------ Glass menu (the mark at the left)
    Component {
        id: glassC
        Column {
            spacing: 2
            Row {
                spacing: 10; height: 46
                Rectangle { width: 34; height: 34; radius: 10; anchors.verticalCenter: parent.verticalCenter
                            gradient: Gradient { GradientStop { position: 0; color: Qt.lighter(glass.theme.accent, 1.3) }
                                                 GradientStop { position: 1; color: glass.theme.accent } }
                            Icon { anchors.centerIn: parent; name: "glass"; size: 18; color: "white" } }
                Column { anchors.verticalCenter: parent.verticalCenter
                    Label { role: "headline"; text: "Project Glass" }
                    Label { role: "caption"; secondary: true; text: "Your desktop, refined" } }
            }
            Sep {}
            LinkRow { text: "Control Center…"; icon: "gear"; onActivated: glass.openControlCenter("") }
            LinkRow { text: "Search apps"; icon: "search"; onActivated: glass.openLauncher() }
            LinkRow { text: "Show Windows tray"; icon: "tray"; onActivated: glass.revealTray() }
            Sep {}
            LinkRow { text: "Turn Glass off"; icon: "power"; onActivated: glass.setPower(false) }
            LinkRow { text: "Restore Windows desktop"; icon: "restore"; onActivated: glass.restoreWindowsDesktop() }
        }
    }

    // ------------------------------------------------------------------ the master power switch
    Component {
        id: powerC
        Column {
            spacing: 12
            Header { title: "Project Glass" }
            Rectangle {
                width: parent.width; height: 92; radius: 18
                color: glass.theme.control
                Rectangle {
                    id: pbtn
                    x: 14; anchors.verticalCenter: parent.verticalCenter
                    width: 60; height: 60; radius: 30
                    color: pa.pressed ? Qt.darker(glass.theme.accent, 1.15) : glass.theme.accent
                    border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.25)
                    Icon { anchors.centerIn: parent; name: "power"; size: 26; color: glass.theme.on_accent; strokeWidth: 2.2 }
                    MouseArea { id: pa; anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: glass.setPower(false)
                                Accessible.role: Accessible.Button; Accessible.name: "Turn Project Glass off" }
                }
                Column {
                    anchors.left: pbtn.right; anchors.leftMargin: 14; anchors.right: parent.right; anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Label { role: "headline"; text: glass.powerBusy ? "Switching…" : "Glass is on" }
                    Label { width: parent.width; role: "caption"; secondary: true; wrapMode: Text.Wrap; maximumLineCount: 3
                            text: "Turning it off brings back the Windows taskbar and the full screen. Your settings are kept." }
                }
            }
            Label { width: parent.width; role: "caption"; tertiary: true; wrapMode: Text.Wrap
                    text: "Turn it back on from Glass Control Center, the Start menu (Project Glass) or Ctrl+Alt+Shift+G." }
        }
    }
}
