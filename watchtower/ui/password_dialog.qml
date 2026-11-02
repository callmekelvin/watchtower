import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Modal password prompt used when a NAS mount requires credentials.
Popup {
    id: root

    property string connectionId: ""
    property string promptTitle: "Enter Password"
    property string promptMessage: ""

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    anchors.centerIn: parent
    width: 420
    height: 240
    padding: 20

    function openPrompt(id, title, message) {
        root.connectionId = id;
        root.promptTitle = title;
        root.promptMessage = message;
        passwordField.text = "";
        root.open();
        passwordField.forceActiveFocus();
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        Label {
            text: root.promptTitle
            font.bold: true
            font.pointSize: 12
            Layout.fillWidth: true
        }

        Label {
            text: root.promptMessage
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            visible: text !== ""
        }

        TextField {
            id: passwordField
            Layout.fillWidth: true
            echoMode: TextInput.Password
            placeholderText: "Password"
            focus: true

            Keys.onReturnPressed: {
                submitPassword();
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
                text: "OK"
                enabled: passwordField.text !== ""
                onClicked: submitPassword()
            }
        }
    }

    function submitPassword() {
        if (bridge && root.connectionId !== "") {
            bridge.submitNasPassword(root.connectionId, passwordField.text);
        }
        root.close();
    }
}
