// Ресурспаки и шейдеры сборки: включить, выключить, добавить файл
import QtQuick
import QtQuick.Dialogs
import Nexora

TabPage {
    id: root
    property string addType: "resourcepack"

    Repeater {
        model: [
            { type: "resourcepack", title: I18n.t("q.resourcepacks"), items: Build.resourcepacks, filter: "Resource packs (*.zip)" },
            { type: "shader", title: I18n.t("q.shaders"), items: Build.shaders, filter: "Shader packs (*.zip)" }
        ]
        delegate: Column {
            id: group
            required property var modelData
            width: root.innerWidth
            bottomPadding: 24
            NxSectionHeader {
                text: group.modelData.title
                actionText: I18n.t("q.add")
                onAction: { root.addType = group.modelData.type; fileDialog.nameFilters = [group.modelData.filter]; fileDialog.open() }
            }
            Item { width: 1; height: 8 }
            NxText {
                visible: group.modelData.items.length === 0
                height: 36
                leftPadding: 8
                text: I18n.t("q.none_yet")
                muted: true
            }
            Repeater {
                model: group.modelData.items
                delegate: Rectangle {
                    id: row
                    required property var modelData
                    width: group.width
                    height: 52
                    radius: NxTheme.rButton
                    color: hov.hovered ? NxTheme.fill1 : "transparent"
                    HoverHandler { id: hov }
                    NxCover { id: ic; x: 8; width: 36; height: 36; radius: NxTheme.rButton; anchors.verticalCenter: parent.verticalCenter; source: row.modelData.icon; dim: !row.modelData.enabled }
                    Column {
                        anchors.left: ic.right; anchors.leftMargin: 12
                        anchors.right: tg.left; anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        NxText { width: parent.width; text: row.modelData.name; variant: "strong"; color: row.modelData.enabled ? NxTheme.text : NxTheme.muted }
                        NxText { width: parent.width; text: row.modelData.size; variant: "mono"; muted: true; font.pixelSize: 12; lineHeight: 16 }
                    }
                    NxToggle {
                        id: tg
                        anchors.right: parent.right; anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        checked: row.modelData.enabled
                        onToggled: Build.setEnabled(group.modelData.type, row.modelData.filename, checked)
                    }
                }
            }
        }
    }

    FileDialog {
        id: fileDialog
        fileMode: FileDialog.OpenFiles
        onAccepted: Build.addLocalContent(root.addType, selectedFiles)
    }
}
