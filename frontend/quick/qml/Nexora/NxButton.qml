// Кнопка: primary (только главные действия), secondary, ghost, danger
import QtQuick
import QtQuick.Templates as T

T.Button {
    id: root
    property string variant: "secondary"
    property string iconName: ""
    property string trailingIcon: ""
    property bool small: false
    property bool loading: false
    property bool dangerText: false
    property bool fullWidth: false

    readonly property bool primary: variant === "primary"
    readonly property bool danger: variant === "danger"
    readonly property color fg: primary ? NxTheme.onAccent
                              : danger ? NxTheme.onDanger
                              : dangerText ? NxTheme.danger : NxTheme.text

    implicitHeight: small ? 28 : 32
    implicitWidth: Math.max(implicitHeight, row.implicitWidth + leftPadding + rightPadding)
    leftPadding: small ? 10 : 14
    rightPadding: small ? 10 : 14
    focusPolicy: Qt.TabFocus
    opacity: enabled || loading ? 1 : 0.4
    hoverEnabled: true

    background: Rectangle {
        radius: NxTheme.rButton
        color: {
            if (root.primary) return root.down ? NxTheme.accentPressed : root.hovered ? NxTheme.accentHover : NxTheme.accent
            if (root.danger) return root.down ? Qt.darker(NxTheme.danger, 1.2) : root.hovered ? NxTheme.dangerHover : NxTheme.danger
            if (root.variant === "ghost") return root.down ? NxTheme.fill2 : (root.hovered || root.checked) ? NxTheme.fill1 : "transparent"
            return root.down || root.checked ? NxTheme.fill3 : root.hovered ? NxTheme.fill2 : NxTheme.fill1
        }
        Behavior on color { ColorAnimation { duration: NxTheme.fast } }
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: NxTheme.rButton + 3
            color: "transparent"
            border.color: NxTheme.accent
            border.width: 2
            visible: root.visualFocus
        }
    }

    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 8
            NxSpinner { visible: root.loading; color: root.fg; size: root.small ? 14 : 16; anchors.verticalCenter: parent.verticalCenter }
            NxIcon {
                visible: !root.loading && root.iconName !== ""
                name: root.iconName; color: root.fg; size: root.small ? 14 : 16
                anchors.verticalCenter: parent.verticalCenter
            }
            NxText {
                visible: root.text !== ""
                text: root.text
                color: root.fg
                font.weight: root.primary || root.danger ? Font.DemiBold : Font.Medium
                anchors.verticalCenter: parent.verticalCenter
            }
            NxIcon {
                visible: root.trailingIcon !== ""
                name: root.trailingIcon; color: root.fg; size: 14
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
