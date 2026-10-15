// Миры сборки
import QtQuick
import Nexora

TabPage {
    id: root
    property string target: ""

    Item {
        width: root.innerWidth
        height: 28
        visible: Build.worlds.length > 0
        NxText { anchors.verticalCenter: parent.verticalCenter; text: I18n.count(Build.worlds.length, "q.worlds"); muted: true }
        NxButton {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            small: true; variant: "ghost"; iconName: "folder"
            text: I18n.t("q.saves_folder")
            onClicked: Shell.openPath(Library.current.gameDir + "/saves")
        }
    }
    Item { width: 1; height: 8; visible: Build.worlds.length > 0 }
    Repeater {
        model: Build.worlds
        delegate: WorldRow {
            required property var modelData
            width: root.innerWidth
            world: modelData
            large: true
            onDeleteRequested: { root.target = modelData.name; confirm.open() }
        }
    }
    NxEmptyState {
        visible: !Build.loading && Build.worlds.length === 0
        leftPadding: 0
        compact: true
        illustration: "worlds"
        text: I18n.t("q.no_worlds")
        NxButton {
            text: I18n.t("q.play")
            iconName: "play"
            enabled: Library.current.state === "ready"
            onClicked: Library.play(Library.current.name)
        }
    }

    NxDialog {
        id: confirm
        title: I18n.tf("q.delete_world_title", { name: root.target })
        text: I18n.t("q.delete_world_text")
        onAccepted: Build.deleteWorld(root.target)
    }
}
