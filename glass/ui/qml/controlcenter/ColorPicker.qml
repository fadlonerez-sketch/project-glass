import QtQuick
import "../components"

// Full colour picker: saturation/brightness field, hue strip, HEX and RGB inputs. Edits a draft.
Item {
    id: root
    property string draft: "#8E5CF7"
    property real hue: 0
    property real sat: 0
    property real val: 0
    signal edited(string hex)
    implicitHeight: 196
    implicitWidth: 520

    function load(hex) {
        var hsv = cc.hexToHsv(hex)
        if (hsv[1] > 0.01) hue = hsv[0]
        sat = hsv[1]; val = hsv[2]
        draft = hex
        var rgb = cc.hexToRgb(hex)
        hexIn.text = hex; rIn.text = rgb[0]; gIn.text = rgb[1]; bIn.text = rgb[2]
    }
    function fromHsv() { var h = cc.hsvToHex(hue, sat, val); load(h); edited(h) }

    // saturation (x) / value (y) field
    Rectangle {
        id: field
        width: 220; height: 160; radius: 12
        color: Qt.hsva(root.hue / 360, 1, 1, 1)
        Rectangle { anchors.fill: parent; radius: 12
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "white" } GradientStop { position: 1; color: "#00FFFFFF" } } }
        Rectangle { anchors.fill: parent; radius: 12
            gradient: Gradient { GradientStop { position: 0; color: "#00000000" } GradientStop { position: 1; color: "black" } } }
        Rectangle {
            x: root.sat * field.width - 9; y: (1 - root.val) * field.height - 9
            width: 18; height: 18; radius: 9; color: root.draft; border.width: 3; border.color: "white"
        }
        MouseArea {
            anchors.fill: parent; preventStealing: true
            function set(e) { root.sat = Math.max(0, Math.min(1, e.x / width)); root.val = Math.max(0, Math.min(1, 1 - e.y / height)); root.fromHsv() }
            onPressed: (e) => set(e)
            onPositionChanged: (e) => { if (pressed) set(e) }
        }
        Accessible.role: Accessible.ColorChooser
        Accessible.name: "Saturation and brightness"
    }
    // hue strip
    Rectangle {
        id: hueBar
        x: 0; y: 172; width: 220; height: 14; radius: 7
        gradient: Gradient { orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#FF0000" } GradientStop { position: 0.17; color: "#FFFF00" }
            GradientStop { position: 0.33; color: "#00FF00" } GradientStop { position: 0.5; color: "#00FFFF" }
            GradientStop { position: 0.67; color: "#0000FF" } GradientStop { position: 0.83; color: "#FF00FF" }
            GradientStop { position: 1.0; color: "#FF0000" } }
        Rectangle { x: root.hue / 360 * hueBar.width - 9; y: -2; width: 18; height: 18; radius: 9
                    color: Qt.hsva(root.hue / 360, 1, 1, 1); border.width: 3; border.color: "white" }
        MouseArea { anchors.fill: parent; anchors.margins: -6; preventStealing: true
            function set(e) { root.hue = Math.max(0, Math.min(359.9, (e.x - 6) / hueBar.width * 360)); if (root.sat < 0.05) root.sat = 0.75; if (root.val < 0.1) root.val = 0.85; root.fromHsv() }
            onPressed: (e) => set(e); onPositionChanged: (e) => { if (pressed) set(e) } }
        Accessible.role: Accessible.Slider
        Accessible.name: "Hue"
    }

    component Field: Rectangle {
        property alias text: inp.text
        property alias input: inp
        property string label
        signal committed(string text)
        width: 64; height: 32; radius: 8
        color: glass.theme.dark ? glass.theme.surface2 : "#FFFFFF"
        border.width: 1; border.color: inp.activeFocus ? glass.theme.accent : glass.theme.hairline
        TextInput { id: inp; anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 8
                    verticalAlignment: TextInput.AlignVCenter; color: glass.theme.text; font.pixelSize: 13; selectByMouse: true
                    onEditingFinished: parent.committed(text) }
        Label { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.bottom; anchors.topMargin: 3
                role: "micro"; tertiary: true; text: parent.label }
        Accessible.role: Accessible.EditableText
        Accessible.name: label
    }

    Column {
        x: 248; y: 0; spacing: 18
        Row {
            spacing: 10
            Rectangle { width: 64; height: 64; radius: 16; color: root.draft; border.width: 1; border.color: glass.theme.hairline }
            Column { anchors.verticalCenter: parent.verticalCenter; spacing: 2
                Label { role: "headline"; text: root.draft }
                Label { role: "caption"; secondary: true; text: "Draft — not applied yet" } }
        }
        Row {
            spacing: 10
            Field { id: hexIn; width: 96; label: "HEX"
                    onCommitted: (t) => { var h = cc.normalizeHex(t); if (h) { root.load(h); root.edited(h) } else root.load(root.draft) } }
            Field { id: rIn; label: "R"; onCommitted: root.commitRgb() }
            Field { id: gIn; label: "G"; onCommitted: root.commitRgb() }
            Field { id: bIn; label: "B"; onCommitted: root.commitRgb() }
        }
    }
    function commitRgb() {
        var h = cc.rgbToHex(parseInt(rIn.text) || 0, parseInt(gIn.text) || 0, parseInt(bIn.text) || 0)
        if (h) { load(h); edited(h) } else load(draft)
    }
}
