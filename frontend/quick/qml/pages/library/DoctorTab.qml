// Диагностика: вердикт одной строкой, управление логом и сам лог (умные логи)
import QtQuick
import QtQuick.Controls as C
import Nexora

Item {
    id: root
    readonly property var v: Build.verdict
    readonly property bool bad: v.state === "error" || v.state === "warning"
    readonly property var s: Logs.summary
    property var open: ({})

    onVisibleChanged: if (visible) Logs.ensure()
    Component.onCompleted: if (visible) Logs.ensure()
    Connections { target: Library; function onSelectedChanged() { root.open = ({}); if (root.visible) Logs.ensure() } }

    function summaryText() {
        const parts = []
        if (s.minecraft) parts.push("Minecraft " + s.minecraft)
        if (s.loader && s.loader !== "vanilla") parts.push(s.loader + (s.loader_version ? " " + s.loader_version : ""))
        if (s.mods) parts.push(I18n.count(s.mods, "q.mods"))
        if (s.java) parts.push("Java " + s.java)
        if (s.load_seconds) parts.push(I18n.tf("q.loaded_in", { s: Math.round(s.load_seconds) }))
        return parts.join(" · ")
    }

    // Вердикт
    Rectangle {
        id: bar
        x: 32
        y: 24
        width: parent.width - 64
        height: 56
        radius: NxTheme.rButton
        color: root.bad ? NxTheme.warnBg : root.v.state === "ok" ? NxTheme.okBg : NxTheme.fill1
        Item {
            id: lead
            x: 16; width: 20; height: 20
            anchors.verticalCenter: parent.verticalCenter
            NxSpinner { visible: root.v.state === "loading"; anchors.centerIn: parent; color: NxTheme.muted }
            NxIcon {
                visible: root.v.state !== "loading"
                anchors.centerIn: parent
                size: 20
                name: root.v.state === "ok" ? "check" : "alert"
                color: root.v.state === "ok" ? NxTheme.success : root.bad ? NxTheme.warning : NxTheme.muted
            }
        }
        Column {
            anchors.left: lead.right; anchors.leftMargin: 12
            anchors.right: acts.left; anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            NxText { width: parent.width; text: root.v.state === "loading" ? I18n.t("q.doctor_checking") : root.v.title; variant: "strong" }
            NxText {
                width: parent.width
                visible: text !== ""
                text: root.v.state === "loading" ? "" : root.v.count > 1 ? I18n.tf("q.doctor_more", { n: root.v.count - 1 }) : (root.v.details || "")
                variant: "mono"
                muted: true
            }
        }
        Row {
            id: acts
            anchors.right: parent.right; anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            NxButton {
                visible: root.bad && !!root.v.fixAction
                text: root.v.fixLabel || I18n.t("q.fix")
                onClicked: Build.applyFix(root.v.fixAction, root.v.fixParams || {})
            }
            NxButton {
                visible: (root.v.issues || []).length > 1
                variant: "ghost"
                text: I18n.t("q.all_problems")
                onClicked: problems.open()
            }
        }
    }

    // Управление
    Flow {
        id: ctl
        x: 32
        anchors.top: bar.bottom
        anchors.topMargin: 16
        width: parent.width - 64
        spacing: 12
        NxDropdown {
            width: 240
            model: Logs.sources
            value: Logs.source
            placeholder: Logs.loading ? I18n.t("common.loading") : I18n.t("q.no_logs")
            onActivated: val => { root.open = ({}); Logs.reload(val) }
        }
        NxSegmentedControl {
            value: Logs.level
            model: [{ value: "all", label: I18n.t("q.level_all") }, { value: "error", label: I18n.t("q.level_errors") },
                    { value: "warn", label: I18n.t("q.level_warnings") }, { value: "info", label: I18n.t("q.level_info") }]
            onActivated: val => Logs.setLevel(val)
        }
        Row {
            height: 32
            spacing: 8
            NxToggle { checked: Logs.hideNoise; onToggled: Logs.setHideNoise(checked); anchors.verticalCenter: parent.verticalCenter }
            NxText { text: I18n.t("q.hide_noise"); anchors.verticalCenter: parent.verticalCenter }
        }
        NxTextField { width: 200; iconName: "search"; placeholder: I18n.t("q.search_log"); onEdited: Logs.setQuery(text) }
        NxIconButton { iconName: "refresh"; tip: I18n.t("q.recheck"); onClicked: { Logs.reload(Logs.source); Build.reloadVerdict() } }
        NxButton { variant: "ghost"; iconName: "share"; text: I18n.t("q.share_log"); onClicked: Build.shareLog() }
    }

    NxText {
        id: sum
        x: 32
        anchors.top: ctl.bottom
        anchors.topMargin: 8
        width: parent.width - 64
        visible: text !== ""
        text: root.summaryText()
        variant: "mono"
        muted: true
    }

    // Лог
    Rectangle {
        x: 32
        anchors.top: sum.visible ? sum.bottom : ctl.bottom
        anchors.topMargin: 8
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        width: parent.width - 64
        radius: NxTheme.rButton
        color: NxTheme.surface1
        clip: true

        ListView {
            id: log
            anchors.fill: parent
            anchors.topMargin: 8
            anchors.bottomMargin: 8
            model: Logs.lines
            boundsBehavior: Flickable.StopAtBounds
            C.ScrollBar.vertical: NxScrollBar {}
            onCountChanged: { const i = Logs.firstErrorRow(); if (i >= 0) positionViewAtIndex(i, ListView.Center); else positionViewAtEnd() }
            footer: NxText {
                visible: Logs.hiddenNoise > 0
                leftPadding: 16
                topPadding: 6
                text: I18n.tf("q.noise_hidden", { n: Logs.hiddenNoise })
                variant: "mono"
                muted: true
            }
            delegate: Column {
                id: line
                required property var modelData
                required property int index
                readonly property bool expanded: !!root.open[modelData.index]
                width: log.width
                Rectangle {
                    width: parent.width
                    height: msg.height + 2
                    color: line.modelData.level === "error" ? NxTheme.errBg : line.modelData.level === "warn" ? NxTheme.warnBg : lh.hovered ? NxTheme.fill1 : "transparent"
                    HoverHandler { id: lh }
                    NxText { x: 16; width: 68; text: line.modelData.time; variant: "mono"; muted: true; elide: Text.ElideNone }
                    NxDot {
                        x: 92; y: 6
                        size: 6
                        kind: line.modelData.level === "error" ? "err" : line.modelData.level === "warn" ? "warn" : ""
                        opacity: line.modelData.level === "info" ? 0.6 : 1
                    }
                    NxText {
                        x: 108
                        width: 112
                        text: line.modelData.tag ? "[" + line.modelData.tag + "]" : ""
                        variant: "mono"
                        color: line.modelData.mod ? NxTheme.accent : NxTheme.muted
                    }
                    TextEdit {
                        id: msg
                        x: 228
                        width: parent.width - 228 - (cnt.visible ? cnt.width + 24 : 16)
                        text: line.modelData.message
                        readOnly: true
                        selectByMouse: true
                        wrapMode: Text.WrapAnywhere
                        color: line.modelData.level === "info" ? Qt.rgba(NxTheme.text.r, NxTheme.text.g, NxTheme.text.b, 0.82) : NxTheme.text
                        selectionColor: Qt.rgba(NxTheme.accent.r, NxTheme.accent.g, NxTheme.accent.b, 0.35)
                        font.family: NxTheme.fontMono
                        font.pixelSize: 12
                    }
                    Rectangle {
                        id: cnt
                        visible: line.modelData.count > 1
                        anchors.right: parent.right
                        anchors.rightMargin: 16
                        y: 1
                        width: cntText.implicitWidth + 12
                        height: 16
                        radius: 3
                        color: NxTheme.fill1
                        NxText { id: cntText; anchors.centerIn: parent; text: "×" + line.modelData.count; variant: "monoStrong"; font.pixelSize: 11; lineHeight: 16; muted: true }
                    }
                }
                // Стек-трейс
                Column {
                    visible: line.modelData.stack.length > 0
                    x: 228
                    width: parent.width - 244
                    Repeater {
                        model: line.expanded ? line.modelData.stack : []
                        delegate: NxText { required property string modelData; width: parent.width; text: modelData; variant: "mono"; muted: true }
                    }
                    NxText {
                        text: line.expanded ? "▾ " + I18n.t("q.collapse") : "▸ " + I18n.count(line.modelData.stack.length, "q.more_lines")
                        variant: "mono"
                        color: sh.hovered ? NxTheme.text : NxTheme.muted
                        HoverHandler { id: sh; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            onTapped: { const o = Object.assign({}, root.open); o[line.modelData.index] = !line.expanded; root.open = o }
                        }
                    }
                }
                // Подсказка простым языком
                Rectangle {
                    visible: line.modelData.hint !== ""
                    x: 228
                    width: parent.width - 244
                    height: visible ? hint.implicitHeight + 12 : 0
                    radius: 4
                    color: NxTheme.fill1
                    NxIcon { x: 10; y: 7; name: "lightbulb"; size: 14; color: NxTheme.warning }
                    NxText {
                        id: hint
                        x: 32; y: 6
                        width: parent.width - 42
                        text: line.modelData.hint
                        font.pixelSize: 12
                        lineHeight: 18
                        wrapMode: Text.Wrap
                        elide: Text.ElideNone
                    }
                }
                Item { width: 1; height: line.modelData.hint !== "" ? 4 : 0 }
            }
        }

        Column {
            visible: !Logs.loading && log.count === 0
            x: 16
            y: 24
            spacing: 6
            NxText { text: Logs.error !== "" ? Logs.error : Logs.sources.length === 0 ? I18n.t("q.no_logs") : I18n.t("q.no_lines"); muted: true }
        }
        NxSpinner { visible: Logs.loading; anchors.centerIn: parent; color: NxTheme.muted }
    }

    // Все проблемы Доктора
    NxDrawer {
        id: problems
        title: I18n.t("q.all_problems")
        bodySpacing: 8
        Repeater {
            model: root.v.issues || []
            delegate: Rectangle {
                id: issue
                required property var modelData
                width: problems.bodyWidth
                height: col.implicitHeight + 24
                radius: NxTheme.rButton
                color: NxTheme.surface2
                Rectangle { y: 12; width: 2; height: parent.height - 24; radius: 1; color: issue.modelData.severity === "error" ? NxTheme.danger : issue.modelData.severity === "warning" ? NxTheme.warning : NxTheme.info }
                Column {
                    id: col
                    x: 16; y: 12
                    width: parent.width - 32
                    spacing: 8
                    NxText { width: parent.width; text: issue.modelData.title; variant: "strong"; wrapMode: Text.Wrap; elide: Text.ElideNone }
                    NxText { visible: text !== ""; width: parent.width; text: issue.modelData.details || ""; muted: true; wrapMode: Text.Wrap; elide: Text.ElideNone }
                    Flow {
                        width: parent.width
                        spacing: 8
                        Repeater {
                            model: issue.modelData.fixes || []
                            delegate: NxButton {
                                required property var modelData
                                small: true
                                text: modelData.label
                                onClicked: Build.applyFix(modelData.action, modelData.params || {})
                            }
                        }
                    }
                }
            }
        }
    }
}
