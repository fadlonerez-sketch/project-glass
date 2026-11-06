import QtQuick
import "../components"

Column {
    spacing: 24
    readonly property var st: cc.status
    Component.onCompleted: cc.refreshStatus()

    Section {
        title: "Project Glass"
        Row_ {
            title: cc.shellConnected ? "Running" : "Not running"
            subtitle: cc.shellConnected ? "Version " + (st.version || "") + " · " + (st.screens || []).length + " display(s)" : "The top bar and Dock aren't on screen."
            PushButton { visible: !cc.shellConnected; text: "Start Project Glass"; primary: true; onClicked: cc.startGlass() }
            PushButton { visible: cc.shellConnected; text: "Quit"; onClicked: cc.shellCommand("quit") }
        }
        SettingToggle { title: "Start with Windows"; key: "system.start_with_windows" }
        SettingToggle { title: "Hide the Windows taskbar while Glass runs"; subtitle: "Reversible: restored automatically when Glass quits or stops unexpectedly"; key: "system.hide_taskbar" }
        SettingToggle { title: "Reserve screen space"; subtitle: "Maximised windows stop short of the top bar and the Dock (full-screen apps still use the whole display)"; key: "system.reserve_space"; last: true }
    }

    Section {
        title: "Recovery"
        footer: "Recovery hotkey: Ctrl+Alt+Shift+R restores the standard Windows desktop at any time, even if Glass stops responding. The Start menu also has a “Restore Windows Desktop” shortcut."
        Row_ {
            title: "Restore the Windows desktop"
            subtitle: "Quits Glass and brings back the Windows taskbar"
            PushButton { text: "Restore now"; icon: "restore"; destructive: true; onClicked: cc.restoreWindows() }
        }
        Row_ {
            title: "Windows tray icons"; subtitle: "Show the Windows taskbar for a moment to reach notification-area icons"
            last: true
            PushButton { text: "Show tray"; icon: "tray"; enabled: cc.shellConnected; onClicked: cc.shellCommand("reveal_tray") }
        }
    }

    Section {
        title: "Display"
        Row_ { title: "Brightness"; subtitle: st.brightness >= 0 ? st.brightness + "% (adjust from the Dynamic Glass)" : "Not available for this display"
               PushButton { text: "Display settings"; icon: "external"; onClicked: cc.openSettingsPage("display") } }
        Row_ { title: "Night light"; last: true
               PushButton { text: "Open"; icon: "external"; onClicked: cc.openSettingsPage("night_light") } }
    }
    Section {
        title: "Battery"
        Row_ { title: st.power && st.power.present ? st.power.percent + "%" + (st.power.charging ? " · charging" : st.power.plugged ? " · plugged in" : "") : "No battery"
               subtitle: st.power && st.power.health ? "Battery health " + st.power.health + "%" : ""
               PushButton { text: "Battery settings"; icon: "external"; onClicked: cc.openSettingsPage("battery") } }
        Row_ { title: "Power mode & sleep"; last: true
               PushButton { text: "Open"; icon: "external"; onClicked: cc.openSettingsPage("power") } }
    }
    Section {
        title: "Network"
        Row_ { title: st.network ? (st.network.ssid || st.network.name || "Not connected") : "—"
               subtitle: st.network ? (st.network.internet ? "Connected to the internet" : "No internet") : ""
               PushButton { text: "Network settings"; icon: "external"; onClicked: cc.openSettingsPage("network") } }
        Row_ { title: "Bluetooth"; last: true
               PushButton { text: "Open"; icon: "external"; onClicked: cc.openSettingsPage("bluetooth") } }
    }
    Section {
        title: "Sound"
        Row_ { title: st.audio && st.audio.device ? st.audio.device : "No output device"
               subtitle: st.audio && st.audio.available ? "Volume " + Math.round(st.audio.volume * 100) + "%" + (st.audio.muted ? " · muted" : "") : ""
               PushButton { text: "Sound settings"; icon: "external"; onClicked: cc.openSettingsPage("sound") } }
        Row_ { title: "Volume mixer"; last: true
               PushButton { text: "Open"; icon: "external"; onClicked: cc.openSettingsPage("volume_mixer") } }
    }
}
