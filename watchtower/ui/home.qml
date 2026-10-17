import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: mainWindow
    visible: true
    width: 800
    height: 600
    title: "Watchtower"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        // Toolbar
        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            Button {
                text: "Refresh Devices"
                onClicked: bridge.refreshDevices()
            }

            Item { Layout.fillWidth: true }
        }

        // Camera Device lists
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            DeviceList {
                id: cameraList
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "Cameras"
                devices: bridge ? bridge.videoInputs : []
                onDeviceSelected: deviceId => {
                    cameraList.selectedDeviceId = deviceId;
                }
            }
        }
    }
}
