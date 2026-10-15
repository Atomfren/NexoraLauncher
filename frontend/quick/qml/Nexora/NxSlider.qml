// Ползунок: дорожка 4 px, заполнение акцентом, ручка 16 px
import QtQuick
import QtQuick.Templates as T

T.Slider {
    id: root
    implicitWidth: 200
    implicitHeight: 20
    hoverEnabled: true
    focusPolicy: Qt.TabFocus

    background: Item {
        x: root.leftPadding
        width: root.availableWidth
        height: root.height
        Rectangle { y: (parent.height - 4) / 2; width: parent.width; height: 4; radius: 2; color: NxTheme.surface3 }
        Rectangle { y: (parent.height - 4) / 2; width: root.visualPosition * parent.width; height: 4; radius: 2; color: NxTheme.accent }
    }
    handle: Rectangle {
        x: root.leftPadding + root.visualPosition * (root.availableWidth - width)
        y: (root.height - height) / 2
        width: 16; height: 16; radius: 8
        color: NxTheme.text
        scale: root.pressed ? 1.1 : 1
        Behavior on scale { NumberAnimation { duration: NxTheme.fast } }
        Rectangle {
            anchors.fill: parent; anchors.margins: -3; radius: 11
            color: "transparent"; border.color: NxTheme.accent; border.width: 2; visible: root.visualFocus
        }
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
