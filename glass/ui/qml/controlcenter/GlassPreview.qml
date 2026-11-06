import QtQuick
import "../components"

// Live Liquid Glass preview: real glass surfaces over a colourful, moving scene, using the current
// material values (the same shader as the desktop). Shows the difference every slider makes.
Item {
    id: root
    implicitHeight: 230
    clip: true

    Rectangle {
        id: scene
        anchors.fill: parent
        radius: 16
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#FF6A5B" }
            GradientStop { position: 0.35; color: "#FFB547" }
            GradientStop { position: 0.65; color: "#2FC7D9" }
            GradientStop { position: 1.0; color: "#7A5CF7" }
        }
        Repeater {
            model: 14
            Rectangle { x: index * 64 - 40; y: -40; width: 7; height: root.height + 80; rotation: 18
                        color: Qt.rgba(1, 1, 1, 0.55) }
        }
        Text { x: 22; y: 118; text: "Aa Refraction"; color: "#121218"; font.pixelSize: 54; font.weight: Font.Bold; font.family: "Segoe UI Variable Display" }
        Rectangle {
            id: orb
            width: 90; height: 90; radius: 45; y: 18
            color: "#FFFFFF"; opacity: 0.85
            SequentialAnimation on x {
                running: root.visible && !glass.theme.reduce_motion; loops: Animation.Infinite
                NumberAnimation { from: 20; to: root.width - 110; duration: 5200; easing.type: Easing.InOutSine }
                NumberAnimation { to: 20; duration: 5200; easing.type: Easing.InOutSine }
            }
        }
    }
    ShaderEffectSource { id: src; sourceItem: scene; hideSource: false; live: true; mipmap: true; visible: false
                         textureSize: Qt.size(scene.width * 2, scene.height * 2) }

    GlassSurface {
        id: g1
        backdropItem: src; backdropFrame: scene
        tone: "base"; radius: 28; margin: 24
        x: 30 - margin; y: 36 - margin
        width: root.width * 0.46 + 2 * margin; height: 150 + 2 * margin
        Column {
            parent: g1.contentArea
            anchors.centerIn: parent; spacing: 4
            Label { anchors.horizontalCenter: parent.horizontalCenter; role: "title"; text: "Liquid Glass" }
            Label { anchors.horizontalCenter: parent.horizontalCenter; role: "caption"; secondary: true
                    text: "Intensity " + Math.round(glass.material.intensity * 100) + "%" }
        }
    }
    GlassSurface {
        id: g2
        backdropItem: src; backdropFrame: scene
        tone: "deep"; margin: 24
        width: 210 + 2 * margin; height: 40 + 2 * margin; radius: 20
        x: root.width * 0.58 - margin; y: 34 - margin
        Row {
            parent: g2.contentArea
            anchors.centerIn: parent; spacing: 10
            Rectangle { width: 8; height: 8; radius: 4; color: glass.theme.accent; anchors.verticalCenter: parent.verticalCenter }
            Label { role: "callout"; color: "white"; font.weight: Font.DemiBold; text: "Dynamic Glass" }
        }
    }
    GlassSurface {
        id: g3
        backdropItem: src; backdropFrame: scene
        tone: "base"; margin: 24; radius: 22
        width: root.width * 0.36 + 2 * margin; height: 64 + 2 * margin
        x: root.width * 0.58 - margin; y: 110 - margin
        Row {
            parent: g3.contentArea
            anchors.centerIn: parent; spacing: 10
            Repeater { model: ["#E5484D", "#3DAA4D", "#2F7CF6", "#8E5CF7"]
                Rectangle { width: 40; height: 40; radius: 10; color: modelData } }
        }
    }
}
