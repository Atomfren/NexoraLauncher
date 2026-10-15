// Поле ввода: обычное, поиск (iconName: "search"), моно; состояние ошибки через error
import QtQuick
import QtQuick.Templates as T

Item {
    id: root
    property alias text: input.text
    property alias placeholder: ph.text
    property alias input: input
    property string label: ""
    property string error: ""
    property string iconName: ""
    property string prefix: ""
    property string kbd: ""
    property bool mono: false
    property bool clearable: iconName === "search"
    signal accepted()
    signal edited()

    implicitWidth: 240
    implicitHeight: (label ? 22 : 0) + 32 + (error ? 22 : 0)

    NxText {
        id: lbl
        visible: root.label !== ""
        text: root.label
        variant: "strong"
        font.pixelSize: 12
        lineHeight: 16
        color: NxTheme.muted
    }

    Rectangle {
        id: box
        y: root.label ? 22 : 0
        width: parent.width
        height: 32
        radius: NxTheme.rInput
        color: area.containsMouse && !input.activeFocus ? NxTheme.surface3 : NxTheme.surface2
        border.width: input.activeFocus ? 2 : root.error ? 1 : 0
        border.color: input.activeFocus ? NxTheme.accent : NxTheme.danger
        Behavior on color { ColorAnimation { duration: NxTheme.fast } }

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.IBeamCursor
            onClicked: input.forceActiveFocus()
        }

        Row {
            id: lead
            x: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            NxIcon { visible: root.iconName !== ""; name: root.iconName; size: 16; anchors.verticalCenter: parent.verticalCenter }
            NxText { visible: root.prefix !== ""; text: root.prefix; variant: "mono"; muted: true; anchors.verticalCenter: parent.verticalCenter }
        }

        TextInput {
            id: input
            anchors.left: lead.right
            anchors.leftMargin: lead.width > 0 ? 8 : 0
            anchors.right: tail.left
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            color: NxTheme.text
            selectionColor: Qt.rgba(NxTheme.accent.r, NxTheme.accent.g, NxTheme.accent.b, 0.35)
            selectedTextColor: NxTheme.text
            font.family: root.mono ? NxTheme.fontMono : NxTheme.fontUi
            font.pixelSize: root.mono ? 12 : 13
            clip: true
            selectByMouse: true
            onAccepted: root.accepted()
            onTextEdited: root.edited()
            Keys.onEscapePressed: event => { if (root.clearable && text) { text = ""; root.edited() } else event.accepted = false }

            NxText {
                id: ph
                anchors.fill: parent
                visible: !input.text && !input.preeditText
                muted: true
                font.family: input.font.family
                font.pixelSize: input.font.pixelSize
            }
        }

        Row {
            id: tail
            anchors.right: parent.right
            anchors.rightMargin: root.clearable && input.text ? 2 : 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            NxKbd { visible: root.kbd !== "" && !input.text; text: root.kbd; anchors.verticalCenter: parent.verticalCenter }
            NxIconButton {
                visible: root.clearable && input.text !== ""
                iconName: "x"; small: true; tip: I18n.t("q.clear")
                onClicked: { input.text = ""; root.edited(); input.forceActiveFocus() }
            }
        }
    }

    NxText {
        visible: root.error !== ""
        y: box.y + box.height + 6
        text: root.error
        color: NxTheme.danger
        font.pixelSize: 12
        lineHeight: 16
    }
}
