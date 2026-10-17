from typing import List

from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QMediaDevices, QCameraDevice

from backend.models import MediaDevice

# Convert Device ID from Bytes to String
def _decode_id(device_id: bytes) -> str:
    return bytes(device_id).decode("utf-8", errors="replace")

# Convert QCameraDevice to Custom Media Device Model
def _to_media_device(device) -> MediaDevice:
    return MediaDevice(
        device_id=_decode_id(device.id()),
        description=device.description(),
        is_default=device.isDefault(),
    )

# Retrieves QMediaDevices 
class DeviceManager(QObject):

    # Device Manager signal emitted when available video inputs change.
    videoInputsChanged = Signal()  

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._media_devices = QMediaDevices()
        # Forward QT hardware change event to backend QML Bridge Listener
        self._media_devices.videoInputsChanged.connect(self.videoInputsChanged)

    def video_inputs(self) -> List[MediaDevice]:
        return [
            _to_media_device(device)
            for device in QMediaDevices.videoInputs()
        ]

    def find_camera_device(self, device_id: str) -> QCameraDevice | None:
        for device in QMediaDevices.videoInputs():
            if _decode_id(device.id()) == device_id:
                return device
        return None