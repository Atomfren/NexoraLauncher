// Единственная залитая акцентом кнопка. Состояния: none, installing, launching, ready, running.
import QtQuick

Item {
    id: root
    property string state_: "ready"
    property real progress: 0
    property real startedAt: 0          // время старта процесса (Unix, секунды)
    signal play()
    signal install()
    signal stop()
    signal more(Item anchor)

    readonly property bool busy: state_ === "installing" || state_ === "launching"
    readonly property bool split: state_ === "ready"
    property real now: Date.now() / 1000

    implicitHeight: 44
    implicitWidth: main.width + (split ? moreBtn.width + 1 : 0)

    Timer {
        interval: 1000
        repeat: true
        running: root.state_ === "running"
        triggeredOnStart: true
        onTriggered: root.now = Date.now() / 1000
    }

    function clock(sec) {
        sec = Math.max(0, Math.floor(sec))
        const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60
        const mm = (m < 10 ? "0" : "") + m, ss = (s < 10 ? "0" : "") + s
        return h ? h + ":" + mm + ":" + ss : mm + ":" + ss
    }

    Rectangle {
        id: main
        width: Math.max(148, content.implicitWidth + 48)
        height: root.height
        radius: NxTheme.rButton
        color: root.busy ? NxTheme.surface3
             : root.state_ === "running" ? (mainArea.containsMouse ? Qt.rgba(NxTheme.danger.r, NxTheme.danger.g, NxTheme.danger.b, 0.24) : NxTheme.errBg)
             : mainArea.pressed ? NxTheme.accentPressed : mainArea.containsMouse ? NxTheme.accentHover : NxTheme.accent
        Behavior on color { ColorAnimation { duration: NxTheme.fast } }
        Behavior on width { NumberAnimation { duration: NxTheme.base; easing.type: NxTheme.ease } }

        // Квадратные правые углы у разделённой кнопки
        Rectangle {
            visible: root.split
            anchors.right: parent.right
            width: NxTheme.rButton
            height: parent.height
            color: parent.color
        }

        Row {
            id: content
            anchors.centerIn: parent
            spacing: 10
            readonly property color fg: root.busy ? NxTheme.text : root.state_ === "running" ? NxTheme.danger : NxTheme.onAccent

            NxSpinner { visible: root.busy; size: 16; color: content.fg; anchors.verticalCenter: parent.verticalCenter }
            NxIcon {
                visible: !root.busy
                name: root.state_ === "none" ? "download" : root.state_ === "running" ? "square" : "play"
                size: root.state_ === "running" ? 16 : 18
                color: content.fg
                anchors.verticalCenter: parent.verticalCenter
            }
            NxText {
                text: root.state_ === "none" ? I18n.t("q.install")
                    : root.state_ === "installing" ? I18n.tf("q.installing_pct", { pct: Math.round(root.progress) })
                    : root.state_ === "launching" ? (root.progress > 0 ? I18n.tf("q.launching_pct", { pct: Math.round(root.progress) }) : I18n.t("q.launching"))
                    : root.state_ === "running" ? I18n.t("q.stop") : I18n.t("q.play")
                color: content.fg
                font.pixelSize: 16
                font.weight: Font.DemiBold
                lineHeight: 22
                anchors.verticalCenter: parent.verticalCenter
            }
            NxText {
                visible: root.state_ === "running" && root.startedAt > 0
                text: root.clock(root.now - root.startedAt)
                variant: "monoStrong"
                font.pixelSize: 14
                lineHeight: 20
                opacity: 0.8
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        NxProgressBar {
            visible: root.busy
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 12
            anchors.bottomMargin: 5
            height: 3
            color: NxTheme.fill2
            value: root.progress
            indeterminate: root.progress <= 0
        }

        MouseArea {
            id: mainArea
            anchors.fill: parent
            hoverEnabled: true
            enabled: !root.busy
            cursorShape: root.busy ? Qt.ArrowCursor : Qt.PointingHandCursor
            onClicked: root.state_ === "none" ? root.install() : root.state_ === "running" ? root.stop() : root.play()
        }
    }

    Rectangle {
        id: moreBtn
        visible: root.split
        x: main.width + 1
        width: 40
        height: root.height
        radius: NxTheme.rButton
        color: moreArea.pressed ? NxTheme.accentPressed : moreArea.containsMouse ? NxTheme.accentHover : NxTheme.accent
        Behavior on color { ColorAnimation { duration: NxTheme.fast } }
        Rectangle { width: NxTheme.rButton; height: parent.height; color: parent.color }
        NxIcon { anchors.centerIn: parent; name: "chevron-down"; size: 18; color: NxTheme.onAccent }
        MouseArea {
            id: moreArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.more(moreBtn)
        }
    }
}
