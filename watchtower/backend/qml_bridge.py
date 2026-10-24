from datetime import datetime
from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal, Slot, Property

from backend.device_manager import DeviceManager
from backend.capture_session_manager import CaptureSessionManager
from backend.storage_manager import StorageManager

def _device_to_dict(device) -> Dict[str, Any]:
    return {
        "deviceId": device.device_id,
        "description": device.description,
        "isDefault": device.is_default,
        "photoResolutions": device.photo_resolutions,
        "videoFormats": [
            {
                "resolution": vf.resolution,
                "width": vf.width,
                "height": vf.height,
                "minFrameRate": vf.min_frame_rate,
                "maxFrameRate": vf.max_frame_rate,
                "pixelFormat": vf.pixel_format,
            }
            for vf in device.video_formats
        ],
    }

# QML Bridge - Exposes Backend State/ Functions and Signals to QML
class QmlBridge(QObject):
    # Device Manager Signals
    # videoInputsChanged - QML property notification signal for videoInputs
    # errorOccurred - Notifies via QML UI Message when monitoring/ enumeration fails
    # lastRefreshTimeChanged - QML property notification signal for lastRefreshTime
    videoInputsChanged = Signal()
    errorOccurred = Signal(str)
    lastRefreshTimeChanged = Signal()

    # Storage Manager Signals
    # storagePolicyChanged - Notifies QML Properties in changes in Storage Policies, such as Purge Interval and Minimum Storage Space
    # storageStatusChanged - Notifies QML Properties for changes in Storage Use
    # storageCritical - Notifies via QML UI Message of Storage Failture
    storagePolicyChanged = Signal()
    storageStatusChanged = Signal()
    storageCritical = Signal(str)

    def __init__(self, device_manager: DeviceManager, capture_manager: CaptureSessionManager, storage_manager: StorageManager, parent: QObject | None = None):
        super().__init__(parent)
        self._device_manager = device_manager
        self._capture_manager = capture_manager
        self._storage_manager = storage_manager

        # Forward device manager signals
        self._device_manager.videoInputsChanged.connect(self.videoInputsChanged)
        self._device_manager.lastRefreshTimeChanged.connect(self.lastRefreshTimeChanged)
        self._device_manager.errorOccurred.connect(self.errorOccurred)

        # Forward storage manager signals
        self._storage_manager.policyChanged.connect(self.storagePolicyChanged)
        self._storage_manager.storageStatusChanged.connect(self.storageStatusChanged)
        self._storage_manager.storageCritical.connect(self.storageCritical)

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

    # Property - Access the Capture Session Manager from QML
    @Property(QObject, constant=True)
    def captureManager(self) -> CaptureSessionManager:
        return self._capture_manager

    # Property - Access the Storage Manager from QML
    @Property(QObject, constant=True)
    def storageManager(self) -> StorageManager:
        return self._storage_manager

    # Property - Minimum free space (GB)
    @Property(int, notify=storagePolicyChanged)
    def minFreeSpaceGb(self) -> int:
        return self._storage_manager.minFreeSpaceGb

    # Property - Maximum retention age (days)
    @Property(int, notify=storagePolicyChanged)
    def maxRetentionDays(self) -> int:
        return self._storage_manager.maxRetentionDays

    # Property - Purge check interval (minutes)
    @Property(int, notify=storagePolicyChanged)
    def checkIntervalMinutes(self) -> int:
        return self._storage_manager.checkIntervalMinutes

    # Property - Whether purging is limited to active recording folders
    @Property(bool, notify=storagePolicyChanged)
    def purgeActiveOnly(self) -> bool:
        return self._storage_manager.purgeActiveOnly

    # Property - Managed folders registered for purging
    @Property(list, notify=storagePolicyChanged)
    def managedFolders(self) -> List[str]:
        return self._storage_manager.managedFolders

    # Property - Current disk usage text
    @Property(str, notify=storageStatusChanged)
    def storageStatusText(self) -> str:
        return self._storage_manager.storageStatusText

    # Property - Current disk usage ratio (0.0 - 1.0)
    @Property(float, notify=storageStatusChanged)
    def storageUsageRatio(self) -> float:
        return self._storage_manager.storageUsageRatio

    # Function - Trigger Device Retrieval Worker Thread
    @Slot()
    def refreshDevices(self) -> None:
        self._device_manager.refresh()

    # Function - Save storage policy values
    @Slot(int, int, int)
    def saveStoragePolicy(self, min_free_space_gb: int, max_retention_days: int, check_interval_minutes: int) -> None:
        self._storage_manager.saveStoragePolicy(min_free_space_gb, max_retention_days, check_interval_minutes)

    # Function - Reload storage policy values from settings
    @Slot()
    def loadStoragePolicy(self) -> None:
        self._storage_manager.loadStoragePolicy()

    # Function - Manually trigger a storage purge
    @Slot()
    def triggerPurgeNow(self) -> None:
        self._storage_manager.triggerPurgeNow()

    # Function - Set whether to purge active recording folders only
    @Slot(bool)
    def setPurgeActiveOnly(self, active_only: bool) -> None:
        self._storage_manager.setPurgeActiveOnly(active_only)

    # Function - Add a folder to the managed purge registry
    @Slot(str)
    def addManagedFolder(self, folder_path: str) -> None:
        self._storage_manager.addManagedFolder(folder_path)

    # Function - Remove a folder from the managed purge registry
    @Slot(str)
    def removeManagedFolder(self, folder_path: str) -> None:
        self._storage_manager.removeManagedFolder(folder_path)

    # Function - Clear all managed folders
    @Slot()
    def clearManagedFolders(self) -> None:
        self._storage_manager.clearManagedFolders()
