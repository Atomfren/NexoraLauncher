// Уведомления в правом нижнем углу: исчезают через 3 с, не больше трёх сразу
import QtQuick

Item {
    id: root
    width: 420
    height: col.implicitHeight

    function show(text, kind) {
        if (toasts.count >= 3) toasts.remove(0)
        toasts.append({ text: text, kind: kind || "ok", born: Date.now() })
    }

    ListModel { id: toasts }

    Timer {
        interval: 250
        repeat: true
        running: toasts.count > 0
        onTriggered: {
            const now = Date.now()
            for (let i = toasts.count - 1; i >= 0; --i) {
                const life = toasts.get(i).kind === "err" ? 6000 : 3000
                if (now - toasts.get(i).born > life) toasts.remove(i)
            }
        }
    }

    Column {
        id: col
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        spacing: 8
        add: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: NxTheme.base; easing.type: NxTheme.ease }
            NumberAnimation { property: "y"; from: col.height; duration: NxTheme.base; easing.type: NxTheme.ease }
        }
        move: Transition { NumberAnimation { property: "y"; duration: NxTheme.base; easing.type: NxTheme.ease } }

        Repeater {
            model: toasts
            delegate: Rectangle {
                id: toast
                required property string text
                required property string kind
                required property int index
                anchors.right: parent ? parent.right : undefined
                width: Math.min(root.width, row.implicitWidth + 28)
                height: Math.max(40, msg.implicitHeight + 20)
                radius: NxTheme.rButton
                color: NxTheme.pop
                border.color: NxTheme.line
                NxShadow { anchors.fill: parent }

                Row {
                    id: row
                    x: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 10
                    NxIcon {
                        name: toast.kind === "err" ? "circle-alert" : toast.kind === "info" ? "check" : "check"
                        color: toast.kind === "err" ? NxTheme.danger : toast.kind === "info" ? NxTheme.info : NxTheme.success
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    NxText {
                        id: msg
                        text: toast.text
                        variant: "strong"
                        width: Math.min(implicitWidth, root.width - 54)
                        wrapMode: Text.Wrap
                        elide: Text.ElideNone
                        lineHeightMode: Text.ProportionalHeight
                        lineHeight: 1.1
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea { anchors.fill: parent; onClicked: toasts.remove(toast.index) }
            }
        }
    }
}
