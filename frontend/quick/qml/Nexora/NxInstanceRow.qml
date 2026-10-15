// Строка сборки в библиотеке: обложка 40 px, имя, загрузчик и версия, время игры
import QtQuick

Rectangle {
    id: root
    property string name: ""
    property string loader: "vanilla"
    property string version: ""
    property string playtime: ""
    property string state_: "ready"
    property url cover
    property bool selected: false
    signal clicked()
    signal contextMenu(real x, real y)

    height: 56
    radius: NxTheme.rButton
    color: selected ? NxTheme.fill2 : area.containsMouse ? NxTheme.fill1 : "transparent"
    Behavior on color { ColorAnimation { duration: NxTheme.fast } }

    Rectangle {
        visible: root.selected
        x: -8
        y: 14
        width: 2
        height: parent.height - 28
        radius: 1
        color: NxTheme.accent
    }

    NxCover {
        id: cov
        x: 8
        width: 40
        height: 40
        anchors.verticalCenter: parent.verticalCenter
        source: root.cover
        dim: root.state_ === "none"
    }

    Column {
        anchors.left: cov.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        NxText { width: parent.width; text: root.name; variant: "strong"; lineHeight: 18 }
        Item {
            width: parent.width
            height: 16
            NxLoaderBadge { loader: root.loader; text: root.version; mono: true; anchors.verticalCenter: parent.verticalCenter }
            NxDot {
                visible: root.state_ === "running"
                kind: "ok"; size: 6
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
            }
            NxSpinner {
                visible: root.state_ === "installing" || root.state_ === "launching"
                size: 12; color: NxTheme.muted
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
            }
            NxText {
                visible: root.state_ === "ready" || root.state_ === "none"
                text: root.playtime
                variant: "mono"; muted: true
                font.pixelSize: 12; lineHeight: 16
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: mouse => {
            root.clicked()
            if (mouse.button === Qt.RightButton) root.contextMenu(mouse.x, mouse.y)
        }
    }
}
