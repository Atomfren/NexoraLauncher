// Настройки сборки: имя, версия, память, Java, аргументы, окно
import QtQuick
import Nexora

TabPage {
    id: root
    signal askDelete()
    property string restoreTarget: ""
    onVisibleChanged: if (visible) Build.loadSnapshots()
    readonly property var cur: Library.current
    readonly property var gs: Build.globalSettings
    readonly property var loaderNames: ({ vanilla: "Vanilla", fabric: "Fabric", quilt: "Quilt", forge: "Forge", neoforge: "NeoForge" })
    spacing: 24

    function save(changes) { Library.update(cur.name, changes) }

    NxSettingGroup {
        width: Math.min(root.innerWidth, 640)
        NxSettingRow {
            first: true
            label: I18n.t("q.name")
            NxTextField {
                id: nameField
                width: 260
                text: root.cur.name || ""
                onAccepted: Library.rename(root.cur.name, text)
                input.onEditingFinished: if (text.trim() && text.trim() !== root.cur.name) Library.rename(root.cur.name, text)
            }
        }
        NxSettingRow {
            label: "Minecraft"
            NxText { text: root.cur.version || ""; variant: "mono" }
        }
        NxSettingRow {
            label: I18n.t("q.loader")
            Row {
                spacing: 8
                NxLoaderBadge { loader: root.cur.loader || "vanilla"; text: root.loaderNames[root.cur.loader] || ""; color: NxTheme.text; anchors.verticalCenter: parent.verticalCenter }
                NxText { text: root.cur.loaderVersion || ""; variant: "mono"; muted: true; anchors.verticalCenter: parent.verticalCenter }
            }
        }
        NxSettingRow {
            label: I18n.t("q.memory")
            hint: mem.value === 0 ? I18n.tf("q.memory_default", { mem: I18n.memory(root.gs.max_memory || 4096) }) : ""
            Row {
                spacing: 12
                NxText {
                    width: 64
                    horizontalAlignment: Text.AlignRight
                    text: mem.value === 0 ? I18n.t("q.auto") : I18n.memory(mem.value * 1024)
                    variant: "mono"
                    anchors.verticalCenter: parent.verticalCenter
                }
                NxSlider {
                    id: mem
                    width: 200
                    from: 0; to: 16; stepSize: 0.5
                    value: (root.cur.maxMemory || 0) / 1024
                    anchors.verticalCenter: parent.verticalCenter
                    onPressedChanged: if (!pressed) root.save({ max_memory: Math.round(value * 1024) })
                }
            }
        }
    }

    NxSettingGroup {
        width: Math.min(root.innerWidth, 640)
        NxSettingRow {
            first: true
            label: "Java"
            NxTextField {
                width: 300
                mono: true
                text: root.cur.javaPath || ""
                placeholder: I18n.t("q.java_auto")
                input.onEditingFinished: if (text !== (root.cur.javaPath || "")) root.save({ java_path: text.trim() })
            }
        }
        NxSettingRow {
            label: I18n.t("q.jvm_args")
            NxTextField {
                width: 300
                mono: true
                text: root.cur.jvmArgs || ""
                placeholder: root.gs.jvm_args || "-XX:+UseG1GC"
                input.onEditingFinished: if (text !== (root.cur.jvmArgs || "")) root.save({ jvm_args: text.trim() })
            }
        }
        NxSettingRow {
            label: I18n.t("q.window_size")
            Row {
                spacing: 8
                NxTextField {
                    width: 84; mono: true
                    text: root.cur.width ? String(root.cur.width) : ""
                    placeholder: "854"
                    input.validator: IntValidator { bottom: 0; top: 7680 }
                    input.onEditingFinished: root.save({ width: parseInt(text) || 0 })
                }
                NxText { text: "×"; muted: true; anchors.verticalCenter: parent.verticalCenter }
                NxTextField {
                    width: 84; mono: true
                    text: root.cur.height ? String(root.cur.height) : ""
                    placeholder: "480"
                    input.validator: IntValidator { bottom: 0; top: 4320 }
                    input.onEditingFinished: root.save({ height: parseInt(text) || 0 })
                }
            }
        }
        NxSettingRow {
            label: I18n.t("q.fullscreen")
            NxToggle { checked: !!root.cur.fullscreen; onToggled: root.save({ fullscreen: checked }) }
        }
    }

    // Точки восстановления
    Column {
        width: Math.min(root.innerWidth, 640)
        spacing: 8
        NxSectionHeader { text: I18n.t("q.restore_points"); actionText: I18n.t("q.create_point"); onAction: Build.createSnapshot("") }
        NxText {
            visible: Build.snapshots.length === 0
            width: parent.width
            text: I18n.t("q.no_points")
            muted: true
            wrapMode: Text.Wrap
            elide: Text.ElideNone
        }
        Repeater {
            model: Build.snapshots
            delegate: Rectangle {
                id: snap
                required property var modelData
                width: parent.width
                height: 52
                radius: NxTheme.rButton
                color: sh.hovered ? NxTheme.fill1 : "transparent"
                HoverHandler { id: sh }
                NxIcon { x: 12; name: snap.modelData.auto ? "history" : "archive"; anchors.verticalCenter: parent.verticalCenter }
                Column {
                    x: 40
                    width: parent.width - 260
                    anchors.verticalCenter: parent.verticalCenter
                    NxText { width: parent.width; text: snap.modelData.label; variant: "strong" }
                    NxText { width: parent.width; text: snap.modelData.date + " · " + snap.modelData.mods + " · " + snap.modelData.size; variant: "mono"; muted: true }
                }
                Row {
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4
                    NxButton { small: true; variant: "ghost"; text: I18n.t("q.restore"); onClicked: { root.restoreTarget = snap.modelData.id; restoreDialog.open() } }
                    NxIconButton { small: true; iconName: "trash"; tip: I18n.t("common.delete"); onClicked: Build.deleteSnapshot(snap.modelData.id) }
                }
            }
        }
    }

    NxDialog {
        id: restoreDialog
        title: I18n.t("q.restore_point_title")
        text: I18n.t("q.restore_point_text")
        acceptText: I18n.t("q.restore")
        danger: false
        onAccepted: Build.restoreSnapshot(root.restoreTarget)
    }

    NxButton {
        variant: "ghost"
        dangerText: true
        iconName: "trash"
        text: I18n.t("q.delete_build")
        onClicked: root.askDelete()
    }
}
