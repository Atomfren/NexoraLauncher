// Группа строк настроек на поверхности surface-1, без обводки
import QtQuick

Rectangle {
    id: root
    default property alias rows: col.data
    width: parent ? parent.width : 600
    height: col.implicitHeight + 8
    radius: NxTheme.rButton
    color: NxTheme.surface1
    Column {
        id: col
        x: 16
        y: 4
        width: parent.width - 32
    }
}
