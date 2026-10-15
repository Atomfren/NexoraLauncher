// Кнопка-иконка 32 / 28 px
import QtQuick
import QtQuick.Templates as T
import QtQuick.Controls as C

T.ToolButton {
    id: root
    property string iconName: ""
    property bool small: false
    property bool on: false
    property string tip: ""
    property int iconSize: small ? 14 : 16
    property color iconColor: hovered || down || on ? NxTheme.text : NxTheme.muted

    implicitWidth: small ? 28 : 32
    implicitHeight: implicitWidth
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    opacity: enabled ? 1 : 0.4

    background: Rectangle {
        radius: NxTheme.rButton
        color: root.down ? NxTheme.fill2 : (root.hovered || root.on) ? NxTheme.fill1 : "transparent"
        Behavior on color { ColorAnimation { duration: NxTheme.fast } }
        Rectangle {
            anchors.fill: parent; anchors.margins: -2; radius: NxTheme.rButton + 2
            color: "transparent"; border.color: NxTheme.accent; border.width: 2; visible: root.visualFocus
        }
    }
    contentItem: Item {
        NxIcon { anchors.centerIn: parent; name: root.iconName; size: root.iconSize; color: root.iconColor }
    }

    C.ToolTip.visible: tip !== "" && hovered
    C.ToolTip.delay: 600
    C.ToolTip.text: tip
    Accessible.name: tip

    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
