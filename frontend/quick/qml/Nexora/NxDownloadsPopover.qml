// Список фоновых задач: установка, загрузки, экспорт
import QtQuick

NxPopover {
    id: root
    width: 360
    padding: 0

    contentItem: Column {
        Item {
            width: parent.width
            height: 44
            NxText { x: 16; anchors.verticalCenter: parent.verticalCenter; text: I18n.t("q.downloads"); variant: "h2" }
            NxButton {
                anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                visible: Shell.tasks.length > Shell.activeTasks
                text: I18n.t("q.clear"); variant: "ghost"; small: true
                onClicked: Shell.clearFinishedTasks()
            }
        }
        NxText {
            visible: Shell.tasks.length === 0
            x: 16
            height: 44
            text: I18n.t("q.no_downloads")
            muted: true
        }
        Repeater {
            model: Shell.tasks
            delegate: Item {
                id: task
                required property var modelData
                readonly property bool done: modelData.status === "done"
                readonly property bool failed: modelData.status === "failed" || modelData.status === "cancelled"
                readonly property bool active: !done && !failed
                width: root.width
                height: col.implicitHeight + 20
                Column {
                    id: col
                    x: 16
                    y: 10
                    width: parent.width - 32
                    spacing: 6
                    Row {
                        width: parent.width
                        spacing: 10
                        Item {
                            width: 20; height: 20
                            anchors.verticalCenter: parent.verticalCenter
                            NxProgressRing { visible: task.active; value: task.modelData.progress; size: 20 }
                            NxIcon { visible: task.done; name: "check"; size: 18; color: NxTheme.success; anchors.centerIn: parent }
                            NxIcon { visible: task.failed; name: "circle-alert"; size: 18; color: NxTheme.danger; anchors.centerIn: parent }
                        }
                        Column {
                            width: parent.width - 30
                            NxText { width: parent.width; text: task.modelData.title; variant: "strong" }
                            NxText {
                                width: parent.width
                                text: task.failed ? task.modelData.error : task.done ? I18n.t("q.task_done") : task.modelData.message
                                visible: text !== ""
                                variant: "mono"; muted: !task.failed
                                color: task.failed ? NxTheme.danger : NxTheme.muted
                            }
                        }
                    }
                    NxProgressBar {
                        visible: task.active
                        width: parent.width
                        value: task.modelData.progress
                        indeterminate: task.modelData.progress <= 0
                    }
                }
            }
        }
        Item { width: 1; height: 8 }
    }
}
