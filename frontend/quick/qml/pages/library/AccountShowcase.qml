// Витрина аккаунта в шапке сборки: 3D-модель со скином и плащом, ник со стрелками
// переключения аккаунтов и «+» для нового. Модель можно крутить мышью.
import QtQuick
import QtQuick.Dialogs
import Nexora
import Nexora.Skin

Item {
    id: root
    readonly property var acc: Shell.account
    readonly property bool hasAccount: acc.id !== undefined
    readonly property bool many: Shell.accounts.length > 1
    property real baseYaw: 25
    property bool dragging: false

    implicitWidth: 260
    implicitHeight: 272

    NxSkinView {
        id: model
        objectName: "skinView"
        anchors.horizontalCenter: parent.horizontalCenter
        width: 180
        height: 226
        visible: root.hasAccount
        skin: Shell.skin.skin || ""
        cape: Shell.skin.cape || ""
        slim: !!Shell.skin.slim
        yaw: root.dragging ? root.baseYaw : root.baseYaw + Math.sin(time * 0.5) * 12
        opacity: ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: NxTheme.base } }

        // Дыхание: руки и плащ слегка покачиваются
        NumberAnimation on time {
            from: 0; to: Math.PI * 200
            duration: 400000
            loops: Animation.Infinite
            running: model.visible && root.visible && Qt.application.state === Qt.ApplicationActive
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
            property real lastX: 0
            onPressed: mouse => {
                lastX = mouse.x
                root.baseYaw = model.yaw
                root.dragging = true
            }
            onPositionChanged: mouse => {
                root.baseYaw += (mouse.x - lastX) * 0.9
                lastX = mouse.x
            }
            onReleased: root.dragging = false
            onClicked: mouse => { if (mouse.button === Qt.RightButton) skinMenu.openAt(nameRow) }
        }
    }

    // Нет аккаунта — приглашение добавить
    Column {
        visible: !root.hasAccount
        anchors.horizontalCenter: parent.horizontalCenter
        y: 60
        spacing: 10
        NxText { anchors.horizontalCenter: parent.horizontalCenter; text: I18n.t("q.no_account"); muted: true }
        NxButton { anchors.horizontalCenter: parent.horizontalCenter; iconName: "plus"; text: I18n.t("q.add_account"); onClicked: Shell.requestAddAccount() }
    }

    // Подпись: ‹ ник › и «+»
    Row {
        id: nameRow
        visible: root.hasAccount
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: model.bottom
        anchors.topMargin: 6
        spacing: 2
        NxIconButton {
            objectName: "prevAccount"
            small: true
            iconName: "chevron-left"
            tip: I18n.t("q.prev_account")
            visible: root.many
            anchors.verticalCenter: parent.verticalCenter
            onClicked: Shell.stepAccount(-1)
        }
        Rectangle {
            id: nameChip
            width: Math.min(150, nameCol.implicitWidth + 20)
            height: 40
            radius: NxTheme.rButton
            color: chipArea.containsMouse ? Qt.rgba(NxTheme.bg.r, NxTheme.bg.g, NxTheme.bg.b, 0.75) : Qt.rgba(NxTheme.bg.r, NxTheme.bg.g, NxTheme.bg.b, 0.55)
            Behavior on color { ColorAnimation { duration: NxTheme.fast } }
            Column {
                id: nameCol
                anchors.centerIn: parent
                width: Math.min(130, implicitWidth)
                NxText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(130, implicitWidth)
                    text: root.acc.name || ""
                    variant: "strong"
                    horizontalAlignment: Text.AlignHCenter
                    lineHeight: 18
                }
                NxText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.acc.kind || ""
                    muted: true
                    font.pixelSize: 11
                    lineHeight: 14
                }
            }
            MouseArea {
                id: chipArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: skinMenu.openAt(nameChip)
            }
        }
        NxIconButton {
            objectName: "nextAccount"
            small: true
            iconName: "chevron-right"
            tip: I18n.t("q.next_account")
            visible: root.many
            anchors.verticalCenter: parent.verticalCenter
            onClicked: Shell.stepAccount(1)
        }
        NxIconButton {
            small: true
            iconName: "plus"
            tip: I18n.t("q.add_account")
            anchors.verticalCenter: parent.verticalCenter
            onClicked: Shell.requestAddAccount()
        }
    }

    NxMenu {
        id: skinMenu
        items: [
            { text: I18n.t("q.skin_pick_wide"), icon: "user", action: "wide" },
            { text: I18n.t("q.skin_pick_slim"), icon: "user", action: "slim" },
            { text: I18n.t("q.cape_pick"), icon: "image", action: "cape" },
            { text: I18n.t("q.skin_reset_item"), icon: "refresh", action: "reset" },
            { separator: true },
            { text: I18n.t("q.all_accounts"), icon: "users", action: "manage" }
        ]
        onTriggered: action => {
            if (action === "wide" || action === "slim") { skinDialog.slim = action === "slim"; skinDialog.open() }
            else if (action === "cape") capeDialog.open()
            else if (action === "reset") Shell.resetSkin()
            else if (action === "manage") Shell.navigate("settings", "accounts")
        }
    }

    FileDialog {
        id: skinDialog
        property bool slim: false
        fileMode: FileDialog.OpenFile
        nameFilters: [I18n.t("q.skin_file") + " (*.png)"]
        onAccepted: Shell.chooseSkin(selectedFile.toString(), slim)
    }
    FileDialog {
        id: capeDialog
        fileMode: FileDialog.OpenFile
        nameFilters: [I18n.t("q.cape_file") + " (*.png)"]
        onAccepted: Shell.chooseCape(selectedFile.toString())
    }
}
