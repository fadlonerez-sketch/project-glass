import QtQuick
import "../components"

// Dock widgets. In the horizontal bar they are wide and low (they share the bar's thickness and read like part of
// it); in a vertical Dock they are compact squares. They never magnify.
Item {
    id: root
    property string type: "weather"
    property real iconSize: 38
    property bool wide: true
    signal activated(Item anchorItem)
    readonly property var w: glass.weather
    readonly property bool hasTemp: w.temperature !== undefined && w.temperature !== null
    readonly property string unit: "°"
    Accessible.role: Accessible.Button
    Accessible.name: type === "weather" ? "Weather" + (hasTemp ? ", " + Math.round(w.temperature) + " degrees, " + (w.condition || "") : "")
                    : type === "calendar" ? "Calendar, " + Qt.formatDate(now, "dddd d MMMM")
                    : type === "clock" ? "Clock, " + Qt.formatTime(now, "HH:mm")
                    : type === "system" ? "System load" : "Garvis"
    Accessible.onPressAction: root.activated(root)

    property date now: new Date()
    Timer {
        // minute precision everywhere except the analogue clock's second hand
        interval: root.type === "clock" && !root.wide ? 1000 : 1000 * (60 - new Date().getSeconds()) + 30
        running: root.type === "clock" || root.type === "calendar"
        repeat: true
        onTriggered: { root.now = new Date(); interval = root.type === "clock" && !root.wide ? 1000 : 60000 }
    }

    // hover plate: widgets are quiet until the pointer is on them
    Rectangle {
        anchors.fill: parent
        anchors.margins: root.wide ? 0 : 0
        radius: root.wide ? Math.min(12, height * 0.32) : root.iconSize * 0.26
        color: area.pressed ? glass.theme.control_pressed : area.containsMouse ? glass.theme.control_hover : (root.wide ? "transparent" : glass.theme.control)
        Behavior on color { ColorAnimation { duration: 140 } }
    }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.activated(root) }

    readonly property real big: Math.round(iconSize * 0.46)       // primary figure
    readonly property real pad: Math.round(iconSize * 0.24)

    // ================================================================== wide (horizontal bar)
    Item {
        visible: root.wide
        anchors.fill: parent

        // ---- weather: icon · temperature · condition / high-low
        Row {
            visible: root.type === "weather"
            anchors.verticalCenter: parent.verticalCenter
            x: root.pad
            spacing: root.iconSize * 0.2
            WeatherIcon { anchors.verticalCenter: parent.verticalCenter; size: root.iconSize * 0.74
                          kind: root.w.icon || "partly"; day: root.w.is_day !== false; opacity: root.hasTemp ? 1 : 0.45 }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: root.hasTemp ? Math.round(root.w.temperature) + root.unit : (root.w.needsSetup ? "" : "—")
                visible: text !== ""
                font.family: glass.theme.font_display; font.pixelSize: root.big; font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 0
                Label { role: "caption"; font.weight: Font.Medium; width: Math.min(implicitWidth, root.width * 0.42)
                        text: root.w.needsSetup ? "Weather" : root.w.error && !root.hasTemp ? "Offline" : (root.w.condition || "") }
                Label { role: "micro"; secondary: true
                        text: root.w.needsSetup ? "Choose your city" : (root.w.high !== undefined ? "H " + Math.round(root.w.high) + "°  L " + Math.round(root.w.low) + "°" : (root.w.place || "")) }
            }
        }

        // ---- calendar: date tile · weekday / month
        Row {
            visible: root.type === "calendar"
            anchors.verticalCenter: parent.verticalCenter
            x: root.pad
            spacing: root.iconSize * 0.24
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: root.iconSize * 0.72; height: root.iconSize * 0.8; radius: 7
                color: glass.theme.dark ? "#2B2B33" : "#FFFFFF"
                border.width: 1; border.color: glass.theme.hairline
                clip: true
                Rectangle { width: parent.width; height: parent.height * 0.32; color: glass.theme.accent
                    Label { anchors.centerIn: parent; font.pixelSize: Math.round(Math.max(7, parent.height * 0.62)); font.weight: Font.Bold
                            color: glass.theme.on_accent; text: Qt.formatDate(root.now, "ddd").toUpperCase() } }
                Label { anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.3; height: parent.height * 0.7
                        font.family: glass.theme.font_display; font.pixelSize: Math.round(parent.height * 0.44); font.weight: Font.DemiBold
                        text: root.now.getDate() }
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                Label { role: "callout"; font.weight: Font.DemiBold; text: Qt.formatDate(root.now, "dddd") }
                Label { role: "micro"; secondary: true; text: Qt.formatDate(root.now, "MMMM yyyy") }
            }
        }

        // ---- clock: time · date
        Column {
            visible: root.type === "clock"
            anchors.centerIn: parent
            spacing: -2
            Label { anchors.horizontalCenter: parent.horizontalCenter
                    text: Qt.formatTime(root.now, glass.settings["topbar.clock.format"] === "12h" ? "h:mm AP" : "HH:mm")
                    font.family: glass.theme.font_display; font.pixelSize: root.big; font.weight: Font.DemiBold; font.features: { "tnum": 1 } }
            Label { anchors.horizontalCenter: parent.horizontalCenter; role: "micro"; secondary: true; text: Qt.formatDate(root.now, "ddd d MMM") }
        }

        // ---- system: two slim meters
        Column {
            visible: root.type === "system"
            anchors.verticalCenter: parent.verticalCenter
            x: root.pad; width: parent.width - 2 * root.pad
            spacing: root.iconSize * 0.12
            Repeater {
                model: [{ label: "CPU", key: "cpu" }, { label: "Memory", key: "mem" }]
                Item {
                    width: parent.width; height: root.iconSize * 0.3
                    readonly property real v: (sysmon && sysmon.stats[modelData.key]) || 0
                    Label { id: ml; role: "micro"; secondary: true; text: modelData.label; width: root.iconSize * 1.15; anchors.verticalCenter: parent.verticalCenter }
                    Rectangle {
                        anchors.left: ml.right; anchors.right: pct.left; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
                        height: 4; radius: 2; color: glass.theme.track
                        Rectangle { width: parent.width * Math.max(0.03, parent.parent.v); height: parent.height; radius: 2
                                    color: parent.parent.v > 0.85 ? glass.theme.danger : glass.theme.accent
                                    Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } } }
                    }
                    Label { id: pct; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; role: "micro"; secondary: true
                            text: Math.round(parent.v * 100) + "%"; font.features: { "tnum": 1 }; width: root.iconSize * 0.7; horizontalAlignment: Text.AlignRight }
                }
            }
        }

        // ---- Garvis: orb · name / state
        Row {
            visible: root.type === "garvis"
            anchors.verticalCenter: parent.verticalCenter
            x: root.pad
            spacing: root.iconSize * 0.22
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: root.iconSize * 0.66; height: width; radius: width / 2
                gradient: Gradient {
                    GradientStop { position: 0; color: Qt.lighter(glass.theme.accent, 1.45) }
                    GradientStop { position: 1; color: glass.theme.accent }
                }
                border.width: glass.garvis.active ? 1.5 : 0; border.color: "white"
                Icon { anchors.centerIn: parent; name: "sparkle"; size: parent.width * 0.55; color: "white" }
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                Label { role: "callout"; font.weight: Font.DemiBold; text: "Garvis" }
                Row {
                    spacing: 5
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 6; height: 6; radius: 3
                                color: glass.garvis.engine ? (glass.garvis.stopped ? glass.theme.warning : glass.theme.success) : glass.theme.text3 }
                    Label { role: "micro"; secondary: true
                            text: !glass.garvis.engine ? "Offline" : glass.garvis.stopped ? "Stopped" : glass.garvis.active ? "Working · " + (glass.garvis.app || "") : "Ready" }
                }
            }
        }
    }

    // ================================================================== compact (vertical Dock)
    Item {
        visible: !root.wide
        anchors.fill: parent
        WeatherIcon { visible: root.type === "weather"; anchors.centerIn: parent; anchors.verticalCenterOffset: -root.iconSize * 0.1
                      size: root.iconSize * 0.56; kind: root.w.icon || "partly"; day: root.w.is_day !== false }
        Label { visible: root.type === "weather"; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 1
                role: "micro"; font.weight: Font.DemiBold; text: root.hasTemp ? Math.round(root.w.temperature) + "°" : "—" }
        Column {
            visible: root.type === "calendar"
            anchors.centerIn: parent
            Label { anchors.horizontalCenter: parent.horizontalCenter; role: "micro"; color: glass.theme.accent; font.weight: Font.Bold
                    text: Qt.formatDate(root.now, "ddd").toUpperCase() }
            Label { anchors.horizontalCenter: parent.horizontalCenter; font.family: glass.theme.font_display; font.pixelSize: Math.round(root.iconSize * 0.4)
                    font.weight: Font.DemiBold; text: root.now.getDate() }
        }
        Label { visible: root.type === "clock"; anchors.centerIn: parent; role: "caption"; font.weight: Font.DemiBold; font.features: { "tnum": 1 }
                text: Qt.formatTime(root.now, "HH:mm") }
        Column {
            visible: root.type === "system"
            anchors.centerIn: parent; spacing: 3
            Repeater {
                model: ["cpu", "mem"]
                Rectangle { width: root.iconSize * 0.6; height: 4; radius: 2; color: glass.theme.track
                    Rectangle { width: parent.width * Math.max(0.03, (sysmon && sysmon.stats[modelData]) || 0); height: 4; radius: 2; color: glass.theme.accent } }
            }
        }
        Rectangle {
            visible: root.type === "garvis"
            anchors.centerIn: parent
            width: root.iconSize * 0.66; height: width; radius: width / 2
            gradient: Gradient { GradientStop { position: 0; color: Qt.lighter(glass.theme.accent, 1.45) } GradientStop { position: 1; color: glass.theme.accent } }
            Icon { anchors.centerIn: parent; name: "sparkle"; size: parent.width * 0.55; color: "white" }
        }
    }
}
