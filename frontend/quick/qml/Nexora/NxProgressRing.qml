// Кольцо прогресса (загрузки, установка из каталога)
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property real value: 0          // 0…100
    property int size: 20
    property color color: NxTheme.accent
    width: size
    height: size

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: NxTheme.surface3
            strokeWidth: 2.5 * root.size / 20
            fillColor: "transparent"
            PathAngleArc { centerX: root.size / 2; centerY: root.size / 2; radiusX: root.size * 0.4; radiusY: root.size * 0.4; startAngle: 0; sweepAngle: 360 }
        }
        ShapePath {
            strokeColor: root.color
            strokeWidth: 2.5 * root.size / 20
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.size / 2; centerY: root.size / 2
                radiusX: root.size * 0.4; radiusY: root.size * 0.4
                startAngle: -90
                sweepAngle: 360 * Math.max(0.01, Math.min(100, root.value)) / 100
                Behavior on sweepAngle { NumberAnimation { duration: 200 } }
            }
        }
    }
}
