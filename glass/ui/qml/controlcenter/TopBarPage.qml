import QtQuick
import "../components"

Column {
    spacing: 24
    Section {
        title: "Top bar"
        SettingToggle { title: "Show the top bar"; key: "topbar.visible" }
        SettingChoice { title: "Size"; key: "topbar.size"; options: [["compact", "Compact"], ["regular", "Regular"], ["large", "Large"]] }
        SettingChoice { title: "Style"; subtitle: "A full-width bar, or floating elements only"; key: "topbar.background"; options: [["bar", "Bar"], ["floating", "Floating"]] }
        SettingChoice { title: "Displays"; key: "topbar.displays"; options: [["primary", "Main display"], ["all", "All displays"]] }
        SettingChoice { title: "Dynamic Glass appears on"; subtitle: "With the top bar on several displays"; key: "topbar.island_display"; options: [["active", "Active display"], ["primary", "Main display"]] }
        SettingToggle { title: "Show the active app's name"; key: "topbar.show_app_name"; last: true }
    }
    Section {
        title: "Dynamic Glass"
        footer: "Hovering over media expands the player. Clicking the Dynamic Glass opens its control center. These are separate gestures."
        SettingChoice { title: "Animation"; subtitle: "How the Dynamic Glass changes shape"; key: "topbar.animation"
                        options: [["fluid", "Fluid"], ["gentle", "Gentle"], ["minimal", "Minimal"]] }
        SettingToggle { title: "Show playing media"; key: "topbar.media.enabled" }
        SettingToggle { title: "Album artwork"; key: "topbar.media.artwork" }
        SettingToggle { title: "Visualiser"; key: "topbar.media.visualizer" }
        SettingToggle { title: "Playback progress"; key: "topbar.media.progress" }
        SettingToggle { title: "Expand on hover"; key: "topbar.media.hover_expand" }
        SettingSlider { title: "Hover delay"; subtitle: "The pill reacts at once; the player opens after this"; key: "topbar.media.expand_delay_ms"; from: 0; to: 600; step: 10; percent: false; unit: " ms" }
        SettingSlider { title: "Collapse delay"; key: "topbar.media.collapse_delay_ms"; from: 100; to: 5000; step: 50; percent: false; unit: " ms"; last: true }
    }
    Section {
        title: "Status indicators"
        SettingToggle { title: "Network"; key: "topbar.indicators.network" }
        SettingToggle { title: "Sound"; key: "topbar.indicators.audio" }
        SettingToggle { title: "Battery"; key: "topbar.indicators.battery" }
        SettingToggle { title: "Battery percentage"; key: "topbar.indicators.battery_percent" }
        SettingToggle { title: "Tray access"; subtitle: "A button that shows the Windows notification-area icons"; key: "topbar.indicators.tray" }
        SettingToggle { title: "Clock"; key: "topbar.indicators.clock" }
        SettingChoice { title: "Clock format"; key: "topbar.clock.format"; options: [["24h", "24-hour"], ["12h", "12-hour"]] }
        SettingToggle { title: "Show the date"; key: "topbar.clock.show_date" }
        SettingToggle { title: "Show seconds"; key: "topbar.clock.show_seconds"; last: true }
    }
    Section {
        title: "Notifications in the Dynamic Glass"
        SettingToggle { title: "Show notifications"; key: "topbar.notifications.enabled" }
        SettingSlider { title: "Display time"; key: "topbar.notifications.duration_s"; from: 2; to: 30; step: 1; percent: false; unit: " s"; last: true }
    }
}
