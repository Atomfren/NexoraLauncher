// Каталог Modrinth: тип, поиск, «Ставлю в», фильтры слева, результаты, карточка проекта справа
import QtQuick
import QtQuick.Controls as C
import Nexora

Item {
    id: page
    readonly property bool narrow: width < 860
    readonly property var loaderNames: ({ fabric: "Fabric", quilt: "Quilt", forge: "Forge", neoforge: "NeoForge" })

    Connections {
        target: Shell
        function onNavigateRequested(p, sub) {
            if (p !== "catalog") return
            Catalog.start()
            if (sub) Catalog.setType(sub)
        }
    }

    // --- Верхняя строка ---
    Item {
        id: top
        x: 24
        y: 8
        width: parent.width - 48
        height: 48
        NxSegmentedControl {
            id: types
            anchors.verticalCenter: parent.verticalCenter
            value: Catalog.type
            model: [
                { value: "mod", label: I18n.t("q.type_mods") }, { value: "modpack", label: I18n.t("q.type_packs") },
                { value: "resourcepack", label: I18n.t("q.resourcepacks") }, { value: "shader", label: I18n.t("q.shaders") },
                { value: "plugin", label: I18n.t("q.type_plugins") }
            ]
            onActivated: v => Catalog.setType(v)
        }
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            NxTextField {
                id: search
                width: page.narrow ? 200 : 280
                iconName: "search"
                placeholder: I18n.t("q.search_catalog")
                onEdited: Catalog.setQuery(text)
            }
            NxDropdown {
                visible: Catalog.type !== "modpack"
                width: Math.min(300, implicitWidth)
                label: I18n.t("q.install_into")
                alignRight: true
                model: Catalog.targets
                value: Catalog.target
                placeholder: Catalog.type === "plugin" ? I18n.t("q.no_own_server") : I18n.t("q.no_builds")
                onActivated: v => Catalog.setFilter("target", v)
            }
        }
    }

    // --- Фильтры ---
    Flickable {
        id: rail
        visible: !page.narrow
        x: 24
        anchors.top: top.bottom
        anchors.topMargin: 16
        anchors.bottom: parent.bottom
        width: 208
        clip: true
        contentHeight: railCol.implicitHeight + 24
        boundsBehavior: Flickable.StopAtBounds
        Column {
            id: railCol
            width: parent.width
            spacing: 24
            Column {
                visible: Catalog.type !== "plugin"
                width: parent.width
                spacing: 8
                NxText { text: I18n.t("q.col_version"); variant: "caption" }
                NxTextField {
                    width: parent.width
                    mono: true
                    text: Catalog.gameVersion
                    placeholder: I18n.t("q.any_version")
                    input.onEditingFinished: if (text.trim() !== Catalog.gameVersion) Catalog.setFilter("version", text.trim())
                }
            }
            Column {
                visible: Catalog.type === "mod" || Catalog.type === "modpack"
                width: parent.width
                spacing: 2
                NxText { text: I18n.t("q.loader"); variant: "caption"; bottomPadding: 6 }
                Repeater {
                    model: ["fabric", "quilt", "forge", "neoforge"]
                    delegate: FilterRow {
                        required property string modelData
                        text: page.loaderNames[modelData]
                        loader: modelData
                        checked: Catalog.loader === modelData
                        onToggled: Catalog.setFilter("loader", checked ? "" : modelData)
                    }
                }
            }
            Column {
                width: parent.width
                spacing: 2
                NxText { text: I18n.t("q.categories"); variant: "caption"; bottomPadding: 6 }
                Repeater {
                    model: Catalog.categories
                    delegate: FilterRow {
                        required property var modelData
                        text: modelData.label
                        checked: Catalog.category === modelData.value
                        onToggled: Catalog.setFilter("category", modelData.value)
                    }
                }
            }
        }
    }

    // --- Результаты ---
    ListView {
        id: list
        anchors.left: page.narrow ? parent.left : rail.right
        anchors.leftMargin: 24
        anchors.right: parent.right
        anchors.rightMargin: 24
        anchors.top: top.bottom
        anchors.topMargin: 16
        anchors.bottom: parent.bottom
        clip: true
        spacing: 2
        model: Catalog.results
        boundsBehavior: Flickable.StopAtBounds
        C.ScrollBar.vertical: NxScrollBar {}
        onAtYEndChanged: if (atYEnd && count > 0) Catalog.loadMore()

        header: Item {
            width: list.width
            height: 36
            NxText {
                anchors.verticalCenter: parent.verticalCenter
                text: Catalog.loading && Catalog.results.length === 0 ? I18n.t("common.loading") : I18n.tf("q.found_n", { n: Catalog.total })
                muted: true
            }
            NxDropdown {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                alignRight: true
                value: Catalog.sort
                model: [{ value: "relevance", label: I18n.t("q.sort_relevance") }, { value: "downloads", label: I18n.t("q.sort_downloads") },
                        { value: "updated", label: I18n.t("q.sort_updated") }, { value: "newest", label: I18n.t("q.sort_newest") }]
                onActivated: v => Catalog.setFilter("sort", v)
            }
        }

        delegate: Rectangle {
            id: row
            required property var modelData
            width: list.width
            height: 68
            radius: NxTheme.rButton
            color: hov.hovered ? NxTheme.fill1 : "transparent"
            HoverHandler { id: hov; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: { Catalog.openProject(row.modelData.id); drawer.open() } }

            NxCover { id: ic; x: 8; width: 40; height: 40; radius: NxTheme.rButton; anchors.verticalCenter: parent.verticalCenter; source: row.modelData.icon }
            Column {
                anchors.left: ic.right; anchors.leftMargin: 12
                anchors.right: num.left; anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Row {
                    width: parent.width
                    spacing: 8
                    NxText { id: ttl; text: row.modelData.title; variant: "strong"; width: Math.min(implicitWidth, parent.width * 0.6) }
                    NxText { text: row.modelData.author; muted: true; width: parent.width - ttl.width - 8 }
                }
                NxText { width: parent.width; text: row.modelData.description; muted: true }
            }
            NxText {
                id: num
                visible: list.width > 640
                width: visible ? 76 : 0
                anchors.right: st.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                horizontalAlignment: Text.AlignRight
                text: row.modelData.downloads
                variant: "mono"
                muted: true
            }
            InstallButton {
                id: st
                anchors.right: parent.right
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                state_: row.modelData.state
                progress: row.modelData.progress
                onInstall: Catalog.install(row.modelData.id)
            }
        }

        footer: Item {
            width: list.width
            height: 64
            NxSpinner { visible: Catalog.loading; anchors.centerIn: parent; color: NxTheme.muted }
        }

        NxEmptyState {
            visible: !Catalog.loading && Catalog.results.length === 0
            y: 36
            leftPadding: 0
            compact: true
            illustration: "search"
            text: Catalog.error !== "" ? I18n.t("q.catalog_offline") : I18n.tf("q.nothing_for", { q: Catalog.query })
            NxButton { visible: Catalog.error !== ""; iconName: "refresh"; text: I18n.t("q.retry"); onClicked: Catalog.search() }
            NxButton { visible: Catalog.error === "" && Catalog.query !== ""; text: I18n.t("q.reset_search"); onClicked: { search.text = ""; Catalog.setQuery("") } }
        }
    }

    // --- Карточка проекта ---
    NxDrawer {
        id: drawer
        readonly property var p: Catalog.project
        title: p.title || ""
        subtitle: p.author || ""
        iconSource: p.icon || ""
        onClosed: Catalog.closeProject()

        NxText {
            width: drawer.bodyWidth
            text: drawer.p.description || ""
            wrapMode: Text.Wrap
            elide: Text.ElideNone
            lineHeightMode: Text.ProportionalHeight
            lineHeight: 1.25
            bottomPadding: 20
        }
        Grid {
            columns: 2
            columnSpacing: 16
            rowSpacing: 8
            bottomPadding: 24
            NxText { text: I18n.t("q.downloads_count"); muted: true }
            NxText { text: drawer.p.downloads || "—"; variant: "mono" }
            NxText { text: I18n.t("q.followers"); muted: true }
            NxText { text: drawer.p.followers || "—"; variant: "mono" }
            NxText { text: "Minecraft"; muted: true }
            Flow {
                width: drawer.bodyWidth - 140
                spacing: 6
                Repeater { model: drawer.p.allVersions || drawer.p.versions || []; delegate: NxChip { required property string modelData; text: modelData; mono: true } }
            }
            NxText { text: I18n.t("q.loader"); muted: true }
            Flow {
                width: drawer.bodyWidth - 140
                spacing: 12
                Repeater {
                    model: drawer.p.allLoaders || drawer.p.loaders || []
                    delegate: NxLoaderBadge {
                        required property string modelData
                        loader: ["vanilla", "fabric", "quilt", "forge", "neoforge", "paper", "purpur"].indexOf(modelData) >= 0 ? modelData : "vanilla"
                        text: modelData
                        color: NxTheme.text
                    }
                }
            }
        }
        NxSectionHeader { width: drawer.bodyWidth; text: I18n.t("q.versions") }
        NxSpinner { visible: !!drawer.p.loadingDetails; color: NxTheme.muted }
        Repeater {
            model: Catalog.projectVersions
            delegate: Item {
                required property var modelData
                width: drawer.bodyWidth
                height: 32
                NxText { x: 8; width: 120; anchors.verticalCenter: parent.verticalCenter; text: parent.modelData.number; variant: "mono" }
                NxText { x: 136; width: parent.width - 260; anchors.verticalCenter: parent.verticalCenter; text: parent.modelData.mc; variant: "mono"; muted: true }
                NxChip {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: parent.modelData.type
                    kind: parent.modelData.type === "release" ? "" : "warn"
                }
            }
        }
        Item { width: 1; height: 16; visible: (drawer.p.gallery || []).length > 0 }
        NxSectionHeader { visible: (drawer.p.gallery || []).length > 0; width: drawer.bodyWidth; text: I18n.t("q.tab_shots") }
        Grid {
            columns: 2
            spacing: 8
            Repeater {
                model: drawer.p.gallery || []
                delegate: NxCover {
                    required property string modelData
                    width: (drawer.bodyWidth - 8) / 2
                    height: Math.round(width * 9 / 16)
                    radius: NxTheme.rButton
                    source: modelData
                }
            }
        }

        footer: NxButton {
            x: 24
            y: 16
            width: parent.width - 48
            readonly property string st: drawer.p.state || "none"
            variant: st === "none" ? "primary" : "secondary"
            enabled: st === "none"
            loading: st === "busy"
            iconName: st === "installed" ? "check" : "download"
            text: st === "busy" ? I18n.tf("q.installing_pct", { pct: Math.round(drawer.p.progress || 0) })
                : st === "installed" ? I18n.t("q.installed_short")
                : Catalog.type === "modpack" ? I18n.t("q.install_as_build")
                : I18n.tf("q.install_into_name", { name: Catalog.target })
            onClicked: Catalog.install(drawer.p.id)
        }
    }

    // Строка фильтра с флажком
    component FilterRow: Rectangle {
        id: fr
        property string text
        property string loader: ""
        property bool checked: false
        signal toggled()
        width: parent ? parent.width : 200
        height: 28
        radius: 4
        color: fh.hovered ? NxTheme.fill1 : "transparent"
        HoverHandler { id: fh; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: fr.toggled() }
        NxCheckbox { x: 4; anchors.verticalCenter: parent.verticalCenter; checked: fr.checked; onClicked: fr.toggled() }
        Row {
            x: 30
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            NxLoaderMark { visible: fr.loader !== ""; loader: fr.loader || "vanilla"; size: 14; anchors.verticalCenter: parent.verticalCenter }
            NxText { text: fr.text; anchors.verticalCenter: parent.verticalCenter }
        }
    }

    // Кнопка установки в строке: «+», кольцо прогресса, галочка
    component InstallButton: Item {
        id: ib
        property string state_: "none"
        property real progress: 0
        signal install()
        width: 32
        height: 32
        Rectangle {
            anchors.fill: parent
            radius: 16
            visible: ib.state_ === "none"
            color: ia.containsMouse ? NxTheme.fill3 : NxTheme.fill1
            NxIcon { anchors.centerIn: parent; name: "plus"; size: 18; color: NxTheme.text }
            MouseArea { id: ia; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: ib.install() }
        }
        NxProgressRing { visible: ib.state_ === "busy"; anchors.centerIn: parent; size: 24; value: Math.max(3, ib.progress) }
        NxIcon { visible: ib.state_ === "installed"; anchors.centerIn: parent; name: "check"; size: 18; color: NxTheme.success }
    }
}
