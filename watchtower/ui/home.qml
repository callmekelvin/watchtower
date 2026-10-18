import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: mainWindow
    visible: true
    width: 1024
    height: 768
    title: "Watchtower"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        // Toolbar
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Layout.alignment: Qt.AlignRight

            Button {
                text: "Refresh Devices"
                onClicked: bridge && bridge.refreshDevices()
            }

            Label {
                id: lastRefreshLabel
                text: bridge && bridge.lastRefreshTime ? "Last refreshed: " + bridge.lastRefreshTime : ""
                visible: text !== ""
            }
        }

        // Camera Device list and capture preview
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            DeviceList {
                id: cameraList
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 350
                title: "Cameras"
                devices: bridge ? bridge.videoInputs : []
                selectedDeviceId: bridge && bridge.captureManager ? bridge.captureManager.currentDeviceId : ""
                onDeviceSelected: deviceId => {
                    // For the Selected Device ID
                    if (bridge && bridge.captureManager) {
                        bridge.captureManager.setCameraById(deviceId);
                    }
                }
            }

            CameraCapture {
                id: cameraCapture
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 650
                title: "Screen Capture"
                device: {
                    // Don't show any Cameras if none are selected
                    if (!cameraList.selectedDeviceId || !bridge) {
                        return null;
                    }

                    // Show the Selected Camera Device
                    for (var i = 0; i < bridge.videoInputs.length; i++) {
                        if (bridge.videoInputs[i].deviceId === cameraList.selectedDeviceId) {
                            return bridge.videoInputs[i];
                        }
                    }
                    return null;
                }
            }
        }

        // Error / status area
        Label {
            id: errorLabel
            Layout.fillWidth: true
            text: ""
            color: "red"
            wrapMode: Text.Wrap
            visible: text !== ""
        }
    }

    Connections {
        target: bridge
        function onErrorOccurred(message) {
            errorLabel.text = message;
        }
    }

    Connections {
        target: bridge ? bridge.captureManager : null
        function onErrorOccurred(message) {
            errorLabel.text = message;
        }
    }
}
