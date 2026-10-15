// Текст по шкале дизайна: display, h1, h2, body, strong, caption, mono
import QtQuick

Text {
    id: root
    property string variant: "body"
    property bool muted: false
    readonly property var spec: NxTheme[variant === "monoStrong" ? "mono" : variant] || NxTheme.body
    readonly property bool isMono: variant === "mono" || variant === "monoStrong"

    color: muted || variant === "caption" ? NxTheme.muted : NxTheme.text
    font.family: isMono ? NxTheme.fontMono : NxTheme.fontUi
    font.pixelSize: spec.px
    font.weight: variant === "monoStrong" ? Font.Medium : spec.weight
    font.capitalization: variant === "caption" ? Font.AllUppercase : Font.MixedCase
    font.letterSpacing: variant === "caption" ? 0.4 : (variant === "display" ? -0.3 : 0)
    font.features: { "tnum": 1 }
    lineHeightMode: Text.FixedHeight
    lineHeight: spec.line
    verticalAlignment: Text.AlignVCenter
    elide: Text.ElideRight
    textFormat: Text.PlainText
}
