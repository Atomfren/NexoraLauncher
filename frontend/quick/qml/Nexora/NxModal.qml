// Модальная форма: заголовок, поля, «Отмена» и главное действие
import QtQuick
import QtQuick.Templates as T

T.Popup {
    id: root
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset, implicitContentHeight + topPadding + bottomPadding)
    property string title: ""
    property string acceptText: I18n.t("common.save")
    property bool acceptEnabled: true
    property bool busy: false
    default property alias fields: box.data
    readonly property int fieldWidth: width - 48
    signal accepted()

    parent: T.Overlay.overlay
    anchors.centerIn: parent
    width: 440
    modal: true
    dim: true
    padding: 24
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside

    T.Overlay.modal: Rectangle { color: NxTheme.scrim }
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

    function submit() {
        if (!acceptEnabled || busy) return
        accepted()
    }

    contentItem: Column {
        spacing: 20
        NxText { width: parent.width; text: root.title; variant: "h2" }
        Column { id: box; width: parent.width; spacing: 16 }
        Row {
            anchors.right: parent.right
            spacing: 8
            NxButton { variant: "ghost"; text: I18n.t("common.cancel"); onClicked: root.close() }
            NxButton { variant: "primary"; text: root.acceptText; enabled: root.acceptEnabled; loading: root.busy; onClicked: root.submit() }
        }
    }
}
