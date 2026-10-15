// Контурная иконка Lucide нужного цвета (рисуется провайдером image://nx/icon)
import QtQuick
import QtQuick.Window

Image {
    id: root
    property string name: ""
    property color color: NxTheme.muted
    property int size: 16

    width: size
    height: size
    visible: name !== ""
    source: name ? NxTheme.icon(name, color) : ""
    sourceSize: Qt.size(Math.ceil(size * Screen.devicePixelRatio), Math.ceil(size * Screen.devicePixelRatio))
    fillMode: Image.PreserveAspectFit
    smooth: true
    cache: true
}
