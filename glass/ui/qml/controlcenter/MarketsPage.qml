import QtQuick
import "../components"

Column {
    id: page
    spacing: 24
    readonly property var m: cc.markets || ({})
    property string target: "markets.watchlist"

    component SymbolList: Section {
        id: sl
        property string key
        property var entries: []
        readonly property var symbols: cc.settings[key] || []
        Repeater {
            model: sl.symbols
            Row_ {
                readonly property var e: (sl.entries || []).find(x => x.symbol === modelData) || null
                title: e && e.name && e.name !== modelData ? modelData + "  ·  " + e.name : modelData
                subtitle: !e || e.price === null || e.price === undefined ? (e && e.error ? e.error : "No data yet")
                          : e.price.toFixed(2) + " " + (e.currency || "") + "   " + ((e.changePct || 0) >= 0 ? "▲ " : "▼ ") + Math.abs(e.changePct || 0).toFixed(2) + "%   ·   " + e.statusLabel
                last: index === sl.symbols.length - 1
                Row {
                    spacing: 4
                    IconButton { visible: index > 0; icon: "chevron-up"; size: 28; iconSize: 13; tooltip: "Move earlier"; onClicked: cc.moveSymbol(sl.key, modelData, -1) }
                    IconButton { visible: index < sl.symbols.length - 1; icon: "chevron-down"; size: 28; iconSize: 13; tooltip: "Move later"; onClicked: cc.moveSymbol(sl.key, modelData, 1) }
                    PushButton { text: "Remove"; destructive: true; onClicked: cc.removeSymbol(sl.key, modelData) }
                }
            }
        }
        Item { width: parent.width; height: 40; visible: sl.symbols.length === 0
               Label { anchors.verticalCenter: parent.verticalCenter; role: "callout"; tertiary: true; text: "Nothing here yet — add a symbol below." } }
    }

    Section {
        title: "Markets in the top bar"
        footer: "Indices sit to the left of the Dynamic Glass and your watchlist to the right, on the display that has the Dynamic Glass. Tickers that don't fit are left out from the outer end. The status beside them always says how fresh the numbers are: Live, Delayed (with how long), Closed (as of the last trade) or Not updated since (when refreshing fails). Old or delayed numbers are never shown as live."
        SettingToggle { title: "Show markets"; key: "markets.enabled" }
        SettingToggle { title: "Show market indices"; key: "markets.show_indices" }
        SettingToggle { title: "Miniature charts"; subtitle: "Today's movement, with the previous close as a dotted line"; key: "markets.sparklines" }
        SettingSlider { title: "Refresh every"; subtitle: "While a market you watch is open; much less often when all are closed"; key: "markets.refresh_s"
                        from: 60; to: 1800; step: 30; percent: false; unit: " s" }
        Row_ {
            title: "Now"; last: true
            subtitle: !cc.shellConnected ? "Start Project Glass to fetch quotes" : (page.m.label || "—") + (page.m.updated ? "   ·   " + page.m.updated : "")
            PushButton { text: "Refresh now"; icon: "refresh"; enabled: cc.shellConnected; onClicked: { cc.shellCommand("refresh_markets"); refreshT.restart() } }
            Timer { id: refreshT; interval: 2500; onTriggered: cc.refreshMarkets() }
        }
    }

    SymbolList { title: "Watchlist"; key: "markets.watchlist"; entries: page.m.watchlist || [] }
    SymbolList { title: "Indices"; key: "markets.indices"; entries: page.m.indices || [] }

    Section {
        title: "Add a symbol"
        Item {
            width: parent.width; height: 52
            Row {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                spacing: 10
                Rectangle {
                    width: parent.width - addTo.width - 10; height: 34; radius: 9; color: glass.theme.dark ? glass.theme.surface2 : glass.theme.bg
                    border.width: 1; border.color: q.activeFocus ? glass.theme.accent : glass.theme.hairline
                    Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 15; color: glass.theme.text3 }
                    TextInput { id: q; anchors.fill: parent; anchors.leftMargin: 34; anchors.rightMargin: 10
                                verticalAlignment: TextInput.AlignVCenter; color: glass.theme.text; font.pixelSize: 13; clip: true
                                onTextChanged: qT.restart()
                                Accessible.role: Accessible.EditableText; Accessible.name: "Search companies, ETFs and indices" }
                    Label { x: 34; anchors.verticalCenter: parent.verticalCenter; role: "callout"; tertiary: true; visible: !q.text
                            text: "Company, ticker or index (e.g. Tesla, VOO, ^FTSE)" }
                    Timer { id: qT; interval: 300; onTriggered: cc.searchMarkets(q.text) }
                }
                Segmented {
                    id: addTo
                    anchors.verticalCenter: parent.verticalCenter
                    options: [["markets.watchlist", "Watchlist"], ["markets.indices", "Indices"]]
                    value: page.target
                    onPicked: (v) => page.target = v
                }
            }
        }
        Repeater {
            model: cc.marketResults
            Row_ {
                title: modelData.symbol + "  ·  " + modelData.name
                subtitle: (modelData.exchange || "") + (modelData.type ? " · " + modelData.type.toLowerCase() : "")
                last: index === cc.marketResults.length - 1
                PushButton { text: "Add"; icon: "plus"; primary: true; onClicked: { cc.addSymbol(page.target, modelData.symbol); q.text = "" } }
            }
        }
    }

    Section {
        title: "About the data"
        footer: "Quotes come from Yahoo Finance's public chart service, which is unofficial: it has no published terms for apps, can change without notice, and may be delayed by the exchange. Glass asks for a few symbols every few minutes, only while markets are open, and keeps the last good values to show (clearly marked as not current) when you're offline. This is information, not investment advice."
        Row_ { title: "Source"; subtitle: page.m.source || "Yahoo Finance (unofficial)"; last: true }
    }
}
