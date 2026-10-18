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

            // Create a Camera Device Item for each Device in the devices List
            Repeater {
                model: root.devices
                
                CameraDeviceItem {
                    Layout.fillWidth: true
                    device: modelData

                    // If Clicked -> Set this Camera as the Current Selected Device
                    isSelected: root.selectedDeviceId === modelData.deviceId
                    onClicked: root.deviceSelected(modelData.deviceId)
                }
            }
        }
    }
}
