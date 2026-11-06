import QtQuick
import "../components"

Rectangle {
    id: seg
    property var options: []        // [[value, label], ...]
    property var value
    signal picked(var value)
    width: row.width + 6; height: 30
    radius: 9
    color: glass.theme.control
    Accessible.role: Accessible.PageTabList
    Rectangle {    // the sliding selection
        id: sel
        property Item target: row.children[Math.max(0, seg.options.findIndex(o => o[0] === seg.value))] || null
        x: target ? target.x + 3 : 3; y: 3
        width: target ? target.width : 0; height: parent.height - 6
        radius: 7
        color: glass.theme.dark ? glass.theme.surface3 : "#FFFFFF"
        border.width: glass.theme.dark ? 0 : 1; border.color: glass.theme.hairline
        Behavior on x { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
    }
    Row {
        id: row
        x: 3; y: 3; height: parent.height - 6
        Repeater {
            model: seg.options
            Item {
                width: lbl.implicitWidth + 24; height: row.height
                Label { id: lbl; anchors.centerIn: parent; role: "callout"; text: modelData[1]
                        font.weight: seg.value === modelData[0] ? Font.DemiBold : Font.Normal }
                MouseArea { anchors.fill: parent; onClicked: seg.picked(modelData[0])
                            Accessible.role: Accessible.PageTab; Accessible.name: modelData[1] }
            }
        }
    }
}
