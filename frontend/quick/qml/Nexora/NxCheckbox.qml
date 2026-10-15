// Флажок 16×16; partial — «выбрано не всё»
import QtQuick
import QtQuick.Templates as T

T.CheckBox {
    id: root
    property bool partial: false
    implicitWidth: 16 + (text ? 10 + label.implicitWidth : 0)
    implicitHeight: Math.max(16, text ? 20 : 16)
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    opacity: enabled ? 1 : 0.4
    padding: 0

    indicator: Rectangle {
        width: 16; height: 16; radius: 3
        anchors.verticalCenter: parent.verticalCenter
        color: root.checked || root.partial ? NxTheme.accent : root.hovered ? NxTheme.fill3 : NxTheme.surface3
        Behavior on color { ColorAnimation { duration: NxTheme.fast } }
        NxIcon {
            anchors.centerIn: parent
            size: 12
            name: root.partial && !root.checked ? "minus" : "check"
            color: NxTheme.onAccent
            visible: root.checked || root.partial
        }
        Rectangle {
            anchors.fill: parent; anchors.margins: -3; radius: 6
            color: "transparent"; border.color: NxTheme.accent; border.width: 2; visible: root.visualFocus
        }
    }
    contentItem: NxText {
        id: label
        leftPadding: 26
        text: root.text
        visible: root.text !== ""
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
