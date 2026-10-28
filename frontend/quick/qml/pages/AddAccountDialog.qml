// Добавление аккаунта: Nexora (свой сервер со скинами), локальный (ник) или Microsoft
import QtQuick
import Nexora

NxModal {
    id: root
    property string reason: ""
    property string mode: "nexora"
    property string nexoraMode: "signin"     // signin | signup
    readonly property string nick: field.text.trim()
    readonly property bool valid: /^[A-Za-z0-9_]{3,16}$/.test(nick)
    readonly property var ms: Shell.microsoft
    readonly property var nx: Shell.nexora

    // Nexora: вход по нику или почте, регистрация — ник, почта и пароль
    readonly property bool signup: nexoraMode === "signup"
    readonly property string nxNick: nxName.text.trim()
    readonly property string nxEmail: nxMail.text.trim()
    readonly property bool nickOk: /^[A-Za-z0-9_]{3,16}$/.test(nxNick)
    // Те же правила, что у filter_var на сервере: латиница, без точки в начале и в конце
    // части до «собаки» и без двух точек подряд. Иначе окно пропускало бы адрес,
    // а сервер отвечал отказом уже после отправки.
    readonly property bool emailOk: /^[A-Za-z0-9!#$%&'*+\/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+\/=?^_`{|}~-]+)*@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$/.test(nxEmail)
    readonly property bool passOk: nxPass.text.length >= 8
    readonly property bool nexoraValid: signup ? (nickOk && emailOk && passOk)
                                               : (nxNick.length >= 3 && nxPass.text.length > 0)

    title: I18n.t("q.add_account")
    acceptText: mode === "nexora" ? (signup ? I18n.t("q.sign_up") : I18n.t("q.sign_in"))
                                  : mode === "offline" ? I18n.t("q.add") : I18n.t("q.ms_start")
    acceptEnabled: mode === "nexora" ? nexoraValid
                 : mode === "offline" ? valid
                 : (ms.available !== false
                    && (ms.state === "idle" || ms.state === "error" || ms.state === "done"))
    busy: (mode === "microsoft" && ms.state === "starting") || (mode === "nexora" && nx.state === "busy")
    onOpened: {
        field.text = ""; nxName.text = ""; nxMail.text = ""; nxPass.text = ""
        mode = "nexora"; nexoraMode = "signin"
        Shell.resetNexora()
        Shell.checkMicrosoft()
        nxName.input.forceActiveFocus()
    }
    onClosed: reason = ""
    onAccepted: {
        if (mode === "nexora") {
            if (signup) Shell.registerNexoraAccount(nxNick, nxEmail, nxPass.text)
            else Shell.addNexoraAccount(nxNick, nxPass.text)
        } else if (mode === "offline") {
            Shell.addOfflineAccount(nick); close()
        } else {
            Shell.startMicrosoftLogin()
        }
    }
    Connections {
        target: Shell
        function onMicrosoftChanged() { if (Shell.microsoft.state === "done" && root.opened) root.close() }
        function onNexoraChanged() { if (Shell.nexora.state === "done" && root.opened) root.close() }
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
        model: [{ value: "nexora", label: I18n.t("q.account_nexora") },
                { value: "offline", label: I18n.t("q.account_offline") },
                { value: "microsoft", label: "Microsoft" }]
        onActivated: v => { root.mode = v; Shell.resetNexora() }
    }

    // --- Nexora ---------------------------------------------------------------------------
    Column {
        visible: root.mode === "nexora"
        width: root.fieldWidth
        spacing: 16

        NxSegmentedControl {
            value: root.nexoraMode
            model: [{ value: "signin", label: I18n.t("q.nexora_signin") },
                    { value: "signup", label: I18n.t("q.nexora_signup") }]
            onActivated: v => { root.nexoraMode = v; Shell.resetNexora() }
        }
        NxTextField {
            id: nxName
            width: parent.width
            label: root.signup ? I18n.t("q.nickname") : I18n.t("q.nexora_login")
            placeholder: "Steve"
            error: root.signup && nxName.text && !root.nickOk ? I18n.t("q.nickname_rule") : ""
            onAccepted: root.submit()
        }
        NxTextField {
            id: nxMail
            visible: root.signup
            width: parent.width
            label: I18n.t("q.email")
            placeholder: "steve@example.com"
            error: nxMail.text && !root.emailOk ? I18n.t("q.email_rule") : ""
            onAccepted: root.submit()
        }
        NxTextField {
            id: nxPass
            width: parent.width
            label: I18n.t("q.password")
            password: true
            error: root.signup && nxPass.text && !root.passOk ? I18n.t("q.password_rule") : ""
            onAccepted: root.submit()
        }
        NxText {
            width: parent.width
            text: root.nx.state === "error" ? root.nx.error
                                            : root.signup ? I18n.t("q.nexora_note") : I18n.t("q.nexora_password_note")
            color: root.nx.state === "error" ? NxTheme.danger : NxTheme.muted
            font.pixelSize: 12
            lineHeight: 16
            wrapMode: Text.Wrap
            elide: Text.ElideNone
        }
    }

    // --- Локальный ------------------------------------------------------------------------
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

    // --- Microsoft ------------------------------------------------------------------------
    NxText {
        visible: root.mode === "microsoft" && root.ms.state !== "waiting"
        width: root.fieldWidth
        text: root.ms.state === "error" ? root.ms.error
            : root.ms.available === false ? I18n.t("q.ms_unavailable") : I18n.t("q.ms_note")
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
