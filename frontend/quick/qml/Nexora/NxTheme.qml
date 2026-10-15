// Токены дизайна Nexora: «глубинный сланец» (тёмная) и «песчаник» (светлая)
pragma Singleton
import QtQuick

QtObject {
    id: root
    property bool dark: true
    property string fontUi: "Segoe UI"
    property string fontMono: "Consolas"

    // Цвета
    readonly property color bg: dark ? "#121211" : "#F3EFE6"
    readonly property color surface1: dark ? "#1B1A18" : "#FBF8F2"
    readonly property color surface2: dark ? "#23221F" : "#ECE6DA"
    readonly property color surface3: dark ? "#2D2B27" : "#E2DACB"
    readonly property color text: dark ? "#EDEAE4" : "#1E1C18"
    readonly property color muted: dark ? "#9C978D" : "#6E685D"
    readonly property color line: dark ? "#2F2D29" : "#DDD5C6"
    readonly property color accent: dark ? "#F0B23A" : "#C98A12"
    readonly property color accentPressed: dark ? "#D99A22" : "#B07A0E"
    readonly property color accentHover: Qt.tint(accent, "#24FFFFFF")
    readonly property color onAccent: dark ? "#1A1408" : "#FFFFFF"
    readonly property color success: dark ? "#6FBF73" : "#3F8F45"
    readonly property color danger: dark ? "#E0614F" : "#C2412F"
    readonly property color dangerHover: Qt.tint(danger, "#24FFFFFF")
    readonly property color onDanger: dark ? "#1F0B07" : "#FFFFFF"
    readonly property color warning: dark ? "#E3A33B" : "#B07812"
    readonly property color info: dark ? "#7FA7D9" : "#3F6FA8"
    readonly property color pop: dark ? "#26241F" : "#FBF8F2"
    readonly property color scrim: dark ? "#80000000" : "#521E190F"
    readonly property color shadow: dark ? "#59000000" : "#2E46320F"

    // Полупрозрачные заливки от цвета текста: 7 / 12 / 18 %
    readonly property color fill1: Qt.rgba(text.r, text.g, text.b, 0.07)
    readonly property color fill2: Qt.rgba(text.r, text.g, text.b, 0.12)
    readonly property color fill3: Qt.rgba(text.r, text.g, text.b, 0.18)
    readonly property color okBg: Qt.rgba(success.r, success.g, success.b, 0.16)
    readonly property color errBg: Qt.rgba(danger.r, danger.g, danger.b, 0.14)
    readonly property color warnBg: Qt.rgba(warning.r, warning.g, warning.b, 0.14)
    readonly property color infoBg: Qt.rgba(info.r, info.g, info.b, 0.16)

    // Отступы (сетка 8 px)
    readonly property int sp4: 4
    readonly property int sp8: 8
    readonly property int sp12: 12
    readonly property int sp16: 16
    readonly property int sp24: 24
    readonly property int sp32: 32
    readonly property int sp48: 48

    // Радиусы
    readonly property int rInput: 4
    readonly property int rButton: 6
    readonly property int rCover: 10

    // Движение
    readonly property int fast: 120
    readonly property int base: 180
    readonly property int ease: Easing.OutCubic

    // Типографика: размер / межстрочный / насыщенность
    readonly property var display: ({ px: 32, line: 40, weight: Font.DemiBold })
    readonly property var h1: ({ px: 22, line: 28, weight: Font.DemiBold })
    readonly property var h2: ({ px: 16, line: 22, weight: Font.DemiBold })
    readonly property var body: ({ px: 13, line: 20, weight: Font.Normal })
    readonly property var strong: ({ px: 13, line: 20, weight: Font.Medium })
    readonly property var caption: ({ px: 11, line: 16, weight: Font.Medium })
    readonly property var mono: ({ px: 12, line: 18, weight: Font.Normal })

    // Цвет без «#» для адресов image://nx/...
    function hex(c) { return c.toString().substring(1) }
    function icon(name, c) { return "image://nx/icon/" + name + "/" + hex(c) }
}
