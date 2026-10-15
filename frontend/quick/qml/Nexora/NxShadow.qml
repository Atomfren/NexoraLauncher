// Мягкая тень без шейдеров: несколько полупрозрачных слоёв под поверхностью.
// Кладётся первым ребёнком фона, anchors.fill: parent.
import QtQuick

Item {
    id: root
    property int radius: NxTheme.rButton
    property int offsetY: 8
    property int spread: 12
    z: -1

    Repeater {
        model: 6
        delegate: Rectangle {
            required property int index
            readonly property real k: (index + 1) / 6
            x: -root.spread * k
            y: -root.spread * k + root.offsetY * k
            width: root.width + 2 * root.spread * k
            height: root.height + 2 * root.spread * k
            radius: root.radius + root.spread * k
            color: NxTheme.shadow
            opacity: 0.16 * (1 - k * 0.8)
        }
    }
}
