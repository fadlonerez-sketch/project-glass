import QtQuick
import "../components"

Column {
    id: page
    spacing: 24
    readonly property var perm: cc.permissions
    readonly property var scopes: (perm.clients && perm.clients.garvis) || []
    readonly property var deny: perm.deny_list || []
    readonly property var scopeInfo: [
        ["inspect", "See windows and controls", "List windows, read UI Automation trees, names and values (never password fields)"],
        ["act", "Use controls", "Invoke buttons, toggle, select, expand/collapse, scroll — without moving your mouse"],
        ["text", "Enter text", "Set the text of fields directly (no keystrokes)"],
        ["windows", "Manage windows", "Focus, move, resize, minimise, restore and close windows"],
        ["input", "Synthetic keyboard and mouse", "Keys and clicks for apps that expose too little; needs the window in front"]
    ]
    Component.onCompleted: { cc.refreshPermissions(); cc.refreshAudit() }

    Section {
        title: "Garvis computer control"
        Row_ {
            title: cc.engineConnected ? (page.perm.stopped ? "Paused by emergency stop" : "Engine running") : "Engine not running"
            subtitle: cc.engineConnected ? "Garvis uses Glass's semantic UI Automation engine — no screenshots, no OCR." : "Start Project Glass to enable computer control."
            Rectangle { width: 12; height: 12; radius: 6; anchors.verticalCenter: parent.verticalCenter
                        color: !cc.engineConnected ? glass.theme.text3 : page.perm.stopped ? glass.theme.warning : glass.theme.success }
        }
        Row_ {
            title: "Emergency stop"
            subtitle: "Immediately blocks every Garvis action. Hotkey: Ctrl+Alt+Shift+Q"
            last: true
            PushButton { visible: !page.perm.stopped; enabled: cc.engineConnected; text: "Stop Garvis control"; destructive: true; icon: "stop"
                         onClicked: cc.setStopped(true) }
            PushButton { visible: !!page.perm.stopped; text: "Resume"; primary: true; onClicked: cc.setStopped(false) }
        }
    }

    Section {
        title: "Permissions"
        footer: "Garvis still asks you before consequential actions (sending, deleting, paying, installing) through its own confirmations."
        Repeater {
            model: page.scopeInfo
            Row_ {
                title: modelData[1]; subtitle: modelData[2]; last: index === page.scopeInfo.length - 1
                Toggle { enabled: cc.engineConnected; checked: page.scopes.indexOf(modelData[0]) >= 0; accessibleName: modelData[1]
                         onToggled: (c) => cc.setScope(modelData[0], c) }
            }
        }
    }

    Section {
        title: "Never control these apps"
        footer: "Process names (e.g. keepass.exe). Glass's own Control Center is always protected."
        Repeater {
            model: page.deny
            Row_ { title: modelData; last: index === page.deny.length - 1
                   IconButton { icon: "close"; size: 28; iconSize: 12; tooltip: "Remove"
                                onClicked: cc.setDenyList(page.deny.filter(d => d !== modelData)) } }
        }
        Item {
            width: parent.width; height: 52
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 260; height: 32; radius: 8; color: glass.theme.dark ? glass.theme.surface2 : glass.theme.bg
                border.width: 1; border.color: denyIn.activeFocus ? glass.theme.accent : glass.theme.hairline
                TextInput { id: denyIn; anchors.fill: parent; anchors.margins: 8; color: glass.theme.text; font.pixelSize: 13
                            onAccepted: { if (text.trim()) { cc.setDenyList(page.deny.concat([text.trim()])); text = "" } } }
                Label { x: 8; anchors.verticalCenter: parent.verticalCenter; role: "callout"; tertiary: true; text: "app.exe"; visible: !denyIn.text }
            }
            PushButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: "Add"; icon: "plus"
                         enabled: cc.engineConnected; onClicked: denyIn.accepted() }
        }
    }

    Section {
        title: "Activity log"
        Repeater {
            model: cc.audit.slice(0, 60)
            Row_ {
                title: (modelData.method || "") + (modelData.target ? " · " + modelData.target : "")
                subtitle: (modelData.client || "") + " · " + Qt.formatDateTime(new Date((modelData.time || 0) * 1000), "d MMM HH:mm:ss")
                          + (modelData.detail ? " · " + modelData.detail : "")
                last: index === Math.min(cc.audit.length, 60) - 1
                Rectangle {
                    width: outcome.implicitWidth + 16; height: 22; radius: 11
                    color: modelData.outcome === "ok" ? Qt.rgba(0.2, 0.7, 0.4, 0.16) : Qt.rgba(0.9, 0.3, 0.3, 0.16)
                    Label { id: outcome; anchors.centerIn: parent; role: "caption"; text: modelData.outcome || ""
                            color: modelData.outcome === "ok" ? glass.theme.success : glass.theme.danger }
                }
            }
        }
        Item { width: parent.width; height: 44; visible: cc.audit.length === 0
               Label { anchors.verticalCenter: parent.verticalCenter; role: "callout"; tertiary: true; text: "No activity yet." } }
    }
}
