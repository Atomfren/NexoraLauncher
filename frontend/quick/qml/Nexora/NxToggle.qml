// Переключатель 34×20
import QtQuick
import QtQuick.Templates as T

T.Switch {
    id: root
    implicitWidth: 34
    implicitHeight: 20
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    opacity: enabled ? 1 : 0.4
    padding: 0

    indicator: Rectangle {
        width: 34
        height: 20
        radius: 10
        color: root.checked ? (root.hovered ? NxTheme.accentHover : NxTheme.accent) : (root.hovered ? NxTheme.fill3 : NxTheme.surface3)
        Behavior on color { ColorAnimation { duration: NxTheme.base } }
        Rectangle {
            width: 14; height: 14; radius: 7; y: 3
            x: root.checked ? 17 : 3
            color: root.checked ? NxTheme.onAccent : NxTheme.muted
            Behavior on x { NumberAnimation { duration: NxTheme.base; easing.type: NxTheme.ease } }
        }
        Rectangle {
            anchors.fill: parent; anchors.margins: -3; radius: 13
            color: "transparent"; border.color: NxTheme.accent; border.width: 2; visible: root.visualFocus
        }
    }
    contentItem: Item {}
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
