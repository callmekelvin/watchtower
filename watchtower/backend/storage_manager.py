import os
from typing import List, Set

from PySide6.QtCore import QObject, QDir, QSettings, QStorageInfo, QThread, Signal, Slot, Property, QTimer

from backend.storage_purge_worker import StoragePurgeWorker


class StorageManager(QObject):
    """Main-thread owner of the storage purge policy and disk-usage status.

    Policy values are persisted via QSettings. The manager coordinates the
    StoragePurgeWorker (which lives on a background thread) and notifies the
    rest of the application through policyChanged, storageStatusChanged and
    storageCritical signals.
    """

    policyChanged = Signal()
    storageStatusChanged = Signal()
    storageCritical = Signal(str)

    # Cross-thread signals used to communicate with StoragePurgeWorker.
    _setCheckIntervalMinutes = Signal(int)
    _dispatchPurge = Signal(list, set, list, bool, int, int, str)
    _startPurgeTimer = Signal()
    _stopPurgeTimer = Signal()

    # Default policy values.
    DEFAULT_MIN_FREE_SPACE_GB = 5
    DEFAULT_MAX_RETENTION_DAYS = 30
    DEFAULT_CHECK_INTERVAL_MINUTES = 5
    DEFAULT_PURGE_ACTIVE_ONLY = False

    # How often the disk-usage status is refreshed (ms).
    _STATUS_REFRESH_INTERVAL_MS = 5000

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        # Persistant Settings for Application (Key Value Pair)
        self._settings = QSettings("Watchtower", "Watchtower")
        self._min_free_space_gb: int = self.DEFAULT_MIN_FREE_SPACE_GB
        self._max_retention_days: int = self.DEFAULT_MAX_RETENTION_DAYS
        self._check_interval_minutes: int = self.DEFAULT_CHECK_INTERVAL_MINUTES

        self._active_folders: List[str] = []
        self._protected_files: Set[str] = set()

        # Managed folders are explicitly registered for purging (auto-added when
        # recording starts, or manually by the user).
        self._managed_folders: Set[str] = set()

        # If True, purge only active recording folders - otherwise purge active folders plus managed folders.
        self._purge_active_only: bool = self.DEFAULT_PURGE_ACTIVE_ONLY

        # Load existing Application Settings
        self._load_policy()

        # Purge Worker thread setup - Singular Purge Worker Thread
        self._thread = QThread(self)
        self._worker = StoragePurgeWorker()
        self._worker.moveToThread(self._thread)

        self._setCheckIntervalMinutes.connect(self._worker.setCheckIntervalMinutes)
        self._dispatchPurge.connect(self._worker.performPurge)
        self._startPurgeTimer.connect(self._worker.startTimer)
        self._stopPurgeTimer.connect(self._worker.stopTimer)

        self._worker.purgeTimerFired.connect(self._on_purge_due)
        self._worker.purgedFiles.connect(self._on_purged_files)
        self._worker.purgeFailed.connect(self._on_purge_failed)

        self._thread.started.connect(self._startPurgeTimer)
        self._thread.start()
        self._setCheckIntervalMinutes.emit(self._check_interval_minutes)

        # Refresh disk-usage status periodically for the UI
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(self._STATUS_REFRESH_INTERVAL_MS)
        self._update_status()


    # Policy properties
    @Property(int, notify=policyChanged)
    def minFreeSpaceGb(self) -> int:
        return self._min_free_space_gb

    @Property(int, notify=policyChanged)
    def maxRetentionDays(self) -> int:
        return self._max_retention_days

    @Property(int, notify=policyChanged)
    def checkIntervalMinutes(self) -> int:
        return self._check_interval_minutes

    @Property(bool, notify=policyChanged)
    def purgeActiveOnly(self) -> bool:
        return self._purge_active_only

    @Property(list, notify=policyChanged)
    def managedFolders(self) -> List[str]:
        return sorted(self._managed_folders)


    # Status properties
    @Property(str, notify=storageStatusChanged)
    def storageStatusText(self) -> str:
        return self._status_text()

    @Property(float, notify=storageStatusChanged)
    def storageUsageRatio(self) -> float:
        return self._usage_ratio()

    @Property(float, notify=storageStatusChanged)
    def freeSpaceGb(self) -> float:
        return self._free_space_gb(self._status_root_path())


    # ------------------------------------------------------------------
    # Public slots/ functions
    # ------------------------------------------------------------------
    # Function - Reload policy from QSettings and refresh the UI
    @Slot()
    def loadStoragePolicy(self) -> None:
        self._load_policy()
        self._setCheckIntervalMinutes.emit(self._check_interval_minutes)
        self.policyChanged.emit()
        self._update_status()

    # Function - Save Purge policy values and apply them immediately
    @Slot(int, int, int)
    def saveStoragePolicy(self, min_free_space_gb: int, max_retention_days: int, check_interval_minutes: int) -> None:
        self._min_free_space_gb = max(0, int(min_free_space_gb))
        self._max_retention_days = max(1, int(max_retention_days))
        self._check_interval_minutes = max(1, int(check_interval_minutes))

        # Save Storage Purge Settings into Application Settings
        self._settings.setValue("storage/minFreeSpaceGb", self._min_free_space_gb)
        self._settings.setValue("storage/maxRetentionDays", self._max_retention_days)
        self._settings.setValue("storage/checkIntervalMinutes", self._check_interval_minutes)

        self._setCheckIntervalMinutes.emit(self._check_interval_minutes)
        self.policyChanged.emit()
        self._update_status()

    # Function - Manully trigger immediate purge
    @Slot()
    def triggerPurgeNow(self) -> None:
        self._on_purge_due()

    # Function - Add/ register one Managed Folder to be purged
    @Slot(str)
    def addManagedFolder(self, folder_path: str) -> None:
        normalized = self._normalize_folder(folder_path)
        if normalized and normalized not in self._managed_folders:
            self._managed_folders.add(normalized)
            self._save_managed_folders()
            self.policyChanged.emit()
            self._update_status()

    # Function - Remove one Managed Folder from purge register
    @Slot(str)
    def removeManagedFolder(self, folder_path: str) -> None:
        normalized = self._normalize_folder(folder_path)
        if normalized and normalized in self._managed_folders:
            self._managed_folders.discard(normalized)
            self._save_managed_folders()
            self.policyChanged.emit()
            self._update_status()

    # Function - Clear all managed folders/ folders from purge register
    @Slot()
    def clearManagedFolders(self) -> None:
        if self._managed_folders:
            self._managed_folders.clear()
            self._save_managed_folders()
            self.policyChanged.emit()
            self._update_status()

    # Function - Set whether purging is limited to active recording folders from UI
    @Slot(bool)
    def setPurgeActiveOnly(self, active_only: bool) -> None:
        active_only = bool(active_only)
        if self._purge_active_only != active_only:
            self._purge_active_only = active_only
            self._settings.setValue("storage/purgeActiveOnly", self._purge_active_only)
            self.policyChanged.emit()


    # ------------------------------------------------------------------
    # Integration with CaptureSessionManager
    # ------------------------------------------------------------------
    def updateActiveFolders(self, folders: List[str], protected_files: Set[str]) -> None:
        """Update the folders/files currently being recorded.

        Called by CaptureSessionManager whenever recording state changes.
        """
        self._active_folders = list(folders)
        self._protected_files = set(protected_files)
        self._update_status()

    def free_space_gb_for_path(self, path: str) -> float:
        """Return the free space (in GB) for the volume containing ``path``."""
        return self._free_space_gb(path)


    # ------------------------------------------------------------------
    # Storage Purge Worker Coordination
    # ------------------------------------------------------------------
    def _on_purge_due(self) -> None:
        # If Purging Folders with Active Recordings Only is enabled but there are no cameras connected for recording -> Return Early
        if self._purge_active_only and not self._active_folders:
            return

        # If we are purging only from folders which active Recordings
        if self._purge_active_only:
            folders_to_scan = list(self._active_folders)
            root_path = folders_to_scan[0] if folders_to_scan else self._status_root_path()
        else:
            # Otherwise, purge from both Active Recordings and Selected Folders - take intersection
            folders_to_scan = list(set(self._active_folders) | self._managed_folders)
            root_path = self._status_root_path()

        if not folders_to_scan:
            return

        min_free_bytes = self._min_free_space_gb * (1024 ** 3)
        max_retention_seconds = self._max_retention_days * 24 * 60 * 60

        # Emit Signal for Purging to Purge Folders with Recordings
        self._dispatchPurge.emit(
            list(self._active_folders),
            set(self._protected_files),
            folders_to_scan,
            self._purge_active_only,
            min_free_bytes,
            max_retention_seconds,
            root_path,
        )

    # After Purging Files - Check available/ free space, if insufficient, emit Storage Critical Signal up to UI/ QML
    def _on_purged_files(self, deleted: List[str]) -> None:
        self._update_status()
        if deleted:
            free_gb = self.freeSpaceGb
            if free_gb < self._min_free_space_gb:
                self.storageCritical.emit(f"Free space ({free_gb:.2f} GB) is still below the minimum ({self._min_free_space_gb} GB) after purging.")

    # On Purge Failed - Emit Storage Critical Signal up to UI/ QML
    def _on_purge_failed(self, reason: str) -> None:
        self.storageCritical.emit(f"Purge failed: {reason}")

    # ------------------------------------------------------------------
    # Helper Functions
    # ------------------------------------------------------------------
    # Load Storage Purge Policies from Application Settings
    def _load_policy(self) -> None:
        self._min_free_space_gb = int(
            self._settings.value(
                "storage/minFreeSpaceGb", self.DEFAULT_MIN_FREE_SPACE_GB
            )
        )
        self._max_retention_days = int(
            self._settings.value(
                "storage/maxRetentionDays", self.DEFAULT_MAX_RETENTION_DAYS
            )
        )
        self._check_interval_minutes = int(
            self._settings.value(
                "storage/checkIntervalMinutes", self.DEFAULT_CHECK_INTERVAL_MINUTES
            )
        )
        self._purge_active_only = bool(
            self._settings.value(
                "storage/purgeActiveOnly", self.DEFAULT_PURGE_ACTIVE_ONLY
            )
        )
        self._managed_folders = self._load_managed_folders()

    # Load Managed Folders from Application Settings
    def _load_managed_folders(self) -> Set[str]:
        folders = self._settings.value("storage/managedFolders", [])
        if folders is None:
            return set()
        result: Set[str] = set()
        for folder in folders:
            normalized = self._normalize_folder(folder)
            if normalized:
                result.add(normalized)
        return result

    # Save Managed Folders as Application Settings
    def _save_managed_folders(self) -> None:
        self._settings.setValue("storage/managedFolders", sorted(self._managed_folders))

    # Resolve Folder Path
    def _normalize_folder(self, folder_path: str) -> str | None:
        if not folder_path:
            return None
        try:
            return os.path.normpath(os.path.abspath(folder_path))
        except Exception:
            return None

    # Resolve Root Path
    def _status_root_path(self) -> str:
        for folder in self._active_folders:
            if os.path.isdir(folder):
                return folder
        for folder in sorted(self._managed_folders):
            if os.path.isdir(folder):
                return folder
        home = QDir.homePath()
        if home:
            return home
        return QDir.currentPath()

    # Obtain Storage Information from OS
    def _storage_info(self, path: str) -> QStorageInfo:
        if path and os.path.exists(path):
            return QStorageInfo(path)
        return QStorageInfo(self._status_root_path())

    # Get Free Storage
    def _free_space_gb(self, path: str) -> float:
        info = self._storage_info(path)
        available = info.bytesAvailable()
        if available < 0:
            return 0.0
        return available / (1024 ** 3)

    # Get Total Storage
    def _total_space_gb(self, path: str) -> float:
        info = self._storage_info(path)
        total = info.bytesTotal()
        if total <= 0:
            return 0.0
        return total / (1024 ** 3)

    # Format Storage Usage as a Percentage
    def _usage_ratio(self) -> float:
        info = self._storage_info(self._status_root_path())
        total = info.bytesTotal()
        available = info.bytesAvailable()
        if total <= 0 or available < 0:
            return 0.0
        return 1.0 - (available / total)

    # Format Storage information from Bytes to GB as String
    def _status_text(self) -> str:
        info = self._storage_info(self._status_root_path())
        free_gb = info.bytesAvailable() / (1024 ** 3)
        total_gb = info.bytesTotal() / (1024 ** 3)
        if total_gb <= 0:
            return "Disk usage unavailable"
        used_gb = total_gb - free_gb
        ratio = self._usage_ratio() * 100.0
        return (f"{free_gb:.2f} GB free of {total_gb:.2f} GB ({used_gb:.2f} GB used, {ratio:.1f}%)")

    # Update Purge Storage Settings
    def _update_status(self) -> None:
        self.storageStatusChanged.emit()

    # Stop Purge Worker Thread
    def shutdown(self) -> None:
        """Stop the purge worker thread.  Should be called before app exit."""
        self._stopPurgeTimer.emit()
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
