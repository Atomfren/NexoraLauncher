// Радиокнопка-индикатор 16×16 (выбор делает строка-родитель)
import QtQuick

Rectangle {
    property bool checked: false
    width: 16
    height: 16
    radius: 8
    color: checked ? NxTheme.accent : NxTheme.surface3
    Rectangle { anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: NxTheme.onAccent; visible: parent.checked }
}
