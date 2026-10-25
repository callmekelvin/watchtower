import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

// Right-hand panel that shows the live camera preview for the selected device.
// When no device is selected the panel is blank with a placeholder message.
Rectangle {
    id: root

    property var device: null
    property string title: "Screen Capture"
    property bool isRecording: false

    color: "#1a1a1a"
    radius: 4

    function updateRecordingState() {
        root.isRecording = bridge && bridge.captureManager && root.device
            ? bridge.captureManager.isDeviceRecording(root.device.deviceId)
            : false;
    }

    Component.onCompleted: {
        updateRecordingState();
    }

    onDeviceChanged: {
        updateRecordingState();
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 12

        Label {
            text: root.title
            font.bold: true
            color: "white"
            visible: root.device !== null
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            VideoOutput {
                id: videoOutput

                anchors.fill: parent
                fillMode: VideoOutput.PreserveAspectFit
                visible: root.device !== null

                Component.onCompleted: {
                    if (bridge && bridge.captureManager && root.device && videoOutput.videoSink) {
                        bridge.captureManager.setVideoSinkForDevice(root.device.deviceId, videoOutput.videoSink);
                    }
                }

                Component.onDestruction: {
                    if (bridge && bridge.captureManager && root.device) {
                        bridge.captureManager.clearVideoSinkForDevice(root.device.deviceId);
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                text: "Select a device to view its capture"
                color: "white"
                font.pointSize: 12
                visible: root.device === null
            }
        }

        ColumnLayout {
            visible: root.device !== null
            Layout.fillWidth: true
            spacing: 8

            Label {
                text: root.device ? root.device.description : ""
                color: "white"
                font.bold: true
                font.pointSize: 11
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }

            Label {
                text: root.device ? "ID: " + root.device.deviceId : ""
                color: "#aaaaaa"
                font.pointSize: 8
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }

            // Recording controls
            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Button {
                    id: recordButton
                    text: "Record"
                    visible: !root.isRecording
                    enabled: root.device !== null
                    Layout.alignment: Qt.AlignLeft
                    onClicked: {
                        if (bridge && bridge.captureManager && root.device) {
                            recordingPopup.deviceId = root.device.deviceId;
                            recordingPopup.deviceDescription = root.device.description;
                            recordingPopup.open();
                        }
                    }
                }

                Button {
                    id: stopButton
                    text: "Stop Recording"
                    visible: root.isRecording
                    Layout.alignment: Qt.AlignLeft
                    onClicked: {
                        if (bridge && bridge.captureManager && root.device) {
                            bridge.captureManager.stopRecordingForDevice(root.device.deviceId);
                        }
                    }
                }

                RowLayout {
                    visible: root.isRecording
                    spacing: 6

                    Rectangle {
                        width: 12
                        height: 12
                        radius: 6
                        color: "red"
                    }

                    Label {
                        text: "Recording"
                        color: "white"
                    }
                }
            }
        }
    }

    RecordingPopup {
        id: recordingPopup
        onStartRecording: folderPath => {
            if (bridge && bridge.captureManager && root.device) {
                bridge.captureManager.startRecordingForDevice(root.device.deviceId, folderPath);
            }
        }
    }

    Connections {
        target: bridge ? bridge.captureManager : null
        function onDeviceRecordingStateChanged(deviceId, recording) {
            if (root.device && deviceId === root.device.deviceId) {
                root.isRecording = recording;
            }
        }
    }
}
