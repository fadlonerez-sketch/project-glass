import QtQuick
import "../components"

Column {
    spacing: 24
    Section {
        title: "LaunchDeck"
        footer: "LaunchDeck is your application launcher (Alt+Space). Glass shares its appearance with it and opens its search from the Dock and the top bar."
        Row_ {
            title: cc.launchdeckInstalled() ? "Installed" : "Not found"
            subtitle: cc.launchdeckInstalled() ? "Search apps, files, websites and commands" : "Expected at %USERPROFILE%\\LaunchDeck"
            PushButton { text: "Open search"; icon: "search"; primary: true; onClicked: cc.launchdeck("launcher") }
        }
        Row_ { title: "LaunchDeck settings"; subtitle: "Hotkey, search locations, websites and commands"; last: true
               PushButton { text: "Open"; icon: "external"; onClicked: cc.launchdeck("settings") } }
    }
    Section {
        title: "Dock applications"
        Row_ { title: "Pinned apps, recent history and widgets"; subtitle: "Pin, reorder, remove and add apps"; last: true
               PushButton { text: "Go to Dock"; onClicked: root_.page = "dock" } }
    }
    Section {
        title: "History"
        footer: "Recently Used is built from when apps start and stop. On first run it was seeded from LaunchDeck's usage history."
        Row_ { title: "Startup apps"; subtitle: "Windows' list of apps that start at sign-in"; last: true
               PushButton { text: "Open"; icon: "external"; onClicked: cc.openSettingsPage("startup") } }
    }
}
