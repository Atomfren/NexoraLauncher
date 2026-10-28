// Настройки: слева разделы, справа сгруппированные строки (подпись слева, управление справа)
import QtQuick
import QtQuick.Controls as C
import Nexora

Item {
    id: page
    property string section: "general"
    readonly property var v: Prefs.values
    readonly property var sections: [
        { value: "general", label: I18n.t("q.set_general") },
        { value: "languages", label: I18n.t("q.set_languages") },
        { value: "game", label: I18n.t("q.set_game") },
        { value: "java", label: "Java" },
        { value: "accounts", label: I18n.t("q.set_accounts") },
        { value: "updates", label: I18n.t("q.set_updates") },
        { value: "about", label: I18n.t("q.set_about") }
    ]

    Connections {
        target: Shell
        function onNavigateRequested(p, sub) { if (p === "settings" && sub) page.section = sub }
    }
    onSectionChanged: {
        if (section === "java" && Prefs.javas.length === 0) Prefs.detectJava()
        if (section === "updates" && Prefs.update.state === "idle") Prefs.checkUpdate()
        if (section === "game") Prefs.loadGpu()
        if (section === "languages") Prefs.loadLanguages()
    }

    Column {
        id: nav
        x: 16
        y: 8
        width: 200
        spacing: 2
        Repeater {
            model: page.sections
            delegate: Rectangle {
                required property var modelData
                readonly property bool active: page.section === modelData.value
                width: nav.width - 8
                height: 34
                radius: NxTheme.rButton
                color: active ? NxTheme.fill2 : hov.hovered ? NxTheme.fill1 : "transparent"
                HoverHandler { id: hov; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: page.section = parent.modelData.value }
                NxText { x: 12; anchors.verticalCenter: parent.verticalCenter; text: parent.modelData.label; variant: "strong"; color: parent.active || hov.hovered ? NxTheme.text : NxTheme.muted }
            }
        }
    }

    Flickable {
        anchors.left: nav.right
        anchors.leftMargin: 24
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        clip: true
        contentHeight: body.implicitHeight + 48
        boundsBehavior: Flickable.StopAtBounds
        C.ScrollBar.vertical: NxScrollBar {}

        Column {
            id: body
            y: 8
            width: Math.min(parent.width - 48, 712)
            spacing: 24

            NxText { text: page.sections.find(s => s.value === page.section).label; variant: "h1" }

            // --- Общие ---
            NxSettingGroup {
                visible: page.section === "general"
                NxSettingRow {
                    first: true
                    label: I18n.t("q.language")
                    NxDropdown {
                        width: 160
                        alignRight: true
                        value: page.v.language || "ru"
                        model: {
                            var out = [{ value: "ru", label: "Русский" }, { value: "en", label: "English" }]
                            var mine = Prefs.languages.installed || []
                            for (var i = 0; i < mine.length; i++) out.push({ value: mine[i].code, label: mine[i].name })
                            return out
                        }
                        onActivated: val => Prefs.save({ language: val })
                    }
                }
                NxSettingRow {
                    label: I18n.t("q.theme")
                    NxSegmentedControl {
                        value: Shell.dark ? "dark" : "light"
                        model: [{ value: "dark", label: I18n.t("q.theme_dark_short") }, { value: "light", label: I18n.t("q.theme_light_short") }]
                        onActivated: val => Shell.setDark(val === "dark")
                    }
                }
                NxSettingRow {
                    label: I18n.t("q.sidebar_position")
                    NxSegmentedControl {
                        value: Shell.sidebarPosition
                        model: [{ value: "left", label: I18n.t("q.side_left") }, { value: "right", label: I18n.t("q.side_right") },
                                { value: "top", label: I18n.t("q.side_top") }, { value: "bottom", label: I18n.t("q.side_bottom") }]
                        onActivated: val => Shell.setSidebarPosition(val)
                    }
                }
                NxSettingRow {
                    visible: Shell.sidebarPosition === "left" || Shell.sidebarPosition === "right"
                    label: I18n.t("q.narrow_sidebar")
                    NxToggle { checked: !Shell.sidebarWide; onToggled: Shell.toggleSidebar() }
                }
            }
            NxSettingGroup {
                visible: page.section === "general"
                NxSettingRow {
                    first: true
                    label: I18n.t("q.data_folder")
                    Row {
                        spacing: 8
                        NxText { width: Math.min(implicitWidth, 300); text: Prefs.system.data_dir || ""; variant: "mono"; muted: true; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter }
                        NxButton { small: true; variant: "ghost"; text: I18n.t("q.open"); onClicked: Shell.openPath(Prefs.system.data_dir) }
                    }
                }
                NxSettingRow {
                    label: I18n.t("q.hide_on_launch")
                    NxToggle { checked: !!page.v.hide_on_launch; onToggled: Prefs.save({ hide_on_launch: checked }) }
                }
                // Запасной путь для сборок CurseForge (All The Mods), если API FTB недоступен
                NxSettingRow {
                    label: I18n.t("q.cf_key")
                    hint: page.v.curseforge_key_set ? I18n.t("q.cf_key_set") : I18n.t("q.cf_key_hint")
                    Row {
                        spacing: 8
                        NxTextField {
                            id: cfKey
                            width: 220
                            mono: true
                            placeholder: page.v.curseforge_key_set ? "••••••••" : I18n.t("q.cf_key_placeholder")
                            input.echoMode: TextInput.Password
                            onAccepted: if (text.trim()) { Prefs.save({ curseforge_api_key: text.trim() }); text = "" }
                        }
                        NxButton {
                            visible: !!page.v.curseforge_key_set
                            small: true; variant: "ghost"; iconName: "x"
                            text: I18n.t("q.remove")
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: Prefs.save({ curseforge_api_key: "" })
                        }
                    }
                }
            }

            // --- Игра и память ---
            NxSettingGroup {
                visible: page.section === "game"
                NxSettingRow {
                    first: true
                    label: I18n.t("q.default_memory")
                    Row {
                        spacing: 12
                        NxText { width: 64; horizontalAlignment: Text.AlignRight; text: I18n.memory(mem.value * 1024); variant: "mono"; anchors.verticalCenter: parent.verticalCenter }
                        NxSlider {
                            id: mem
                            width: 220
                            from: 1; to: Math.max(2, Math.floor(Prefs.totalMemoryMb / 1024)); stepSize: 0.5
                            value: (page.v.max_memory || 4096) / 1024
                            anchors.verticalCenter: parent.verticalCenter
                            onPressedChanged: if (!pressed) Prefs.save({ max_memory: Math.round(value * 1024) })
                        }
                    }
                }
                NxSettingRow {
                    label: I18n.t("q.recommended_pc")
                    NxChip {
                        clickable: true
                        kind: "info"
                        mono: true
                        text: I18n.tf("q.of_total", { mem: I18n.memory(Prefs.recommendedMemoryMb), total: I18n.memory(Prefs.totalMemoryMb) })
                        onClicked: Prefs.save({ max_memory: Prefs.recommendedMemoryMb })
                    }
                }
            }
            NxSettingGroup {
                visible: page.section === "game"
                NxSettingRow {
                    first: true
                    label: I18n.t("q.window_size")
                    Row {
                        spacing: 8
                        NxTextField {
                            width: 84; mono: true
                            text: String(page.v.game_width || 854)
                            input.validator: IntValidator { bottom: 320; top: 7680 }
                            input.onEditingFinished: Prefs.save({ game_width: parseInt(text) || 854 })
                        }
                        NxText { text: "×"; muted: true; anchors.verticalCenter: parent.verticalCenter }
                        NxTextField {
                            width: 84; mono: true
                            text: String(page.v.game_height || 480)
                            input.validator: IntValidator { bottom: 240; top: 4320 }
                            input.onEditingFinished: Prefs.save({ game_height: parseInt(text) || 480 })
                        }
                    }
                }
                NxSettingRow {
                    label: I18n.t("q.fullscreen")
                    NxToggle { checked: !!page.v.fullscreen; onToggled: Prefs.save({ fullscreen: checked }) }
                }
                NxSettingRow {
                    visible: !!Prefs.gpu.supported
                    label: I18n.t("q.gpu")
                    hint: Prefs.gpu.loading ? I18n.t("q.gpu_looking")
                        : Prefs.gpu.discrete_name ? I18n.tf("q.gpu_found", { name: Prefs.gpu.discrete_name })
                        : I18n.t("q.gpu_single")
                    NxSegmentedControl {
                        enabled: !!Prefs.gpu.discrete_name
                        value: page.v.gpu_preference || "auto"
                        model: [{ value: "auto", label: I18n.t("q.gpu_auto") },
                                { value: "discrete", label: I18n.t("q.gpu_discrete") },
                                { value: "integrated", label: I18n.t("q.gpu_integrated") },
                                { value: "system", label: I18n.t("q.gpu_system") }]
                        onActivated: val => Prefs.save({ gpu_preference: val })
                    }
                }
                NxSettingRow {
                    label: I18n.t("q.jvm_args")
                    NxTextField {
                        width: 300; mono: true
                        text: page.v.jvm_args || ""
                        placeholder: "-XX:+UseG1GC"
                        input.onEditingFinished: Prefs.save({ jvm_args: text.trim() })
                    }
                }
            }

            // --- Языки ---
            NxSettingGroup {
                visible: page.section === "languages"
                NxSettingRow {
                    first: true
                    label: I18n.t("q.lang_current")
                    hint: I18n.t("q.restart_for_language")
                    NxDropdown {
                        width: 180
                        alignRight: true
                        value: page.v.language || "ru"
                        model: {
                            var out = [{ value: "ru", label: "Русский" }, { value: "en", label: "English" }]
                            var mine = Prefs.languages.installed || []
                            for (var i = 0; i < mine.length; i++) out.push({ value: mine[i].code, label: mine[i].name })
                            return out
                        }
                        onActivated: val => Prefs.save({ language: val })
                    }
                }
            }
            NxSettingGroup {
                visible: page.section === "languages"
                NxSettingRow {
                    first: true
                    label: I18n.t("q.lang_available")
                    hint: Prefs.languages.loading ? I18n.t("common.loading")
                        : (Prefs.languages.error || I18n.t("q.lang_from_site"))
                    NxButton {
                        small: true
                        variant: "ghost"
                        iconName: "refresh"
                        text: I18n.t("common.refresh")
                        loading: !!Prefs.languages.loading
                        onClicked: Prefs.loadLanguages()
                    }
                }
                Repeater {
                    model: Prefs.languages.available || []
                    delegate: NxSettingRow {
                        required property var modelData
                        label: modelData.name + (modelData.version ? " · " + modelData.version : "")
                        hint: I18n.tf("q.lang_coverage", { done: modelData.translated, total: modelData.total })
                            + (modelData.author ? " · " + modelData.author : "")
                        Row {
                            spacing: 8
                            NxButton {
                                small: true
                                visible: !modelData.installed || modelData.update_available
                                loading: Prefs.languages.busy === modelData.code
                                text: modelData.update_available ? I18n.t("q.update_install") : I18n.t("q.lang_download")
                                onClicked: Prefs.installLanguage(modelData.code)
                            }
                            NxButton {
                                small: true
                                variant: "ghost"
                                dangerText: true
                                visible: modelData.installed
                                text: I18n.t("common.delete")
                                onClicked: Prefs.removeLanguage(modelData.code)
                            }
                        }
                    }
                }
                NxSettingRow {
                    visible: !Prefs.languages.loading && (Prefs.languages.available || []).length === 0
                    label: I18n.t("q.lang_none")
                }
            }

            // --- Java ---
            NxSettingGroup {
                visible: page.section === "java"
                NxSettingRow {
                    first: true
                    label: I18n.t("q.java_auto_pick")
                    hint: I18n.t("q.java_auto_hint")
                    NxToggle { checked: !page.v.java_path; onToggled: if (checked) Prefs.save({ java_path: "" }) }
                }
                Repeater {
                    model: Prefs.javas
                    delegate: NxSettingRow {
                        required property var modelData
                        label: "Java " + modelData.major + " · " + modelData.version
                        hint: modelData.path
                        NxRadio {
                            checked: page.v.java_path === modelData.path
                            TapHandler { onTapped: Prefs.save({ java_path: modelData.path }) }
                        }
                    }
                }
            }
            Row {
                visible: page.section === "java"
                spacing: 8
                NxButton { iconName: "search"; text: I18n.t("q.find_java"); loading: Prefs.javaLoading; onClicked: Prefs.detectJava() }
            }

            // --- Аккаунты ---
            NxSettingGroup {
                visible: page.section === "accounts"
                Repeater {
                    model: Shell.accounts
                    delegate: NxSettingRow {
                        required property var modelData
                        required property int index
                        first: index === 0
                        label: modelData.name
                        hint: modelData.kind
                        Row {
                            spacing: 8
                            NxChip { visible: modelData.active; text: I18n.t("q.active"); kind: "ok"; anchors.verticalCenter: parent.verticalCenter }
                            NxButton { visible: !modelData.active; small: true; variant: "ghost"; text: I18n.t("q.make_active"); onClicked: Shell.activateAccount(modelData.id) }
                            NxIconButton { small: true; iconName: "log-out"; tip: I18n.t("q.sign_out"); onClicked: Shell.removeAccount(modelData.id) }
                        }
                    }
                }
                NxText { visible: Shell.accounts.length === 0; height: 52; text: I18n.t("q.no_accounts"); muted: true }
            }
            NxButton {
                visible: page.section === "accounts"
                iconName: "plus"
                text: I18n.t("q.add_account")
                onClicked: Shell.requestAddAccount()
            }
            NxSettingGroup {
                visible: page.section === "accounts"
                NxSettingRow {
                    first: true
                    label: I18n.t("q.ms_client_id")
                    hint: I18n.t("q.ms_client_hint")
                    NxTextField {
                        width: 300; mono: true
                        text: page.v.ms_client_id || ""
                        placeholder: "00000000-0000-0000-0000-000000000000"
                        input.onEditingFinished: Prefs.save({ ms_client_id: text.trim() })
                    }
                }
            }

            // --- Обновления ---
            NxSettingGroup {
                visible: page.section === "updates"
                NxSettingRow {
                    first: true
                    label: I18n.t("q.version")
                    NxText { text: "Nexora " + Shell.version; variant: "mono" }
                }
                NxSettingRow {
                    label: I18n.t("q.check_auto")
                    NxToggle { checked: page.v.check_updates !== false; onToggled: Prefs.save({ check_updates: checked }) }
                }
            }
            Row {
                visible: page.section === "updates"
                spacing: 12
                NxButton {
                    iconName: "refresh"
                    text: I18n.t("q.check_updates")
                    loading: Prefs.update.state === "checking"
                    onClicked: Prefs.checkUpdate()
                }
                NxButton {
                    visible: !!Prefs.update.available && !!Prefs.update.can_install
                    variant: "primary"
                    iconName: "download"
                    loading: Prefs.update.state === "downloading"
                    text: I18n.tf("q.install_version", { v: Prefs.update.latest || "" })
                    onClicked: Prefs.installUpdate()
                }
                NxText {
                    anchors.verticalCenter: parent.verticalCenter
                    muted: true
                    text: Prefs.update.state === "error" ? (Prefs.update.error || "")
                        : Prefs.update.state === "ready" ? (Prefs.update.available ? I18n.tf("q.update_available", { v: Prefs.update.latest }) : I18n.t("q.up_to_date"))
                        : ""
                }
            }
            NxText {
                visible: page.section === "updates" && !!Prefs.update.available && !!Prefs.update.notes
                width: parent.width
                text: Prefs.update.notes || ""
                muted: true
                wrapMode: Text.Wrap
                elide: Text.ElideNone
                maximumLineCount: 12
            }

            // --- О программе ---
            Row {
                visible: page.section === "about"
                spacing: 16
                Image {
                    width: 56; height: 56
                    source: "image://nx/logo/" + NxTheme.hex(NxTheme.text) + "/" + NxTheme.hex(NxTheme.accent)
                    sourceSize: Qt.size(112, 112)
                }
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    NxText { text: "Nexora"; variant: "h1" }
                    NxText { text: Shell.version + " · Qt Quick"; variant: "mono"; muted: true }
                }
            }
            NxSettingGroup {
                visible: page.section === "about"
                NxSettingRow {
                    first: true
                    // Раньше здесь была ссылка на исходники: код закрыт, обещать их нельзя
                    label: I18n.t("q.website")
                    NxButton { small: true; variant: "ghost"; iconName: "external"; text: I18n.t("q.open"); onClicked: Shell.openUrl(Shell.website) }
                }
                NxSettingRow {
                    label: I18n.t("q.launcher_logs")
                    NxButton { small: true; variant: "ghost"; iconName: "folder"; text: I18n.t("q.open_folder"); onClicked: Shell.openPath(Prefs.system.logs_dir) }
                }
            }
            NxText {
                visible: page.section === "about"
                width: parent.width
                text: I18n.t("q.not_affiliated")
                muted: true
                wrapMode: Text.Wrap
                elide: Text.ElideNone
            }
        }
    }
}
