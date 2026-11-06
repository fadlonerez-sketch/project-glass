import QtQuick
import "../components"

// The expanded control center inside the Dynamic Glass (opened by clicking the pill).
Item {
    id: root
    implicitHeight: col.implicitHeight
    readonly property var s: glass.settings
    readonly property var net: glass.network
    readonly property real half: (width - 10) / 2

    Column {
        id: col
        width: parent.width
        spacing: 10

        // Row 1: connectivity + now playing
        Row {
            spacing: 10
            Column {
                spacing: 10
                width: root.half
                ControlTile {
                    width: parent.width
                    icon: "globe"
                    title: root.net.kind === "wifi" ? "Wi-Fi" : root.net.kind === "ethernet" ? "Ethernet" : "Network"
                    subtitle: root.net.internet ? (root.net.ssid || root.net.name || "Connected") : "Not connected"
                    active: !!root.net.internet
                    showChevron: true
                    onClicked: glass.openSettingsPage(root.net.kind === "wifi" ? "wifi" : "network")
                    onChevronClicked: glass.openSettingsPage("wifi_networks")
                }
                ControlTile {
                    width: parent.width
                    icon: "bluetooth"; title: "Bluetooth"; subtitle: "Devices & pairing"
                    onClicked: glass.openSettingsPage("bluetooth")
                }
            }
            Rectangle {
                width: root.half; height: 118; radius: 16
                color: glass.theme.control
                Rectangle {
                    id: art
                    x: 12; y: 12; width: 44; height: 44; radius: 10
                    color: glass.theme.track; clip: true
                    Image { anchors.fill: parent; source: glass.media.artworkUrl || ""; fillMode: Image.PreserveAspectCrop
                            asynchronous: true; mipmap: true; visible: status === Image.Ready }
                    Icon { anchors.centerIn: parent; name: "sparkle"; size: 18; color: glass.theme.text3; visible: !glass.media.artworkUrl }
                }
                Column {
                    anchors.left: art.right; anchors.leftMargin: 10; anchors.right: parent.right; anchors.rightMargin: 10
                    y: 14; spacing: 1
                    Label { width: parent.width; role: "callout"; font.weight: Font.DemiBold
                            text: glass.media.present ? (glass.media.title || "Unknown") : "Not Playing" }
                    Label { width: parent.width; role: "caption"; secondary: true; text: glass.media.artist || glass.media.appName || "" }
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter; y: 70; spacing: 14
                    opacity: glass.media.present ? 1 : 0.35
                    IconButton { icon: "previous"; size: 34; iconSize: 15; onClicked: glass.previousTrack(); tooltip: "Previous" }
                    IconButton { icon: glass.media.playing ? "pause" : "play"; size: 38; iconSize: 19; onClicked: glass.playPause()
                                 tooltip: glass.media.playing ? "Pause" : "Play" }
                    IconButton { icon: "next"; size: 34; iconSize: 15; onClicked: glass.nextTrack(); tooltip: "Next" }
                }
            }
        }

        // Row 2: appearance + Garvis
        Row {
            spacing: 10
            ControlTile {
                width: root.half
                icon: glass.theme.dark ? "moon" : "sun"
                title: s["appearance.theme"] === "adaptive" ? "Adaptive" : s["appearance.theme"] === "dark" ? "Dark" : "Light"
                subtitle: "Appearance"
                active: glass.theme.dark
                onClicked: {
                    var order = ["adaptive", "light", "dark"]
                    glass.setSetting("appearance.theme", order[(order.indexOf(s["appearance.theme"]) + 1) % 3])
                }
            }
            ControlTile {
                width: root.half
                icon: glass.garvis.stopped ? "stop" : "sparkle"
                title: "Garvis"
                subtitle: !glass.garvis.engine ? "Control engine offline"
                          : glass.garvis.stopped ? "Control paused — tap to resume"
                          : glass.garvis.active ? "Using " + (glass.garvis.app || "an app") + " — tap to stop"
                          : "Ready"
                active: glass.garvis.engine && !glass.garvis.stopped
                enabled: !!glass.garvis.engine
                onClicked: glass.garvis.stopped ? glass.resumeControl() : glass.emergencyStop()
            }
        }

        // Sliders
        Column {
            width: parent.width
            spacing: 6
            Label { role: "caption"; secondary: true; text: "Liquid Glass"; leftPadding: 4 }
            GlassSlider {
                width: parent.width; icon: "glass"; accessibleName: "Liquid Glass intensity"
                value: s["glass.intensity"]; live: true
                onMoved: (v) => glass.setSetting("glass.intensity", Math.round(v * 100) / 100)
            }
            Label { role: "caption"; secondary: true; text: "Display"; leftPadding: 4; visible: glass.brightness >= 0 }
            GlassSlider {
                visible: glass.brightness >= 0
                width: parent.width; icon: "brightness"; accessibleName: "Brightness"
                value: glass.brightness / 100; live: false
                onMoved: (v) => glass.setBrightness(Math.round(v * 100))
            }
            Label { role: "caption"; secondary: true; text: "Sound" + (glass.audio.device ? " · " + glass.audio.device : ""); leftPadding: 4 }
            GlassSlider {
                width: parent.width; accessibleName: "Volume"
                enabled: !!glass.audio.available
                value: glass.audio.muted ? 0 : (glass.audio.volume || 0)
                iconComponent: Component { SpeakerIcon { size: 15; color: "#5A5A64"; level: glass.audio.volume || 0; muted: !!glass.audio.muted } }
                onMoved: (v) => { if (glass.audio.muted && v > 0) glass.setMuted(false); glass.setVolume(v) }
            }
        }

        // Footer: shortcuts on the left, the master power switch on the right
        Item {
            width: parent.width; height: 34
            Rectangle {
                id: powerBtn
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                width: pRow.implicitWidth + 26; height: 32; radius: 16
                color: pwr.pressed ? glass.theme.control_pressed : pwr.containsMouse ? glass.theme.control_hover : glass.theme.control
                border.width: 1; border.color: glass.theme.hairline
                Row { id: pRow; anchors.centerIn: parent; spacing: 7
                      Icon { anchors.verticalCenter: parent.verticalCenter; name: "power"; size: 14; color: glass.theme.danger; strokeWidth: 2.1 }
                      Label { anchors.verticalCenter: parent.verticalCenter; role: "callout"; font.weight: Font.DemiBold; text: "Turn Glass off" } }
                MouseArea { id: pwr; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: glass.setPower(false)
                            Accessible.role: Accessible.Button; Accessible.name: "Turn Project Glass off" }
            }
        Row {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            IconButton { icon: "gear"; filled: true; tooltip: "Control Center"; onClicked: glass.openControlCenter("") }
            IconButton { icon: "search"; filled: true; tooltip: "Search apps (LaunchDeck)"; onClicked: glass.openLauncher() }
            IconButton { icon: "tray"; filled: true; tooltip: "Show Windows tray"; onClicked: glass.revealTray() }
            IconButton { icon: "bell"; filled: true; tooltip: "Notification settings"; onClicked: glass.openControlCenter("notifications") }
        }
        }
    }
}
