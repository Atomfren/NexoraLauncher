// Строка настроек: подпись слева, элемент управления справа. Разделитель — линия сверху.
import QtQuick

Item {
    id: root
    property string label: ""
    property string hint: ""
    property bool first: false
    default property alias control: box.data

    width: parent ? parent.width : 400
    height: Math.max(52, box.childrenRect.height + 16, labels.implicitHeight + 16)

    Rectangle { visible: !root.first; width: parent.width; height: 1; color: NxTheme.line }
    Column {
        id: labels
        anchors.left: parent.left
        anchors.right: box.left
        anchors.rightMargin: 24
        anchors.verticalCenter: parent.verticalCenter
        NxText { width: parent.width; text: root.label }
        NxText { visible: root.hint !== ""; width: parent.width; text: root.hint; muted: true; font.pixelSize: 12; lineHeight: 16; wrapMode: Text.Wrap; elide: Text.ElideNone }
    }
    Item {
        id: box
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: childrenRect.width
        height: childrenRect.height
    }
}
