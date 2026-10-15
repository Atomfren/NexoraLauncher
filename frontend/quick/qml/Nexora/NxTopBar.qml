// Верхняя панель: поиск и команды (Ctrl+K), загрузки, кнопки окна. За пустое место окно перетаскивается.
import QtQuick
import QtQuick.Window

Item {
    id: root
    property var window: null
    signal paletteRequested()
    signal downloadsClicked(Item anchor)

    height: 44

    // Перетаскивание окна и разворот двойным щелчком
    Item {
        anchors.fill: parent
        DragHandler {
            target: null
            onActiveChanged: if (active && root.window) root.window.startSystemMove()
        }
        TapHandler {
            onDoubleTapped: if (root.window) root.window.toggleMaximized()
        }
    }

    Rectangle {
        id: cmdk
        x: 16
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(320, root.width * 0.42)
        height: 30
        radius: NxTheme.rInput
        color: cmdkArea.containsMouse ? NxTheme.surface2 : NxTheme.surface1
        Behavior on color { ColorAnimation { duration: NxTheme.fast } }
        NxIcon { id: si; x: 10; anchors.verticalCenter: parent.verticalCenter; name: "search" }
        NxText { anchors.left: si.right; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: I18n.t("q.search_commands"); muted: true }
        NxKbd { anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: "Ctrl K" }
        MouseArea { id: cmdkArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.paletteRequested() }
    }

    Row {
        anchors.right: parent.right
        height: parent.height
        spacing: 8

        Rectangle {
            id: dl
            anchors.verticalCenter: parent.verticalCenter
            width: dlRow.implicitWidth + 20
            height: 30
            radius: NxTheme.rButton
            color: dlArea.containsMouse ? NxTheme.fill1 : "transparent"
            Row {
                id: dlRow
                anchors.centerIn: parent
                spacing: 8
                NxProgressRing { visible: Shell.activeTasks > 0; value: Shell.tasksProgress; size: 18; anchors.verticalCenter: parent.verticalCenter }
                NxIcon { visible: Shell.activeTasks === 0; name: "download"; size: 18; color: dlArea.containsMouse ? NxTheme.text : NxTheme.muted; anchors.verticalCenter: parent.verticalCenter }
                NxText { text: I18n.t("q.downloads"); variant: "strong"; color: dlArea.containsMouse ? NxTheme.text : NxTheme.muted; anchors.verticalCenter: parent.verticalCenter }
                NxText { visible: Shell.activeTasks > 0; text: Shell.activeTasks; variant: "monoStrong"; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
            }
            MouseArea { id: dlArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.downloadsClicked(dl) }
        }

        // Кнопки окна
        Row {
            height: parent.height
            Repeater {
                model: [
                    { kind: "min" }, { kind: "max" }, { kind: "close" }
                ]
                delegate: Rectangle {
                    id: wc
                    required property var modelData
                    width: 44
                    height: 44
                    color: wcArea.containsMouse ? (modelData.kind === "close" ? NxTheme.danger : NxTheme.fill1) : "transparent"
                    readonly property color fg: wcArea.containsMouse ? (modelData.kind === "close" ? NxTheme.onDanger : NxTheme.text) : NxTheme.muted
                    Rectangle { visible: wc.modelData.kind === "min"; anchors.centerIn: parent; width: 10; height: 1; color: wc.fg }
                    Rectangle {
                        visible: wc.modelData.kind === "max"
                        anchors.centerIn: parent
                        width: 10; height: 10
                        color: "transparent"; border.color: wc.fg; border.width: 1
                    }
                    Item {
                        visible: wc.modelData.kind === "close"
                        anchors.centerIn: parent
                        width: 12; height: 12
                        Rectangle { anchors.centerIn: parent; width: 14; height: 1; rotation: 45; color: wc.fg; antialiasing: true }
                        Rectangle { anchors.centerIn: parent; width: 14; height: 1; rotation: -45; color: wc.fg; antialiasing: true }
                    }
                    MouseArea {
                        id: wcArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            if (!root.window) return
                            if (wc.modelData.kind === "min") root.window.showMinimized()
                            else if (wc.modelData.kind === "max") root.window.toggleMaximized()
                            else root.window.close()
                        }
                    }
                }
            }
        }
    }
}
