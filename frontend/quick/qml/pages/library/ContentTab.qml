// Моды сборки: поиск, обновления, добавление, таблица с выбором и переключателями
import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import Nexora

Item {
    id: root
    property string contentType: "mod"
    property string query: ""
    property var picked: ({})
    signal optifineRequested()
    signal turboRequested()
    readonly property var all: Build.mods
    readonly property var rows: query ? all.filter(m => m.name.toLowerCase().indexOf(query.toLowerCase()) >= 0
                                                   || m.filename.toLowerCase().indexOf(query.toLowerCase()) >= 0) : all
    readonly property var pickedNames: Object.keys(picked).filter(k => picked[k] && all.some(m => m.filename === k))
    readonly property bool narrow: width < 760

    function toggle(filename) {
        const p = Object.assign({}, picked)
        p[filename] = !p[filename]
        picked = p
    }
    function pickAll(on) {
        const p = {}
        if (on) for (const m of rows) p[m.filename] = true
        picked = p
    }

    Connections { target: Library; function onSelectedChanged() { root.picked = ({}); root.query = ""; search.text = "" } }

    // Панель инструментов
    Row {
        id: toolbar
        x: 32
        y: 24
        width: parent.width - 64
        spacing: 8
        NxTextField {
            id: search
            width: 240
            iconName: "search"
            placeholder: I18n.t("q.find_mod")
            onEdited: root.query = text
        }
        Item { width: toolbar.width - search.width - upd.width - turbo.width - add.width - 32; height: 1 }
        NxButton {
            id: upd
            iconName: "refresh"
            loading: Build.checkingUpdates
            text: Build.updatesCount > 0 ? I18n.tf("q.update_all", { n: Build.updatesCount }) : I18n.t("q.check_updates")
            enabled: Build.mods.length > 0 && !Build.checkingUpdates
            onClicked: Build.updatesCount > 0 ? Build.applyUpdates() : Build.checkUpdates()
        }
        NxButton {
            id: turbo
            visible: Library.current.loader !== "vanilla"
            width: visible ? implicitWidth : 0
            iconName: "zap"
            text: I18n.t("q.turbo")
            onClicked: root.turboRequested()
        }
        NxButton {
            id: add
            iconName: "plus"
            trailingIcon: "chevron-down"
            text: I18n.t("q.add_mod")
            onClicked: addMenu.openAt(add)
        }
    }

    // Выбрано N: массовые действия
    Rectangle {
        id: batch
        visible: root.pickedNames.length > 0
        x: 32
        anchors.top: toolbar.bottom
        anchors.topMargin: 16
        width: parent.width - 64
        height: visible ? 44 : 0
        radius: NxTheme.rButton
        color: NxTheme.surface2
        NxText { x: 12; anchors.verticalCenter: parent.verticalCenter; text: I18n.tf("q.selected_n", { n: root.pickedNames.length }); variant: "strong" }
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            NxButton { small: true; variant: "ghost"; text: I18n.t("q.enable"); onClicked: { Build.setManyEnabled(root.contentType, root.pickedNames, true); root.pickAll(false) } }
            NxButton { small: true; variant: "ghost"; text: I18n.t("q.disable"); onClicked: { Build.setManyEnabled(root.contentType, root.pickedNames, false); root.pickAll(false) } }
            NxButton { small: true; variant: "ghost"; dangerText: true; text: I18n.t("common.delete"); onClicked: removeDialog.open() }
            NxIconButton { small: true; iconName: "x"; tip: I18n.t("q.clear_selection"); onClicked: root.pickAll(false) }
        }
    }

    // Заголовок таблицы
    Item {
        id: header
        visible: root.rows.length > 0
        x: 32
        anchors.top: batch.visible ? batch.bottom : toolbar.bottom
        anchors.topMargin: batch.visible ? 8 : 16
        width: parent.width - 64
        height: 28
        NxCheckbox {
            x: 8
            anchors.verticalCenter: parent.verticalCenter
            checked: root.pickedNames.length > 0 && root.pickedNames.length === root.rows.length
            partial: root.pickedNames.length > 0
            onClicked: root.pickAll(root.pickedNames.length === 0)
        }
        NxText { x: 48; anchors.verticalCenter: parent.verticalCenter; text: I18n.t("q.col_name"); variant: "caption" }
        NxText { x: parent.width - (root.narrow ? 228 : 338); anchors.verticalCenter: parent.verticalCenter; text: I18n.t("q.col_version"); variant: "caption" }
        NxText { visible: !root.narrow; x: parent.width - 188; anchors.verticalCenter: parent.verticalCenter; text: I18n.t("q.col_source"); variant: "caption" }
    }

    ListView {
        id: list
        x: 32
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        width: parent.width - 64
        clip: true
        model: root.rows
        boundsBehavior: Flickable.StopAtBounds
        C.ScrollBar.vertical: NxScrollBar {}
        footer: Item { width: 1; height: 24 }
        delegate: Rectangle {
            id: row
            required property var modelData
            readonly property bool on: modelData.enabled
            readonly property bool sel: !!root.picked[modelData.filename]
            width: list.width
            height: 44
            radius: NxTheme.rButton
            color: sel || hov.hovered ? NxTheme.fill1 : "transparent"
            HoverHandler { id: hov }

            NxCheckbox { x: 8; anchors.verticalCenter: parent.verticalCenter; checked: row.sel; onClicked: root.toggle(row.modelData.filename) }
            NxCover {
                id: icon
                x: 40
                anchors.verticalCenter: parent.verticalCenter
                width: 32; height: 32
                radius: NxTheme.rButton
                source: row.modelData.icon
                dim: !row.on
            }
            Column {
                anchors.left: icon.right
                anchors.leftMargin: 12
                anchors.right: ver.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                NxText { width: parent.width; text: row.modelData.name; variant: "strong"; lineHeight: 18; color: row.on ? NxTheme.text : NxTheme.muted }
                NxText { width: parent.width; text: row.modelData.filename; muted: true; font.pixelSize: 12; lineHeight: 16; elide: Text.ElideMiddle }
            }
            Row {
                id: ver
                x: parent.width - (root.narrow ? 228 : 338)
                width: 150
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                clip: true
                NxText { text: row.modelData.version || "—"; variant: "mono"; muted: !row.modelData.version; anchors.verticalCenter: parent.verticalCenter }
                NxIcon { visible: !!row.modelData.newVersion; name: "arrow-right"; size: 12; color: NxTheme.info; anchors.verticalCenter: parent.verticalCenter }
                NxText { visible: !!row.modelData.newVersion; text: row.modelData.newVersion || ""; variant: "mono"; color: NxTheme.info; anchors.verticalCenter: parent.verticalCenter }
            }
            NxText {
                visible: !root.narrow
                x: parent.width - 188
                width: 100
                anchors.verticalCenter: parent.verticalCenter
                text: row.modelData.source
                muted: true
                font.pixelSize: 12
            }
            NxToggle {
                x: parent.width - 80
                anchors.verticalCenter: parent.verticalCenter
                checked: row.on
                onToggled: Build.setEnabled(root.contentType, row.modelData.filename, checked)
            }
            NxIconButton {
                id: kebab
                x: parent.width - 36
                anchors.verticalCenter: parent.verticalCenter
                small: true
                iconName: "kebab"
                tip: I18n.t("q.actions")
                onClicked: { rowMenu.target = row.modelData.filename; rowMenu.openAt(kebab) }
            }
        }
    }

    NxEmptyState {
        visible: root.rows.length === 0
        anchors.top: toolbar.bottom
        leftPadding: 32
        compact: true
        illustration: root.query ? "search" : "mods"
        text: root.query ? I18n.tf("q.nothing_for", { q: root.query }) : I18n.t("q.no_mods")
        NxButton { visible: !root.query; iconName: "plus"; text: I18n.t("q.open_catalog"); onClicked: Shell.navigate("catalog", "mod") }
        NxButton { visible: !root.query; variant: "ghost"; text: I18n.t("q.add_jar"); onClicked: fileDialog.open() }
        NxButton { visible: !!root.query; text: I18n.t("q.reset_search"); onClicked: { search.text = ""; root.query = "" } }
    }

    NxMenu {
        id: addMenu
        alignRight: true
        items: [
            { text: I18n.t("q.from_catalog"), icon: "compass", action: "catalog" },
            { text: I18n.t("q.jar_file"), icon: "package", action: "file" },
            { text: "OptiFine…", icon: "zap", action: "optifine" }
        ]
        onTriggered: action => action === "catalog" ? Shell.navigate("catalog", "mod")
                              : action === "optifine" ? root.optifineRequested() : fileDialog.open()
    }

    NxMenu {
        id: rowMenu
        property string target: ""
        alignRight: true
        items: [
            { text: I18n.t("q.open_folder"), icon: "folder", action: "folder" },
            { separator: true },
            { text: I18n.t("common.delete"), icon: "trash", danger: true, action: "delete" }
        ]
        onTriggered: action => {
            if (action === "folder") Shell.openPath(Library.current.gameDir + "/mods")
            else { root.picked = ({ [target]: true }); removeDialog.open() }
        }
    }

    NxDialog {
        id: removeDialog
        title: I18n.count(root.pickedNames.length, "q.remove_mods_title")
        text: I18n.t("q.remove_mods_text")
        onAccepted: { Build.removeContent(root.contentType, root.pickedNames); root.pickAll(false) }
    }

    FileDialog {
        id: fileDialog
        title: I18n.t("q.jar_file")
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Minecraft mods (*.jar)"]
        onAccepted: Build.addLocalContent(root.contentType, selectedFiles)
    }
}
