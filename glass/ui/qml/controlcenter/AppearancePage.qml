import QtQuick
import "../components"

Column {
    id: page
    spacing: 24
    property string draft: cc.settings["appearance.accent"] || "#8E5CF7"
    Component.onCompleted: picker.load(draft)
    Connections { target: cc; function onSettingsChanged() { if (!page.dirty) { page.draft = cc.settings["appearance.accent"]; picker.load(page.draft) } } }
    readonly property bool dirty: draft !== cc.settings["appearance.accent"]
    readonly property var previewTok: { cc.settings; cc.theme; return cc.previewTheme(draft) }

    // Theme cards
    Section {
        title: "Appearance"
        Item {
            width: parent.width; height: 168
            Row {
                anchors.centerIn: parent; spacing: 18
                Repeater {
                    model: [["light", "Light"], ["dark", "Dark"], ["adaptive", "Adaptive"]]
                    Column {
                        spacing: 8
                        Rectangle {
                            width: 150; height: 100; radius: 12
                            border.width: cc.settings["appearance.theme"] === modelData[0] ? 3 : 1
                            border.color: cc.settings["appearance.theme"] === modelData[0] ? glass.theme.accent : glass.theme.hairline
                            clip: true
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0; color: modelData[0] === "dark" ? "#1B1B20" : "#F3F3F6" }
                                GradientStop { position: modelData[0] === "adaptive" ? 0.5 : 1; color: modelData[0] === "dark" ? "#1B1B20" : "#F3F3F6" }
                                GradientStop { position: modelData[0] === "adaptive" ? 0.5001 : 1; color: modelData[0] === "light" ? "#F3F3F6" : "#1B1B20" }
                                GradientStop { position: 1; color: modelData[0] === "light" ? "#F3F3F6" : "#1B1B20" }
                            }
                            Rectangle { x: 10; y: 10; width: parent.width - 20; height: 12; radius: 6; color: modelData[0] === "dark" ? "#2E2E35" : "#FFFFFF"; opacity: 0.9 }
                            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 12; width: 34; height: 8; radius: 4; color: "#0B0B0F" }
                            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 8
                                        width: 92; height: 18; radius: 7; color: modelData[0] === "dark" ? "#2E2E35" : "#FFFFFF"
                                        Row { anchors.centerIn: parent; spacing: 4
                                              Repeater { model: 5; Rectangle { width: 10; height: 10; radius: 3; color: index === 1 ? glass.theme.accent : "#9A9AA6" } } } }
                            MouseArea { anchors.fill: parent; onClicked: cc.set("appearance.theme", modelData[0])
                                        Accessible.role: Accessible.RadioButton; Accessible.name: modelData[1] + " appearance" }
                        }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; role: "callout"; text: modelData[1]
                                font.weight: cc.settings["appearance.theme"] === modelData[0] ? Font.DemiBold : Font.Normal }
                    }
                }
            }
        }
    }
    Label { width: parent.width; wrapMode: Text.Wrap; role: "caption"; tertiary: true
            text: "Adaptive follows Windows' light/dark setting and switches with it." ; topPadding: -16; leftPadding: 4 }

    // Accent colour
    Section {
        title: "Accent colour"
        footer: "The accent is used across the top bar, the Dock, menus, toggles and LaunchDeck. Purple is only the starting choice."
        Item {
            width: parent.width; height: 64
            Flow {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width; spacing: 10
                Repeater {
                    model: cc.presets
                    Rectangle {
                        width: 28; height: 28; radius: 14; color: modelData.hex
                        border.width: page.draft === modelData.hex ? 3 : 0
                        border.color: glass.theme.dark ? "white" : "#16161A"
                        scale: pa.containsMouse ? 1.12 : 1
                        Behavior on scale { NumberAnimation { duration: 120 } }
                        MouseArea { id: pa; anchors.fill: parent; hoverEnabled: true
                                    onClicked: { page.draft = modelData.hex; picker.load(modelData.hex) }
                                    Accessible.role: Accessible.RadioButton; Accessible.name: modelData.name }
                    }
                }
            }
        }
        Item {
            width: parent.width; height: picker.implicitHeight + 24
            ColorPicker { id: picker; y: 8; onEdited: (h) => page.draft = h }
        }
        Item {
            width: parent.width; height: 56
            visible: (cc.settings["appearance.saved_colors"] || []).length > 0
            Row {
                anchors.verticalCenter: parent.verticalCenter; spacing: 8
                Label { role: "callout"; secondary: true; text: "Saved"; anchors.verticalCenter: parent.verticalCenter }
                Repeater {
                    model: cc.settings["appearance.saved_colors"] || []
                    Rectangle {
                        width: 26; height: 26; radius: 8; color: modelData
                        border.width: page.draft === modelData ? 2 : 1; border.color: page.draft === modelData ? glass.theme.text : glass.theme.hairline
                        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                                    onClicked: (e) => { if (e.button === Qt.RightButton) cc.forgetColor(modelData); else { page.draft = modelData; picker.load(modelData) } } }
                    }
                }
            }
        }
        // live preview of the draft
        Item {
            width: parent.width; height: 70
            Row {
                anchors.verticalCenter: parent.verticalCenter; spacing: 12
                Rectangle { width: 120; height: 32; radius: 9; color: page.previewTok.accent
                    Label { anchors.centerIn: parent; role: "callout"; font.weight: Font.DemiBold; color: page.previewTok.on_accent; text: "Button" } }
                Rectangle { width: 44; height: 26; radius: 13; color: page.previewTok.accent; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { x: 20; y: 2; width: 22; height: 22; radius: 11; color: "white" } }
                Label { role: "body"; color: page.previewTok.accent_text; text: "Link text"; anchors.verticalCenter: parent.verticalCenter }
                Rectangle { width: 30; height: 30; radius: 15; color: page.previewTok.accent_soft; anchors.verticalCenter: parent.verticalCenter
                    Icon { anchors.centerIn: parent; name: "sparkle"; size: 15; color: page.previewTok.accent } }
            }
            Row {
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                PushButton { text: "Save colour"; icon: "plus"; onClicked: cc.saveColor(page.draft) }
                PushButton { text: "Reset"; onClicked: { cc.resetKeys(["appearance.accent"]); page.draft = "#8E5CF7"; picker.load("#8E5CF7") } }
                PushButton { text: "Apply"; primary: true; opacity: page.dirty ? 1 : 0.5; onClicked: cc.set("appearance.accent", page.draft) }
            }
        }
    }

    Section {
        title: "Materials and motion"
        SettingSlider { title: "Transparency"; subtitle: "How see-through Liquid Glass surfaces are when Liquid Glass is on"; key: "appearance.transparency" }
        SettingSlider { title: "Accent tint"; subtitle: "Let surfaces pick up a whisper of the accent hue"; key: "appearance.accent_tint" }
        SettingSlider { title: "Animation speed"; key: "appearance.animation_speed"; from: 0.5; to: 2.0; step: 0.05; percent: false; unit: "×" }
        SettingToggle { title: "Reduce motion"; subtitle: "Shorter, calmer transitions; no ambient animation"; key: "appearance.reduce_motion"; last: true }
    }
}
