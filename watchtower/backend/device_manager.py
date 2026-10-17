from datetime import datetime
from typing import List

from PySide6.QtCore import QObject, QThread, Signal, Slot, QMetaObject, Qt
from PySide6.QtMultimedia import QCameraDevice, QMediaDevices

from backend.device_worker import DeviceWorker, _decode_id
from backend.models import MediaDevice

# Backend layer that observes hardware camera changes on a worker thread
# The actual QMediaDevices instance lives on a dedicated QThread so that platform USB enumeration does not block the main thread
class DeviceManager(QObject):
    # Emitted when the cached list of video inputs changes.
    videoInputsChanged = Signal()

    # Emitted when monitoring or enumeration fails on the worker thread.
    errorOccurred = Signal(str)

    # Emitted when the last successful refresh timestamp changes.
    lastRefreshTimeChanged = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._devices: List[MediaDevice] = []
        self._last_refresh_time: datetime | None = None

        # Worker thread setup
        self._thread = QThread(self)
        self._worker = DeviceWorker()
        self._worker.moveToThread(self._thread)

        # Cross-thread signal forwarding (automatically queued to main thread).
        self._worker.devicesChanged.connect(self._on_devices_changed)
        self._worker.errorOccurred.connect(self.errorOccurred)

        # Clean up worker when the thread finishes.
        self._thread.finished.connect(self._worker.deleteLater)

        # Start monitoring once the thread's event loop is running.
        self._thread.started.connect(self._worker.start_monitoring)
        self._thread.start()

    def video_inputs(self) -> List[MediaDevice]:
        return list(self._devices)

    def last_refresh_time(self) -> datetime | None:
        return self._last_refresh_time

    def find_camera_device(self, device_id: str) -> QCameraDevice | None:
        # QCameraDevice value objects are queried directly here
        # This is only called from the main thread and does not interact with the worker's QMediaDevices instance.
        for device in QMediaDevices.videoInputs():
            if _decode_id(device.id()) == device_id:
                return device
        return None

    # Function - Trigger QT Worker to refresh device list
    @Slot()
    def refresh(self) -> None:
        if self._worker is not None:
            QMetaObject.invokeMethod(self._worker, "refresh_devices", Qt.QueuedConnection)

    # Function - Save new device list from the worker thread + notify QML Bridge
    @Slot(list, object)
    def _on_devices_changed(self, devices: List[MediaDevice], timestamp: datetime) -> None:
        self._devices = devices
        self._last_refresh_time = timestamp
        self.lastRefreshTimeChanged.emit()
        self.videoInputsChanged.emit()

    # Stop the worker thread gracefully - Should be called before app exit
    def shutdown(self) -> None:
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
