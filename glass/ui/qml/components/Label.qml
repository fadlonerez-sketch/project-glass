import QtQuick

// Typography roles: display, title, headline, body, callout, caption, micro.
Text {
    property string role: "body"
    property bool secondary: false
    property bool tertiary: false
    readonly property var sizes: ({ display: 28, title: 20, headline: 15, body: 13, callout: 12, caption: 11, micro: 10 })
    readonly property var weights: ({ display: Font.DemiBold, title: Font.DemiBold, headline: Font.DemiBold,
                                      body: Font.Normal, callout: Font.Normal, caption: Font.Normal, micro: Font.Medium })
    color: tertiary ? glass.theme.text3 : secondary ? glass.theme.text2 : glass.theme.text
    font.family: (role === "display" || role === "title") ? glass.theme.font_display : glass.theme.font_text
    font.pixelSize: sizes[role] || 13
    font.weight: weights[role] !== undefined ? weights[role] : Font.Normal
    font.letterSpacing: role === "display" ? -0.4 : role === "title" ? -0.2 : role === "micro" ? 0.2 : 0
    elide: Text.ElideRight
    verticalAlignment: Text.AlignVCenter
    textFormat: Text.PlainText
    renderType: Text.QtRendering
}
