import QtQuick
import QtQuick.Window

// The Liquid Glass material. The item is the shape plus a margin for its shadow; put content in `contentArea`
// (or use GlassPanel). All glass effects scale with glass.material.intensity inside the shader; at 0 this is
// the plain base material with its hairline and shadow.
ShaderEffect {
    id: root
    property real radius: 16
    property real margin: 26
    property string tone: "base"           // base | elevated | deep | accent
    property real elevation: 1.0           // scales the shadow (depth)
    property Item backdropItem: null       // a hidden, mipmapped Image of this monitor's desktop backdrop
    property color glowColor: glass.theme.accent
    property real glow: 0.0                // accent rim glow 0..1 (Garvis activity, focus)
    property real tintOverride: -1         // >=0 forces the tint opacity (e.g. opaque menus)
    property int geometryTick: 0           // bump when an ancestor moves, to re-map the backdrop
    property Item backdropFrame: null      // map the backdrop onto this item instead of the monitor (previews)
    property var materialOverride: null    // a material map to use instead of glass.material (preset previews)
    property point lightPoint: Qt.point(-1, -1)   // cursor position in shape (contentArea) coords, for the dynamic light
    property real lightStrength: 0
    readonly property alias contentArea: inner

    readonly property var m: materialOverride || glass.material
    readonly property bool darkTheme: glass.theme.dark
    readonly property color toneColor: tone === "deep" ? (darkTheme ? "#0B0B0F" : "#17171C")
                                     : tone === "elevated" ? (darkTheme ? Qt.lighter(glass.theme.surface, 1.12) : "#FFFFFF")
                                     : tone === "accent" ? glass.theme.accent
                                     : m.baseColor
    readonly property color glassTint: tone === "deep" ? (darkTheme ? "#08080B" : "#141418")
                                     : tone === "accent" ? glass.theme.accent : m.tintColor

    // ---- uniforms (names match liquidglass.frag) ------------------------------------------------
    property vector2d itemSize: Qt.vector2d(width, height)
    property vector4d shapeRect: Qt.vector4d(margin, margin, Math.max(0, width - 2 * margin), Math.max(0, height - 2 * margin))
    property real intensity: m.intensity
    property real blur: m.blur
    property real refraction: m.refraction
    property real shine: m.shine
    property real tintOpacity: tintOverride >= 0 ? tintOverride
                               : (tone === "deep" ? Math.max(0.62, m.tintOpacity)
                                  : tone === "elevated" ? Math.max(0.56, m.tintOpacity)   // panels full of text
                                  : m.tintOpacity)
    property color tintColor: Qt.rgba(toneColor.r + (glassTint.r - toneColor.r) * intensity,
                                      toneColor.g + (glassTint.g - toneColor.g) * intensity,
                                      toneColor.b + (glassTint.b - toneColor.b) * intensity, 1)
    // Where this item sits on its monitor, from the window's *intended* placement (backdropOrigin /
    // backdropSize, declared by the Shell windows), so the mapping holds during moves and display changes.
    property vector4d backdropRect: {
        geometryTick; x; y; width; height;
        if (backdropFrame) {
            var f = root.mapToItem(backdropFrame, 0, 0)
            return Qt.vector4d(f.x / backdropFrame.width, f.y / backdropFrame.height,
                               width / backdropFrame.width, height / backdropFrame.height)
        }
        var w = root.Window.window
        if (!w || !backdropItem) return Qt.vector4d(0, 0, 1, 1)
        var g = root.mapToItem(null, 0, 0)
        var o = w.backdropOrigin !== undefined ? w.backdropOrigin : Qt.point(w.x - root.Screen.virtualX, w.y - root.Screen.virtualY)
        var sz = w.backdropSize !== undefined ? w.backdropSize : Qt.size(root.Screen.width, root.Screen.height)
        return Qt.vector4d((o.x + g.x) / sz.width, (o.y + g.y) / sz.height, width / sz.width, height / sz.height)
    }
    property real dpr: Screen.devicePixelRatio
    property real shadowStrength: Math.min(1.0, m.depth * 1.35 * elevation)
    property real darkMode: (tone === "deep" || darkTheme) ? 1.0 : 0.0
    property real backdropLod: 8
    property vector4d accentGlow: Qt.vector4d(glowColor.r, glowColor.g, glowColor.b, glow)
    property real edge: m.edge
    property real rimTop: 1
    property color accentColor: m.accentColor || glass.theme.accent
    property vector4d accentTint: Qt.vector4d(accentColor.r, accentColor.g, accentColor.b,
                                              tone === "accent" ? 0 : (m.tintStrength || 0) * (tone === "deep" ? 0.55 : 1.0))
    property vector4d pointerLight: Qt.vector4d(lightPoint.x + margin, lightPoint.y + margin, lightStrength, 0)
    property real frost: m.frost || 0
    Behavior on lightStrength { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    property variant backdrop: backdropItem

    fragmentShader: shaderUrl
    blending: true

    Item {
        id: inner
        x: root.margin; y: root.margin
        width: Math.max(0, root.width - 2 * root.margin)
        height: Math.max(0, root.height - 2 * root.margin)
    }
}
