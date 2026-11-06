import QtQuick
import "../components"

// A titled group of settings rows on a rounded card, rows separated by hairlines.
Column {
    id: root
    property string title: ""
    property string footer: ""
    default property alias rows: card.rowsData
    width: parent ? parent.width : 400
    spacing: 8
    Label { visible: root.title !== ""; role: "callout"; font.weight: Font.DemiBold; secondary: true; text: root.title; leftPadding: 4 }
    Rectangle {
        id: card
        property alias rowsData: inner.data
        width: parent.width
        height: inner.implicitHeight + 8
        radius: 14
        color: glass.theme.surface
        border.width: 1; border.color: glass.theme.hairline
        Column {
            id: inner
            x: 16; y: 4; width: parent.width - 32
        }
    }
    Label { visible: root.footer !== ""; width: parent.width; wrapMode: Text.Wrap; role: "caption"; tertiary: true
            text: root.footer; leftPadding: 4 }
}
