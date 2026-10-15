// Ввод одной строки: переименование сборки, адрес сервера
import QtQuick
import QtQuick.Templates as T
import Nexora

T.Popup {
    id: root
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset, implicitContentHeight + topPadding + bottomPadding)
    property string title: ""
    property string label: ""
    property string value: ""
    property string placeholder: ""
    property string acceptText: I18n.t("common.save")
    property bool mono: false
    signal accepted(string text)

    parent: T.Overlay.overlay
    anchors.centerIn: parent
    width: 400
    modal: true
    dim: true
    padding: 24
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside
    onOpened: { field.text = value; field.input.selectAll(); field.input.forceActiveFocus() }

    T.Overlay.modal: Rectangle { color: NxTheme.scrim }
    background: Rectangle {
        radius: NxTheme.rButton
        color: NxTheme.pop
        border.color: NxTheme.line
        NxShadow { anchors.fill: parent }
    }

    function submit() {
        const text = field.text.trim()
        if (!text) return
        close()
        accepted(text)
    }

    contentItem: Column {
        spacing: 16
        NxText { text: root.title; variant: "h2" }
        NxTextField {
            id: field
            width: parent.width
            label: root.label
            placeholder: root.placeholder
            mono: root.mono
            onAccepted: root.submit()
        }
        Row {
            anchors.right: parent.right
            spacing: 8
            NxButton { variant: "ghost"; text: I18n.t("common.cancel"); onClicked: root.close() }
            NxButton { variant: "primary"; text: root.acceptText; enabled: field.text.trim() !== ""; onClicked: root.submit() }
        }
    }
}
