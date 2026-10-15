// Скриншоты сборки сеткой
import QtQuick
import Nexora

TabPage {
    id: root
    readonly property int cols: Math.max(1, Math.floor((innerWidth + 12) / 202))
    readonly property real cell: (innerWidth - (cols - 1) * 12) / cols

    Flow {
        width: root.innerWidth
        spacing: 12
        Repeater {
            model: Build.screenshots
            delegate: Column {
                required property var modelData
                width: root.cell
                spacing: 6
                NxCover {
                    width: parent.width
                    height: Math.round(parent.width * 9 / 16)
                    radius: NxTheme.rButton
                    source: parent.modelData.url
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Shell.openPath(parent.parent.modelData.path) }
                }
                NxText { width: parent.width; text: parent.modelData.date; variant: "mono"; muted: true }
            }
        }
    }
    NxEmptyState {
        visible: Build.screenshots.length === 0
        leftPadding: 0
        compact: true
        illustration: "worlds"
        text: I18n.t("q.no_shots")
    }
}
