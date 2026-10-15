// Пустое состояние: линейная иллюстрация, одна фраза, действия. Выравнивание — слева сверху.
import QtQuick
import QtQuick.Window

Column {
    id: root
    property string illustration: "library"
    property string text: ""
    property bool compact: false
    default property alias actions: acts.data

    topPadding: compact ? 32 : 48
    leftPadding: compact ? 0 : 48
    spacing: 16
    width: Math.min(520, parent ? parent.width : 520)

    Image {
        width: 72
        height: 72
        source: "image://nx/illus/" + root.illustration + "/" + NxTheme.hex(NxTheme.muted)
        sourceSize: Qt.size(72 * Screen.devicePixelRatio, 72 * Screen.devicePixelRatio)
    }
    NxText {
        width: Math.min(360, root.width - root.leftPadding)
        text: root.text
        variant: "h2"
        wrapMode: Text.Wrap
        elide: Text.ElideNone
        lineHeightMode: Text.ProportionalHeight
        lineHeight: 1.2
    }
    Row { id: acts; spacing: 8; topPadding: 4 }
}
