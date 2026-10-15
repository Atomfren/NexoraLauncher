// Пункт меню: иконка, текст, галочка или подсказка справа
import QtQuick

Rectangle {
    id: root
    property string text: ""
    property string iconName: ""
    property string hint: ""
    property bool checked: false
    property bool danger: false
    property bool selected: false
    property Item leading: null
    signal triggered()

    width: parent ? parent.width : implicitWidth
    implicitWidth: row.implicitWidth + 16
    implicitHeight: 32
    radius: 4
    color: area.containsMouse || selected ? NxTheme.fill1 : "transparent"
    opacity: enabled ? 1 : 0.4

    Row {
        id: row
        x: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        NxIcon {
            visible: root.iconName !== ""
            name: root.iconName
            color: root.danger ? NxTheme.danger : NxTheme.muted
            anchors.verticalCenter: parent.verticalCenter
        }
        NxText {
            text: root.text
            color: root.danger ? NxTheme.danger : NxTheme.text
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    NxIcon {
        visible: root.checked
        name: "check"
        size: 14
        color: NxTheme.muted
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
    }
    NxText {
        visible: root.hint !== "" && !root.checked
        text: root.hint
        variant: "mono"
        muted: true
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.triggered()
    }
}
