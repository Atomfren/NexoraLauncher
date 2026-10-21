// Строка мира: миниатюра, имя, когда играли, размер; действия при наведении
import QtQuick
import Nexora

Rectangle {
    id: root
    property var world: ({})
    property bool large: false
    signal deleteRequested()
    signal exportRequested()

    height: large ? 84 : 60
    radius: NxTheme.rButton
    color: area.hovered ? NxTheme.fill1 : "transparent"

    HoverHandler { id: area }

    NxCover {
        id: thumb
        x: 8
        anchors.verticalCenter: parent.verticalCenter
        width: root.large ? 112 : 72
        height: root.large ? 64 : 44
        radius: NxTheme.rButton
        source: root.world.icon || ""
    }
    Column {
        anchors.left: thumb.right
        anchors.leftMargin: 12
        anchors.right: size.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        NxText { width: parent.width; text: root.world.name || ""; variant: "strong" }
        NxText {
            width: parent.width
            text: root.large ? I18n.tf("q.played_at", { when: root.world.lastPlayed || "" }) : (root.world.lastPlayed || "")
            muted: true
            font.pixelSize: 12
            lineHeight: 16
        }
    }
    NxText {
        id: size
        anchors.right: actions.left
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: root.world.size || ""
        variant: "mono"
        muted: true
    }
    Row {
        id: actions
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4
        opacity: area.hovered || root.large ? 1 : 0
        NxIconButton { iconName: "folder"; small: !root.large; tip: I18n.t("q.open_folder"); onClicked: Shell.openPath(root.world.path) }
        NxIconButton { visible: root.large; iconName: "share"; tip: I18n.t("q.export_world"); onClicked: root.exportRequested() }
        NxIconButton { visible: root.large; iconName: "trash"; tip: I18n.t("q.delete_world"); onClicked: root.deleteRequested() }
    }
}
