import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Modal popup for creating, editing, connecting, and disconnecting NAS connections.
Popup {
    id: root

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    anchors.centerIn: parent
    width: 560
    height: 560
    padding: 20

    // Editing state for the add/edit form.
    property string editingId: ""
    property string editName: ""
    property string editProtocol: "smb"
    property string editHost: ""
    property string editShare: ""
    property string editUsername: ""
    property string editDomain: ""
    property string editMountOptions: ""

    onOpened: {
        resetForm();
    }

    function resetForm() {
        editingId = "";
        editName = "";
        editProtocol = "smb";
        editHost = "";
        editShare = "";
        editUsername = "";
        editDomain = "";
        editMountOptions = "";
    }

    function editConnection(conn) {
        editingId = conn.id;
        editName = conn.name;
        editProtocol = conn.protocol;
        editHost = conn.host;
        editShare = conn.share;
        editUsername = conn.username || "";
        editDomain = conn.domain || "";
        editMountOptions = conn.mount_options || "";
    }

    function saveCurrentConnection() {
        if (!bridge) {
            return;
        }
        if (editName.trim() === "" || editHost.trim() === "" || editShare.trim() === "") {
            return;
        }
        bridge.saveNasConnection({
            id: editingId,
            name: editName.trim(),
            protocol: editProtocol,
            host: editHost.trim(),
            share: editShare.trim(),
            username: editUsername.trim() || null,
            domain: editDomain.trim() || null,
            mount_options: editMountOptions.trim() || null,
            enabled: true
        });
        resetForm();
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        Label {
            text: "NAS Settings"
            font.bold: true
            font.pointSize: 12
        }

        // Connections list
        ListView {
            id: connectionsList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 120
            clip: true
            model: bridge ? bridge.nasConnections : []
            spacing: 6

            delegate: Rectangle {
                width: connectionsList.width
                height: 72
                color: "#f5f5f5"
                radius: 4
                border.color: modelData.status === "connected" ? "#4caf50" : "#cccccc"
                border.width: 2

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 10

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Label {
                            text: modelData.name
                            font.bold: true
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }

                        Label {
                            text: modelData.protocol.toUpperCase() + " - " + modelData.share
                            font.pointSize: 8
                            color: "#555555"
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }

                        Label {
                            text: modelData.status === "connected" ? "Connected" : "Disconnected"
                            font.pointSize: 8
                            color: modelData.status === "connected" ? "#4caf50" : "#888888"
                        }
                    }

                    Button {
                        text: modelData.status === "connected" ? "Disconnect" : "Connect"
                        enabled: !bridge.anyRecordingActive
                        flat: true
                        font.pointSize: 8
                        onClicked: {
                            if (modelData.status === "connected") {
                                bridge.requestNasDisconnect(modelData.id);
                            } else {
                                bridge.requestNasConnect(modelData.id);
                            }
                        }
                    }

                    Button {
                        text: "Edit"
                        flat: true
                        font.pointSize: 8
                        onClicked: root.editConnection(modelData)
                    }

                    Button {
                        text: "Delete"
                        flat: true
                        font.pointSize: 8
                        onClicked: bridge.deleteNasConnection(modelData.id)
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                text: "No NAS connections configured"
                color: "#888888"
                visible: connectionsList.count === 0
            }
        }

        // Add/Edit form
        GridLayout {
            columns: 2
            columnSpacing: 12
            rowSpacing: 10
            Layout.fillWidth: true

            Label { text: "Name:" }
            TextField {
                id: nameField
                Layout.fillWidth: true
                text: root.editName
                onTextChanged: root.editName = text
            }

            Label { text: "Protocol:" }
            ComboBox {
                id: protocolBox
                model: ["smb", "nfs"]
                currentIndex: root.editProtocol === "nfs" ? 1 : 0
                onCurrentIndexChanged: root.editProtocol = model[currentIndex]
            }

            Label { text: "Host:" }
            TextField {
                id: hostField
                Layout.fillWidth: true
                text: root.editHost
                onTextChanged: root.editHost = text
            }

            Label { text: "Share:" }
            TextField {
                id: shareField
                Layout.fillWidth: true
                text: root.editShare
                onTextChanged: root.editShare = text
            }

            Label { text: "Username:" }
            TextField {
                id: userField
                Layout.fillWidth: true
                text: root.editUsername
                onTextChanged: root.editUsername = text
            }

            Label { text: "Domain:" }
            TextField {
                id: domainField
                Layout.fillWidth: true
                text: root.editDomain
                onTextChanged: root.editDomain = text
            }

            Label { text: "Mount options:" }
            TextField {
                id: optionsField
                Layout.fillWidth: true
                text: root.editMountOptions
                onTextChanged: root.editMountOptions = text
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Button {
                text: "Save"
                enabled: nameField.text.trim() !== "" && hostField.text.trim() !== "" && shareField.text.trim() !== ""
                onClicked: root.saveCurrentConnection()
            }

            Button {
                text: "Clear"
                onClicked: root.resetForm()
            }

            Item {
                Layout.fillWidth: true
            }

            Label {
                text: "Connect/Disconnect is disabled while recording."
                color: "#888888"
                font.pointSize: 8
                visible: bridge && bridge.anyRecordingActive
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: 12
            spacing: 8

            Item {
                Layout.fillWidth: true
            }

            Button {
                text: "Close"
                onClicked: root.close()
            }
        }
    }
}
