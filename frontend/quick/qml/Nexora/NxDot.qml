// Точка состояния: ok, warn, err, off
import QtQuick

Rectangle {
    property string kind: ""
    property int size: 8
    width: size
    height: size
    radius: size / 2
    color: kind === "ok" ? NxTheme.success : kind === "warn" ? NxTheme.warning : kind === "err" ? NxTheme.danger
         : kind === "off" ? NxTheme.surface3 : NxTheme.muted
}
