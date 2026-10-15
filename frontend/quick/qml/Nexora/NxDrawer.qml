// Выдвижная панель справа (480 px): шапка, прокручиваемое тело, подвал
import QtQuick
import QtQuick.Templates as T
import QtQuick.Controls as C

T.Popup {
    id: root
    property string title: ""
    property string subtitle: ""
    property url iconSource
    property alias header: lead.data
    property alias footer: foot.data
    default property alias body: bodyCol.data
    property bool scrollable: true
    property alias bodySpacing: bodyCol.spacing
    readonly property int bodyWidth: width - 48

    parent: T.Overlay.overlay
    x: parent ? parent.width - width : 0
    y: 0
    width: Math.min(480, parent ? parent.width - 72 : 480)
    height: parent ? parent.height : 600
    modal: true
    dim: true
    padding: 0
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside

    T.Overlay.modal: Rectangle { color: NxTheme.scrim }
    background: Rectangle {
        color: NxTheme.surface1
        NxShadow { anchors.fill: parent; radius: 0; offsetY: 0 }
    }
    enter: Transition {
        NumberAnimation { property: "x"; from: (root.parent ? root.parent.width : 0) - root.width + 24; duration: NxTheme.base; easing.type: NxTheme.ease }
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: NxTheme.base; easing.type: NxTheme.ease }
    }
    exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 100 } }

    contentItem: Item {
        Item {
            id: head
            width: parent.width
            height: 80
            Item {
                id: lead
                x: 24
                width: childrenRect.width
                height: childrenRect.height
                anchors.verticalCenter: parent.verticalCenter
            }
            NxCover {
                id: icon
                visible: root.iconSource.toString() !== ""
                x: 24
                width: 48; height: 48
                radius: NxTheme.rButton
                anchors.verticalCenter: parent.verticalCenter
                source: root.iconSource
            }
            Column {
                anchors.left: icon.visible ? icon.right : lead.right
                anchors.leftMargin: icon.visible || lead.width > 0 ? 12 : 0
                anchors.right: close.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                NxText { width: parent.width; text: root.title; variant: "h2" }
                NxText { visible: root.subtitle !== ""; width: parent.width; text: root.subtitle; muted: true }
            }
            NxIconButton {
                id: close
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                iconName: "x"
                tip: I18n.t("common.close")
                onClicked: root.close()
            }
        }
        Flickable {
            id: flick
            anchors.top: head.bottom
            anchors.bottom: foot.top
            width: parent.width
            clip: true
            interactive: root.scrollable
            contentHeight: root.scrollable ? bodyCol.implicitHeight + 24 : height
            boundsBehavior: Flickable.StopAtBounds
            C.ScrollBar.vertical: NxScrollBar {}
            Column {
                id: bodyCol
                x: 24
                width: root.bodyWidth
                height: root.scrollable ? implicitHeight : flick.height
                spacing: 0
            }
        }
        Item {
            id: foot
            anchors.bottom: parent.bottom
            width: parent.width
            // Дети подвала сами ставят x: 24, y: 16, width: parent.width - 48
            height: children.length ? childrenRect.y + childrenRect.height + 16 : 0
        }
    }
}
