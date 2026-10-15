// Значок загрузчика: vanilla, fabric, quilt, forge, neoforge, optifine, paper, purpur
import QtQuick
import QtQuick.Window

Image {
    property string loader: "vanilla"
    property int size: 16
    width: size
    height: size
    source: "image://nx/loader/" + loader
    sourceSize: Qt.size(Math.ceil(size * Screen.devicePixelRatio), Math.ceil(size * Screen.devicePixelRatio))
    smooth: true
}
