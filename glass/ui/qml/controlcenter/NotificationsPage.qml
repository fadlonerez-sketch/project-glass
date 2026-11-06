import QtQuick
import "../components"

Column {
    id: page
    spacing: 24
    readonly property var rules: cc.settings["notifications.apps"] || ({})
    readonly property string mirror: cc.status.mirror || "unavailable"
    function setRule(app, field, value) {
        var r = JSON.parse(JSON.stringify(page.rules))
        r[app] = r[app] || {}
        r[app][field] = value
        cc.set("notifications.apps", r)
    }

    Section {
        title: "Notifications"
        SettingToggle { title: "Allow notifications"; key: "notifications.enabled" }
        SettingToggle { title: "Do not disturb"; subtitle: "Only high-priority notifications are presented"; key: "notifications.dnd" }
        SettingChoice { title: "Presentation"; key: "notifications.presentation"
                        options: [["island", "Dynamic Glass"], ["banner", "Banner"], ["silent", "Silent"]] }
        SettingChoice { title: "Present at least"; subtitle: "Lower-priority ones go straight to the list"; key: "notifications.min_priority"
                        options: [["low", "Low"], ["normal", "Normal"], ["high", "High"]] }
        SettingToggle { title: "Garvis notifications"; subtitle: "Approval requests and errors from Garvis"; key: "notifications.garvis"; last: true }
    }

    Section {
        title: "Windows notifications"
        footer: page.mirror === "needs_identity"
            ? "Windows only lets apps with package identity read notifications. Run scripts\\install-identity.ps1 once (it creates a local signing certificate and trusts it for your account) — see docs\\NOTIFICATIONS.md. Until then Glass shows its own and Garvis's notifications."
            : page.mirror === "denied" ? "Windows denied access. Allow it in Settings › Privacy & security › Notifications." : ""
        SettingToggle { title: "Mirror Windows notifications"; key: "notifications.mirror_windows" }
        Row_ {
            title: "Status"
            subtitle: ({ active: "Active", needs_identity: "Needs package identity", denied: "Access denied", unavailable: "Unavailable" })[page.mirror] || page.mirror
            last: true
            PushButton { text: "Windows notification settings"; icon: "external"; onClicked: cc.openSettingsPage("notifications") }
        }
    }

    Section {
        title: "Per application"
        footer: "Rules apply by app name (Windows notifications report their app)."
        Repeater {
            model: Object.keys(page.rules)
            Row_ {
                title: modelData
                last: index === Object.keys(page.rules).length - 1
                Row {
                    spacing: 8
                    Segmented { options: [["low", "Low"], ["normal", "Normal"], ["high", "High"]]
                                value: page.rules[modelData].priority || "normal"
                                onPicked: (v) => page.setRule(modelData, "priority", v) }
                    Toggle { checked: page.rules[modelData].enabled !== false; accessibleName: modelData + " notifications"
                             onToggled: (c) => page.setRule(modelData, "enabled", c) }
                }
            }
        }
        Item {
            width: parent.width; height: 52
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 240; height: 32; radius: 8; color: glass.theme.dark ? glass.theme.surface2 : glass.theme.bg
                border.width: 1; border.color: appName.activeFocus ? glass.theme.accent : glass.theme.hairline
                TextInput { id: appName; anchors.fill: parent; anchors.margins: 8; color: glass.theme.text; font.pixelSize: 13
                            onAccepted: { if (text.trim()) { page.setRule(text.trim(), "enabled", true); text = "" } } }
                Label { x: 8; anchors.verticalCenter: parent.verticalCenter; role: "callout"; tertiary: true; text: "App name, e.g. WhatsApp"; visible: !appName.text }
            }
            PushButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: "Add rule"; icon: "plus"
                         onClicked: appName.accepted() }
        }
    }
}
