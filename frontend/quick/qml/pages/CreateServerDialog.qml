// Создать свой сервер: ядро, версия, память, согласие с EULA
import QtQuick
import Nexora

NxModal {
    id: root
    property string core: "fabric"
    title: I18n.t("q.create_server")
    acceptText: I18n.t("q.create")
    acceptEnabled: name.text.trim() !== "" && version.text.trim() !== "" && eula.checked
    onOpened: { name.text = I18n.t("q.server_default_name"); version.text = Library.current.version || ""; eula.checked = false }
    onAccepted: { Network.createOwn(name.text, version.text.trim(), Math.round(mem.value * 1024), core, eula.checked); close() }

    NxTextField { id: name; width: root.fieldWidth; label: I18n.t("q.name") }
    Column {
        spacing: 6
        NxText { text: I18n.t("q.core"); variant: "strong"; font.pixelSize: 12; lineHeight: 16; muted: true }
        NxSegmentedControl {
            value: root.core
            model: [{ value: "fabric", label: "Fabric" }, { value: "vanilla", label: "Vanilla" }, { value: "paper", label: "Paper" }, { value: "purpur", label: "Purpur" }]
            onActivated: v => root.core = v
        }
    }
    NxTextField { id: version; width: 200; label: I18n.t("q.mc_version"); mono: true; placeholder: "1.21.4" }
    Column {
        spacing: 6
        NxText { text: I18n.t("q.memory"); variant: "strong"; font.pixelSize: 12; lineHeight: 16; muted: true }
        Row {
            spacing: 12
            NxSlider { id: mem; width: 260; from: 1; to: 16; stepSize: 0.5; value: 3; anchors.verticalCenter: parent.verticalCenter }
            NxText { text: I18n.memory(mem.value * 1024); variant: "mono"; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    Row {
        spacing: 10
        NxCheckbox { id: eula; anchors.verticalCenter: parent.verticalCenter }
        NxText {
            width: root.fieldWidth - 30
            text: I18n.t("q.eula")
            wrapMode: Text.Wrap
            elide: Text.ElideNone
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    NxButton { variant: "ghost"; small: true; iconName: "external"; text: "minecraft.net/eula"; onClicked: Shell.openUrl("https://www.minecraft.net/eula") }
}
