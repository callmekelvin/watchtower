from PySide6.QtCore import QObject, Slot, Signal
from PySide6.QtMultimedia import QMediaDevices, QCameraDevice
from backend.models import MediaDevice

def _decode_id(device_id: bytes) -> str:
    return bytes(device_id).decode("utf-8", errors="replace")

def _map_to_media_device(device) -> MediaDevice:
    return MediaDevice(
        device_id=_decode_id(device.id()),
        description=device.description(),
        is_default=device.isDefault(),
    )

class QmlBridge(QObject):

    def __init__(self):
        super().__init__()

    @Slot(result=None)
    def get_video_inputs(self) -> None:
        for device in QMediaDevices.videoInputs():
            test = _map_to_media_device(device)
            print(test)
        return
