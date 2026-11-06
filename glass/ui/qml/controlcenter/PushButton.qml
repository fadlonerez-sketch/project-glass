import QtQuick
import "../components"

Rectangle {
    id: b
    property string text: ""
    property string icon: ""
    property bool primary: false
    property bool destructive: false
    signal clicked()
    width: row.implicitWidth + 28; height: 32; radius: 9
    color: primary ? (ma.pressed ? glass.theme.accent_pressed : ma.containsMouse ? glass.theme.accent_hover : glass.theme.accent)
                   : (ma.pressed ? glass.theme.control_pressed : ma.containsMouse ? glass.theme.control_hover : glass.theme.control)
    Behavior on color { ColorAnimation { duration: 100 } }
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: b.clicked()
    Row {
        id: row
        anchors.centerIn: parent; spacing: 6
        Icon { visible: b.icon !== ""; name: b.icon; size: 14; anchors.verticalCenter: parent.verticalCenter
               color: b.primary ? glass.theme.on_accent : b.destructive ? glass.theme.danger : glass.theme.text }
        Label { role: "callout"; font.weight: Font.Medium; text: b.text
                color: b.primary ? glass.theme.on_accent : b.destructive ? glass.theme.danger : glass.theme.text }
    }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: b.clicked() }
}
