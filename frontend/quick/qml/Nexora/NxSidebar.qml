// Боковая панель: 4 раздела. Ширина 72 / 220. Аккаунт — в шапке сборки (AccountShowcase).
// Положение выбирается в настройках: слева, справа (вертикальная) или сверху, снизу (горизонтальная полоса).
import QtQuick
import QtQuick.Controls as C
import QtQuick.Window

Rectangle {
    id: root
    property string page: "library"
    property bool wide: false
    // Горизонтальная полоса (панель сверху или снизу): подписи видны всегда, кнопки «Свернуть» нет
    property bool horizontal: false
    signal navigate(string page)
    signal toggleWide()

    // Ширину задаём через implicitWidth: её читает раскладка окна, и соседняя колонка
    // сдвигается вместе с анимацией (с обычным width раскладка отставала — наслоение и чёрная полоса)
    property real currentWidth: wide ? 220 : 72
    Behavior on currentWidth { NumberAnimation { duration: NxTheme.base; easing.type: NxTheme.ease } }
    implicitWidth: currentWidth
    implicitHeight: 56
    color: NxTheme.surface1
    clip: true

    // Логотип — ссылка на сайт Nexora
    component Logo: Item {
        id: logoBox
        property bool showName: true
        width: showName ? 46 + nameText.implicitWidth + 12 : 48
        height: 36
        Rectangle {
            anchors.fill: parent
            radius: NxTheme.rButton
            color: logoArea.containsMouse ? NxTheme.fill1 : "transparent"
            Behavior on color { ColorAnimation { duration: NxTheme.fast } }
        }
        Image {
            id: logo
            x: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 24; height: 24
            source: "image://nx/logo/" + NxTheme.hex(NxTheme.text) + "/" + NxTheme.hex(NxTheme.accent)
            sourceSize: Qt.size(24 * Screen.devicePixelRatio, 24 * Screen.devicePixelRatio)
        }
        NxText {
            id: nameText
            anchors.left: logo.right
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            text: "Nexora"
            font.pixelSize: 15
            font.weight: Font.DemiBold
            opacity: logoBox.showName ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: NxTheme.fast } }
        }
        MouseArea {
            id: logoArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: Shell.openUrl(Shell.website)
            C.ToolTip.visible: containsMouse
            C.ToolTip.text: I18n.t("q.website")
            C.ToolTip.delay: 500
            Accessible.role: Accessible.Link
            Accessible.name: I18n.t("q.website")
        }
    }

    // --- Вертикальная панель (слева или справа) ---
    Column {
        visible: !root.horizontal
        x: 12
        y: 12
        width: parent.width - 24
        spacing: 4

        Logo { showName: root.wide }
        Item { width: 1; height: 8 }

        NxSidebarItem { iconName: "library"; text: I18n.t("q.nav_library"); wide: root.wide; current: root.page === "library" || root.page === "wizard"; onClicked: root.navigate("library") }
        NxSidebarItem { iconName: "compass"; text: I18n.t("q.nav_catalog"); wide: root.wide; current: root.page === "catalog"; onClicked: root.navigate("catalog") }
        NxSidebarItem { iconName: "globe"; text: I18n.t("q.nav_network"); wide: root.wide; current: root.page === "network"; onClicked: root.navigate("network") }
    }

    Column {
        visible: !root.horizontal
        x: 12
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 12
        width: parent.width - 24
        spacing: 4

        NxSidebarItem { iconName: "sliders"; text: I18n.t("q.nav_settings"); wide: root.wide; current: root.page === "settings"; onClicked: root.navigate("settings") }
        NxSidebarItem { iconName: "panel-left"; text: root.wide ? I18n.t("q.sidebar_collapse") : I18n.t("q.sidebar_expand"); wide: root.wide; onClicked: root.toggleWide() }
    }

    // --- Горизонтальная полоса (сверху или снизу) ---
    Row {
        visible: root.horizontal
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4
        Logo { showName: true; anchors.verticalCenter: parent.verticalCenter }
        Item { width: 12; height: 1 }
        Repeater {
            model: [
                { page: "library", icon: "library", text: I18n.t("q.nav_library") },
                { page: "catalog", icon: "compass", text: I18n.t("q.nav_catalog") },
                { page: "network", icon: "globe", text: I18n.t("q.nav_network") },
                { page: "settings", icon: "sliders", text: I18n.t("q.nav_settings") }
            ]
            delegate: NxSidebarItem {
                required property var modelData
                width: 46 + labelMetrics.advanceWidth + 16
                anchors.verticalCenter: parent ? parent.verticalCenter : undefined
                iconName: modelData.icon
                text: modelData.text
                wide: true
                current: root.page === modelData.page || (modelData.page === "library" && root.page === "wizard")
                onClicked: root.navigate(modelData.page)
                TextMetrics { id: labelMetrics; text: modelData.text; font.pixelSize: 13; font.weight: Font.DemiBold; font.family: NxTheme.fontUi }
            }
        }
    }
}
