import QtQuick
import "../components"

// One Liquid Glass preset with a live preview: the real shader, rendered with the preset's values and your current
// theme and accent, over the same scene for every preset so the differences are easy to see.
Item {
    id: root
    property string key: ""
    property string name: ""
    property string about: ""
    readonly property bool selected: cc.currentPreset === key
    readonly property var mat: { cc.settings; cc.theme; return cc.presetMaterial(key) }
    height: 212
    Accessible.role: Accessible.RadioButton
    Accessible.name: name + (selected ? ", selected" : "")
    Accessible.checked: selected
    Accessible.onPressAction: cc.applyPreset(key)

    Rectangle {
        anchors.fill: parent; radius: 18
        color: glass.theme.surface
        border.width: root.selected ? 2 : 1
        border.color: root.selected ? glass.theme.accent : (ma.containsMouse ? glass.theme.separator : glass.theme.hairline)
        Behavior on border.color { ColorAnimation { duration: 140 } }
    }
    Item {
        id: stage
        x: 8; y: 8; width: parent.width - 16; height: 132
        clip: true
        Rectangle {
            id: scene
            anchors.fill: parent; radius: 12
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "#FF6A5B" }
                GradientStop { position: 0.45; color: "#2FC7D9" }
                GradientStop { position: 1.0; color: "#7A5CF7" }
            }
            Repeater { model: 9; Rectangle { x: index * 34 - 20; y: -30; width: 5; height: 200; rotation: 18; color: Qt.rgba(1, 1, 1, 0.55) } }
            Text { x: 10; y: 70; text: "Aa Glass"; color: "#121218"; font.pixelSize: 40; font.weight: Font.Bold; font.family: "Segoe UI Variable Display" }
        }
        ShaderEffectSource { id: src; sourceItem: scene; hideSource: false; live: false; mipmap: true; visible: false
                             textureSize: Qt.size(scene.width * 2, scene.height * 2) }
        GlassSurface {
            id: g
            materialOverride: root.mat
            backdropItem: src; backdropFrame: scene
            radius: 22; margin: 18
            x: 18 - margin; y: 26 - margin
            width: stage.width - 36 + 2 * margin; height: 80 + 2 * margin
            Row {
                parent: g.contentArea
                anchors.centerIn: parent; spacing: 8
                Rectangle { width: 8; height: 8; radius: 4; color: glass.theme.accent; anchors.verticalCenter: parent.verticalCenter }
                Label { role: "callout"; font.weight: Font.DemiBold; text: root.name }
            }
        }
    }
    Column {
        x: 14; y: stage.y + stage.height + 10; width: parent.width - 28
        spacing: 2
        Row {
            spacing: 6
            Label { role: "headline"; text: root.name }
            Rectangle { visible: root.selected; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16; radius: 8; color: glass.theme.accent
                        Icon { anchors.centerIn: parent; name: "check"; size: 10; color: glass.theme.on_accent; strokeWidth: 2.4 } }
        }
        Label { width: parent.width; role: "caption"; secondary: true; wrapMode: Text.Wrap; maximumLineCount: 2; text: root.about }
    }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: cc.applyPreset(root.key) }
}
