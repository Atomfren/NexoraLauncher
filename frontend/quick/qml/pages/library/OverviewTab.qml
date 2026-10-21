// Обзор сборки: недавние миры и скриншоты слева; Доктор, свой сервер и параметры справа
import QtQuick
import QtQuick.Layouts
import Nexora

TabPage {
    id: root
    signal openTab(string tab)
    readonly property var cur: Library.current
    readonly property var gs: Build.globalSettings
    readonly property var v: Build.verdict

    GridLayout {
        width: root.innerWidth
        columns: root.innerWidth < 760 ? 1 : 2
        columnSpacing: 32
        rowSpacing: 24

        // --- Левая колонка -------------------------------------------------------------------
        Column {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: 0

            NxSectionHeader {
                text: I18n.t("q.recent_worlds")
                actionText: Build.worlds.length ? I18n.t("q.all_worlds") : ""
                onAction: root.openTab("worlds")
            }
            Item { width: 1; height: 8 }
            Repeater {
                model: Build.worlds.slice(0, 3)
                delegate: WorldRow {
                    required property var modelData
                    width: parent.width
                    world: modelData
                }
            }
            NxEmptyState {
                visible: !Build.loading && Build.worlds.length === 0
                compact: true
                illustration: "worlds"
                text: I18n.t("q.no_worlds")
            }

            Item { width: 1; height: 24; visible: Build.screenshots.length > 0 }
            NxSectionHeader {
                visible: Build.screenshots.length > 0
                text: I18n.t("q.tab_shots")
                actionText: I18n.t("q.open")
                onAction: root.openTab("shots")
            }
            Item { width: 1; height: 8; visible: Build.screenshots.length > 0 }
            Row {
                visible: Build.screenshots.length > 0
                width: parent.width
                spacing: 12
                clip: true
                Repeater {
                    model: Build.screenshots.slice(0, 3)
                    delegate: NxCover {
                        required property var modelData
                        width: 168; height: 96
                        radius: NxTheme.rButton
                        source: modelData.url
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Shell.openPath(parent.modelData.path) }
                    }
                }
            }
        }

        // --- Правая колонка ------------------------------------------------------------------
        Column {
            Layout.preferredWidth: root.innerWidth < 760 ? root.innerWidth : 300
            Layout.alignment: Qt.AlignTop
            spacing: 24

            Column {
                width: parent.width
                spacing: 8
                NxSectionHeader { text: I18n.t("q.doctor") }
                Rectangle {
                    width: parent.width
                    height: verdictCol.implicitHeight + 32
                    radius: NxTheme.rButton
                    color: NxTheme.surface2
                    readonly property color tone: root.v.state === "ok" ? NxTheme.success
                                                : root.v.state === "error" || root.v.state === "warning" ? NxTheme.warning : NxTheme.muted
                    Rectangle { x: 0; y: 16; width: 2; height: parent.height - 32; radius: 1; color: parent.tone }
                    Column {
                        id: verdictCol
                        x: 16; y: 16
                        width: parent.width - 32
                        spacing: 12
                        Row {
                            width: parent.width
                            spacing: 10
                            Item {
                                width: 18; height: 20
                                NxSpinner { visible: root.v.state === "loading"; size: 16; color: NxTheme.muted; anchors.centerIn: parent }
                                NxIcon {
                                    visible: root.v.state !== "loading"
                                    anchors.centerIn: parent
                                    size: 18
                                    name: root.v.state === "ok" ? "check" : "alert"
                                    color: root.v.state === "ok" ? NxTheme.success : root.v.state === "unknown" ? NxTheme.muted : NxTheme.warning
                                }
                            }
                            Column {
                                width: parent.width - 28
                                spacing: 2
                                NxText {
                                    width: parent.width
                                    text: root.v.state === "loading" ? I18n.t("q.doctor_checking") : root.v.title
                                    variant: "strong"
                                    wrapMode: Text.Wrap
                                    elide: Text.ElideNone
                                    maximumLineCount: 3
                                }
                                NxText {
                                    width: parent.width
                                    visible: root.v.state !== "loading" && text !== ""
                                    text: root.v.count > 1 ? I18n.tf("q.doctor_more", { n: root.v.count - 1 }) : (root.v.details || "")
                                    variant: "mono"
                                    muted: true
                                    wrapMode: Text.Wrap
                                    elide: Text.ElideRight
                                    maximumLineCount: 2
                                }
                            }
                        }
                        // Flow: длинная подпись исправления переносит «Подробнее» на новую строку, а не за край
                        Flow {
                            visible: root.v.state === "error" || root.v.state === "warning"
                            width: parent.width
                            spacing: 8
                            NxButton {
                                visible: !!root.v.fixAction
                                small: true
                                text: root.v.fixLabel || I18n.t("q.fix")
                                onClicked: Build.applyFix(root.v.fixAction, root.v.fixParams || {})
                            }
                            NxButton { small: true; variant: "ghost"; text: I18n.t("q.details"); onClicked: root.openTab("doctor") }
                        }
                    }
                }
            }

            Column {
                visible: Build.server.name !== undefined
                width: parent.width
                spacing: 8
                NxSectionHeader { text: I18n.t("q.own_server") }
                NxChip {
                    clickable: true
                    text: (Build.server.name || "") + " · " + (Build.server.state === "running" ? I18n.t("q.server_on")
                          : Build.server.state === "starting" ? I18n.t("q.server_starting") : I18n.t("q.server_off"))
                    dot: Build.server.state === "running" ? "ok" : Build.server.state === "starting" ? "warn" : "off"
                    trailingIcon: "chevron-right"
                    onClicked: Shell.navigate("network")
                }
            }

            Column {
                width: parent.width
                NxSectionHeader { text: I18n.t("q.build") }
                StatRow { label: "Java"; value: root.cur.javaPath || root.gs.java_path || I18n.t("q.java_auto") }
                StatRow { label: I18n.t("q.memory"); value: I18n.memory(root.cur.maxMemory || root.gs.max_memory || 0) }
                StatRow { label: I18n.t("q.last_played"); value: root.cur.lastPlayed || "—" }
            }
        }
    }

    component StatRow: Item {
        property string label
        property string value
        width: parent ? parent.width : 300
        height: 28
        NxText { text: parent.label; muted: true; anchors.verticalCenter: parent.verticalCenter }
        NxText {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, parent.width - 120)
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideLeft
            text: parent.value
            variant: "mono"
        }
    }
}
