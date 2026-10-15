// Обложка/скриншот со скруглением. Обрезка и скругление делаются провайдером image://nx/round —
// без шейдеров, поэтому работает и при программной отрисовке.
// source: адрес image://nx/<вид>/… (scene, mod, head, file, remote)
import QtQuick
import QtQuick.Window

Item {
    id: root
    property url source
    property int radius: NxTheme.rCover
    property bool dim: false
    readonly property alias status: img.status
    readonly property real dpr: Screen.devicePixelRatio
    readonly property string inner: {
        const s = source.toString()
        return s.indexOf("image://nx/") === 0 ? s.substring(11) : ""
    }

    implicitWidth: 40
    implicitHeight: 40

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: NxTheme.surface3
        visible: img.status !== Image.Ready
    }

    Image {
        id: img
        anchors.fill: parent
        visible: status === Image.Ready
        asynchronous: true
        cache: true
        sourceSize: Qt.size(Math.max(1, Math.round(root.width * root.dpr)), Math.max(1, Math.round(root.height * root.dpr)))
        source: root.inner && root.width > 0 && root.height > 0
                ? "image://nx/round/" + Math.round(root.radius * root.dpr) + "/" + (root.dim ? 1 : 0) + "/" + root.inner : ""
        opacity: root.dim ? 0.6 : 1
    }
}
