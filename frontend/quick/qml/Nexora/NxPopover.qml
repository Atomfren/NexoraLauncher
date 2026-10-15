// Всплывающая панель с мягкой тенью (единственное место, где есть тень)
import QtQuick
import QtQuick.Templates as T

T.Popup {
    id: root
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset, implicitContentHeight + topPadding + bottomPadding)
    property color surface: NxTheme.pop
    padding: 4
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside

    background: Rectangle {
        radius: NxTheme.rButton
        color: root.surface
        border.color: NxTheme.line
        border.width: 1
        NxShadow { anchors.fill: parent }
    }

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: NxTheme.fast; easing.type: NxTheme.ease }
        NumberAnimation { property: "y"; from: root.y - 4; to: root.y; duration: NxTheme.fast; easing.type: NxTheme.ease }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 90 }
    }
}
