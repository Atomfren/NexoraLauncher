// Мастер «Новая сборка» на всю страницу: тип → параметры → готово
import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import Nexora

Item {
    id: page
    property int step: 1
    property string kind: "mods"          // vanilla | mods | pack | import
    property string name: ""
    property bool nameTouched: false
    property string mc: ""
    property bool snapshots: false
    property string loader: "fabric"
    property string loaderVersion: ""
    property var pack: null
    property var picked: ({})
    readonly property var loaderNames: ({ vanilla: "Vanilla", fabric: "Fabric", quilt: "Quilt", forge: "Forge", neoforge: "NeoForge" })
    readonly property string effectiveLoader: kind === "vanilla" ? "vanilla" : loader
    readonly property string nameError: Wizard.nameError(name)
    readonly property var pickedPaths: Object.keys(picked).filter(k => picked[k])
    readonly property bool canNext: step === 1
        || (step === 2 && (kind === "vanilla" || kind === "mods") && !nameError && mc !== "" && (kind === "vanilla" || loaderVersion !== "" || Wizard.loaderLoading === false))
        || (step === 2 && kind === "pack" && pack !== null)
        || (step === 2 && kind === "import" && pickedPaths.length > 0)

    function reset() {
        step = 1; name = ""; nameTouched = false; pack = null; picked = ({})
    }
    function suggestName() {
        if (nameTouched) return
        name = kind === "vanilla" ? (mc ? "Ванилла " + mc : "") : (mc ? loaderNames[loader] + " " + mc : "")
    }
    function next() {
        if (step === 1) {
            step = 2
            if (kind === "vanilla" || kind === "mods") Wizard.loadVersions()
            if (kind === "pack") Wizard.searchPacks("")
            if (kind === "import") Wizard.loadForeign()
        } else if (step === 2) {
            step = 3
        }
    }
    function create() {
        if (kind === "vanilla" || kind === "mods")
            Wizard.create(name, mc, effectiveLoader, kind === "vanilla" ? "" : loaderVersion)
        else if (kind === "pack")
            Wizard.installPack(pack.id, pack.title)
        else
            Wizard.importForeign(pickedPaths)
    }

    Connections {
        target: Shell
        function onNavigateRequested(p, sub) {
            if (p !== "wizard") return
            page.reset()
            if (sub === "import") { page.kind = "import"; page.next() }
        }
    }
    Connections {
        target: Wizard
        function onCreated(name) { page.reset(); Shell.navigate("library", "overview") }
        function onVersionsChanged() {
            if (!page.mc && Wizard.versions.length) {
                const first = Wizard.versionOptions(false)[0]
                if (first) { page.mc = first.value; page.suggestName(); Wizard.loadLoaderVersions(page.effectiveLoader, page.mc) }
            }
        }
        function onLoaderVersionsChanged() { page.loaderVersion = Wizard.loaderVersions.length ? Wizard.loaderVersions[0].value : "" }
    }
    onLoaderChanged: { suggestName(); Wizard.loadLoaderVersions(effectiveLoader, mc) }
    onKindChanged: suggestName()

    // --- Шаги слева ---
    Column {
        id: rail
        x: 32
        y: 32
        width: 184
        spacing: 4
        NxText { text: I18n.t("q.new_build"); variant: "h1"; bottomPadding: 20 }
        Repeater {
            model: [I18n.t("q.step_type"), I18n.t("q.step_params"), I18n.t("q.step_done")]
            delegate: Row {
                required property string modelData
                required property int index
                readonly property int n: index + 1
                height: 40
                spacing: 12
                Rectangle {
                    width: 22; height: 22; radius: 11
                    anchors.verticalCenter: parent.verticalCenter
                    color: page.step === parent.n ? NxTheme.accent : page.step > parent.n ? NxTheme.okBg : NxTheme.surface2
                    NxText {
                        visible: page.step <= parent.parent.n
                        anchors.centerIn: parent
                        text: parent.parent.n
                        variant: "monoStrong"; font.pixelSize: 11; lineHeight: 16
                        color: page.step === parent.parent.n ? NxTheme.onAccent : NxTheme.muted
                    }
                    NxIcon { visible: page.step > parent.parent.n; anchors.centerIn: parent; name: "check"; size: 12; color: NxTheme.success }
                }
                NxText {
                    text: parent.modelData
                    variant: "strong"
                    color: page.step === parent.n ? NxTheme.text : NxTheme.muted
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }

    // --- Тело ---
    Flickable {
        id: body
        anchors.left: rail.right
        anchors.leftMargin: 24
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: foot.top
        clip: true
        contentHeight: content.implicitHeight + 64
        boundsBehavior: Flickable.StopAtBounds
        C.ScrollBar.vertical: NxScrollBar {}

        Column {
            id: content
            y: 32
            width: Math.min(body.width - 48, 760)
            spacing: 16

            // Шаг 1: что создаём
            NxText { visible: page.step === 1; text: I18n.t("q.what_create"); variant: "h2" }
            Grid {
                visible: page.step === 1
                columns: 2
                spacing: 16
                Repeater {
                    model: [
                        { k: "vanilla", t: I18n.t("q.kind_vanilla"), pal: "day", seed: 5 },
                        { k: "mods", t: I18n.t("q.kind_mods"), pal: "dusk", seed: 11 },
                        { k: "pack", t: I18n.t("q.kind_pack"), pal: "sky", seed: 41 },
                        { k: "import", t: I18n.t("q.kind_import"), pal: "cave", seed: 23 }
                    ]
                    delegate: Rectangle {
                        id: tile
                        required property var modelData
                        readonly property bool active: page.kind === modelData.k
                        width: (content.width - 16) / 2
                        height: 156
                        radius: NxTheme.rButton
                        color: active || hov.hovered ? NxTheme.surface2 : NxTheme.surface1
                        border.width: active ? 2 : 0
                        border.color: NxTheme.accent
                        HoverHandler { id: hov; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: page.kind = tile.modelData.k; onDoubleTapped: { page.kind = tile.modelData.k; page.next() } }
                        Column {
                            x: 20; y: 20
                            width: parent.width - 40
                            spacing: 16
                            NxCover { width: 96; height: 48; radius: NxTheme.rButton; source: "image://nx/scene/" + tile.modelData.pal + "/" + tile.modelData.seed + "/24/12" }
                            NxText { width: parent.width; text: tile.modelData.t; variant: "h2" }
                            Flow {
                                width: parent.width
                                spacing: 6
                                Repeater {
                                    model: tile.modelData.k === "mods" ? ["fabric", "quilt", "forge", "neoforge"] : []
                                    delegate: NxChip { required property string modelData; text: page.loaderNames[modelData]; loader: modelData }
                                }
                                Repeater {
                                    model: tile.modelData.k === "import" ? ["Prism", "MultiMC", "CurseForge"] : tile.modelData.k === "pack" ? ["Modrinth", ".mrpack"] : []
                                    delegate: NxChip { required property string modelData; text: modelData }
                                }
                            }
                        }
                    }
                }
            }

            // Шаг 2: чистая игра / с модами
            Column {
                visible: page.step === 2 && (page.kind === "vanilla" || page.kind === "mods")
                width: Math.min(content.width, 640)
                spacing: 20
                NxTextField {
                    width: parent.width
                    label: I18n.t("q.name")
                    placeholder: I18n.t("q.name_example")
                    text: page.name
                    error: page.nameTouched || page.name ? page.nameError : ""
                    onEdited: { page.nameTouched = true; page.name = text }
                }
                Row {
                    spacing: 24
                    Column {
                        spacing: 6
                        NxText { text: I18n.t("q.mc_version"); variant: "strong"; font.pixelSize: 12; lineHeight: 16; muted: true }
                        Row {
                            spacing: 8
                            NxDropdown {
                                width: 220
                                model: Wizard.versionOptions(page.snapshots)
                                value: page.mc
                                placeholder: Wizard.versionsLoading ? I18n.t("common.loading") : "—"
                                onActivated: v => { page.mc = v; page.suggestName(); Wizard.loadLoaderVersions(page.effectiveLoader, v) }
                            }
                            NxSpinner { visible: Wizard.versionsLoading; anchors.verticalCenter: parent.verticalCenter; color: NxTheme.muted }
                        }
                    }
                    Row {
                        spacing: 8
                        anchors.bottom: parent.bottom
                        height: 32
                        NxToggle { id: snapToggle; checked: page.snapshots; onToggled: page.snapshots = checked; anchors.verticalCenter: parent.verticalCenter }
                        NxText { text: I18n.t("q.show_snapshots"); anchors.verticalCenter: parent.verticalCenter }
                    }
                }
                NxText { visible: Wizard.versionsError !== ""; width: parent.width; text: Wizard.versionsError; color: NxTheme.danger; wrapMode: Text.Wrap; elide: Text.ElideNone }
                Column {
                    visible: page.kind === "mods"
                    spacing: 6
                    NxText { text: I18n.t("q.loader"); variant: "strong"; font.pixelSize: 12; lineHeight: 16; muted: true }
                    NxSegmentedControl {
                        value: page.loader
                        model: [{ value: "fabric", label: "Fabric" }, { value: "quilt", label: "Quilt" }, { value: "forge", label: "Forge" }, { value: "neoforge", label: "NeoForge" }]
                        onActivated: v => page.loader = v
                    }
                }
                Column {
                    visible: page.kind === "mods"
                    spacing: 6
                    NxText { text: I18n.t("q.loader_version"); variant: "strong"; font.pixelSize: 12; lineHeight: 16; muted: true }
                    Row {
                        spacing: 8
                        NxDropdown {
                            width: 260
                            model: Wizard.loaderVersions
                            value: page.loaderVersion
                            placeholder: Wizard.loaderLoading ? I18n.t("common.loading") : I18n.t("q.loader_unavailable")
                            onActivated: v => page.loaderVersion = v
                        }
                        NxSpinner { visible: Wizard.loaderLoading; anchors.verticalCenter: parent.verticalCenter; color: NxTheme.muted }
                    }
                }
            }

            // Шаг 2: модпак
            Column {
                visible: page.step === 2 && page.kind === "pack"
                width: Math.min(content.width, 640)
                spacing: 8
                NxSegmentedControl {
                    value: Wizard.packSource
                    model: [{ value: "modrinth", label: "Modrinth" }, { value: "ftb", label: "FTB" },
                            { value: "curseforge", label: "CurseForge" }]
                    onActivated: v => Wizard.setPackSource(v, packSearch.text)
                }
                NxTextField {
                    id: packSearch
                    width: parent.width
                    iconName: "search"
                    placeholder: I18n.t("q.find_pack")
                    onEdited: packTimer.restart()
                    Timer { id: packTimer; interval: 300; onTriggered: Wizard.searchPacks(parent.text) }
                }
                NxSpinner { visible: Wizard.packsLoading; color: NxTheme.muted }
                Repeater {
                    model: Wizard.packs
                    delegate: Rectangle {
                        id: prow
                        required property var modelData
                        readonly property bool active: page.pack && page.pack.id === modelData.id
                        width: parent.width
                        height: 56
                        radius: NxTheme.rButton
                        color: active ? NxTheme.fill2 : ph.hovered ? NxTheme.fill1 : "transparent"
                        HoverHandler { id: ph; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: page.pack = prow.modelData }
                        NxRadio { x: 12; checked: prow.active; anchors.verticalCenter: parent.verticalCenter }
                        NxCover { id: pic; x: 40; width: 36; height: 36; radius: NxTheme.rButton; anchors.verticalCenter: parent.verticalCenter; source: prow.modelData.icon }
                        Column {
                            anchors.left: pic.right; anchors.leftMargin: 12
                            anchors.right: dl.left; anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            NxText { width: parent.width; text: prow.modelData.title; variant: "strong" }
                            NxText { width: parent.width; text: prow.modelData.description; muted: true; font.pixelSize: 12; lineHeight: 16 }
                        }
                        NxText { id: dl; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; text: prow.modelData.downloads; variant: "mono"; muted: true }
                    }
                }
            }

            // Шаг 2: перенос
            Column {
                visible: page.step === 2 && page.kind === "import"
                width: Math.min(content.width, 640)
                spacing: 8
                NxText { text: I18n.t("q.found_builds"); variant: "h2"; bottomPadding: 4 }
                NxSpinner { visible: Wizard.foreignLoading; color: NxTheme.muted }
                NxText { visible: !Wizard.foreignLoading && Wizard.foreign.length === 0; width: parent.width; text: I18n.t("q.no_foreign"); muted: true; wrapMode: Text.Wrap; elide: Text.ElideNone }
                Repeater {
                    model: Wizard.foreign
                    delegate: Rectangle {
                        id: frow
                        required property var modelData
                        width: parent.width
                        height: 48
                        radius: NxTheme.rButton
                        color: fh.hovered ? NxTheme.fill1 : "transparent"
                        HoverHandler { id: fh }
                        NxCheckbox {
                            x: 12
                            anchors.verticalCenter: parent.verticalCenter
                            checked: !!page.picked[frow.modelData.path]
                            onClicked: { const p = Object.assign({}, page.picked); p[frow.modelData.path] = checked; page.picked = p }
                        }
                        NxText { x: 40; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 260; text: frow.modelData.name; variant: "strong" }
                        Row {
                            anchors.right: parent.right; anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 12
                            NxLoaderBadge { loader: frow.modelData.loader; text: frow.modelData.version; mono: true; anchors.verticalCenter: parent.verticalCenter }
                            NxChip { text: frow.modelData.sourceTitle; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
                Item { width: 1; height: 8 }
                NxButton { iconName: "package"; text: I18n.t("q.import_file"); onClicked: importDialog.open() }
            }

            // Шаг 3: итог
            Row {
                visible: page.step === 3
                spacing: 24
                NxCover {
                    width: 112; height: 112
                    source: page.kind === "pack" && page.pack ? page.pack.icon : "image://nx/scene/dusk/" + (page.name.length * 3 + 7) + "/20/20"
                }
                Grid {
                    columns: 2
                    columnSpacing: 16
                    rowSpacing: 8
                    anchors.verticalCenter: parent.verticalCenter
                    NxText { text: I18n.t("q.name"); muted: true }
                    NxText {
                        text: page.kind === "pack" ? (page.pack ? page.pack.title : "")
                            : page.kind === "import" ? I18n.count(page.pickedPaths.length, "q.builds_n") : page.name
                        variant: "strong"
                    }
                    NxText { visible: page.kind !== "import"; text: "Minecraft"; muted: true }
                    NxText { visible: page.kind !== "import"; text: page.kind === "pack" ? I18n.t("q.by_pack") : page.mc; variant: "mono" }
                    NxText { visible: page.kind !== "import"; text: I18n.t("q.loader"); muted: true }
                    NxLoaderBadge {
                        visible: page.kind === "vanilla" || page.kind === "mods"
                        loader: page.effectiveLoader
                        text: page.loaderNames[page.effectiveLoader] + (page.kind === "mods" && page.loaderVersion ? " " + page.loaderVersion : "")
                        color: NxTheme.text
                    }
                    NxText { visible: page.kind === "pack"; text: I18n.t("q.by_pack") }
                }
            }
        }
    }

    // --- Подвал ---
    Item {
        id: foot
        anchors.left: body.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 72
        NxButton { y: 16; variant: "ghost"; text: I18n.t("common.cancel"); onClicked: { page.reset(); Shell.navigate("library") } }
        Row {
            y: 16
            anchors.right: parent.right
            anchors.rightMargin: 48
            spacing: 8
            NxButton { visible: page.step > 1; text: I18n.t("q.back"); onClicked: page.step -= 1 }
            NxButton {
                visible: page.step < 3
                variant: "primary"
                text: I18n.t("q.next")
                trailingIcon: "arrow-right"
                enabled: page.canNext
                onClicked: page.next()
            }
            NxButton {
                visible: page.step === 3
                variant: "primary"
                iconName: "check"
                loading: Wizard.busy
                text: page.kind === "import" ? I18n.t("q.do_import") : I18n.t("q.create")
                onClicked: page.create()
            }
        }
    }

    FileDialog {
        id: importDialog
        nameFilters: [I18n.t("q.pack_files") + " (*.zip *.mrpack)"]
        onAccepted: Wizard.importFile(selectedFile.toString())
    }
}
