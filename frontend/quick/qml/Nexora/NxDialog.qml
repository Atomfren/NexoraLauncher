// Компактный диалог подтверждения — только для опасных действий
import QtQuick
import QtQuick.Templates as T

T.Popup {
    id: root
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset, implicitContentHeight + topPadding + bottomPadding)
    property string title: ""
    property string text: ""
    property string acceptText: I18n.t("common.delete")
    property bool danger: true
    default property alias extra: extraBox.data
    signal accepted()

    parent: T.Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(400, parent ? parent.width * 0.92 : 400)
    modal: true
    dim: true
    padding: 24
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside

    T.Overlay.modal: Rectangle {
        color: NxTheme.scrim
        Behavior on opacity { NumberAnimation { duration: NxTheme.base } }
    }

    background: Rectangle {
        radius: NxTheme.rButton
        color: NxTheme.pop
        border.color: NxTheme.line
        NxShadow { anchors.fill: parent }
    }

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: NxTheme.base; easing.type: NxTheme.ease }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: NxTheme.base; easing.type: NxTheme.ease }
    }
    exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 100 } }

    contentItem: Column {
        spacing: 16
        NxText { width: parent.width; text: root.title; variant: "h2"; wrapMode: Text.Wrap; elide: Text.ElideNone }
        NxText {
            visible: root.text !== ""
            width: parent.width
            text: root.text
            muted: true
            wrapMode: Text.Wrap
            elide: Text.ElideNone
            lineHeightMode: Text.ProportionalHeight
            lineHeight: 1.15
        }
        Column { id: extraBox; width: parent.width; spacing: 8 }
        Row {
            anchors.right: parent.right
            spacing: 8
            NxButton { variant: "ghost"; text: I18n.t("common.cancel"); onClicked: root.close() }
            NxButton {
                variant: root.danger ? "danger" : "primary"
                text: root.acceptText
                onClicked: { root.close(); root.accepted() }
            }
        }
    }
}
