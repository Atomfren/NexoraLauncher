// Окно OptiFine внутри сборки: версии, страница загрузки, «ждём файл» → «найден · установить»
import QtQuick
import QtQuick.Templates as T
import QtQuick.Dialogs
import Nexora

T.Popup {
    id: root
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset, implicitContentHeight + topPadding + bottomPadding)
    readonly property var st: OptiFine.status
    readonly property bool supported: !!st.supported

    parent: T.Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(660, parent ? parent.width * 0.94 : 660)
    modal: true
    dim: true
    padding: 0
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside
    onOpened: OptiFine.open()
    onClosed: OptiFine.close()

    T.Overlay.modal: Rectangle { color: NxTheme.scrim }
    background: Rectangle {
        radius: NxTheme.rButton
        color: NxTheme.surface1
        border.color: NxTheme.line
        NxShadow { anchors.fill: parent }
    }
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: NxTheme.base; easing.type: NxTheme.ease }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: NxTheme.base; easing.type: NxTheme.ease }
    }

    contentItem: Column {
        // Шапка
        Item {
            width: parent.width
            height: 64
            NxLoaderMark { x: 24; loader: "optifine"; size: 24; anchors.verticalCenter: parent.verticalCenter }
            NxText { x: 60; text: "OptiFine"; variant: "h2"; anchors.verticalCenter: parent.verticalCenter }
            NxChip {
                visible: !!root.st.installed
                x: 140
                anchors.verticalCenter: parent.verticalCenter
                kind: "ok"
                text: I18n.tf("q.optifine_current", { v: (root.st.edition || "").replace(/_/g, " ") })
            }
            NxIconButton { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; iconName: "x"; onClicked: root.close() }
        }

        Column {
            x: 24
            width: parent.width - 48
            spacing: 8
            bottomPadding: 8

            NxSpinner { visible: OptiFine.state === "loading"; color: NxTheme.muted }
            NxText { visible: OptiFine.state === "error"; width: parent.width; text: OptiFine.error; color: NxTheme.danger; wrapMode: Text.Wrap; elide: Text.ElideNone }

            // Не поддерживается — альтернатива
            Rectangle {
                visible: OptiFine.state !== "loading" && !root.supported && root.st.mod_loader !== undefined
                width: parent.width
                height: 72
                radius: NxTheme.rButton
                color: NxTheme.surface2
                NxCover { id: alt; x: 16; width: 40; height: 40; radius: NxTheme.rButton; anchors.verticalCenter: parent.verticalCenter; source: "image://nx/mod/31/142" }
                Column {
                    anchors.left: alt.right; anchors.leftMargin: 16
                    anchors.right: altBtn.left; anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    NxText { width: parent.width; text: I18n.t("q.alt_title"); variant: "strong" }
                    NxText { width: parent.width; text: I18n.t("q.alt_text"); muted: true; font.pixelSize: 12; lineHeight: 16 }
                }
                NxButton { id: altBtn; anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; text: I18n.t("q.add_both"); onClicked: { OptiFine.installAlternative(); root.close() } }
            }

            // Версии
            NxText { visible: root.supported && OptiFine.versions.length > 0; text: I18n.tf("q.versions_for", { v: root.st.mc_version || "" }); variant: "caption"; topPadding: 4 }
            NxText { visible: root.supported && OptiFine.state === "idle" && OptiFine.versions.length === 0; width: parent.width; text: I18n.t("q.optifine_none"); muted: true; wrapMode: Text.Wrap; elide: Text.ElideNone }
            Repeater {
                model: root.supported ? OptiFine.versions.slice(0, 6) : []
                delegate: Rectangle {
                    id: vr
                    required property var modelData
                    required property int index
                    readonly property bool active: OptiFine.selected === index
                    width: parent.width
                    height: 44
                    radius: NxTheme.rButton
                    color: active ? NxTheme.fill2 : vh.hovered ? NxTheme.fill1 : "transparent"
                    HoverHandler { id: vh; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: OptiFine.select(vr.index) }
                    NxRadio { x: 12; checked: vr.active; anchors.verticalCenter: parent.verticalCenter }
                    NxText { x: 40; width: 140; text: vr.modelData.edition; variant: "mono"; anchors.verticalCenter: parent.verticalCenter }
                    NxText { x: 188; width: 64; text: vr.modelData.mc; variant: "mono"; muted: true; anchors.verticalCenter: parent.verticalCenter }
                    NxText { x: 260; text: vr.modelData.date; variant: "mono"; muted: true; anchors.verticalCenter: parent.verticalCenter }
                    NxChip {
                        anchors.right: parent.right; anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        visible: vr.index === 0 && !vr.modelData.preview || vr.modelData.preview
                        kind: vr.modelData.preview ? "warn" : "ok"
                        text: vr.modelData.preview ? "preview" : I18n.t("q.recommended")
                    }
                }
            }

            // Ждём / найден
            Rectangle {
                visible: OptiFine.state === "wait"
                width: parent.width
                height: 48
                radius: NxTheme.rButton
                color: NxTheme.fill1
                NxSpinner { x: 12; anchors.verticalCenter: parent.verticalCenter; color: NxTheme.muted }
                NxText { x: 40; anchors.verticalCenter: parent.verticalCenter; text: I18n.t("q.waiting_file"); muted: true }
                NxText {
                    anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, parent.width - 300)
                    text: OptiFine.versions.length ? OptiFine.versions[OptiFine.selected].filename : ""
                    variant: "mono"; muted: true; elide: Text.ElideMiddle
                }
            }
            Rectangle {
                visible: OptiFine.state === "found" || OptiFine.state === "installing"
                width: parent.width
                height: 52
                radius: NxTheme.rButton
                color: NxTheme.okBg
                NxIcon { x: 12; name: "check"; size: 18; color: NxTheme.success; anchors.verticalCenter: parent.verticalCenter }
                NxText {
                    x: 40
                    width: parent.width - 180
                    anchors.verticalCenter: parent.verticalCenter
                    text: I18n.tf("q.found_file", { f: OptiFine.found.filename || "" })
                    variant: "strong"
                    elide: Text.ElideMiddle
                }
                NxButton {
                    anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                    variant: "primary"; small: true
                    loading: OptiFine.state === "installing"
                    text: I18n.t("q.install")
                    onClicked: OptiFine.install()
                }
            }
        }

        // Подвал
        Item {
            width: parent.width
            height: 68
            Row {
                x: 24
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                NxButton {
                    visible: root.supported
                    variant: OptiFine.state === "idle" ? "secondary" : "ghost"
                    iconName: "external"
                    text: I18n.t("q.open_download_page")
                    onClicked: OptiFine.openDownloadPage()
                }
                NxButton { visible: root.supported; variant: "ghost"; iconName: "package"; text: I18n.t("q.pick_file"); onClicked: jarDialog.open() }
                NxButton { visible: !!root.st.installed; variant: "ghost"; dangerText: true; text: I18n.t("q.remove_optifine"); onClicked: OptiFine.remove() }
            }
            NxButton { anchors.right: parent.right; anchors.rightMargin: 24; anchors.verticalCenter: parent.verticalCenter; variant: "ghost"; text: I18n.t("common.close"); onClicked: root.close() }
        }
    }

    FileDialog {
        id: jarDialog
        nameFilters: ["OptiFine (*.jar)"]
        onAccepted: OptiFine.installFile(selectedFile.toString())
    }
}
