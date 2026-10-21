// Сеть: избранные серверы слева, свой сервер справа; консоль и бэкапы — выдвижные панели
import QtQuick
import QtQuick.Controls as C
import Nexora

Item {
    id: page
    readonly property bool narrow: width < 860
    readonly property var own: Network.own
    readonly property bool hasOwn: own.name !== undefined
    readonly property bool running: own.state === "running"
    readonly property bool starting: own.state === "starting" || own.state === "stopping"
    // Цвета §-кодов Minecraft под тему
    readonly property var mc: NxTheme.dark
        ? ({ "0": "#8a8a8a", "1": "#6f7bff", "2": "#5fd35f", "3": "#3fd4d4", "4": "#f06060", "5": "#c860d8", "6": "#ffaa00", "7": "#bcbcbc",
             "8": "#7d7d7d", "9": "#8f9aff", "a": "#7ef07e", "b": "#6fe8e8", "c": "#ff7878", "d": "#ff8fff", "e": "#f2e45a", "f": "#f4f1ea" })
        : ({ "0": "#3a3a3a", "1": "#2330b8", "2": "#1f8a1f", "3": "#158a8a", "4": "#b02020", "5": "#8a2a9a", "6": "#b87000", "7": "#5a5a5a",
             "8": "#3f3f3f", "9": "#3a46d6", "a": "#2f9a2f", "b": "#1a9a9a", "c": "#d03a3a", "d": "#b030b0", "e": "#9a8a00", "f": "#1e1c18" })
    property string selected: ""

    function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
    function motdHtml(spans) {
        let out = ""
        for (const s of spans) {
            let t = esc(s.text)
            if (s.bold) t = "<b>" + t + "</b>"
            if (s.italic) t = "<i>" + t + "</i>"
            out += s.color ? "<span style='color:" + mc[s.color] + "'>" + t + "</span>" : t
        }
        return out
    }
    function clock(sec) {
        const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60
        return (h ? h + ":" : "") + (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
    }

    Connections {
        target: Shell
        function onPageChanged() { Shell.page === "network" ? Network.activate() : Network.deactivate() }
    }

    // --- Избранные серверы ---
    Item {
        id: fav
        x: 32
        y: 8
        width: page.narrow ? parent.width - 64 : parent.width - 64 - ownCard.width - 32
        height: page.narrow ? Math.max(260, parent.height - ownCard.height - 48) : parent.height - 32

        NxSectionHeader {
            id: favHead
            width: parent.width
            text: ""
            NxText { text: I18n.t("q.favorite_servers"); variant: "h2"; anchors.verticalCenter: parent.verticalCenter }
            NxButton {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                small: true; variant: "ghost"; iconName: "plus"
                text: I18n.t("q.add_server")
                onClicked: addDialog.open()
            }
        }
        ListView {
            id: servers
            anchors.top: favHead.bottom
            anchors.topMargin: 8
            anchors.bottom: parent.bottom
            width: parent.width
            clip: true
            spacing: 2
            model: Network.servers
            boundsBehavior: Flickable.StopAtBounds
            C.ScrollBar.vertical: NxScrollBar {}
            delegate: Rectangle {
                id: srv
                required property var modelData
                readonly property bool sel: page.selected === modelData.id
                width: servers.width
                height: 72
                radius: NxTheme.rButton
                color: sel || sh.hovered ? NxTheme.fill1 : "transparent"
                HoverHandler { id: sh }
                TapHandler { onTapped: page.selected = srv.modelData.id; onDoubleTapped: Network.connectTo(srv.modelData.id, "") }
                NxCover { id: si; x: 8; width: 48; height: 48; anchors.verticalCenter: parent.verticalCenter; source: "image://nx/scene/" + srv.modelData.palette + "/" + srv.modelData.seed + "/20/20" }
                Column {
                    anchors.left: si.right; anchors.leftMargin: 12
                    anchors.right: stats.left; anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    NxText { width: parent.width; text: srv.modelData.name; variant: "strong" }
                    Text {
                        width: parent.width
                        text: srv.modelData.motd.length ? page.motdHtml(srv.modelData.motd) : srv.modelData.address
                        textFormat: Text.StyledText
                        color: NxTheme.muted
                        font.family: NxTheme.fontMono
                        font.pixelSize: 13
                        elide: Text.ElideRight
                        maximumLineCount: 1
                    }
                }
                Row {
                    id: stats
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 12
                    Row {
                        width: 72
                        spacing: 6
                        layoutDirection: Qt.RightToLeft
                        anchors.verticalCenter: parent.verticalCenter
                        NxText { text: srv.modelData.ping || "…"; variant: "mono"; anchors.verticalCenter: parent.verticalCenter }
                        NxDot { kind: srv.modelData.pingKind || "off"; anchors.verticalCenter: parent.verticalCenter }
                    }
                    NxText { width: 64; horizontalAlignment: Text.AlignRight; text: srv.modelData.players || ""; variant: "mono"; muted: true; anchors.verticalCenter: parent.verticalCenter }
                    NxButton {
                        opacity: sh.hovered || srv.sel ? 1 : 0
                        small: true
                        text: I18n.t("q.connect")
                        enabled: srv.modelData.online
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: Network.connectTo(srv.modelData.id, "")
                    }
                    NxIconButton {
                        opacity: sh.hovered || srv.sel ? 1 : 0
                        small: true
                        iconName: "trash"
                        tip: I18n.t("common.delete")
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: Network.removeServer(srv.modelData.id)
                    }
                }
            }
            NxEmptyState {
                visible: Network.loaded && Network.servers.length === 0
                leftPadding: 0
                compact: true
                illustration: "server"
                text: I18n.t("q.no_servers")
                NxButton { iconName: "plus"; text: I18n.t("q.add_server"); onClicked: addDialog.open() }
            }
        }
    }

    // --- Свой сервер ---
    Rectangle {
        id: ownCard
        x: page.narrow ? 32 : parent.width - width - 32
        y: page.narrow ? fav.y + fav.height + 16 : 16
        width: page.narrow ? parent.width - 64 : 404
        height: ownCol.implicitHeight + 48
        radius: NxTheme.rButton
        color: NxTheme.surface1

        Column {
            id: ownCol
            x: 24
            y: 24
            width: parent.width - 48
            spacing: 16

            // Нет своего сервера
            Column {
                visible: !page.hasOwn
                width: parent.width
                spacing: 12
                NxText { text: I18n.t("q.own_server"); variant: "h2" }
                NxText {
                    width: parent.width
                    text: I18n.t("q.own_server_pitch")
                    muted: true
                    wrapMode: Text.Wrap
                    elide: Text.ElideNone
                    lineHeightMode: Text.ProportionalHeight
                    lineHeight: 1.2
                }
                NxButton { iconName: "plus"; text: I18n.t("q.create_server"); onClicked: createDialog.open() }
            }

            // Шапка
            Row {
                visible: page.hasOwn
                width: parent.width
                spacing: 12
                NxCover { width: 48; height: 48; source: "image://nx/scene/sky/" + (page.own.seed || 77) + "/20/20" }
                Column {
                    width: parent.width - 60 - stateChip.width - 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    NxText { width: parent.width; text: page.own.name || ""; variant: "h2" }
                    NxLoaderBadge {
                        loader: page.own.core === "vanilla" ? "vanilla" : page.own.core === "fabric" ? "fabric" : page.own.core === "purpur" ? "purpur" : "paper"
                        text: (page.own.core || "").charAt(0).toUpperCase() + (page.own.core || "").slice(1) + " " + (page.own.version || "")
                    }
                }
                NxChip {
                    id: stateChip
                    anchors.verticalCenter: parent.verticalCenter
                    text: page.running ? I18n.t("q.state_running") : page.starting ? I18n.t("q.state_starting")
                        : page.own.installed === false ? I18n.t("q.state_installing") : I18n.t("q.state_stopped")
                    kind: page.running ? "ok" : page.starting ? "warn" : ""
                    dot: page.starting ? "spin" : page.running ? "ok" : "off"
                }
            }
            NxProgressBar { visible: page.hasOwn && page.starting; width: parent.width; indeterminate: true }

            // Адрес для друзей
            Column {
                visible: page.hasOwn && page.running
                width: parent.width
                spacing: 6
                NxText { text: I18n.t("q.address_for_friends"); variant: "strong"; font.pixelSize: 12; lineHeight: 16; muted: true }
                Rectangle {
                    width: parent.width
                    height: 36
                    radius: NxTheme.rInput
                    color: NxTheme.surface2
                    NxText {
                        x: 12
                        width: parent.width - 52
                        anchors.verticalCenter: parent.verticalCenter
                        text: page.own.address || page.own.lan || ""
                        variant: "mono"
                        font.pixelSize: 13
                    }
                    NxIconButton {
                        anchors.right: parent.right
                        anchors.rightMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        small: true
                        iconName: "copy"
                        tip: I18n.t("q.copy")
                        onClicked: Shell.copy(page.own.address || page.own.lan || "")
                    }
                }
                NxText {
                    visible: !page.own.address
                    width: parent.width
                    text: I18n.t("q.lan_only")
                    muted: true
                    font.pixelSize: 12
                    lineHeight: 16
                    wrapMode: Text.Wrap
                    elide: Text.ElideNone
                }
            }

            // Игроки и аптайм
            Item {
                visible: page.hasOwn
                width: parent.width
                height: 28
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 12
                    Row {
                        spacing: -6
                        anchors.verticalCenter: parent.verticalCenter
                        Repeater {
                            model: (page.own.players || []).slice(0, 5)
                            delegate: Rectangle {
                                required property string modelData
                                width: 32; height: 32; radius: 6
                                color: NxTheme.surface1
                                NxCover { anchors.centerIn: parent; width: 28; height: 28; radius: 4; source: "image://nx/head/" + (modelData.length * 7 + modelData.charCodeAt(0)) }
                            }
                        }
                    }
                    NxText { text: (page.own.players || []).length + " " + I18n.t("q.online"); variant: "mono"; muted: !page.running; anchors.verticalCenter: parent.verticalCenter }
                }
                NxText {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: page.running ? I18n.tf("q.uptime", { t: page.clock(page.own.uptime || 0) }) : page.starting ? I18n.t("q.loading_world") : I18n.t("q.not_started")
                    variant: "mono"
                    muted: true
                }
            }

            // Действия
            Flow {
                visible: page.hasOwn
                width: parent.width
                spacing: 8
                NxButton {
                    iconName: page.running || page.starting ? "square" : "play"
                    text: page.running || page.starting ? I18n.t("q.stop_server") : I18n.t("q.start_server")
                    loading: page.own.state === "stopping"
                    enabled: page.own.installed !== false
                    onClicked: page.running || page.starting ? Network.stop() : Network.start()
                }
                NxButton { variant: "ghost"; iconName: "terminal"; text: I18n.t("q.console"); onClicked: consoleDrawer.open() }
                NxButton { variant: "ghost"; iconName: "archive"; text: I18n.t("q.backups"); onClicked: { Network.loadBackups(); backupsDrawer.open() } }
                NxButton { variant: "ghost"; iconName: "sliders"; text: I18n.t("q.server_settings"); onClicked: { Network.loadProps(); propsDrawer.open() } }
                NxButton {
                    variant: "ghost"
                    iconName: "package"
                    text: page.own.core === "fabric" ? I18n.t("q.server_mods") : I18n.t("q.server_plugins")
                    onClicked: { Network.loadMods(); modsDrawer.open() }
                }
                NxIconButton { iconName: "plus"; tip: I18n.t("q.create_server"); onClicked: createDialog.open() }
            }
        }
    }

    // --- Консоль ---
    NxDrawer {
        id: consoleDrawer
        title: I18n.t("q.console")
        subtitle: page.own.name || ""
        scrollable: false
        onOpened: Network.setConsoleOpen(true)
        onClosed: Network.setConsoleOpen(false)

        Rectangle {
            width: consoleDrawer.bodyWidth
            height: parent.height - 8
            radius: NxTheme.rButton
            color: NxTheme.bg
            ListView {
                id: consoleList
                anchors.fill: parent
                anchors.margins: 8
                clip: true
                model: Network.console
                onCountChanged: positionViewAtEnd()
                C.ScrollBar.vertical: NxScrollBar {}
                delegate: Text {
                    required property string modelData
                    width: consoleList.width
                    text: modelData
                    color: modelData.indexOf("WARN") >= 0 ? NxTheme.warning : modelData.indexOf("ERROR") >= 0 ? NxTheme.danger : NxTheme.text
                    font.family: NxTheme.fontMono
                    font.pixelSize: 12
                    wrapMode: Text.WrapAnywhere
                }
                NxText { visible: consoleList.count === 0; text: I18n.t("q.console_empty"); muted: true }
            }
        }
        footer: Row {
            x: 24; y: 16
            width: parent.width - 48
            spacing: 8
            NxTextField {
                id: cmd
                width: parent.width - send.width - 8
                mono: true
                prefix: ">"
                placeholder: I18n.t("q.command")
                enabled: page.running
                onAccepted: { Network.sendCommand(text); text = "" }
            }
            NxButton { id: send; text: I18n.t("q.send"); enabled: page.running && cmd.text !== ""; onClicked: { Network.sendCommand(cmd.text); cmd.text = "" } }
        }
    }

    // --- Бэкапы ---
    NxDrawer {
        id: backupsDrawer
        title: I18n.t("q.backups")
        subtitle: page.own.name || ""
        property string target: ""
        NxText {
            visible: Network.backups.length === 0
            width: backupsDrawer.bodyWidth
            text: I18n.t("q.no_backups")
            muted: true
            wrapMode: Text.Wrap
            elide: Text.ElideNone
        }
        Repeater {
            model: Network.backups
            delegate: Rectangle {
                id: bk
                required property var modelData
                width: backupsDrawer.bodyWidth
                height: 52
                radius: NxTheme.rButton
                color: bh.hovered ? NxTheme.fill1 : "transparent"
                HoverHandler { id: bh }
                Column {
                    x: 8
                    anchors.verticalCenter: parent.verticalCenter
                    NxText { text: bk.modelData.date; variant: "strong" }
                    NxText { text: bk.modelData.reason + " · " + bk.modelData.size; muted: true; font.pixelSize: 12; lineHeight: 16 }
                }
                NxButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    small: true
                    variant: "ghost"
                    text: I18n.t("q.restore")
                    enabled: !page.running
                    onClicked: { backupsDrawer.target = bk.modelData.filename; restoreDialog.open() }
                }
            }
        }
        footer: NxButton {
            x: 24; y: 16
            width: parent.width - 48
            iconName: "archive"
            text: I18n.t("q.backup_now")
            onClicked: Network.createBackup()
        }
    }

    // --- Настройки сервера (server.properties) ---
    NxDrawer {
        id: propsDrawer
        title: I18n.t("q.server_settings")
        subtitle: page.own.name || ""
        NxText {
            width: propsDrawer.bodyWidth
            text: I18n.t("q.server_settings_hint")
            muted: true
            font.pixelSize: 12
            lineHeight: 16
            wrapMode: Text.Wrap
            elide: Text.ElideNone
        }
        NxSettingGroup {
            width: propsDrawer.bodyWidth
            Repeater {
                model: Network.props
                delegate: NxSettingRow {
                    id: prop
                    required property var modelData
                    required property int index
                    first: index === 0
                    label: modelData.label
                    hint: modelData.hint
                    // Создаётся только нужный элемент: невидимые расширяли бы строку
                    Loader {
                        sourceComponent: prop.modelData.kind === "bool" ? toggleField
                            : prop.modelData.options.length ? choiceField : textField
                    }
                    Component {
                        id: toggleField
                        NxToggle {
                            checked: prop.modelData.checked
                            onToggled: Network.setProp(prop.modelData.key, checked)
                        }
                    }
                    Component {
                        id: choiceField
                        NxDropdown {
                            width: 150
                            model: prop.modelData.options
                            value: prop.modelData.value
                            alignRight: true
                            onActivated: v => Network.setProp(prop.modelData.key, v)
                        }
                    }
                    Component {
                        id: textField
                        NxTextField {
                            width: prop.modelData.kind === "number" ? 80 : 200
                            mono: prop.modelData.kind === "number"
                            text: prop.modelData.value
                            onAccepted: Network.setProp(prop.modelData.key, text)
                            input.onEditingFinished: if (text !== prop.modelData.value) Network.setProp(prop.modelData.key, text)
                        }
                    }
                }
            }
        }
    }

    // --- Моды и плагины своего сервера ---
    NxDrawer {
        id: modsDrawer
        title: page.own.core === "fabric" ? I18n.t("q.server_mods") : I18n.t("q.server_plugins")
        subtitle: page.own.name || ""
        NxText {
            visible: page.own.core === "vanilla"
            width: modsDrawer.bodyWidth
            text: I18n.t("q.server_mods_vanilla")
            muted: true
            wrapMode: Text.Wrap
            elide: Text.ElideNone
        }
        NxSpinner { visible: Network.modsLoading && Network.mods.length === 0 }
        NxText {
            visible: page.own.core !== "vanilla" && !Network.modsLoading && Network.mods.length === 0
            width: modsDrawer.bodyWidth
            text: I18n.t("q.server_mods_empty")
            muted: true
        }
        NxText {
            visible: Network.mods.length > 0 && (page.running || page.starting)
            width: modsDrawer.bodyWidth
            text: I18n.t("q.stop_to_remove")
            muted: true
            font.pixelSize: 12
            lineHeight: 16
            wrapMode: Text.Wrap
            elide: Text.ElideNone
        }
        Repeater {
            model: Network.mods
            delegate: Rectangle {
                id: md
                required property var modelData
                width: modsDrawer.bodyWidth
                height: 52
                radius: NxTheme.rButton
                color: mh.hovered ? NxTheme.fill1 : "transparent"
                HoverHandler { id: mh }
                Column {
                    x: 8
                    width: parent.width - 60
                    anchors.verticalCenter: parent.verticalCenter
                    NxText { width: parent.width; text: md.modelData.name; variant: "strong"; color: md.modelData.enabled ? NxTheme.text : NxTheme.muted }
                    NxText {
                        width: parent.width
                        text: [md.modelData.version, md.modelData.size, md.modelData.tunnel ? I18n.t("q.tunnel_mod") : ""].filter(x => x).join(" · ")
                        muted: true
                        font.pixelSize: 12
                        lineHeight: 16
                    }
                }
                NxIconButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    small: true
                    iconName: "trash"
                    tip: I18n.t("q.remove")
                    enabled: !page.running && !page.starting
                    onClicked: Network.removeMod(md.modelData.filename)
                }
            }
        }
        footer: NxButton {
            x: 24; y: 16
            width: parent.width - 48
            iconName: "compass"
            text: I18n.t("q.find_in_catalog")
            enabled: page.own.core !== "vanilla"
            onClicked: {
                const target = page.own.name
                modsDrawer.close()
                Shell.navigate("catalog", "plugin")
                Catalog.setFilter("target", target)
            }
        }
    }

    NxDialog {
        id: restoreDialog
        title: I18n.t("q.restore_title")
        text: I18n.t("q.restore_text")
        acceptText: I18n.t("q.restore")
        onAccepted: Network.restoreBackup(backupsDrawer.target)
    }

    AddServerDialog { id: addDialog }
    CreateServerDialog { id: createDialog }
}
