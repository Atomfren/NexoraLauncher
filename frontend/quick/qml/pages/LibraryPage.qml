// Библиотека: слева список сборок, справа выбранная сборка с фоном и вкладками
import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts
import QtQuick.Dialogs
import Nexora
import "library"

Item {
    id: page
    readonly property var cur: Library.current
    readonly property bool hasBuild: cur.name !== undefined
    property string tab: "overview"
    readonly property var loaderNames: ({ vanilla: "Vanilla", fabric: "Fabric", quilt: "Quilt", forge: "Forge", neoforge: "NeoForge" })

    Connections {
        target: Shell
        function onNavigateRequested(p, sub) { if (p === "library" && sub) page.tab = sub }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // --- Список сборок ----------------------------------------------------------------
        Rectangle {
            Layout.preferredWidth: 280
            Layout.fillHeight: true
            color: NxTheme.surface1
            topLeftRadius: NxTheme.rButton

            Column {
                id: listTop
                x: 12
                y: 16
                width: parent.width - 24
                spacing: 12
                Item {
                    width: parent.width
                    height: 22
                    NxText { x: 4; text: I18n.t("q.builds"); variant: "h2" }
                    NxText { anchors.right: parent.right; anchors.rightMargin: 4; text: Library.total; variant: "mono"; muted: true }
                }
                NxTextField {
                    id: search
                    width: parent.width
                    iconName: "search"
                    placeholder: I18n.t("q.find_build")
                    onEdited: Library.setQuery(text)
                }
            }

            ListView {
                id: list
                anchors.top: listTop.bottom
                anchors.topMargin: 12
                anchors.bottom: foot.top
                x: 8
                width: parent.width - 16
                clip: true
                spacing: 2
                model: Library.model
                boundsBehavior: Flickable.StopAtBounds
                C.ScrollBar.vertical: NxScrollBar {}
                delegate: NxInstanceRow {
                    required property var model
                    width: list.width
                    name: model.title
                    loader: model.loader
                    version: model.version
                    playtime: model.playtime
                    state_: model.state
                    cover: model.cover
                    selected: model.name === Library.selected
                    onClicked: Library.select(model.name)
                    onContextMenu: (mx, my) => { buildMenu.target = model.name; buildMenu.openAt(this) }
                }
                NxText {
                    visible: Library.loaded && list.count === 0 && Library.total > 0
                    x: 10; y: 8
                    text: I18n.t("common.nothing_found")
                    muted: true
                }
            }

            Item {
                id: foot
                anchors.bottom: parent.bottom
                width: parent.width
                height: 52
                NxButton {
                    x: 12
                    width: parent.width - 24
                    anchors.verticalCenter: parent.verticalCenter
                    iconName: "plus"
                    text: I18n.t("q.new_build")
                    onClicked: Shell.navigate("wizard")
                }
            }
        }

        // --- Выбранная сборка ---------------------------------------------------------------
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            NxEmptyState {
                visible: Library.loaded && Library.total === 0
                illustration: "library"
                text: I18n.t("q.empty_library")
                NxButton { variant: "primary"; iconName: "plus"; text: I18n.t("q.new_build"); onClicked: Shell.navigate("wizard") }
                NxButton { variant: "ghost"; text: I18n.t("q.import_other"); onClicked: Shell.navigate("wizard", "import") }
            }

            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                visible: page.hasBuild

                // Герой: фон-скриншот, имя, метаданные, «Играть»
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 288
                    clip: true

                    Image {
                        id: heroBg
                        anchors.fill: parent
                        readonly property bool real: !!page.cur.background
                        source: real ? page.cur.background : (page.hasBuild ? "image://nx/scene/" + page.cur.palette + "/" + (page.cur.seed * 3 + 1) + "/116/36" : "")
                        fillMode: Image.PreserveAspectCrop
                        smooth: real
                        asynchronous: real
                        sourceSize: real ? Qt.size(1600, 900) : Qt.size(0, 0)
                        opacity: status === Image.Ready ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: NxTheme.base } }
                    }
                    Rectangle {
                        anchors.fill: parent
                        gradient: Gradient {
                            GradientStop { position: 0.30; color: Qt.rgba(NxTheme.bg.r, NxTheme.bg.g, NxTheme.bg.b, 0) }
                            GradientStop { position: 0.68; color: Qt.rgba(NxTheme.bg.r, NxTheme.bg.g, NxTheme.bg.b, 0.7) }
                            GradientStop { position: 1.00; color: NxTheme.bg }
                        }
                    }

                    // Справа — персонаж активного аккаунта (кнопки папки и меню остаются в углу)
                    AccountShowcase {
                        objectName: "accountShowcase"
                        z: 1
                        visible: parent.width >= 820
                        anchors.right: parent.right
                        anchors.rightMargin: 110
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 12
                        width: implicitWidth
                        height: implicitHeight
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 32
                        anchors.rightMargin: 32
                        anchors.bottomMargin: 24
                        spacing: 12

                        NxText {
                            width: parent.width
                            text: page.cur.title || ""
                            variant: "display"
                            style: Text.Normal
                        }
                        Row {
                            spacing: 8
                            opacity: 0.82
                            NxLoaderMark { loader: page.cur.loader || "vanilla"; anchors.verticalCenter: parent.verticalCenter }
                            NxText {
                                text: (page.loaderNames[page.cur.loader] || "") + " " + (page.cur.version || "")
                                    + (page.cur.optifine ? " + OptiFine" : "")
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            NxText { visible: Build.mods.length > 0; text: "·"; muted: true; anchors.verticalCenter: parent.verticalCenter }
                            NxText {
                                visible: Build.mods.length > 0
                                text: I18n.count(Build.mods.length, "q.mods")
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            NxText { text: "·"; muted: true; anchors.verticalCenter: parent.verticalCenter }
                            NxText {
                                text: page.cur.lastPlayedRaw ? page.cur.playtime : I18n.t("q.never_played")
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        Item {
                            width: parent.width
                            height: 48
                            NxPlayButton {
                                id: playBtn
                                y: 4
                                state_: page.cur.state || "ready"
                                progress: page.cur.progress || 0
                                startedAt: page.cur.startedAt || 0
                                onPlay: Library.play(page.cur.name)
                                onInstall: Library.install(page.cur.name)
                                onStop: Library.stop(page.cur.name)
                                onMore: anchor => playMenu.openAt(anchor)
                            }
                            Row {
                                anchors.right: parent.right
                                anchors.verticalCenter: playBtn.verticalCenter
                                spacing: 4
                                NxIconButton { iconName: "folder"; tip: I18n.t("q.open_folder"); onClicked: Shell.openPath(page.cur.gameDir) }
                                NxIconButton {
                                    id: kebab
                                    iconName: "kebab"
                                    tip: I18n.t("q.more")
                                    on: buildMenu.opened
                                    onClicked: { buildMenu.target = page.cur.name; buildMenu.openAt(kebab) }
                                }
                            }
                        }
                    }
                }

                // Вкладки
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: NxTheme.line }
                    NxTabBar {
                        x: 20
                        height: parent.height
                        value: page.tab
                        model: [
                            { value: "overview", label: I18n.t("q.tab_overview") },
                            { value: "mods", label: I18n.t("q.tab_mods"), count: Build.mods.length },
                            { value: "resources", label: I18n.t("q.tab_resources") },
                            { value: "worlds", label: I18n.t("q.tab_worlds"), count: Build.worlds.length },
                            { value: "shots", label: I18n.t("q.tab_shots"), count: Build.screenshots.length },
                            { value: "doctor", label: I18n.t("q.tab_doctor") },
                            { value: "settings", label: I18n.t("q.tab_settings") }
                        ]
                        onActivated: value => page.tab = value
                    }
                }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: ["overview", "mods", "resources", "worlds", "shots", "doctor", "settings"].indexOf(page.tab)
                    OverviewTab { onOpenTab: t => page.tab = t }
                    ContentTab { contentType: "mod"; onOptifineRequested: optiSheet.open(); onTurboRequested: turboDialog.open() }
                    ResourcesTab {}
                    WorldsTab {}
                    ShotsTab {}
                    DoctorTab {}
                    BuildSettingsTab { onAskDelete: deleteDialog.open() }
                }
            }
        }
    }

    // --- Меню и диалоги -------------------------------------------------------------------------
    NxMenu {
        id: playMenu
        items: [
            { text: I18n.t("q.join_server"), icon: "globe", action: "server" },
            { text: I18n.t("q.play_friends"), icon: "users", action: "friends" },
            { text: I18n.t("q.repair"), icon: "wrench", action: "repair" }
        ]
        onTriggered: action => {
            if (action === "server") serverPrompt.open()
            else if (action === "friends") Library.playWithFriends(page.cur.name)
            else if (action === "repair") Library.repair(page.cur.name)
        }
    }

    NxMenu {
        id: buildMenu
        objectName: "buildMenu"
        property string target: ""
        alignRight: true
        items: [
            { text: I18n.t("q.rename"), icon: "pencil", action: "rename" },
            { text: I18n.t("q.duplicate"), icon: "copy", action: "duplicate" },
            { text: I18n.t("q.export"), icon: "archive", action: "export" },
            { text: I18n.t("q.open_folder"), icon: "folder", action: "folder" },
            { text: I18n.t("q.background_pick"), icon: "image", action: "background" },
            { text: I18n.t("q.repair"), icon: "wrench", action: "repair" },
            { text: "OptiFine…", icon: "zap", action: "optifine" },
            { separator: true },
            { text: I18n.t("q.delete_build"), icon: "trash", danger: true, action: "delete" }
        ]
        onTriggered: action => {
            Library.select(target)
            if (action === "rename") renamePrompt.open()
            else if (action === "duplicate") Library.duplicate(target)
            else if (action === "export") exportDialog.open()
            else if (action === "folder") Shell.openPath(page.cur.gameDir)
            else if (action === "repair") Library.repair(target)
            else if (action === "optifine") optiSheet.open()
            else if (action === "background") backgroundDialog.open()
            else if (action === "delete") deleteDialog.open()
        }
    }

    PromptDialog {
        id: renamePrompt
        title: I18n.t("q.rename_build")
        label: I18n.t("q.name")
        value: page.cur.title || ""
        onAccepted: text => Library.rename(page.cur.name, text)
    }

    PromptDialog {
        id: serverPrompt
        title: I18n.t("q.join_server_title")
        label: I18n.t("q.server_address")
        placeholder: "play.example.com:25565"
        acceptText: I18n.t("q.play")
        mono: true
        onAccepted: text => Library.play(page.cur.name, text)
    }

    OptiFineSheet { id: optiSheet }

    FileDialog {
        id: backgroundDialog
        fileMode: FileDialog.OpenFile
        nameFilters: [I18n.t("q.images") + " (*.png *.jpg *.jpeg *.bmp *.webp *.gif)"]
        onAccepted: Library.setBackground(page.cur.name, selectedFile.toString())
    }

    FileDialog {
        id: exportDialog
        fileMode: FileDialog.SaveFile
        currentFile: "file:///" + (page.cur.name || "build") + ".zip"
        nameFilters: [I18n.t("q.export_zip") + " (*.zip)", I18n.t("q.export_mrpack") + " (*.mrpack)"]
        onAccepted: Library.export(page.cur.name, selectedFile.toString())
    }

    NxModal {
        id: turboDialog
        readonly property var plan: Build.turbo
        title: I18n.t("q.turbo_title")
        acceptText: I18n.t("q.turbo_apply")
        acceptEnabled: plan.state === "ready"
        onOpened: Build.loadTurbo()
        onAccepted: { Build.applyTurbo(jvm.checked); close() }
        NxSpinner { visible: turboDialog.plan.state === "loading"; color: NxTheme.muted }
        NxText {
            visible: turboDialog.plan.state === "error"
            width: turboDialog.fieldWidth
            text: turboDialog.plan.error || ""
            color: NxTheme.danger
            wrapMode: Text.Wrap
            elide: Text.ElideNone
        }
        NxText {
            visible: turboDialog.plan.state === "ready"
            width: turboDialog.fieldWidth
            text: (turboDialog.plan.mods || []).length ? I18n.t("q.turbo_will_install") : I18n.t("q.turbo_nothing")
            muted: true
            wrapMode: Text.Wrap
            elide: Text.ElideNone
        }
        Flow {
            visible: turboDialog.plan.state === "ready"
            width: turboDialog.fieldWidth
            spacing: 6
            Repeater { model: turboDialog.plan.mods || []; delegate: NxChip { required property string modelData; text: modelData; mono: true } }
        }
        Row {
            visible: turboDialog.plan.state === "ready"
            spacing: 10
            NxCheckbox { id: jvm; checked: true; anchors.verticalCenter: parent.verticalCenter }
            NxText { text: I18n.tf("q.turbo_jvm", { mem: turboDialog.plan.memory || "" }); anchors.verticalCenter: parent.verticalCenter }
        }
        NxText { width: turboDialog.fieldWidth; text: I18n.t("q.turbo_snapshot"); muted: true; font.pixelSize: 12; lineHeight: 16; wrapMode: Text.Wrap; elide: Text.ElideNone }
    }

    NxDialog {
        id: deleteDialog
        objectName: "deleteDialog"
        title: I18n.tf("q.delete_title", { name: page.cur.title || "" })
        text: I18n.t("q.delete_text")
        onAccepted: Library.remove(page.cur.name)
    }
}
