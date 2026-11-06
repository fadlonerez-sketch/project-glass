import QtQuick
import "../components"

Column {
    id: page
    spacing: 24
    readonly property var widgets: cc.settings["dock.widgets"] || []
    readonly property var widgetTypes: [["weather", "Weather", "partly"], ["calendar", "Calendar", "calendar"], ["clock", "Clock", "sun"],
                                        ["system", "System load", "cpu"], ["garvis", "Garvis", "sparkle"]]
    function setWidgets(list) { cc.set("dock.widgets", list) }

    Section {
        title: "Dock"
        SettingToggle { title: "Show the Dock"; key: "dock.visible" }
        SettingChoice { title: "Position"; key: "dock.position"; options: [["left", "Left"], ["bottom", "Bottom"], ["right", "Right"]] }
        SettingSlider { title: "Icon size"; subtitle: "The bar is the icon plus a slim margin"; key: "dock.icon_size"; from: 28; to: 64; step: 1; percent: false; unit: " px" }
        SettingSlider { title: "Icon spacing"; key: "dock.spacing"; from: 4; to: 24; step: 1; percent: false; unit: " px" }
        SettingToggle { title: "Magnification"; subtitle: "Icons swell under the pointer without moving their neighbours"; key: "dock.magnification" }
        SettingSlider { title: "Magnified size"; key: "dock.magnification_scale"; from: 1.0; to: 1.6; step: 0.05; percent: false; unit: "×" }
        SettingToggle { title: "Automatically hide and show"; key: "dock.autohide" }
        SettingToggle { title: "Bounce while apps open"; key: "dock.launch_bounce" }
        SettingToggle { title: "Show indicators for open apps"; key: "dock.indicators"; last: true }
    }

    Section {
        title: "Window previews"
        footer: "Rest the pointer on an open app to see its windows; click one to bring it forward. Previews are live views drawn by Windows (DWM) inside the Dock: no picture of your windows is taken, saved or sent anywhere, and Garvis never sees them. Keyboard: Ctrl+Alt+Shift+D moves focus to the Dock; arrows choose, Up shows the windows, Enter opens, Esc returns."
        SettingToggle { title: "Show window previews"; subtitle: "Off: the app's name appears instead"; key: "dock.previews" }
        SettingSlider { title: "Hover delay"; subtitle: "How long the pointer rests before anything appears"; key: "dock.hover_delay_ms"; from: 60; to: 600; step: 10; percent: false; unit: " ms" }
        SettingSlider { title: "Dismiss delay"; subtitle: "Time to move from an icon to its preview"; key: "dock.dismiss_delay_ms"; from: 150; to: 1000; step: 10; percent: false; unit: " ms"; last: true }
    }

    Section {
        title: "Applications in the Dock"
        footer: "Open apps come first; closed apps follow under Recently Used, newest first. Pinned apps stay in the Dock in the order you set, wherever they are."
        SettingToggle { title: "Show recently used apps"; key: "dock.show_recent" }
        SettingSlider { title: "Recent apps"; key: "dock.recent_limit"; from: 0; to: 20; step: 1; percent: false; unit: "" }
        SettingToggle { title: "Show apps from all virtual desktops"; subtitle: "Off: only the current desktop (Garvis's automation desktop is never shown)"; key: "dock.all_desktops" }
        SettingToggle { title: "Show the Search button"; subtitle: "Opens LaunchDeck"; key: "dock.show_launcher"; last: true }
    }

    Section {
        title: "Pinned and recent"
        Repeater {
            model: cc.apps
            Row_ {
                title: modelData.name
                subtitle: (modelData.pinned ? "Pinned" : "Recent") + (modelData.running ? " · open" : "") + (modelData.last_launched ? " · last opened " + cc.ago(modelData.last_launched) : "")
                last: index === cc.apps.length - 1
                Row {
                    spacing: 4
                    Image { width: 22; height: 22; anchors.verticalCenter: parent.verticalCenter; visible: false }
                    IconButton { visible: modelData.pinned && index > 0; icon: "chevron-up"; size: 28; iconSize: 13; tooltip: "Move left"
                                 onClicked: cc.movePinned(modelData.app_id, index - 1) }
                    IconButton { visible: modelData.pinned && index + 1 < cc.apps.length && cc.apps[index + 1].pinned; icon: "chevron-down"; size: 28; iconSize: 13
                                 tooltip: "Move right"; onClicked: cc.movePinned(modelData.app_id, index + 1) }
                    PushButton { text: modelData.pinned ? "Unpin" : "Pin"; icon: "pin"; onClicked: cc.dockOp(modelData.pinned ? "unpin" : "pin", modelData.app_id) }
                    PushButton { visible: !modelData.running; text: "Remove"; destructive: true; onClicked: cc.dockOp("remove", modelData.app_id) }
                }
            }
        }
        Item { width: parent.width; height: 40; visible: cc.apps.length === 0
               Label { anchors.verticalCenter: parent.verticalCenter; role: "callout"; tertiary: true
                       text: cc.shellConnected ? "No apps yet." : "Start Project Glass to manage the Dock's apps." } }
    }

    Section {
        title: "Add an application"
        Item {
            width: parent.width; height: 52
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width; height: 34; radius: 9; color: glass.theme.dark ? glass.theme.surface2 : glass.theme.bg
                border.width: 1; border.color: search.activeFocus ? glass.theme.accent : glass.theme.hairline
                Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 15; color: glass.theme.text3 }
                TextInput { id: search; anchors.fill: parent; anchors.leftMargin: 34; anchors.rightMargin: 10
                            verticalAlignment: TextInput.AlignVCenter; color: glass.theme.text; font.pixelSize: 13
                            onTextChanged: searchTimer.restart()
                            Accessible.role: Accessible.EditableText; Accessible.name: "Search installed apps" }
                Timer { id: searchTimer; interval: 180; onTriggered: cc.searchCatalog(search.text) }
            }
        }
        Repeater {
            model: cc.catalog.slice(0, 8)
            Row_ {
                title: modelData.name; last: index === Math.min(cc.catalog.length, 8) - 1
                PushButton { text: "Add to Dock"; icon: "plus"; onClicked: cc.addApp(modelData.parsing) }
            }
        }
    }

    Section {
        title: "Widgets"
        footer: "Widgets sit at the two ends of the Dock in this order: the first half on the left, the rest on the right. Up to six, so the Dock stays about applications."
        Repeater {
            model: page.widgets
            Row_ {
                title: (page.widgetTypes.find(t => t[0] === modelData.type) || ["", modelData.type])[1]
                last: index === page.widgets.length - 1
                Row {
                    spacing: 4
                    IconButton { visible: index > 0; icon: "chevron-up"; size: 28; iconSize: 13; tooltip: "Move left"
                                 onClicked: { var l = page.widgets.slice(); l.splice(index - 1, 0, l.splice(index, 1)[0]); page.setWidgets(l) } }
                    IconButton { visible: index < page.widgets.length - 1; icon: "chevron-down"; size: 28; iconSize: 13; tooltip: "Move right"
                                 onClicked: { var l = page.widgets.slice(); l.splice(index + 1, 0, l.splice(index, 1)[0]); page.setWidgets(l) } }
                    PushButton { text: "Remove"; destructive: true; onClicked: { var l = page.widgets.slice(); l.splice(index, 1); page.setWidgets(l) } }
                }
            }
        }
        Item {
            width: parent.width; height: 56
            Flow {
                anchors.verticalCenter: parent.verticalCenter; width: parent.width; spacing: 8
                Repeater {
                    model: page.widgetTypes
                    PushButton { icon: "plus"; text: modelData[1]
                                 visible: page.widgets.length < 6
                                 onClicked: { var l = page.widgets.slice(); l.push({ id: modelData[0] + "-" + Date.now(), type: modelData[0], config: {} }); page.setWidgets(l) } }
                }
            }
        }
    }

    Section {
        title: "Weather"
        SettingToggle { title: "Weather widget data"; key: "weather.enabled" }
        Row_ {
            title: "City"
            subtitle: cc.settings["weather.label"] || cc.settings["weather.city"] || "Not set"
            Rectangle {
                width: 240; height: 32; radius: 8; color: glass.theme.dark ? glass.theme.surface2 : glass.theme.bg
                border.width: 1; border.color: city.activeFocus ? glass.theme.accent : glass.theme.hairline
                TextInput { id: city; anchors.fill: parent; anchors.margins: 8; color: glass.theme.text; font.pixelSize: 13; clip: true
                            onTextChanged: cityTimer.restart()
                            Accessible.role: Accessible.EditableText; Accessible.name: "Search city" }
                Label { anchors.verticalCenter: parent.verticalCenter; x: 8; role: "callout"; tertiary: true; text: "Search a city…"; visible: !city.text }
                Timer { id: cityTimer; interval: 350; onTriggered: cc.searchCity(city.text) }
            }
        }
        Repeater {
            model: cc.places
            Row_ {
                title: modelData.label
                PushButton { text: "Use"; primary: true; onClicked: { cc.chooseCity(modelData); city.text = "" } }
            }
        }
        SettingChoice { title: "Units"; key: "weather.units"; options: [["c", "°C"], ["f", "°F"]] }
        SettingToggle { title: "Show details"; subtitle: "Feels-like, humidity and wind in the forecast"; key: "weather.details"; last: true }
    }
}
