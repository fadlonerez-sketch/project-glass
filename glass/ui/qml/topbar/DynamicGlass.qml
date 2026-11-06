import QtQuick
import "../components"
import "../components/Motion.js" as Motion

// The Dynamic Glass pill. Its size, radius and content follow glass.state:
//   idle, media, media_expanded (hover), notification, activity, garvis, controls, control_center (click).
GlassSurface {
    id: pill
    property real barHeight: 32
    property Item backdropSource: null
    property bool primary: true
    readonly property string st: glass.state === "controls" ? (glass.media.present && glass.settings["topbar.media.enabled"] ? "media" : "idle") : glass.state
    readonly property var p: glass.statePayload
    readonly property var spring: Motion.spring(glass.settings["topbar.animation"])
    readonly property bool hovering: hover.hovered
    readonly property real compactH: barHeight - 6
    readonly property size target: {
        switch (st) {
        case "media": return Qt.size((glass.settings["topbar.media.artwork"] ? 268 : 236) + (hovering ? 14 : 0), compactH + (hovering ? 2 : 0))
        case "media_expanded": return Qt.size(404, 172)
        case "notification": return Qt.size(392, 68)
        case "activity": return Qt.size(p.kind === "network" ? 288 : 252, compactH + 4)
        case "garvis": return Qt.size(318, compactH + 4)
        case "control_center": return Qt.size(468, panel.implicitHeight + 28)
        default: return Qt.size(hovering ? 132 : 116, compactH)
        }
    }
    readonly property real targetRadius: st === "control_center" ? 34 : st === "media_expanded" ? 32
                                         : st === "notification" ? 28 : target.height / 2

    // The pill is deep smoked glass; opening the control center turns it into a theme-coloured sheet.
    tone: st === "control_center" ? "elevated" : "deep"
    Behavior on tintColor { ColorAnimation { duration: Motion.ms(glass.theme, 240) } }
    backdropItem: backdropSource
    margin: 30
    elevation: st === "idle" || st === "media" ? 0.12 : 1.0
    glow: st === "garvis" ? 0.9 : 0
    Behavior on glow { NumberAnimation { duration: 400 } }
    width: shapeW + 2 * margin
    height: shapeH + 2 * margin
    radius: shapeR
    property real shapeW: target.width
    property real shapeH: target.height
    property real shapeR: targetRadius
    lightPoint: hover.hovered ? hover.point.position : Qt.point(-1, -1)
    lightStrength: hover.hovered ? 0.85 : 0
    Behavior on shapeW { SpringAnimation { spring: pill.spring.spring; damping: pill.spring.damping; epsilon: 0.2 } }
    Behavior on shapeH { SpringAnimation { spring: pill.spring.spring; damping: pill.spring.damping * 1.1; epsilon: 0.2 } }
    Behavior on shapeR { NumberAnimation { duration: Motion.ms(glass.theme, 260); easing.type: Easing.OutCubic } }
    Accessible.role: Accessible.Pane
    Accessible.name: "Dynamic Glass, " + st

    // ---- interaction: hover (media only) and click (control center) are separate inputs ----------
    Item {
        id: shape
        parent: pill.contentArea
        anchors.fill: parent
        // Hover and click are separate inputs. A hover only counts when the pointer actually moves (a pill growing
        // under a resting pointer is not the user hovering), and it responds at once: the pill swells and lights up
        // under the pointer immediately; the player opens after the short hover-intent delay.
        HoverHandler {
            id: hover
            onHoveredChanged: hovered ? glass.pillEnter() : glass.pillLeave()
            onPointChanged: if (hovered && glass.pillArmPending) glass.pillMove()
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            acceptedButtons: Qt.LeftButton
            onClicked: glass.pillClick()
            Accessible.role: Accessible.Button
            Accessible.name: "Open Control Center"
            Accessible.onPressAction: glass.pillClick()
        }
        clip: true
    }

    component Face: Item {
        property string when: ""
        parent: shape
        anchors.fill: parent
        visible: opacity > 0.01
        opacity: pill.st === when ? 1 : 0
        scale: pill.st === when ? 1 : 0.94
        Behavior on opacity { OpacityAnimator { duration: Motion.ms(glass.theme, pill.st === parent.when ? 260 : 120); easing.type: Easing.OutCubic } }
        Behavior on scale { ScaleAnimator { duration: Motion.ms(glass.theme, 300); easing.type: Easing.OutCubic } }
    }

    // ---- idle ------------------------------------------------------------------------------------
    Face {
        when: "idle"
        Rectangle {
            anchors.centerIn: parent
            width: 7; height: 7; radius: 3.5
            color: glass.theme.accent
            opacity: 0.95
            Rectangle { anchors.centerIn: parent; width: 16; height: 16; radius: 8; color: glass.theme.accent
                        opacity: pill.hovering ? 0.32 : 0.18
                        Behavior on opacity { NumberAnimation { duration: 200 } } }
        }
        Icon { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
               name: "chevron-down"; size: 12; color: Qt.rgba(1, 1, 1, 0.55); opacity: pill.hovering ? 1 : 0
               Behavior on opacity { NumberAnimation { duration: 160 } } }
    }

    // ---- media (compact) ---------------------------------------------------------------------------
    Face {
        when: "media"
        Rectangle {
            id: miniArt
            visible: glass.settings["topbar.media.artwork"]
            x: 5; anchors.verticalCenter: parent.verticalCenter
            width: parent.height - 8; height: width; radius: 6
            color: Qt.rgba(1, 1, 1, 0.12)
            clip: true
            Image { anchors.fill: parent; source: glass.media.artworkUrl || ""; fillMode: Image.PreserveAspectCrop
                    smooth: true; mipmap: true; asynchronous: true; visible: status === Image.Ready }
            Icon { anchors.centerIn: parent; name: "play"; size: 10; color: "white"; visible: !glass.media.artworkUrl }
        }
        Label {
            anchors.left: miniArt.visible ? miniArt.right : parent.left; anchors.leftMargin: 9
            anchors.right: eq.left; anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            role: "callout"; font.weight: Font.DemiBold; color: "white"
            text: glass.media.title || glass.media.appName || "Now Playing"
        }
        Equalizer {
            id: eq
            visible: glass.settings["topbar.media.visualizer"]
            anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
            playing: !!glass.media.playing
        }
    }

    // ---- media (hover expanded) ---------------------------------------------------------------------
    Face {
        when: "media_expanded"
        Rectangle {
            id: bigArt
            x: 18; y: 18
            width: 76; height: 76; radius: 16
            color: Qt.rgba(1, 1, 1, 0.1)
            clip: true
            Image { anchors.fill: parent; source: glass.media.artworkUrl || ""; fillMode: Image.PreserveAspectCrop
                    smooth: true; mipmap: true; asynchronous: true; visible: status === Image.Ready }
            Icon { anchors.centerIn: parent; name: "sparkle"; size: 28; color: Qt.rgba(1, 1, 1, 0.5); visible: !glass.media.artworkUrl }
        }
        Column {
            anchors.left: bigArt.right; anchors.leftMargin: 14
            anchors.right: parent.right; anchors.rightMargin: 18
            y: 22
            spacing: 2
            Label { width: parent.width; role: "micro"; color: Qt.rgba(1, 1, 1, 0.55); text: (glass.media.appName || "").toUpperCase() }
            Label { width: parent.width; role: "headline"; color: "white"; text: glass.media.title || "Unknown title" }
            Label { width: parent.width; role: "callout"; color: Qt.rgba(1, 1, 1, 0.68); text: glass.media.artist || glass.media.album || "" }
        }
        MediaProgress {
            visible: glass.settings["topbar.media.progress"]
            x: 18; y: 106; width: parent.width - 36
            light: true
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 128
            spacing: 26
            IconButton { icon: "previous"; size: 34; iconSize: 18; color: glass.media.can_prev ? "white" : Qt.rgba(1, 1, 1, 0.3)
                         hoverFill: Qt.rgba(1, 1, 1, 0.12); tooltip: "Previous"; onClicked: glass.previousTrack() }
            IconButton { icon: glass.media.playing ? "pause" : "play"; size: 38; iconSize: 22; color: "white"
                         hoverFill: Qt.rgba(1, 1, 1, 0.14); tooltip: glass.media.playing ? "Pause" : "Play"; onClicked: glass.playPause() }
            IconButton { icon: "next"; size: 34; iconSize: 18; color: glass.media.can_next ? "white" : Qt.rgba(1, 1, 1, 0.3)
                         hoverFill: Qt.rgba(1, 1, 1, 0.12); tooltip: "Next"; onClicked: glass.nextTrack() }
        }
    }

    // ---- notification ----------------------------------------------------------------------------------
    Face {
        when: "notification"
        Rectangle {
            id: nIcon
            x: 14; anchors.verticalCenter: parent.verticalCenter
            width: 40; height: 40; radius: 12
            color: pill.p.source === "garvis" ? glass.theme.accent : Qt.rgba(1, 1, 1, 0.12)
            Image {
                anchors.fill: parent; anchors.margins: 4
                visible: pill.p.source === "windows" && status === Image.Ready
                source: pill.p.source === "windows" && pill.p.app_id ? "image://appicon/64/" + encodeURIComponent("shell:AppsFolder\\" + pill.p.app_id) : ""
                asynchronous: true; smooth: true
            }
            Icon { anchors.centerIn: parent; visible: pill.p.source !== "windows"
                   name: pill.p.source === "garvis" ? "sparkle" : "glass"; size: 20; color: "white" }
        }
        Column {
            anchors.left: nIcon.right; anchors.leftMargin: 12
            anchors.right: parent.right; anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 1
            Label { width: parent.width; role: "callout"; font.weight: Font.DemiBold; color: "white"; text: pill.p.title || pill.p.app || "" }
            Label { width: parent.width; role: "caption"; color: Qt.rgba(1, 1, 1, 0.7); text: pill.p.body || ""; visible: text !== ""
                    maximumLineCount: 2; wrapMode: Text.Wrap }
        }
    }

    // ---- activity pulses -----------------------------------------------------------------------------
    Face {
        when: "activity"
        Item {
            id: actIcon
            x: 12; width: 22; height: 22; anchors.verticalCenter: parent.verticalCenter
            SpeakerIcon { anchors.centerIn: parent; visible: pill.p.kind === "volume"; size: 18; color: "white"
                          level: pill.p.level || 0; muted: !!pill.p.muted }
            BatteryIcon { anchors.centerIn: parent; visible: pill.p.kind === "power" || pill.p.kind === "battery_low"; size: 15
                          color: "white"; percent: pill.p.percent || 0; charging: !!pill.p.plugged; plugged: !!pill.p.plugged }
            WifiIcon { anchors.centerIn: parent; visible: pill.p.kind === "network"; size: 17; color: "white"
                       kind: pill.p.internet ? (pill.p.type || "wifi") : "none"; bars: 4; internet: !!pill.p.internet }
        }
        Item {
            anchors.left: actIcon.right; anchors.leftMargin: 10
            anchors.right: parent.right; anchors.rightMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            height: parent.height
            Rectangle {
                visible: pill.p.kind === "volume"
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 40; height: 5; radius: 2.5; color: Qt.rgba(1, 1, 1, 0.2)
                Rectangle { width: parent.width * (pill.p.muted ? 0 : (pill.p.level || 0)); height: parent.height; radius: 2.5; color: "white"
                            Behavior on width { NumberAnimation { duration: 120 } } }
            }
            Label { visible: pill.p.kind === "volume"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    role: "caption"; color: Qt.rgba(1, 1, 1, 0.8); font.features: { "tnum": 1 }
                    text: pill.p.muted ? "Muted" : Math.round((pill.p.level || 0) * 100) + "%" }
            Label {
                visible: pill.p.kind !== "volume"
                anchors.verticalCenter: parent.verticalCenter; width: parent.width
                role: "callout"; font.weight: Font.DemiBold; color: "white"
                text: pill.p.kind === "power" ? (pill.p.plugged ? "Charging · " + pill.p.percent + "%" : "On battery · " + pill.p.percent + "%")
                    : pill.p.kind === "battery_low" ? "Battery low · " + pill.p.percent + "%"
                    : pill.p.kind === "network" ? (pill.p.internet ? "Connected · " + (pill.p.name || "") : "No internet connection")
                    : ""
            }
        }
    }

    // ---- Garvis is operating the computer ---------------------------------------------------------------
    Face {
        when: "garvis"
        Rectangle {
            id: gOrb
            x: 6; anchors.verticalCenter: parent.verticalCenter
            width: parent.height - 8; height: width; radius: width / 2
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.lighter(glass.theme.accent, 1.35) }
                GradientStop { position: 1; color: glass.theme.accent }
            }
            Icon { anchors.centerIn: parent; name: "sparkle"; size: parent.width * 0.62; color: "white" }
            SequentialAnimation { running: !glass.theme.reduce_motion && pill.st === "garvis"; loops: Animation.Infinite
                ScaleAnimator { target: gOrb; to: 1.08; duration: 700; easing.type: Easing.InOutSine }
                ScaleAnimator { target: gOrb; to: 1.0; duration: 700; easing.type: Easing.InOutSine } }
        }
        Label {
            anchors.left: gOrb.right; anchors.leftMargin: 10
            anchors.right: stopBtn.left; anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            role: "callout"; color: "white"
            text: "<b>Garvis</b>  " + (glass.garvis.app ? "is using " + glass.garvis.app : "is controlling the computer")
            textFormat: Text.StyledText
        }
        Rectangle {
            id: stopBtn
            anchors.right: parent.right; anchors.rightMargin: 4; anchors.verticalCenter: parent.verticalCenter
            width: 56; height: parent.height - 8; radius: height / 2
            color: stopArea.containsMouse ? "#FF5A52" : "#E5484D"
            Label { anchors.centerIn: parent; role: "caption"; font.weight: Font.DemiBold; color: "white"; text: "Stop" }
            MouseArea { id: stopArea; anchors.fill: parent; hoverEnabled: true; onClicked: glass.emergencyStop()
                        Accessible.role: Accessible.Button; Accessible.name: "Stop Garvis computer control" }
        }
    }

    // ---- expanded control center ------------------------------------------------------------------------
    Face {
        when: "control_center"
        ControlPanel { id: panel; anchors.fill: parent; anchors.margins: 14 }
    }
}
