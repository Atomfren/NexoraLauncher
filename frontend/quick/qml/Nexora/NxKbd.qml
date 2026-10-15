// Подсказка клавиш: «Ctrl K», «Esc»
import QtQuick

Rectangle {
    property alias text: label.text
    implicitWidth: label.implicitWidth + 10
    implicitHeight: 16
    radius: 3
    color: NxTheme.fill1
    NxText {
        id: label
        anchors.centerIn: parent
        variant: "monoStrong"
        font.pixelSize: 11
        lineHeight: 16
        color: NxTheme.muted
    }
}
