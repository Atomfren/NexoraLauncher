// Вкладки с подчёркиванием акцентом: model — массив { value, label, count? }
import QtQuick

Item {
    id: root
    property var model: []
    property string value: ""
    signal activated(string value)

    implicitHeight: 36
    implicitWidth: row.implicitWidth

    Row {
        id: row
        height: parent.height
        spacing: 4
        Repeater {
            id: rep
            model: root.model
            delegate: Item {
                id: tab
                required property var modelData
                readonly property bool active: modelData.value === root.value
                width: content.implicitWidth + 24
                height: row.height
                Row {
                    id: content
                    anchors.centerIn: parent
                    spacing: 6
                    NxText {
                        text: tab.modelData.label
                        variant: "strong"
                        color: tab.active || area.containsMouse ? NxTheme.text : NxTheme.muted
                        anchors.verticalCenter: parent.verticalCenter
                        Behavior on color { ColorAnimation { duration: NxTheme.fast } }
                    }
                    NxText {
                        visible: tab.modelData.count !== undefined && tab.modelData.count !== null && tab.modelData.count !== 0
                        text: tab.modelData.count !== undefined ? String(tab.modelData.count) : ""
                        variant: "mono"
                        font.pixelSize: 11
                        lineHeight: 16
                        muted: true
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.activated(tab.modelData.value)
                }
            }
        }
    }

    // Подчёркивание переезжает к активной вкладке
    Rectangle {
        id: underline
        readonly property Item target: {
            for (let i = 0; i < rep.count; ++i) {
                const it = rep.itemAt(i)
                if (it && it.active) return it
            }
            return null
        }
        visible: target !== null
        x: target ? target.x + 12 : 0
        width: target ? target.width - 24 : 0
        y: parent.height - 2
        height: 2
        radius: 1
        color: NxTheme.accent
        Behavior on x { NumberAnimation { duration: NxTheme.base; easing.type: NxTheme.ease } }
        Behavior on width { NumberAnimation { duration: NxTheme.base; easing.type: NxTheme.ease } }
    }
}
