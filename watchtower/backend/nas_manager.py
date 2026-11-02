import json
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import (
    QObject,
    QSettings,
    Signal,
    Slot,
    Property,
    QThread,
    QTimer,
    Qt,
)

from backend.nas_connection import NasConnection, NasProtocol
from backend.nas_mount_helper import (
    check_host_port,
    find_available_drive_letter,
    get_default_mount_point,
    is_mount_healthy,
    mount_share,
    probe_nas_write,
    unmount_share,
)


@dataclass
class _MountState:
    mount_point: Path
    drive_letter: Optional[str] = None


class NasMountWorker(QObject):
    """Background worker that unmounts a stale share and remounts it."""

    # connection_id, operation, success, error, mount_point_str, drive_letter
    finished = Signal(str, str, bool, str, str, str)

    def __init__(
        self,
        connection: NasConnection,
        operation: str,
        password: str = "",
        previous_state: Optional[_MountState] = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._connection = connection
        self._operation = operation
        self._password = password
        self._previous_state = previous_state

    @Slot()
    def perform_mount(self) -> None:
        try:
            mount_point = get_default_mount_point(self._connection.id)

            if self._previous_state is not None:
                unmount_share(
                    self._previous_state.mount_point,
                    self._previous_state.drive_letter,
                    lazy=True,
                )

            drive_letter = (
                find_available_drive_letter()
                if platform.system() == "Windows"
                else None
            )

            success, used_drive_letter, error = mount_share(
                self._connection, mount_point, self._password, drive_letter
            )

            if success:
                probe_ok, probe_err = probe_nas_write(mount_point)
                if not probe_ok:
                    unmount_share(mount_point, used_drive_letter, lazy=True)
                    success = False
                    error = probe_err or "NAS write probe failed"
                else:
                    self.finished.emit(
                        self._connection.id,
                        self._operation,
                        True,
                        "",
                        str(mount_point),
                        used_drive_letter or "",
                    )
                    return

            self.finished.emit(
                self._connection.id,
                self._operation,
                False,
                error or "Mount failed",
                "",
                "",
            )
        except Exception as exc:
            self.finished.emit(
                self._connection.id, self._operation, False, str(exc), "", ""
            )
        finally:
            # Clear the password from memory as soon as the mount attempt ends.
            self._password = ""


class NasUnmountWorker(QObject):
    """Background worker that unmounts a share."""

    # connection_id, success, error, previous_state
    finished = Signal(str, bool, str, object)

    def __init__(
        self,
        connection_id: str,
        state: _MountState,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._connection_id = connection_id
        self._state = state

    @Slot()
    def perform_unmount(self) -> None:
        try:
            success, error = unmount_share(
                self._state.mount_point, self._state.drive_letter
            )
            self.finished.emit(self._connection_id, success, error, self._state)
        except Exception as exc:
            self.finished.emit(self._connection_id, False, str(exc), self._state)


class NasRecoveryWatcher(QObject):
    """Watches NAS connections used for recording and remounts them on outage."""

    connectionRestored = Signal(str)
    connectionRestoreFailed = Signal(str, str)

    def __init__(self, nas_manager: "NasManager", parent: QObject | None = None):
        super().__init__(parent)
        self._nas = nas_manager
        self._watched: Set[str] = set()
        self._in_progress: Set[str] = set()
        # Keep workers alive while their background threads are running.
        self._active_workers: Dict[QThread, QObject] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)  # 60 seconds
        self._timer.timeout.connect(self._on_tick)

    def watch(self, connection_id: str) -> None:
        """Start watching a connection for auto-recovery."""
        self._watched.add(connection_id)
        if not self._timer.isActive():
            self._timer.start()

    def unwatch(self, connection_id: str) -> None:
        """Stop watching a connection for auto-recovery."""
        self._watched.discard(connection_id)
        self._in_progress.discard(connection_id)
        if not self._watched:
            self._timer.stop()

    def unwatch_all(self) -> None:
        """Stop watching all connections."""
        self._watched.clear()
        self._in_progress.clear()
        self._timer.stop()

    def _on_tick(self) -> None:
        for connection_id in list(self._watched):
            if connection_id in self._in_progress:
                continue
            if self._nas._is_mounted_and_healthy(connection_id):
                continue
            self._attempt_remount(connection_id)

    def _attempt_remount(self, connection_id: str) -> None:
        conn = self._nas._connections.get(connection_id)
        if conn is None:
            return

        # Remove stale state so the UI shows disconnected while we retry.
        previous_state = self._nas._mount_states.pop(connection_id, None)
        self._in_progress.add(connection_id)

        thread = QThread(self)
        worker = NasMountWorker(conn, operation="", previous_state=previous_state)
        self._active_workers[thread] = worker
        worker.moveToThread(thread)

        thread.started.connect(worker.perform_mount)
        worker.finished.connect(self._on_mount_finished, Qt.QueuedConnection)
        worker.finished.connect(thread.quit, Qt.QueuedConnection)
        thread.finished.connect(self._cleanup_worker, Qt.QueuedConnection)

        self._nas._recovery_threads[connection_id] = thread
        thread.start()

    def _cleanup_worker(self) -> None:
        """Delete a finished worker that has been moved back to the main thread."""
        thread = self.sender()
        worker = self._active_workers.pop(thread, None)
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()

    def _on_mount_finished(
        self,
        connection_id: str,
        _operation: str,
        success: bool,
        error: str,
        mount_point_str: str,
        drive_letter: str,
    ) -> None:
        self._in_progress.discard(connection_id)
        self._nas._recovery_threads.pop(connection_id, None)

        if success:
            mount_point = Path(mount_point_str)
            self._nas._mount_states[connection_id] = _MountState(
                mount_point, drive_letter or None
            )
            self._nas.connectionStatusChanged.emit()
            print(f"[NasRecovery] Connection {connection_id} restored")
            self.connectionRestored.emit(connection_id)
        else:
            print(f"[NasRecovery] Failed to restore {connection_id}: {error}")
            self.connectionRestoreFailed.emit(connection_id, error or "Unknown error")


class NasManager(QObject):
    """Manages NAS connection metadata, mount lifecycle, and recording paths.

    Connection metadata is persisted via QSettings.  Passwords are never stored;
    they are requested from the UI at runtime and held in memory only for the
    duration of a mount operation.

    All mount and unmount operations run on background threads so the GUI
    remains responsive while network I/O is in progress.
    """

    # Emitted whenever the connection list or a connection status changes.
    connectionStatusChanged = Signal()

    # Emitted to request a password from the user:
    #   connection_id, title, message
    passwordPromptRequested = Signal(str, str, str)

    # Emitted when a mount or connection operation fails.
    errorOccurred = Signal(str)

    # Emitted when a recording path has been prepared on a mounted NAS:
    #   device_id, local_folder_path
    recordingPathReady = Signal(str, str)

    # Emitted when mounting for recording fails:
    #   device_id, error_message
    recordingMountFailed = Signal(str, str)

    # Emitted when the set of active NAS recordings changes.
    anyNasRecordingActiveChanged = Signal()

    # Emitted when a watched connection is remounted after an outage.
    connectionRestored = Signal(str)

    # Emitted when a watched connection could not be remounted.
    connectionRestoreFailed = Signal(str, str)

    # Emitted when the user manually disconnects a connection.
    # This lets the recording manager cancel auto-recovery.
    connectionManuallyDisconnected = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._settings = QSettings("Watchtower", "Watchtower")
        self._connections: Dict[str, NasConnection] = {}
        # connection_id -> _MountState for currently mounted shares.
        self._mount_states: Dict[str, _MountState] = {}
        # connection_id awaiting a password, and what to do after mount.
        self._pending_password_for: Optional[str] = None
        self._pending_operation: Optional[str] = None
        # device_id -> connection_id for active NAS recordings.
        self._active_recordings: Dict[str, str] = {}

        # Tracks background recovery threads so they can be cleaned up.
        self._recovery_threads: Dict[str, QThread] = {}
        # Tracks background operation threads (connect / disconnect).
        self._operation_threads: Dict[str, QThread] = {}
        # Tracks active operation workers so they are not garbage collected.
        self._active_workers: Dict[QThread, QObject] = {}
        # connection_ids with a mount/unmount operation currently in progress.
        self._operation_in_progress: Set[str] = set()

        self._recovery_watcher = NasRecoveryWatcher(self)
        self._recovery_watcher.connectionRestored.connect(self.connectionRestored)
        self._recovery_watcher.connectionRestoreFailed.connect(
            self.connectionRestoreFailed
        )

        self._load_connections()

    # ------------------------------------------------------------------
    # Properties exposed to QML
    # ------------------------------------------------------------------
    @Property(list, notify=connectionStatusChanged)
    def connections(self) -> List[Dict[str, Any]]:
        """Return the list of configured NAS connections with live status."""
        result: List[Dict[str, Any]] = []
        for conn in self._connections.values():
            data = conn.to_dict()
            data["status"] = self._status_for(conn.id)
            data["mountPoint"] = str(get_default_mount_point(conn.id))
            result.append(data)
        return result

    @Property(bool, notify=anyNasRecordingActiveChanged)
    def anyNasRecordingActive(self) -> bool:
        return bool(self._active_recordings)

    # ------------------------------------------------------------------
    # Public slots
    # ------------------------------------------------------------------
    @Slot(dict)
    def saveConnection(self, data: Dict[str, Any]) -> None:
        """Create or update a NAS connection from a dictionary."""
        try:
            # QML may pass a QJSValue; convert it to a plain Python dict.
            py_data = dict(data)
            conn = NasConnection.from_dict(py_data)
        except Exception as exc:
            self.errorOccurred.emit(f"Invalid NAS connection: {exc}")
            return

        self._connections[conn.id] = conn
        self._save_connections()
        self.connectionStatusChanged.emit()

    @Slot(str)
    def deleteConnection(self, connection_id: str) -> None:
        """Delete a configured NAS connection."""
        if connection_id in self._mount_states:
            self.requestDisconnect(connection_id)
        self._recovery_watcher.unwatch(connection_id)
        self._connections.pop(connection_id, None)
        self._save_connections()
        self.connectionStatusChanged.emit()

    @Slot(str)
    def requestConnect(self, connection_id: str) -> None:
        """Initiate a connect (mount) for the given connection."""
        if self._active_recordings:
            self.errorOccurred.emit(
                "Cannot connect or disconnect NAS while recording is in progress"
            )
            return

        conn = self._connections.get(connection_id)
        if conn is None:
            self.errorOccurred.emit(f"Unknown NAS connection: {connection_id}")
            return

        if self._is_mounted_and_healthy(connection_id):
            self.connectionStatusChanged.emit()
            return

        if conn.protocol == NasProtocol.NFS:
            self._start_mount_worker(connection_id, "", "connect")
            return

        self._pending_password_for = connection_id
        self._pending_operation = "connect"
        self._prompt_for_password(conn)

    @Slot(str)
    def requestDisconnect(self, connection_id: str) -> None:
        """Unmount a NAS connection."""
        if self._active_recordings:
            self.errorOccurred.emit(
                "Cannot connect or disconnect NAS while recording is in progress"
            )
            return

        # A manual disconnect is a human failsafe: stop auto-recovery.
        self._recovery_watcher.unwatch(connection_id)

        state = self._mount_states.pop(connection_id, None)
        if state is None:
            self.connectionStatusChanged.emit()
            self.connectionManuallyDisconnected.emit(connection_id)
            return

        if connection_id in self._operation_in_progress:
            # Restore state so the UI still reflects the mounted share.
            self._mount_states[connection_id] = state
            return

        self._operation_in_progress.add(connection_id)
        thread = QThread(self)
        worker = NasUnmountWorker(connection_id, state)
        self._active_workers[thread] = worker
        worker.moveToThread(thread)

        thread.started.connect(worker.perform_unmount)
        worker.finished.connect(self._on_unmount_finished, Qt.QueuedConnection)
        worker.finished.connect(thread.quit, Qt.QueuedConnection)
        thread.finished.connect(self._cleanup_worker, Qt.QueuedConnection)

        self._operation_threads[connection_id] = thread
        thread.start()

    @Slot(str, str)
    def submitPassword(self, connection_id: str, password: str) -> None:
        """Receive a password from the UI and complete the pending mount."""
        if self._pending_password_for != connection_id:
            return

        self._pending_password_for = None
        operation = self._pending_operation
        self._pending_operation = None

        if operation is None:
            return

        self._start_mount_worker(connection_id, password, operation)

    def _start_mount_worker(
        self,
        connection_id: str,
        password: str,
        operation: str,
        previous_state: Optional[_MountState] = None,
    ) -> None:
        """Queue a mount operation on a background thread."""
        conn = self._connections.get(connection_id)
        if conn is None:
            return

        if connection_id in self._operation_in_progress:
            return
        self._operation_in_progress.add(connection_id)

        if previous_state is None:
            # Remove any stale state so the UI shows "disconnected" while mounting.
            previous_state = self._mount_states.pop(connection_id, None)

        thread = QThread(self)
        worker = NasMountWorker(
            conn,
            operation=operation,
            password=password,
            previous_state=previous_state,
        )
        self._active_workers[thread] = worker
        worker.moveToThread(thread)

        thread.started.connect(worker.perform_mount)
        worker.finished.connect(self._on_mount_finished, Qt.QueuedConnection)
        worker.finished.connect(thread.quit, Qt.QueuedConnection)
        thread.finished.connect(self._cleanup_worker, Qt.QueuedConnection)

        self._operation_threads[connection_id] = thread
        thread.start()

    def _on_mount_finished(
        self,
        connection_id: str,
        operation: str,
        success: bool,
        error: str,
        mount_point_str: str,
        drive_letter: str,
    ) -> None:
        """Handle completion of a background mount operation."""
        self._operation_in_progress.discard(connection_id)
        self._operation_threads.pop(connection_id, None)

        if not success:
            self.errorOccurred.emit(error or "Failed to mount NAS")
            if operation and operation.startswith("record:"):
                device_id = operation.split(":", 1)[1]
                self.recordingMountFailed.emit(device_id, error or "Failed to mount NAS")
            return

        mount_point = Path(mount_point_str)
        self._mount_states[connection_id] = _MountState(mount_point, drive_letter or None)
        self.connectionStatusChanged.emit()

        if operation and operation.startswith("record:"):
            device_id = operation.split(":", 1)[1]
            self._prepare_recording_path(device_id, connection_id)

    def _on_unmount_finished(
        self,
        connection_id: str,
        success: bool,
        error: str,
        state: _MountState,
    ) -> None:
        """Handle completion of a background unmount operation."""
        self._operation_in_progress.discard(connection_id)
        self._operation_threads.pop(connection_id, None)

        if not success:
            # Restore state so the UI still reflects the previously mounted share.
            self._mount_states[connection_id] = state
            self.errorOccurred.emit(error or "Failed to disconnect NAS")
            return

        self.connectionStatusChanged.emit()
        self.connectionManuallyDisconnected.emit(connection_id)

    def _cleanup_worker(self) -> None:
        """Delete a finished worker that has been moved back to the main thread."""
        thread = self.sender()
        worker = self._active_workers.pop(thread, None)
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()

    @Slot(str, str)
    def mountForRecording(self, connection_id: str, device_id: str) -> None:
        """Mount a NAS share and prepare a per-camera recording folder.

        This is asynchronous: it emits ``recordingPathReady`` on success or
        ``recordingMountFailed`` on failure.  If a password is required, the
        ``passwordPromptRequested`` signal is emitted first.
        """
        conn = self._connections.get(connection_id)
        if conn is None:
            self.recordingMountFailed.emit(
                device_id, f"Unknown NAS connection: {connection_id}"
            )
            return

        if self._is_mounted_and_healthy(connection_id):
            self._prepare_recording_path(device_id, connection_id)
            return

        if conn.protocol == NasProtocol.NFS:
            self._start_mount_worker(connection_id, "", f"record:{device_id}")
            return

        self._pending_password_for = connection_id
        self._pending_operation = f"record:{device_id}"
        self._prompt_for_password(conn)

    @Slot(str, str, bool)
    def setNasRecordingActive(
        self, device_id: str, connection_id: str, active: bool
    ) -> None:
        """Notify the manager that a recording to a NAS connection started/stopped."""
        changed = False
        if active:
            if self._active_recordings.get(device_id) != connection_id:
                self._active_recordings[device_id] = connection_id
                changed = True
        else:
            changed = self._active_recordings.pop(device_id, None) is not None
        if changed:
            self.anyNasRecordingActiveChanged.emit()

    @Slot(str, result=str)
    def statusForConnection(self, connection_id: str) -> str:
        return self._status_for(connection_id)

    @Slot(str, result=bool)
    def isConnectionMounted(self, connection_id: str) -> bool:
        return self._is_mounted_and_healthy(connection_id)

    @Slot(result=bool)
    def isAnyNasRecordingActive(self) -> bool:
        return bool(self._active_recordings)

    @Slot(str)
    def registerRecoveryWatch(self, connection_id: str) -> None:
        """Register a connection for auto-remount if it drops."""
        if connection_id in self._connections:
            self._recovery_watcher.watch(connection_id)

    @Slot(str)
    def unregisterRecoveryWatch(self, connection_id: str) -> None:
        """Unregister a connection from auto-remount."""
        self._recovery_watcher.unwatch(connection_id)

    def connectionHost(self, connection_id: str) -> Optional[str]:
        """Return the host for a connection, or None if unknown."""
        conn = self._connections.get(connection_id)
        if conn is None:
            return None
        return conn.host

    def ensureRecordingPath(
        self, connection_id: str, device_id: str
    ) -> Optional[str]:
        """Return a verified per-camera recording folder on a mounted NAS."""
        if not self._is_mounted_and_healthy(connection_id):
            return None

        state = self._mount_states.get(connection_id)
        if state is None:
            return None

        camera_folder = state.mount_point / self._camera_slug(device_id)
        try:
            camera_folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None

        return str(camera_folder)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _load_connections(self) -> None:
        raw = self._settings.value("nas/connections", [])
        self._connections = {}
        if raw is None:
            return
        for item in raw:
            try:
                data = json.loads(item) if isinstance(item, str) else dict(item)
                conn = NasConnection.from_dict(data)
                self._connections[conn.id] = conn
            except Exception:
                continue

    def _save_connections(self) -> None:
        raw = [json.dumps(conn.to_dict()) for conn in self._connections.values()]
        self._settings.setValue("nas/connections", raw)

    def _is_mounted_and_healthy(self, connection_id: str) -> bool:
        state = self._mount_states.get(connection_id)
        if state is None:
            return False
        if not is_mount_healthy(state.mount_point):
            # Mount became unhealthy (e.g. network dropped) - clean up state.
            self._mount_states.pop(connection_id, None)
            return False
        return True

    def _status_for(self, connection_id: str) -> str:
        return "connected" if self._is_mounted_and_healthy(connection_id) else "disconnected"

    def _prompt_for_password(self, conn: NasConnection) -> None:
        title = f"Connect to {conn.name}"
        message = f"Enter password for {conn.display_share()}"
        if conn.username:
            message += f" (user: {conn.username})"
        self.passwordPromptRequested.emit(conn.id, title, message)

    def _prepare_recording_path(self, device_id: str, connection_id: str) -> None:
        state = self._mount_states.get(connection_id)
        if state is None:
            self.recordingMountFailed.emit(
                device_id, "NAS connection is no longer mounted"
            )
            return

        camera_folder = state.mount_point / self._camera_slug(device_id)
        try:
            camera_folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.recordingMountFailed.emit(
                device_id, f"Failed to create camera folder: {exc}"
            )
            return

        self.recordingPathReady.emit(device_id, str(camera_folder))

    @staticmethod
    def _camera_slug(device_id: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", device_id).strip("_")
        return slug or "camera"

    def get_mount_point(self, connection_id: str) -> Optional[Path]:
        """Return the mount point for a connection, or None if not mounted."""
        state = self._mount_states.get(connection_id)
        if state is None:
            return None
        return state.mount_point
