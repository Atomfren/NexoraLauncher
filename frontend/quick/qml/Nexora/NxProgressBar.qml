// Полоса прогресса 4 px; indeterminate — бегущий отрезок
import QtQuick

Rectangle {
    id: root
    property real value: 0          // 0…100
    property bool indeterminate: false
    property color fillColor: NxTheme.accent

    implicitHeight: 4
    radius: height / 2
    color: NxTheme.surface3
    clip: true

    Rectangle {
        id: fill
        height: parent.height
        radius: parent.radius
        color: root.fillColor
        width: root.indeterminate ? parent.width * 0.36 : parent.width * Math.max(0, Math.min(100, root.value)) / 100
        Behavior on width { enabled: !root.indeterminate; NumberAnimation { duration: 200 } }
        NumberAnimation on x {
            running: root.indeterminate && root.visible
            from: -root.width * 0.36; to: root.width
            duration: 1200; loops: Animation.Infinite; easing.type: Easing.OutCubic
        }
    }
}
