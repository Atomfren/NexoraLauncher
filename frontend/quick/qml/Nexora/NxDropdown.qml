// Выпадающий список: model — массив { value, label, loader? }
import QtQuick

Rectangle {
    id: root
    property var model: []
    property string value: ""
    property string label: ""
    property string placeholder: ""
    property bool alignRight: false
    signal activated(string value)

    readonly property var current: {
        for (let i = 0; i < model.length; ++i) if (model[i].value === value) return model[i]
        return null
    }

    implicitWidth: Math.min(320, row.implicitWidth + 36)
    implicitHeight: 32
    radius: NxTheme.rInput
    color: area.containsMouse || menu.opened ? NxTheme.surface3 : NxTheme.surface2
    Behavior on color { ColorAnimation { duration: NxTheme.fast } }

    Row {
        id: row
        x: 10
        width: Math.min(implicitWidth, root.width - 36)
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        clip: true
        NxText { visible: root.label !== ""; text: root.label; muted: true; anchors.verticalCenter: parent.verticalCenter }
        NxLoaderMark {
            visible: !!(root.current && root.current.loader)
            loader: root.current && root.current.loader ? root.current.loader : "vanilla"
            size: 14
            anchors.verticalCenter: parent.verticalCenter
        }
        NxText {
            text: root.current ? root.current.label : root.placeholder
            muted: !root.current
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    NxIcon { name: "chevron-down"; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: menu.opened ? menu.close() : menu.openBelow()
    }

    NxPopover {
        id: menu
        parent: root
        width: Math.max(root.width, list.implicitWidth + 8)
        x: root.alignRight ? root.width - width : 0
        y: root.height + 4
        height: Math.min(list.implicitHeight + 8, 288)

        function openBelow() { open() }

        contentItem: Flickable {
            clip: true
            contentHeight: list.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: list
                width: parent.width
                Repeater {
                    model: root.model
                    delegate: NxMenuItem {
                        required property var modelData
                        text: modelData.label
                        checked: modelData.value === root.value
                        onTriggered: { menu.close(); if (modelData.value !== root.value) root.activated(modelData.value) }
                    }
                }
            }
        }
    }
}
