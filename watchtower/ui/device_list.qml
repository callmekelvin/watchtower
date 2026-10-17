import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root

    property string title: "Devices"
    property var devices: []
    property string selectedDeviceId: ""

    signal deviceSelected(string deviceId)

    Label {
        text: root.title
        font.bold: true
    }

    ScrollView {
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true

        ColumnLayout {
            width: parent.width
            spacing: 4

            Repeater {
                model: root.devices

                CameraDeviceItem {
                    Layout.fillWidth: true
                    device: modelData
                    isSelected: root.selectedDeviceId === modelData.deviceId
                    // onClicked intentionally disconnected for now
                }
            }
        }
    }
}
