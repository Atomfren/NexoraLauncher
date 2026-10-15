// Добавление аккаунта: локальный (ник) или Microsoft (код на microsoft.com/link)
import QtQuick
import Nexora

NxModal {
    id: root
    property string reason: ""
    property string mode: "offline"
    readonly property string nick: field.text.trim()
    readonly property bool valid: /^[A-Za-z0-9_]{3,16}$/.test(nick)
    readonly property var ms: Shell.microsoft

    title: I18n.t("q.add_account")
    acceptText: mode === "offline" ? I18n.t("q.add") : I18n.t("q.ms_start")
    acceptEnabled: mode === "offline" ? valid : (ms.state === "idle" || ms.state === "error" || ms.state === "done")
    busy: mode === "microsoft" && ms.state === "starting"
    onOpened: { field.text = ""; mode = "offline"; field.input.forceActiveFocus() }
    onClosed: reason = ""
    onAccepted: {
        if (mode === "offline") { Shell.addOfflineAccount(nick); close() }
        else Shell.startMicrosoftLogin()
    }
    Connections {
        target: Shell
        function onMicrosoftChanged() { if (Shell.microsoft.state === "done" && root.opened) root.close() }
    }

    NxText {
        visible: root.reason !== ""
        width: root.fieldWidth
        text: root.reason
        muted: true
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }
    NxSegmentedControl {
        value: root.mode
        model: [{ value: "offline", label: I18n.t("q.account_offline") }, { value: "microsoft", label: "Microsoft" }]
        onActivated: v => root.mode = v
    }

    // Локальный
    NxTextField {
        id: field
        visible: root.mode === "offline"
        width: root.fieldWidth
        label: I18n.t("q.nickname")
        placeholder: "Steve"
        error: field.text && !root.valid ? I18n.t("q.nickname_rule") : ""
        onAccepted: root.submit()
    }
    NxText {
        visible: root.mode === "offline"
        width: root.fieldWidth
        text: I18n.t("q.offline_note")
        muted: true
        font.pixelSize: 12
        lineHeight: 16
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }

    // Microsoft
    NxText {
        visible: root.mode === "microsoft" && root.ms.state !== "waiting"
        width: root.fieldWidth
        text: root.ms.state === "error" ? root.ms.error : I18n.t("q.ms_note")
        color: root.ms.state === "error" ? NxTheme.danger : NxTheme.muted
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }
    Column {
        visible: root.mode === "microsoft" && root.ms.state === "waiting"
        width: root.fieldWidth
        spacing: 12
        NxText { width: parent.width; text: I18n.t("q.ms_enter_code"); wrapMode: Text.Wrap; elide: Text.ElideNone }
        Rectangle {
            width: parent.width
            height: 56
            radius: NxTheme.rInput
            color: NxTheme.surface2
            NxText { anchors.centerIn: parent; text: root.ms.code || ""; variant: "monoStrong"; font.pixelSize: 24; lineHeight: 32; font.letterSpacing: 2 }
        }
        Row {
            spacing: 8
            NxButton { iconName: "copy"; text: I18n.t("q.copy"); onClicked: Shell.copy(root.ms.code) }
            NxButton { variant: "ghost"; iconName: "external"; text: root.ms.url || ""; onClicked: Shell.openUrl(root.ms.url) }
        }
        Row {
            spacing: 8
            NxSpinner { color: NxTheme.muted; anchors.verticalCenter: parent.verticalCenter }
            NxText { text: I18n.t("q.ms_waiting"); muted: true; anchors.verticalCenter: parent.verticalCenter }
        }
    }
}
