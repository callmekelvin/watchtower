import os
import re
from datetime import datetime, timezone
from typing import List, Set, Tuple

from PySide6.QtCore import QObject, QStorageInfo, QTimer, Signal, Slot

from backend.nas_mount_helper import get_network_free_space_gb, is_likely_nas_mount


# Recording filename regex pattern produced by CaptureSessionWorker:
#   {camera}_{YYYYMMDD}_{HHMMSS}_{mmm}.mp4
_FILENAME_TIMESTAMP_RE = re.compile(
    r"_(\d{8})_(\d{6})_(\d{3})\.mp4$", re.IGNORECASE
)

# Return a timezone-aware UTC datetime parsed from the filename, or None
def _parse_filename_timestamp(filename: str):
    match = _FILENAME_TIMESTAMP_RE.search(filename)
    if not match:
        return None
    try:
        dt = datetime.strptime(
            match.group(1) + match.group(2) + match.group(3), "%Y%m%d%H%M%S%f"
        )
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class StoragePurgeWorker(QObject):
    """Background-thread worker that scans active recording folders and deletes old finalized .mp4 files when disk space is low.

    The worker owns a QTimer that fires at the configured check interval.
    When a purge is requested it emits ``purgedFiles`` with the deleted paths, or ``purgeFailed`` if something went wrong.
    """

    purgeTimerFired = Signal()
    purgedFiles = Signal(list)
    purgeFailed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        # Creat Timer to fire Purge Worker on Configured Intervals
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.purgeTimerFired)
        self._check_interval_ms = 5 * 60 * 1000

    @Slot(int)
    def setCheckIntervalMinutes(self, minutes: int) -> None:
        """Update the purge check interval and restart the timer if active."""
        self._check_interval_ms = max(1, int(minutes)) * 60 * 1000
        if self._timer.isActive():
            self._timer.start(self._check_interval_ms)

    @Slot()
    def startTimer(self) -> None:
        if not self._timer.isActive():
            self._timer.start(self._check_interval_ms)

    @Slot()
    def stopTimer(self) -> None:
        self._timer.stop()

    @Slot(list, set, list, bool, "qint64", "qint64", str)
    def performPurge(
        self,
        active_folders: List[str],
        protected_files: Set[str],
        folders_to_scan: List[str],
        purge_active_only: bool,
        min_free_bytes: int,
        max_retention_seconds: int,
        root_path: str,
    ) -> None:
        """Execute a single purge pass.

        Parameters
        ----------
        active_folders:
            Folders currently used by active recording workers.
        protected_files:
            Absolute paths that must not be deleted (active segment files).
        folders_to_scan:
            Folders to actually scan for eligible files. This is either the
            active folders (when purge_active_only is True) or the union of
            active and managed folders.
        purge_active_only:
            Whether the purge was scoped to active folders only.
        min_free_bytes:
            Keep deleting until at least this many bytes are free.
        max_retention_seconds:
            Delete any file older than this many seconds regardless of space.
        root_path:
            Path used to query QStorageInfo for free-space calculations.
        """
        try:
            deleted = self._purge(
                folders_to_scan,
                protected_files,
                min_free_bytes,
                max_retention_seconds,
                root_path,
            )
            self.purgedFiles.emit(deleted)
        except Exception as exc:
            self.purgeFailed.emit(str(exc))

    def _purge(self, folders_to_scan: List[str], protected_files: Set[str], min_free_bytes: int, max_retention_seconds: int, root_path: str) -> List[str]:
        if not folders_to_scan:
            return []

        # Normalize protected paths so they match the normalized scanned paths.
        protected_files = {os.path.normpath(p) for p in protected_files}

        # Get Storage Information
        free_bytes = self._free_bytes_for_path(root_path)
        if free_bytes is None:
            self.purgeFailed.emit(f"Cannot determine free space for '{root_path}'; aborting purge")
            return []

        now_ts = datetime.now(timezone.utc).timestamp()
        retention_cutoff_ts = now_ts - max_retention_seconds

        # Collect eligible finalized .mp4 files from list of folders to scan
        candidates: List[Tuple[datetime, str, int]] = []
        for folder in folders_to_scan:
            if not os.path.isdir(folder):
                continue
            try:
                for entry in os.scandir(folder):
                    if not entry.is_file():
                        continue
                    if not entry.name.lower().endswith(".mp4"):
                        continue
                    file_path = os.path.normpath(entry.path)
                    if file_path in protected_files:
                        continue

                    file_time = _parse_filename_timestamp(entry.name)
                    if file_time is None:
                        stat = entry.stat()
                        file_time = datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        )
                    file_size = entry.stat().st_size
                    candidates.append((file_time, file_path, file_size))
            except OSError as exc:
                self.purgeFailed.emit(f"Failed to scan '{folder}': {exc}")

        # Purge Candidate Video Files by Oldest first
        candidates.sort(key=lambda item: item[0])

        deleted: List[str] = []
        delete_errors: List[str] = []

        # First pass: enforce retention age regardless of free space.
        still_eligible: List[Tuple[datetime, str, int]] = []
        for file_time, file_path, file_size in candidates:
            if file_time.timestamp() <= retention_cutoff_ts:
                if self._delete_file(file_path, delete_errors):
                    deleted.append(file_path)
                    free_bytes += file_size
            else:
                still_eligible.append((file_time, file_path, file_size))

        # Second pass: delete oldest files until we reach min_free_bytes (aggressive)
        for file_time, file_path, file_size in still_eligible:
            if free_bytes >= min_free_bytes:
                break
            if self._delete_file(file_path, delete_errors):
                deleted.append(file_path)
                free_bytes += file_size

        if delete_errors:
            self.purgeFailed.emit(
                "Some files could not be deleted: " + "; ".join(delete_errors[:5])
            )
        return deleted

    def _free_bytes_for_path(self, path: str) -> Optional[int]:
        """Return free bytes for ``path``, with a NAS fallback when needed."""
        storage = QStorageInfo(path) if path else QStorageInfo()
        free_bytes = storage.bytesAvailable()
        total_bytes = storage.bytesTotal()

        # bytesAvailable < 0 means QStorageInfo could not determine free space.
        free_unknown = free_bytes < 0
        if free_unknown:
            free_bytes = 0

        # For local volumes a known positive value is trustworthy.
        if not free_unknown and free_bytes > 0 and not is_likely_nas_mount(path):
            return free_bytes

        # For NAS mounts QStorageInfo may be unreliable.  Try a platform command.
        if is_likely_nas_mount(path) and (free_unknown or free_bytes <= 0 or total_bytes <= 0):
            fallback_gb = get_network_free_space_gb(path)
            if fallback_gb is not None:
                return int(fallback_gb * (1024 ** 3))

        # QStorageInfo truly could not resolve the volume.
        if free_unknown and total_bytes <= 0:
            return None
        return free_bytes

    # Delete the File
    def _delete_file(self, file_path: str, error_log: List[str]) -> bool:
        try:
            os.remove(file_path)
            return True
        except OSError as exc:
            error_log.append(f"'{file_path}': {exc}")
            return False
