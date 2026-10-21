// Главное окно Nexora: боковая панель, верхняя панель, страницы, всплывающие слои
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import Nexora
import "pages"

Window {
    id: win
    width: 1280
    height: 800
    minimumWidth: 1000
    minimumHeight: 660
    visible: true
    title: "Nexora"
    color: NxTheme.bg
    flags: Qt.Window | Qt.FramelessWindowHint

    function toggleMaximized() {
        if (win.visibility === Window.Maximized) win.showNormal()
        else win.showMaximized()
    }

    Component.onCompleted: {
        NxTheme.dark = Qt.binding(() => Shell.dark)
        NxTheme.fontUi = Shell.fontUi
        NxTheme.fontMono = Shell.fontMono
    }

    Connections {
        target: Shell
        function onToastRequested(text, kind) { toasts.show(text, kind) }
        function onAddAccountRequested() { addAccount.open() }
    }
    Connections {
        target: Library
        function onAccountRequired(message) { addAccount.reason = message; addAccount.open() }
    }

    Shortcut { sequence: "Ctrl+K"; onActivated: palette.open() }
    Shortcut { sequence: "Ctrl+N"; onActivated: Shell.navigate("wizard") }
    Shortcut { sequence: "F5"; onActivated: { Library.refresh(); Build.reload() } }

    // Боковая панель слева/справа (вертикальная) или сверху/снизу (горизонтальная полоса).
    // Контент привязан к ней якорями: ширина анимируется, и соседняя колонка двигается вместе с ней.
    Item {
        id: frame
        anchors.fill: parent
        readonly property string side: Shell.sidebarPosition
        readonly property bool vertical: side === "left" || side === "right"

        NxSidebar {
            id: sidebar
            objectName: "sidebar"
            z: 1
            horizontal: !frame.vertical
            x: frame.side === "right" ? frame.width - width : 0
            y: frame.side === "top" ? topBar.height : frame.side === "bottom" ? frame.height - height : 0
            width: frame.vertical ? implicitWidth : frame.width
            height: frame.vertical ? frame.height : implicitHeight
            page: Shell.page
            wide: Shell.sidebarWide
            onNavigate: page => Shell.navigate(page)
            onToggleWide: Shell.toggleSidebar()
        }

        ColumnLayout {
            objectName: "content"
            x: frame.side === "left" ? sidebar.width : 0
            width: frame.width - (frame.vertical ? sidebar.width : 0)
            height: frame.height
            spacing: 0

            NxTopBar {
                id: topBar
                Layout.fillWidth: true
                window: win
                onPaletteRequested: palette.open()
                onDownloadsClicked: anchor => {
                    const p = anchor.mapToItem(downloads.parent, 0, 0)
                    downloads.x = p.x + anchor.width - downloads.width
                    downloads.y = p.y + anchor.height + 6
                    downloads.open()
                }
            }
            // Место под горизонтальную полосу сверху
            Item { Layout.preferredHeight: frame.side === "top" ? sidebar.height : 0; Layout.fillWidth: true }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: ["library", "wizard", "catalog", "network", "settings"].indexOf(Shell.page)

                LibraryPage { id: libraryPage }
                WizardPage {}
                CatalogPage {}
                NetworkPage {}
                SettingsPage {}
            }
            Item { Layout.preferredHeight: frame.side === "bottom" ? sidebar.height : 0; Layout.fillWidth: true }
        }
    }

    // Файлы, брошенные на окно: .jar — в моды выбранной сборки, .zip/.mrpack — импорт
    DropArea {
        id: drop
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: drop => { if (drop.hasUrls) Library.dropFiles(drop.urls) }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 12
            visible: drop.containsDrag
            radius: NxTheme.rButton
            color: Qt.rgba(NxTheme.bg.r, NxTheme.bg.g, NxTheme.bg.b, 0.85)
            border.color: NxTheme.accent
            border.width: 2
            Column {
                anchors.centerIn: parent
                spacing: 8
                NxIcon { anchors.horizontalCenter: parent.horizontalCenter; name: "download"; size: 32; color: NxTheme.accent }
                NxText { anchors.horizontalCenter: parent.horizontalCenter; text: I18n.t("q.drop_here"); variant: "h2" }
                NxText { anchors.horizontalCenter: parent.horizontalCenter; text: I18n.t("q.drop_hint"); muted: true }
            }
        }
    }

    // --- Всплывающие слои -------------------------------------------------------------------
    NxDownloadsPopover { id: downloads; objectName: "downloads"; parent: win.contentItem }
    NxAccountPopover {
        id: accountPop
        objectName: "accountPop"
        parent: win.contentItem
        onAddAccount: addAccount.open()
        onManage: Shell.navigate("settings", "accounts")
    }
    AddAccountDialog { id: addAccount }

    NxCommandPalette {
        id: palette
        objectName: "palette"
        onAboutToShow: items = buildItems()
        function buildItems() {
            const out = []
            for (const b of Library.entries())
                out.push({ group: I18n.t("q.palette_builds"), icon: "library", text: b.title, hint: b.version, action: "select", arg: b.name })
            const cur = Library.current
            out.push({ group: I18n.t("q.palette_actions"), icon: "plus", text: I18n.t("q.new_build"), hint: "Ctrl N", action: "nav", arg: "wizard" })
            if (cur.name)
                out.push({ group: I18n.t("q.palette_actions"), icon: "play", text: I18n.tf("q.palette_play", { name: cur.title }), action: "play", arg: cur.name })
            out.push({ group: I18n.t("q.palette_actions"), icon: "compass", text: I18n.t("q.palette_catalog"), action: "nav", arg: "catalog" })
            out.push({ group: I18n.t("q.palette_actions"), icon: "package", text: I18n.t("q.palette_packs"), action: "catalog", arg: "modpack" })
            out.push({ group: I18n.t("q.palette_actions"), icon: "download", text: I18n.t("q.check_updates_app"), action: "updates", arg: "" })
            out.push({ group: I18n.t("q.palette_actions"), icon: "globe", text: I18n.t("q.palette_network"), action: "nav", arg: "network" })
            out.push({ group: I18n.t("q.palette_settings"), icon: "sliders", text: I18n.t("q.nav_settings"), action: "nav", arg: "settings" })
            out.push({ group: I18n.t("q.palette_settings"), icon: "user", text: I18n.t("q.add_account"), action: "account", arg: "" })
            out.push({ group: I18n.t("q.palette_settings"), icon: "layers", text: Shell.dark ? I18n.t("q.theme_light") : I18n.t("q.theme_dark"), action: "theme", arg: "" })
            return out
        }
        onRun: (action, arg) => {
            if (action === "select") { Shell.navigate("library"); Library.select(arg) }
            else if (action === "play") Library.play(arg)
            else if (action === "nav") Shell.navigate(arg)
            else if (action === "account") addAccount.open()
            else if (action === "theme") Shell.setDark(!Shell.dark)
            else if (action === "catalog") Shell.navigate("catalog", arg)
            else if (action === "updates") Shell.navigate("settings", "updates")
        }
    }

    NxToastHost {
        id: toasts
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 16
        z: 100
    }

    // --- Изменение размера окна без рамки ------------------------------------------------------
    Repeater {
        model: [
            { e: Qt.LeftEdge, x: 0, y: 6, w: 6, h: -12, c: Qt.SizeHorCursor },
            { e: Qt.RightEdge, x: -6, y: 6, w: 6, h: -12, c: Qt.SizeHorCursor },
            { e: Qt.TopEdge, x: 6, y: 0, w: -12, h: 4, c: Qt.SizeVerCursor },
            { e: Qt.BottomEdge, x: 6, y: -6, w: -12, h: 6, c: Qt.SizeVerCursor },
            { e: Qt.TopEdge | Qt.LeftEdge, x: 0, y: 0, w: 8, h: 8, c: Qt.SizeFDiagCursor },
            { e: Qt.TopEdge | Qt.RightEdge, x: -8, y: 0, w: 8, h: 8, c: Qt.SizeBDiagCursor },
            { e: Qt.BottomEdge | Qt.LeftEdge, x: 0, y: -8, w: 8, h: 8, c: Qt.SizeBDiagCursor },
            { e: Qt.BottomEdge | Qt.RightEdge, x: -8, y: -8, w: 8, h: 8, c: Qt.SizeFDiagCursor }
        ]
        delegate: MouseArea {
            required property var modelData
            enabled: win.visibility !== Window.Maximized
            x: modelData.x < 0 ? win.width + modelData.x : modelData.x
            y: modelData.y < 0 ? win.height + modelData.y : modelData.y
            width: modelData.w < 0 ? win.width + modelData.w : modelData.w
            height: modelData.h < 0 ? win.height + modelData.h : modelData.h
            z: 1000
            cursorShape: modelData.c
            onPressed: win.startSystemResize(modelData.e)
        }
    }
}
