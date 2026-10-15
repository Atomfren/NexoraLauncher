// Пункт боковой панели: иконка 20 px, подпись видна в широком режиме
import QtQuick
import QtQuick.Controls as C

Rectangle {
    id: root
    property string iconName: ""
    property string text: ""
    property bool current: false
    property bool wide: false
    signal clicked()

    width: parent ? parent.width : 48
    height: 40
    radius: NxTheme.rButton
    clip: true
    color: current ? NxTheme.fill2 : area.containsMouse ? NxTheme.fill1 : "transparent"
    Behavior on color { ColorAnimation { duration: NxTheme.fast } }

    Rectangle {
        visible: root.current
        x: 0; y: 10
        width: 2; height: parent.height - 20
        radius: 1
        color: NxTheme.accent
    }
    NxIcon {
        id: ico
        x: 14
        anchors.verticalCenter: parent.verticalCenter
        name: root.iconName
        size: 20
        color: root.current || area.containsMouse ? NxTheme.text : NxTheme.muted
    }
    NxText {
        anchors.left: ico.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        variant: "strong"
        color: ico.color
        opacity: root.wide ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: NxTheme.fast } }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
    C.ToolTip.visible: !wide && area.containsMouse
    C.ToolTip.delay: 500
    C.ToolTip.text: text
    Accessible.name: text
}
