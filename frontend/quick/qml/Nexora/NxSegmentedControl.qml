// Сегменты: model — массив { value, label }
import QtQuick

Rectangle {
    id: root
    property var model: []
    property string value: ""
    signal activated(string value)

    implicitWidth: row.implicitWidth + 4
    implicitHeight: 32
    radius: NxTheme.rButton
    color: NxTheme.surface2

    Row {
        id: row
        x: 2
        y: 2
        spacing: 2
        Repeater {
            model: root.model
            delegate: Rectangle {
                id: seg
                required property var modelData
                readonly property bool active: modelData.value === root.value
                width: lbl.implicitWidth + 24
                height: 28
                radius: 4
                color: active ? NxTheme.surface3 : "transparent"
                Behavior on color { ColorAnimation { duration: NxTheme.fast } }
                NxText {
                    id: lbl
                    anchors.centerIn: parent
                    text: seg.modelData.label
                    variant: "strong"
                    color: seg.active || area.containsMouse ? NxTheme.text : NxTheme.muted
                }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (!seg.active) root.activated(seg.modelData.value)
                }
            }
        }
    }
}
