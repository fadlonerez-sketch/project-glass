import QtQuick
import "../components"

Row_ {
    id: r
    property string key: ""
    Toggle {
        checked: !!cc.settings[r.key]
        accessibleName: r.title
        onToggled: (c) => cc.set(r.key, c)
    }
}
