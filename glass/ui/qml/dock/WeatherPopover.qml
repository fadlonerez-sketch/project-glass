import QtQuick
import "../components"
import "../components/Motion.js" as Motion

// Expanded weather: now, feels-like, high/low, humidity, wind, the next hours and the coming days.
GlassPanel {
    id: pop
    property var dockWindow
    property Item backdropSource: null
    readonly property var w: glass.weather
    readonly property string unit: glass.settings["weather.units"] === "f" ? "°F" : "°C"
    tone: "elevated"; margin: 26; radius: 24; padding: 16
    backdropItem: backdropSource
    width: 340 + 2 * (margin + padding)
    height: col.implicitHeight + 2 * (margin + padding)
    visible: opacity > 0.01
    opacity: 0
    scale: 0.96
    Behavior on opacity { OpacityAnimator { duration: Motion.ms(glass.theme, 160) } }
    Behavior on scale { ScaleAnimator { duration: Motion.ms(glass.theme, 220); easing.type: Easing.OutCubic } }
    MouseArea { anchors.fill: parent }

    function openFor(item) {
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

    Column {
        id: col
        width: 340
        spacing: 12

        Item {
            visible: !!pop.w.needsSetup
            width: parent.width; height: 120
            Column {
                anchors.centerIn: parent; spacing: 10
                WeatherIcon { anchors.horizontalCenter: parent.horizontalCenter; size: 44; kind: "partly" }
                Label { anchors.horizontalCenter: parent.horizontalCenter; role: "headline"; text: "Choose your city" }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 160; height: 30; radius: 15; color: glass.theme.accent
                    Label { anchors.centerIn: parent; role: "callout"; color: glass.theme.on_accent; text: "Open Weather settings" }
                    MouseArea { anchors.fill: parent; onClicked: { pop.close(); glass.openControlCenter("dock") } }
                }
            }
        }

        Item {
            visible: !pop.w.needsSetup
            width: parent.width; height: 88
            Column {
                Label { role: "callout"; secondary: true; text: pop.w.place || glass.settings["weather.city"] || "" }
                Label { text: pop.w.temperature !== undefined ? Math.round(pop.w.temperature) + "°" : "—"
                        font.family: glass.theme.font_display; font.pixelSize: 46; font.weight: Font.Light }
            }
            Column {
                anchors.right: parent.right; anchors.top: parent.top
                spacing: 2
                WeatherIcon { anchors.right: parent.right; size: 42; kind: pop.w.icon || "partly"; day: pop.w.is_day !== false }
                Label { anchors.right: parent.right; role: "callout"; text: pop.w.condition || "" }
                Label { anchors.right: parent.right; role: "caption"; secondary: true
                        text: pop.w.high !== undefined && pop.w.high !== null ? "H:" + Math.round(pop.w.high) + "°  L:" + Math.round(pop.w.low) + "°" : "" }
            }
        }

        Row {
            visible: !pop.w.needsSetup && glass.settings["weather.details"]
            spacing: 8
            Repeater {
                model: [
                    { icon: "sun", label: "Feels like", value: pop.w.apparent !== undefined ? Math.round(pop.w.apparent) + "°" : "—" },
                    { icon: "drop", label: "Humidity", value: pop.w.humidity !== undefined && pop.w.humidity !== null ? pop.w.humidity + "%" : "—" },
                    { icon: "wind", label: "Wind", value: pop.w.wind !== undefined && pop.w.wind !== null ? Math.round(pop.w.wind) + (glass.settings["weather.units"] === "f" ? " mph" : " km/h") : "—" }
                ]
                Rectangle {
                    width: (340 - 16) / 3; height: 58; radius: 12; color: glass.theme.control
                    Column { x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                        Row { spacing: 4
                            Icon { name: modelData.icon; size: 12; color: glass.theme.text3 }
                            Label { role: "micro"; tertiary: true; text: modelData.label.toUpperCase() } }
                        Label { role: "headline"; text: modelData.value } }
                }
            }
        }

        Rectangle {
            visible: !pop.w.needsSetup && (pop.w.hourly || []).length > 0
            width: parent.width; height: 92; radius: 14; color: glass.theme.control
            Row {
                anchors.centerIn: parent
                spacing: 4
                Repeater {
                    model: (pop.w.hourly || []).slice(0, 6)
                    Column {
                        width: 50; spacing: 4
                        Label { anchors.horizontalCenter: parent.horizontalCenter; role: "caption"; secondary: true
                                text: index === 0 ? "Now" : modelData.time.slice(11, 13) }
                        WeatherIcon { anchors.horizontalCenter: parent.horizontalCenter; size: 26; kind: modelData.icon; day: modelData.is_day }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; role: "callout"; font.weight: Font.DemiBold
                                text: Math.round(modelData.temperature) + "°" }
                    }
                }
            }
        }

        Column {
            visible: !pop.w.needsSetup && (pop.w.daily || []).length > 1
            width: parent.width
            spacing: 2
            Repeater {
                model: (pop.w.daily || []).slice(1, 5)
                Item {
                    width: parent.width; height: 30
                    Label { role: "callout"; width: 70; anchors.verticalCenter: parent.verticalCenter
                            text: Qt.formatDate(new Date(modelData.date + "T12:00:00"), "dddd") }
                    WeatherIcon { x: 90; anchors.verticalCenter: parent.verticalCenter; size: 22; kind: modelData.icon }
                    Label { x: 124; role: "caption"; secondary: true; anchors.verticalCenter: parent.verticalCenter; text: modelData.condition; width: 110 }
                    Label { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; role: "callout"
                            text: Math.round(modelData.low) + "°  " + Math.round(modelData.high) + "°" }
                }
            }
        }

        Label {
            visible: !!pop.w.error || !!pop.w.stale
            width: parent.width; wrapMode: Text.Wrap; role: "caption"; color: glass.theme.warning
            text: pop.w.stale ? "Showing the last known weather (offline)." : (pop.w.error || "")
        }
        Label { role: "micro"; tertiary: true; text: "Weather data: Open-Meteo.com" }
    }
}
