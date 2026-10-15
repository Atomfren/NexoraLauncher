// Переключатель аккаунтов над кнопкой аккаунта в боковой панели
import QtQuick

NxPopover {
    id: root
    width: 260
    signal addAccount()
    signal manage()

    contentItem: Column {
        NxText { leftPadding: 8; topPadding: 8; height: 28; text: I18n.t("q.account"); variant: "caption" }
        Repeater {
            model: Shell.accounts
            delegate: Rectangle {
                id: row
                required property var modelData
                width: root.availableWidth
                height: 44
                radius: 4
                color: area.containsMouse ? NxTheme.fill1 : "transparent"
                NxCover { id: face; x: 8; width: 28; height: 28; radius: 4; anchors.verticalCenter: parent.verticalCenter; source: "image://nx/head/" + row.modelData.seed }
                Column {
                    anchors.left: face.right; anchors.leftMargin: 10
                    anchors.right: check.left; anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    NxText { width: parent.width; text: row.modelData.name; variant: "strong" }
                    NxText { width: parent.width; text: row.modelData.kind; muted: true; font.pixelSize: 12; lineHeight: 16 }
                }
                NxIcon { id: check; visible: row.modelData.active; name: "check"; color: NxTheme.accent; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { root.close(); if (!row.modelData.active) Shell.activateAccount(row.modelData.id) }
                }
            }
        }
        Item { width: 1; height: 8 }
        NxMenuItem { width: root.availableWidth; iconName: "plus"; text: I18n.t("q.add_account"); onTriggered: { root.close(); root.addAccount() } }
        NxMenuItem { width: root.availableWidth; iconName: "user"; text: I18n.t("q.manage_accounts"); onTriggered: { root.close(); root.manage() } }
    }
}
