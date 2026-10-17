from datetime import datetime
from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal, Slot, Property

from backend.device_manager import DeviceManager

def _device_to_dict(device) -> Dict[str, Any]:
    return {
        "deviceId": device.device_id,
        "description": device.description,
        "isDefault": device.is_default,
    }

# QML Bridge - Exposes Backend State to QML
class QmlBridge(QObject):
    # QML property notification signal for videoInputs
    videoInputsChanged = Signal()

    # Forwarded from DeviceManager when monitoring/ enumeration fails
    errorOccurred = Signal(str)

    # QML property notification signal for lastRefreshTime
    lastRefreshTimeChanged = Signal()

    def __init__(self, device_manager: DeviceManager, parent: QObject | None = None):
        super().__init__(parent)
        self._device_manager = device_manager

        # Notify QML of backend changes.
        self._device_manager.videoInputsChanged.connect(self.videoInputsChanged)
        self._device_manager.lastRefreshTimeChanged.connect(self.lastRefreshTimeChanged)
        self._device_manager.errorOccurred.connect(self.errorOccurred)

    # Property - Retrieve/ Subscribe to Cached Device List
    @Property(list, notify=videoInputsChanged)
    def videoInputs(self) -> List[Dict[str, Any]]:
        return [_device_to_dict(d) for d in self._device_manager.video_inputs()]

    # Property - Retrieve/ Subscribe to Last Successful Refresh Timestamp of Device Retrieval
    @Property(str, notify=lastRefreshTimeChanged)
    def lastRefreshTime(self) -> str:
        timestamp = self._device_manager.last_refresh_time()
        if timestamp is None:
            return "Not Refreshed"
        return timestamp.isoformat()

    # Function - Trigger Device Retrieval Worker Thread
    @Slot()
    def refreshDevices(self) -> None:
        self._device_manager.refresh()
