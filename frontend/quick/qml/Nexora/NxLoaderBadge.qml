// Значок загрузчика с подписью: «Fabric 1.20.1»
import QtQuick

Row {
    id: root
    property string loader: "vanilla"
    property string text: ""
    property bool mono: false
    property color color: NxTheme.muted
    spacing: 6
    NxLoaderMark { loader: root.loader; size: 14; anchors.verticalCenter: parent.verticalCenter }
    NxText {
        text: root.text
        color: root.color
        variant: root.mono ? "mono" : "body"
        font.pixelSize: 12
        lineHeight: 16
        anchors.verticalCenter: parent.verticalCenter
    }
}
