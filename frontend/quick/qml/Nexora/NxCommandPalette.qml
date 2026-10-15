// Ctrl+K: поиск сборок, действий и настроек. Стрелки — выбор, Enter — выполнить, Esc — закрыть.
// items — массив { group, icon, text, hint, action, arg }
import QtQuick
import QtQuick.Templates as T

T.Popup {
    id: root
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset, implicitContentHeight + topPadding + bottomPadding)
    property var items: []
    property int index: 0
    signal run(string action, string arg)

    readonly property var filtered: {
        const q = field.text.trim().toLowerCase()
        const out = q ? items.filter(it => it.text.toLowerCase().indexOf(q) >= 0) : items
        return out.slice(0, q ? 12 : 10)
    }
    onFilteredChanged: index = 0

    parent: T.Overlay.overlay
    x: Math.round((parent.width - width) / 2)
    y: 84
    width: Math.min(560, parent.width * 0.92)
    modal: true
    dim: true
    padding: 0
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside
    onOpened: { field.text = ""; field.forceActiveFocus() }

    T.Overlay.modal: Rectangle { color: NxTheme.scrim }

    background: Rectangle {
        radius: NxTheme.rButton
        color: NxTheme.pop
        border.color: NxTheme.line
        NxShadow { anchors.fill: parent }
    }
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: NxTheme.base; easing.type: NxTheme.ease }
        NumberAnimation { property: "y"; from: 78; to: 84; duration: NxTheme.base; easing.type: NxTheme.ease }
    }

    function activate(i) {
        const it = filtered[i]
        if (!it) return
        close()
        run(it.action, it.arg || "")
    }

    contentItem: Column {
        Item {
            width: parent.width
            height: 48
            NxIcon { id: si; x: 16; anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 18 }
            TextInput {
                id: field
                anchors.left: si.right; anchors.leftMargin: 10
                anchors.right: esc.left; anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                color: NxTheme.text
                font.family: NxTheme.fontUi
                font.pixelSize: 15
                selectByMouse: true
                clip: true
                Keys.onDownPressed: root.index = Math.min(root.filtered.length - 1, root.index + 1)
                Keys.onUpPressed: root.index = Math.max(0, root.index - 1)
                Keys.onReturnPressed: root.activate(root.index)
                Keys.onEnterPressed: root.activate(root.index)
                NxText {
                    anchors.fill: parent
                    visible: !field.text
                    text: I18n.t("q.palette_placeholder")
                    muted: true
                    font.pixelSize: 15
                }
            }
            NxKbd { id: esc; text: "Esc"; anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter }
        }
        Column {
            width: parent.width
            leftPadding: 8
            rightPadding: 8
            bottomPadding: 8
            NxText {
                visible: root.filtered.length === 0
                leftPadding: 8
                height: 48
                text: I18n.t("common.nothing_found")
                muted: true
            }
            Repeater {
                model: root.filtered
                delegate: Column {
                    id: entry
                    required property var modelData
                    required property int index
                    width: parent.width - 16
                    NxText {
                        visible: entry.index === 0 || root.filtered[entry.index - 1].group !== entry.modelData.group
                        leftPadding: 8
                        topPadding: 10
                        height: 30
                        text: entry.modelData.group
                        variant: "caption"
                    }
                    Rectangle {
                        width: parent.width
                        height: 36
                        radius: 4
                        color: root.index === entry.index ? NxTheme.fill2 : "transparent"
                        NxIcon { id: ei; x: 8; anchors.verticalCenter: parent.verticalCenter; name: entry.modelData.icon }
                        NxText { anchors.left: ei.right; anchors.leftMargin: 12; anchors.right: hint.left; anchors.verticalCenter: parent.verticalCenter; text: entry.modelData.text }
                        NxText { id: hint; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: entry.modelData.hint || ""; variant: "mono"; muted: true }
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onEntered: root.index = entry.index
                            onClicked: root.activate(entry.index)
                        }
                    }
                }
            }
        }
    }
}
