// Тонкая полоса прокрутки цвета surface-3
import QtQuick
import QtQuick.Templates as T

T.ScrollBar {
    id: root
    implicitWidth: 10
    implicitHeight: 10
    padding: 2
    minimumSize: 0.08
    visible: size < 1.0
    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 6
        radius: 3
        color: root.pressed ? NxTheme.fill3 : NxTheme.surface3
        opacity: root.active || root.hovered ? 1 : 0.7
    }
}
