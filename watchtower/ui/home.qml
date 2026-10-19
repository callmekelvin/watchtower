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

            // Stack of Camera Capture Items - Only show selected Camera Device at one time
            StackLayout {
                id: captureStack
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 650
                currentIndex: {
                    if (!cameraList.selectedDeviceId || !bridge) {
                        return -1;
                    }
                    for (var i = 0; i < bridge.videoInputs.length; i++) {
                        if (bridge.videoInputs[i].deviceId === cameraList.selectedDeviceId) {
                            return i;
                        }
                    }
                    return -1;
                }

                Repeater {
                    model: bridge ? bridge.videoInputs : []

                    CameraCapture {
                        device: modelData
                        title: "Screen Capture"
                    }
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
