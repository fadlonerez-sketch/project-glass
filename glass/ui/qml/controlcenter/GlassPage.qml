import QtQuick
import "../components"

Column {
    id: page
    spacing: 24
    readonly property real inten: cc.settings["glass.intensity"] || 0

    Rectangle {
        width: parent.width; height: preview.implicitHeight + 16; radius: 18
        color: glass.theme.surface; border.width: 1; border.color: glass.theme.hairline
        GlassPreview { id: preview; anchors.fill: parent; anchors.margins: 8 }
    }

    Column {
        width: parent.width
        spacing: 10
        Row {
            width: parent.width
            Label { role: "headline"; text: "Presets"; width: parent.width - cur.width }
            Label { id: cur; role: "caption"; tertiary: true
                    text: cc.currentPreset === "custom" ? "Custom — your own values" : "" }
        }
        Row {
            width: parent.width
            spacing: 12
            Repeater {
                model: cc.glassPresets
                PresetCard { width: (page.width - 24) / 3; key: modelData.key; name: modelData.name; about: modelData.about }
            }
        }
    }

    Section {
        title: "Liquid Glass"
        footer: "Overall Intensity is a master control: what you see of each effect is its own value × Intensity. At 0% surfaces use the plain theme material, and every value below is kept exactly as you set it. Choosing a preset sets these values; you can fine-tune them afterwards."
        SettingSlider { title: "Overall Intensity"; subtitle: "Master control for the whole material"; key: "glass.intensity" }
        SettingSlider { title: "Blur"; subtitle: "Softness of what shows through · visible " + Math.round((cc.settings["glass.blur"] || 0) * page.inten * 100) + "%"; key: "glass.blur" }
        SettingSlider { title: "Light Refraction"; subtitle: "Lensing at the glass edge, with colour dispersion · visible " + Math.round((cc.settings["glass.refraction"] || 0) * page.inten * 100) + "%"; key: "glass.refraction" }
        SettingSlider { title: "Specular Shine"; subtitle: "Rim highlights, glints, caustics and the pointer light · visible " + Math.round((cc.settings["glass.shine"] || 0) * page.inten * 100) + "%"; key: "glass.shine"; last: true }
    }

    Section {
        title: "Accent tint"
        footer: "The accent colour tints the glass body itself: thicker glass shows it richer, the rim stays clearer, and the edge dispersion leans towards it. Text contrast is protected automatically in Light and Dark."
        SettingToggle { title: "Tint the glass with the accent colour"; subtitle: "Currently " + (cc.theme.accent || ""); key: "glass.accent_tint" }
        SettingSlider { title: "Tint strength"; subtitle: "How much colour the glass holds"; key: "glass.tint_strength"; last: true
                        opacity: cc.settings["glass.accent_tint"] ? 1 : 0.45; enabled: !!cc.settings["glass.accent_tint"] }
    }

    Section {
        title: "Material"
        SettingSlider { title: "Material appearance"; subtitle: "From crystal clear to frosted"; key: "glass.frost" }
        SettingSlider { title: "Edge treatment"; subtitle: "Hairline and rim definition"; key: "glass.edge" }
        SettingSlider { title: "Visual depth"; subtitle: "Shadow and elevation"; key: "glass.depth"; last: true }
    }

    Section {
        title: "What's behind the glass"
        footer: "True refraction: the top bar and the Dock sit in screen strips Glass reserves, so what is physically behind them is your wallpaper. Glass renders that wallpaper exactly as Windows lays it out and refracts, blurs and disperses it on the GPU — no screen capture. Simulated: panels that open over app windows (the player, flyouts, window previews) refract the wallpaper layer, not the window under them; the highlights, glints and caustics are lighting effects, not optics."
        Row_ {
            title: "Restore defaults"; subtitle: "Crystal Glass at 100%, accent tint on"; last: true
            PushButton { text: "Reset Liquid Glass"; onClicked: cc.resetSection("glass") }
        }
    }
}
