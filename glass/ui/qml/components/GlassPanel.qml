import QtQuick

// A GlassSurface whose children are laid out inside the glass shape (not the shadow margin).
GlassSurface {
    id: panel
    default property alias content: holder.data
    property real padding: 0
    implicitWidth: holder.childrenRect.width + 2 * (margin + padding)
    implicitHeight: holder.childrenRect.height + 2 * (margin + padding)
    Item {
        id: holder
        parent: panel.contentArea
        anchors.fill: parent
        anchors.margins: panel.padding
    }
}
