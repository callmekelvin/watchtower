import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property var device
    property bool isSelected: false

    signal clicked()

    implicitHeight: contentLayout.implicitHeight + 16
    height: implicitHeight
    color: isSelected ? "#e0f0ff" : "white"
    border.color: isSelected ? "#2080ff" : "#cccccc"
    border.width: 1
    radius: 4
    clip: true

    ColumnLayout {
        id: contentLayout

        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 8
        spacing: 6

        // Header
        ColumnLayout {
            spacing: 2

            Label {
                text: root.device.description + (root.device.isDefault ? " (Default)" : "")
                font.bold: true
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Label {
                text: "ID: " + root.device.deviceId
                font.pointSize: 8
                color: "gray"
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Label {
                text: "Photo: " + (root.device.photoResolutions.length > 0 ? root.device.photoResolutions[0] : "N/A")
                font.pointSize: 8
                color: "gray"
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        // Video formats panel — always expanded
        ColumnLayout {
            spacing: 2

            Label {
                text: "Video format:"
                font.pointSize: 9
                font.bold: true
                Layout.fillWidth: true
            }

            Repeater {
                model: root.device.videoFormats

                Label {
                    text: modelData.resolution + " @ " + modelData.minFrameRate + "-" + modelData.maxFrameRate + " fps, " + modelData.pixelFormat
                    font.pointSize: 8
                    color: "gray"
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        onClicked: root.clicked()
    }
}
