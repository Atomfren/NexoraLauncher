// Чип/бейдж: neutral, ok, warn, err, info. Если clickable — ведёт себя как кнопка.
import QtQuick

Rectangle {
    id: root
    property string text: ""
    property string kind: ""
    property bool mono: false
    property bool clickable: false
    property string dot: ""           // "", ok, warn, err, off, spin
    property string loader: ""        // значок загрузчика слева
    property string trailingIcon: ""
    signal clicked()

    readonly property color fg: kind === "ok" ? NxTheme.success : kind === "warn" ? NxTheme.warning
                               : kind === "err" ? NxTheme.danger : kind === "info" ? NxTheme.info : NxTheme.text

    implicitHeight: 22
    implicitWidth: row.implicitWidth + 16
    radius: NxTheme.rInput
    color: kind === "ok" ? NxTheme.okBg : kind === "warn" ? NxTheme.warnBg : kind === "err" ? NxTheme.errBg
         : kind === "info" ? NxTheme.infoBg : (mouse.containsMouse && clickable ? NxTheme.fill2 : NxTheme.fill1)
    Behavior on color { ColorAnimation { duration: NxTheme.fast } }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        NxDot { visible: root.dot !== "" && root.dot !== "spin"; kind: root.dot; size: 6; anchors.verticalCenter: parent.verticalCenter }
        NxSpinner { visible: root.dot === "spin"; size: 12; color: root.fg; anchors.verticalCenter: parent.verticalCenter }
        NxLoaderMark { visible: root.loader !== ""; loader: root.loader; size: 12; anchors.verticalCenter: parent.verticalCenter }
        NxText {
            text: root.text
            color: root.fg
            variant: root.mono ? "mono" : "strong"
            font.pixelSize: 12
            lineHeight: 16
            anchors.verticalCenter: parent.verticalCenter
        }
        NxIcon { visible: root.trailingIcon !== ""; name: root.trailingIcon; size: 14; color: NxTheme.muted; anchors.verticalCenter: parent.verticalCenter }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        enabled: root.clickable
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
