// Прокручиваемое тело вкладки с отступами 24 / 32
import QtQuick
import QtQuick.Controls as C
import Nexora

Flickable {
    id: root
    default property alias content: inner.data
    property alias spacing: inner.spacing
    readonly property int innerWidth: width - 64

    clip: true
    contentWidth: width
    contentHeight: inner.implicitHeight + 56
    boundsBehavior: Flickable.StopAtBounds
    C.ScrollBar.vertical: NxScrollBar {}

    Column {
        id: inner
        x: 32
        y: 24
        width: root.width - 64
        spacing: 0
    }
}
