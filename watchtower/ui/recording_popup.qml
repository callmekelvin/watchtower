import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

// Modal popup used to choose an output folder before starting a recording
Popup {
    id: root

    property string deviceId: ""
    property string deviceDescription: ""

    signal startRecording(string folderPath)

    modal: true
    focus: true

    // Pressing Escape or Close Cancel Button will Exit Pop Up
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    anchors.centerIn: parent
    width: 420
    height: 240
    padding: 20

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        Label {
            text: "Start Recording"
            font.bold: true
            font.pointSize: 12
            Layout.fillWidth: true
        }

        Label {
            text: root.deviceDescription ? "Device: " + root.deviceDescription : ""
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            visible: text !== ""
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Button {
                text: "Select Folder"
                onClicked: folderDialog.open()
            }

            Label {
                id: selectedFolderLabel
                text: folderDialog.selectedFolder.toString() !== ""
                    ? "Save to: " + folderDialog.selectedFolder.toString().replace("file://", "")
                    : "No folder selected"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                elide: Text.ElideMiddle
            }
        }

        Item {
            Layout.fillHeight: true
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: 12
            spacing: 8

            Item {
                Layout.fillWidth: true
            }

            Button {
                text: "Cancel"
                onClicked: root.close()
            }

            Button {
                text: "Start Recording"
                enabled: folderDialog.selectedFolder.toString() !== ""
                onClicked: {
                    root.startRecording(folderDialog.selectedFolder.toString());
                    root.close();
                }
            }
        }
    }

    // Use Native Platform Folder Dialogs - Access Selected Folder Via Folder Dialog Name ID
    FolderDialog {
        id: folderDialog
    }
}
