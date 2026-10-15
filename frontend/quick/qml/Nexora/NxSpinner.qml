// Индикатор ожидания: дуга 3/4 круга
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property color color: NxTheme.text
    property int size: 16
    property real stroke: 1.5
    width: size
    height: size

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        RotationAnimator on rotation { from: 0; to: 360; duration: 800; loops: Animation.Infinite; running: root.visible }
        ShapePath {
            strokeColor: root.color
            strokeWidth: root.stroke * root.size / 16
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.size / 2; centerY: root.size / 2
                radiusX: root.size * 0.375; radiusY: root.size * 0.375
                startAngle: 0; sweepAngle: 270
            }
        }
    }
}
