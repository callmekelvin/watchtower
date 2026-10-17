
from typing import Any, Dict, List
from PySide6.QtCore import QObject, Signal, Slot, Property
from backend.device_manager import DeviceManager

def _device_to_dict(device) -> Dict[str, Any]:
    return {
        "deviceId": device.device_id,
        "description": device.description,
        "isDefault": device.is_default,
    }

class QmlBridge(QObject):

    # QML property notification signal for videoInputs
    videoInputsChanged = Signal()  

    def __init__(self, device_manager: DeviceManager, parent: QObject | None = None):
        super().__init__(parent)
        self._device_manager = device_manager

        # Notify of backend device changes to update the videoInputs QML property via notification signal
        self._device_manager.videoInputsChanged.connect(self.videoInputsChanged)

    @Property(list, notify=videoInputsChanged)
    def videoInputs(self) -> List[Dict[str, Any]]:
        return [_device_to_dict(d) for d in self._device_manager.video_inputs()]

    @Slot()
    def refreshDevices(self) -> None:
        # Trigger QML to re-evaluate the videoInputs property.
        self.videoInputsChanged.emit()
