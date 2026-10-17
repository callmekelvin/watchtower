from datetime import datetime, timezone
from typing import List

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtMultimedia import QMediaDevices, QCameraDevice

from backend.models import MediaDevice, VideoFormat

# Convert Device ID from Bytes to String
def _decode_id(device_id: bytes) -> str:
    return bytes(device_id).decode("utf-8", errors="replace")

# Format Pixel Format Name
def _pixel_format_name(pixel_format) -> str:
    return pixel_format.name if hasattr(pixel_format, "name") else str(pixel_format)

# Obtain Photo Resolution for Camera Device
def _largest_photo_resolution(device: QCameraDevice) -> list[str]:
    photo_sizes = device.photoResolutions()
    if not photo_sizes:
        return []

    largest = max(photo_sizes, key=lambda size: size.width() * size.height())
    return [f"{largest.width()}x{largest.height()}"]

# Obtain Best Video Format for Camera Device
def _best_video_format(device: QCameraDevice) -> list[VideoFormat]:
    qt_formats = device.videoFormats()
    if not qt_formats:
        return []

    max_area = max(
        fmt.resolution().width() * fmt.resolution().height() for fmt in qt_formats
    )
    at_max_resolution = [
        fmt
        for fmt in qt_formats
        if fmt.resolution().width() * fmt.resolution().height() == max_area
    ]
    best = max(at_max_resolution, key=lambda fmt: fmt.maxFrameRate())

    return [
        VideoFormat(
            resolution=f"{best.resolution().width()}x{best.resolution().height()}",
            width=best.resolution().width(),
            height=best.resolution().height(),
            min_frame_rate=best.minFrameRate(),
            max_frame_rate=best.maxFrameRate(),
            pixel_format=_pixel_format_name(best.pixelFormat()),
        )
    ]


# Convert QCameraDevice to Custom Media Device Model
def _to_media_device(device: QCameraDevice) -> MediaDevice:
    return MediaDevice(
        device_id=_decode_id(device.id()),
        description=device.description(),
        is_default=device.isDefault(),
        photo_resolutions=_largest_photo_resolution(device),
        video_formats=_best_video_format(device),
    )


class DeviceWorker(QObject):
    """Runs QMediaDevices monitoring on a dedicated thread.

    This QObject must be moved to a QThread. QMediaDevices is created inside
    ``start_monitoring`` so that it has the worker thread's affinity and its
    signals/slots run on that thread rather than blocking the main thread.
    """

    # Emitted when the device list changes or an explicit refresh completes.
    # Args: list of MediaDevice models, UTC datetime of the refresh.
    devicesChanged = Signal(list, object)

    # Emitted when monitoring or enumeration fails.
    errorOccurred = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._media_devices: QMediaDevices | None = None

    # Function - Initialize QMediaDevices on the worker thread and refresh once initially
    @Slot()
    def start_monitoring(self) -> None:
        try:
            if self._media_devices is not None:
                return

            self._media_devices = QMediaDevices(self)
            self._media_devices.videoInputsChanged.connect(self._on_video_inputs_changed)
            self._refresh()
        except Exception as exc:
            self.errorOccurred.emit(f"Failed to start device monitoring: {exc}")

    # Function - Trigger video inputs retrieval refresh on the worker thread.
    @Slot()
    def refresh_devices(self) -> None:
        """"""
        self._refresh()

    # Handler for QMediaDevices.videoInputsChanged signal - Trigger Refresh
    def _on_video_inputs_changed(self) -> None:
        self._refresh()

    # Enumerate video inputs and emit the results (or an error)
    def _refresh(self) -> None:
        try:
            devices = [
                _to_media_device(device)
                for device in QMediaDevices.videoInputs()
            ]
            timestamp = datetime.now(timezone.utc)
            self.devicesChanged.emit(devices, timestamp)
        except Exception as exc:
            self.errorOccurred.emit(f"Failed to enumerate video devices: {exc}")
