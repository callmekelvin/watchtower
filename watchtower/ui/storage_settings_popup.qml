import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

// Modal popup for configuring storage purge policy and viewing disk usage.
Popup {
    id: root

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    anchors.centerIn: parent
    width: 520
    height: 600
    padding: 20

    // Backing values loaded from the backend - If none present, load defaults.
    // Storage policies are applied when the user clicks Save.
    // Managed folders are edited live.
    property int minFreeSpaceGb: 5
    property int maxRetentionDays: 30
    property int checkIntervalMinutes: 5
    property bool purgeActiveOnly: false
    property string diskStatusText: ""
    property real diskUsageRatio: 0.0

    // Triggered when the popup is opened.
    onOpened: {
        if (bridge) {
            bridge.loadStoragePolicy();
            root.minFreeSpaceGb = bridge.minFreeSpaceGb;
            root.maxRetentionDays = bridge.maxRetentionDays;
            root.checkIntervalMinutes = bridge.checkIntervalMinutes;
            root.purgeActiveOnly = bridge.purgeActiveOnly;
            root.diskStatusText = bridge.storageStatusText;
            root.diskUsageRatio = bridge.storageUsageRatio;
        }
    }

    // Select folders to apply storage policies.
    FolderDialog {
        id: addFolderDialog
        onAccepted: {
            if (bridge && selectedFolder.toString() !== "") {
                bridge.addManagedFolder(selectedFolder.toString());
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        Label {
            text: "Storage Settings"
            font.bold: true
            font.pointSize: 12
        }

        Label {
            text: "Storage Policy"
            font.bold: true
        }

        GridLayout {
            columns: 2
            columnSpacing: 12
            rowSpacing: 12

            Label { text: "Minimum free space (GB):" }
            SpinBox {
                id: minFreeSpaceSpin
                from: 0
                to: 9999
                value: root.minFreeSpaceGb
            }

            Label { text: "Maximum retention age (days):" }
            SpinBox {
                id: maxRetentionSpin
                from: 1
                to: 3650
                value: root.maxRetentionDays
            }

            Label { text: "Purge check interval (minutes):" }
            SpinBox {
                id: intervalSpin
                from: 1
                to: 1440
                value: root.checkIntervalMinutes
            }
        }

        Switch {
            id: purgeActiveOnlySwitch
            text: "Purge active recording folders only"
            checked: root.purgeActiveOnly
        }

        Label {
            text: "Managed Folders"
            font.bold: true
        }

        Label {
            text: "Folders are added automatically when recording starts. " +
                  "You can also add or remove folders manually."
            wrapMode: Text.Wrap
            Layout.fillWidth: true
            font.pointSize: 8
            color: "#666666"
        }

        ListView {
            id: managedFoldersList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 80
            clip: true
            model: bridge ? bridge.managedFolders : []
            spacing: 4

            delegate: Rectangle {
                width: managedFoldersList.width
                height: 32
                color: "#f0f0f0"
                radius: 4

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 8

                    Label {
                        text: modelData
                        elide: Text.ElideMiddle
                        Layout.fillWidth: true
                        font.pointSize: 8
                    }

                    Button {
                        text: "Remove"
                        flat: true
                        font.pointSize: 8
                        onClicked: {
                            if (bridge) {
                                bridge.removeManagedFolder(modelData);
                            }
                        }
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                text: "No managed folders"
                color: "#888888"
                visible: managedFoldersList.count === 0
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Button {
                text: "Add Folder"
                onClicked: addFolderDialog.open()
            }

            Button {
                text: "Clear All"
                onClicked: {
                    if (bridge) {
                        bridge.clearManagedFolders();
                    }
                }
            }

            Item {
                Layout.fillWidth: true
            }
        }

        Label {
            text: "Current disk usage"
            font.bold: true
        }

        ProgressBar {
            id: usageProgressBar
            Layout.fillWidth: true
            from: 0.0
            to: 1.0
            value: root.diskUsageRatio
        }

        Label {
            text: root.diskStatusText
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: 12
            spacing: 8

            Item {
                Layout.fillWidth: true
            }

            Button {
                text: "Purge Now"
                onClicked: {
                    if (bridge) {
                        bridge.triggerPurgeNow();
                    }
                }
            }

            Button {
                text: "Cancel"
                onClicked: root.close()
            }

            Button {
                text: "Save"
                onClicked: {
                    if (bridge) {
                        bridge.saveStoragePolicy(
                            minFreeSpaceSpin.value,
                            maxRetentionSpin.value,
                            intervalSpin.value
                        );
                        bridge.setPurgeActiveOnly(purgeActiveOnlySwitch.checked);
                    }
                    root.close();
                }
            }
        }
    }

    Connections {
        target: bridge
        function onStoragePolicyChanged() {
            if (root.opened) {
                root.minFreeSpaceGb = bridge.minFreeSpaceGb;
                root.maxRetentionDays = bridge.maxRetentionDays;
                root.checkIntervalMinutes = bridge.checkIntervalMinutes;
                root.purgeActiveOnly = bridge.purgeActiveOnly;
            }
        }
        function onStorageStatusChanged() {
            if (root.opened) {
                root.diskStatusText = bridge.storageStatusText;
                root.diskUsageRatio = bridge.storageUsageRatio;
            }
        }
    }
}
