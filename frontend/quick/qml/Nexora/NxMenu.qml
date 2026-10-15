// Меню действий. Пункты: { text, icon, danger, separator, enabled, action }.
// Появляется под anchorItem (или над ним, если внизу не хватает места).
import QtQuick
import QtQuick.Templates as T

NxPopover {
    id: root
    property var items: []
    property Item anchorItem: null
    property bool alignRight: false
    property int minWidth: 220
    signal triggered(string action)

    parent: T.Overlay.overlay
    width: Math.max(minWidth, col.implicitWidth + 8)

    function openAt(item) {
        anchorItem = item
        const p = item.mapToItem(parent, 0, 0)
        const h = col.implicitHeight + 8
        x = alignRight ? p.x + item.width - width : p.x
        y = (p.y + item.height + 4 + h > parent.height - 8) ? p.y - h - 4 : p.y + item.height + 4
        open()
    }

    contentItem: Column {
        id: col
        spacing: 0
        Repeater {
            model: root.items
            delegate: Loader {
                id: loader
                required property var modelData
                width: col.width
                sourceComponent: modelData.separator ? sep : item
                Component {
                    id: sep
                    Item { height: 8 }
                }
                Component {
                    id: item
                    NxMenuItem {
                        text: loader.modelData.text
                        iconName: loader.modelData.icon || ""
                        danger: !!loader.modelData.danger
                        checked: !!loader.modelData.checked
                        hint: loader.modelData.hint || ""
                        enabled: loader.modelData.enabled !== false
                        onTriggered: { root.close(); root.triggered(loader.modelData.action) }
                    }
                }
            }
        }
    }
}
