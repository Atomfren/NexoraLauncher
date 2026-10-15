// Заголовок секции: подпись капсом слева, действие справа
import QtQuick

Item {
    id: root
    property string text: ""
    property string actionText: ""
    signal action()
    width: parent ? parent.width : 200
    height: 28
    NxText { text: root.text; variant: "caption"; anchors.verticalCenter: parent.verticalCenter }
    NxButton {
        visible: root.actionText !== ""
        text: root.actionText
        variant: "ghost"
        small: true
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        onClicked: root.action()
    }
}
