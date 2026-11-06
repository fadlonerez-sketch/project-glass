import QtQuick
import "../components"

// Segmented control bound to an enum setting. options: [[value, label], ...]
Row_ {
    id: r
    property string key: ""
    property var options: []
    Segmented {
        options: r.options
        value: cc.settings[r.key]
        onPicked: (v) => cc.set(r.key, v)
    }
}
