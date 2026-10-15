// Боковая панель: 4 раздела, внизу аккаунт. Ширина 72 / 220.
import QtQuick
import QtQuick.Window

Rectangle {
    id: root
    property string page: "library"
    property bool wide: false
    signal navigate(string page)
    signal toggleWide()
    signal accountClicked(Item anchor)

    width: wide ? 220 : 72
    color: NxTheme.surface1
    clip: true
    Behavior on width { NumberAnimation { duration: NxTheme.base; easing.type: NxTheme.ease } }

    Column {
        id: top
        x: 12
        y: 12
        width: parent.width - 24
        spacing: 4

        Item {
            width: parent.width
            height: 36
            Image {
                id: logo
                x: 12
                anchors.verticalCenter: parent.verticalCenter
                width: 24; height: 24
                source: "image://nx/logo/" + NxTheme.hex(NxTheme.text) + "/" + NxTheme.hex(NxTheme.accent)
                sourceSize: Qt.size(24 * Screen.devicePixelRatio, 24 * Screen.devicePixelRatio)
            }
            NxText {
                anchors.left: logo.right
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: "Nexora"
                font.pixelSize: 15
                font.weight: Font.DemiBold
                opacity: root.wide ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: NxTheme.fast } }
            }
        }
        Item { width: 1; height: 8 }

        NxSidebarItem { iconName: "library"; text: I18n.t("q.nav_library"); wide: root.wide; current: root.page === "library" || root.page === "wizard"; onClicked: root.navigate("library") }
        NxSidebarItem { iconName: "compass"; text: I18n.t("q.nav_catalog"); wide: root.wide; current: root.page === "catalog"; onClicked: root.navigate("catalog") }
        NxSidebarItem { iconName: "globe"; text: I18n.t("q.nav_network"); wide: root.wide; current: root.page === "network"; onClicked: root.navigate("network") }
    }

    Column {
        x: 12
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 12
        width: parent.width - 24
        spacing: 4

        NxSidebarItem { iconName: "sliders"; text: I18n.t("q.nav_settings"); wide: root.wide; current: root.page === "settings"; onClicked: root.navigate("settings") }
        NxSidebarItem { iconName: "panel-left"; text: root.wide ? I18n.t("q.sidebar_collapse") : I18n.t("q.sidebar_expand"); wide: root.wide; onClicked: root.toggleWide() }
        Item { width: 1; height: 8 }

        // Аккаунт
        Rectangle {
            id: acc
            width: parent.width
            height: 48
            radius: NxTheme.rButton
            clip: true
            color: accArea.containsMouse ? NxTheme.fill1 : "transparent"
            NxCover {
                id: face
                x: 8
                anchors.verticalCenter: parent.verticalCenter
                width: 32; height: 32
                radius: 4
                source: "image://nx/head/" + (Shell.account.seed || 3)
            }
            Column {
                anchors.left: face.right
                anchors.leftMargin: 10
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                opacity: root.wide ? 1 : 0
                NxText { width: parent.width; text: Shell.account.name || I18n.t("q.no_account"); variant: "strong"; lineHeight: 18 }
                NxText { width: parent.width; text: Shell.account.kind || ""; muted: true; font.pixelSize: 11; lineHeight: 14 }
            }
            MouseArea {
                id: accArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.accountClicked(acc)
            }
        }
    }
}
