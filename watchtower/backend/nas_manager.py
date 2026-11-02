import json
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QSettings, Signal, Slot, Property

from backend.nas_connection import NasConnection
from backend.nas_mount_helper import (
    find_available_drive_letter,
    get_default_mount_point,
    is_mount_healthy,
    mount_share,
    unmount_share,
)


@dataclass
class _MountState:
    mount_point: Path
    drive_letter: Optional[str] = None


class NasManager(QObject):
    """Manages NAS connection metadata, mount lifecycle, and recording paths.

    Connection metadata is persisted via QSettings.  Passwords are never stored;
    they are requested from the UI at runtime and held in memory only for the
    duration of a mount operation.
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

        state = self._mount_states.pop(connection_id, None)
        if state is None:
            self.connectionStatusChanged.emit()
            return

        success, error = unmount_share(state.mount_point, state.drive_letter)
        if not success:
            # Restore state so the UI still reflects the previously mounted share.
            self._mount_states[connection_id] = state
            self.errorOccurred.emit(error or "Failed to disconnect NAS")
        else:
            self.connectionStatusChanged.emit()

    @Slot(str, str)
    def submitPassword(self, connection_id: str, password: str) -> None:
        """Receive a password from the UI and complete the pending mount."""
        if self._pending_password_for != connection_id:
            return

        conn = self._connections.get(connection_id)
        if conn is None:
            return

        self._pending_password_for = None
        operation = self._pending_operation
        self._pending_operation = None

        mount_point = get_default_mount_point(connection_id)
        drive_letter = (
            find_available_drive_letter()
            if platform.system() == "Windows"
            else None
        )

        # The password is held in memory only for the mount operation.
        try:
            success, used_drive_letter, error = mount_share(
                conn, mount_point, password, drive_letter
            )
        finally:
            # Explicitly clear the local password reference as soon as possible.
            password = ""
            del password

        if not success:
            self.errorOccurred.emit(error or "Failed to mount NAS")
            if operation and operation.startswith("record:"):
                device_id = operation.split(":", 1)[1]
                self.recordingMountFailed.emit(device_id, error or "Failed to mount NAS")
            return

        self._mount_states[connection_id] = _MountState(mount_point, used_drive_letter)
        self.connectionStatusChanged.emit()

        if operation and operation.startswith("record:"):
            device_id = operation.split(":", 1)[1]
            self._prepare_recording_path(device_id, connection_id)

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
