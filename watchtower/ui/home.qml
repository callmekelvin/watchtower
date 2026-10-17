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
}
