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

    color: "#1a1a1a"
    radius: 4

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
                    if (bridge && bridge.captureManager && videoOutput.videoSink) {
                        bridge.captureManager.setVideoSink(videoOutput.videoSink);
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

            // Manual record button - functionality not implemented yet.
            Button {
                text: "Record"
                enabled: false
                Layout.alignment: Qt.AlignLeft
                // onClicked: {
                //     // TODO: wire to CaptureSessionManager.startRecording()
                // }
            }
        }
    }
}
