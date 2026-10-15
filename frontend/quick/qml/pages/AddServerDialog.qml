// Добавить сервер в избранное
import QtQuick
import Nexora

NxModal {
    id: root
    title: I18n.t("q.add_server")
    acceptText: I18n.t("q.add")
    acceptEnabled: address.text.trim() !== ""
    onOpened: { name.text = ""; address.text = ""; address.input.forceActiveFocus() }
    onAccepted: { Network.addServer(name.text, address.text); close() }

    NxTextField { id: address; width: root.fieldWidth; label: I18n.t("q.server_address"); placeholder: "play.example.com"; mono: true; onAccepted: root.submit() }
    NxTextField { id: name; width: root.fieldWidth; label: I18n.t("q.name"); placeholder: I18n.t("q.optional"); onAccepted: root.submit() }
}
