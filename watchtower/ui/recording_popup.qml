import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

// Modal popup used to choose an output destination before starting a recording.
// The user may select either a local folder or a configured NAS connection.
Popup {
    id: root

    property string deviceId: ""
    property string deviceDescription: ""

    signal startRecording(string folderPath)
    signal startRecordingToNas(string connectionId)

    modal: true
    focus: true

    // Pressing Escape or Close Cancel Button will Exit Pop Up
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    anchors.centerIn: parent
    width: 460
    height: 360
    padding: 20

    onOpened: {
        destinationTabs.currentIndex = 0;
        folderDialog.selectedFolder = "";
        nasConnectionBox.currentIndex = 0;
    }

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

        TabBar {
            id: destinationTabs
            Layout.fillWidth: true

            TabButton {
                text: "Local Folder"
            }

            TabButton {
                text: "NAS"
                enabled: bridge && bridge.nasConnections.length > 0
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: destinationTabs.currentIndex

            // Local folder tab
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

            // NAS tab
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    text: "Select NAS connection:"
                }

                ComboBox {
                    id: nasConnectionBox
                    Layout.fillWidth: true
                    textRole: "name"
                    valueRole: "id"
                    model: bridge ? bridge.nasConnections : []
                    enabled: bridge && bridge.nasConnections.length > 0
                }

                Label {
                    text: {
                        var conn = bridge && bridge.nasConnections ? bridge.nasConnections[nasConnectionBox.currentIndex] : null;
                        if (conn) {
                            return "Status: " + (conn.status === "connected" ? "Connected" : "Disconnected") +
                                   "\nShare: " + conn.share;
                        }
                        return "";
                    }
                    color: "#666666"
                    font.pointSize: 8
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                    visible: bridge && bridge.nasConnections.length > 0
                }

                Label {
                    text: "No NAS connections configured. Add one in NAS Settings."
                    color: "#888888"
                    visible: bridge && bridge.nasConnections.length === 0
                }
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
                enabled: {
                    if (destinationTabs.currentIndex === 0) {
                        return folderDialog.selectedFolder.toString() !== "";
                    }
                    return bridge && bridge.nasConnections.length > 0 && nasConnectionBox.currentIndex >= 0;
                }
                onClicked: {
                    if (destinationTabs.currentIndex === 0) {
                        root.startRecording(folderDialog.selectedFolder.toString());
                    } else {
                        var connId = nasConnectionBox.currentValue;
                        if (connId) {
                            root.startRecordingToNas(connId);
                        }
                    }
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
