import QtQuick
import "../components"

// One settings row: title + optional subtitle on the left, a control on the right, hairline below.
Item {
    id: root
    property string title: ""
    property string subtitle: ""
    property bool last: false
    default property alias control: slot.data
    property real controlWidth: slot.childrenRect.width
    width: parent ? parent.width : 400
    height: Math.max(48, texts.implicitHeight + 20)
    Column {
        id: texts
        anchors.left: parent.left
        anchors.right: slot.left; anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        Label { width: parent.width; role: "body"; text: root.title }
        Label { width: parent.width; role: "caption"; secondary: true; text: root.subtitle; visible: text !== ""; wrapMode: Text.Wrap; elide: Text.ElideNone }
    }
    Item {
        id: slot
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: childrenRect.width; height: childrenRect.height
    }
    Rectangle { visible: !root.last; anchors.bottom: parent.bottom; width: parent.width; height: 1; color: glass.theme.separator }
}
