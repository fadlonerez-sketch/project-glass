import QtQuick
import "../components"

Column {
    spacing: 24
    Item {
        width: parent.width; height: 170
        Column {
            anchors.centerIn: parent; spacing: 10
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 72; height: 72; radius: 20
                gradient: Gradient { GradientStop { position: 0; color: Qt.lighter(glass.theme.accent, 1.35) }
                                     GradientStop { position: 1; color: glass.theme.accent } }
                Icon { anchors.centerIn: parent; name: "glass"; size: 38; color: "white"; strokeWidth: 2 }
            }
            Label { anchors.horizontalCenter: parent.horizontalCenter; role: "title"; text: "Project Glass" }
            Label { anchors.horizontalCenter: parent.horizontalCenter; role: "callout"; secondary: true
                    text: "Version " + (cc.status.version || "1.0.0") + " · Python + Qt Quick" }
        }
    }
    Section {
        title: "Privacy"
        footer: "Glass makes one kind of network request: the weather for the city you choose (Open-Meteo). It never captures your screen; the Liquid Glass backdrop is rendered from your wallpaper file. Garvis receives structured UI information only — never images."
    }
    Section {
        title: "Data"
        Row_ { title: "Settings, Dock history and logs"; subtitle: "%LOCALAPPDATA%\\ProjectGlass"; last: true
               PushButton { text: "Open folder"; onClicked: cc.openDataDir() } }
    }
}
