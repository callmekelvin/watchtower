from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal

from backend.capture_session_manager import CaptureSessionManager
from backend.models import MediaDevice


class FakeDeviceManager(QObject):
    videoInputsChanged = Signal()
    lastRefreshTimeChanged = Signal()
    errorOccurred = Signal(str)

    def __init__(self, devices=None, parent=None):
        super().__init__(parent)
        self._devices = devices or []
        self._last_refresh_time = None

    def video_inputs(self):
        return list(self._devices)

    def last_refresh_time(self):
        return self._last_refresh_time


@pytest.fixture
def device_manager():
    return FakeDeviceManager()


@pytest.fixture
def capture_manager(qtbot, device_manager):
    mgr = CaptureSessionManager(device_manager)
    yield mgr
    mgr.stopAll()


def test_set_camera_by_id_updates_state(qtbot, capture_manager):
    with qtbot.waitSignals([capture_manager.currentDeviceIdChanged, capture_manager.cameraActiveChanged]):
        capture_manager.setCameraById("cam-1")

    assert capture_manager.currentDeviceId == "cam-1"
    assert capture_manager.cameraActive is True


def test_set_camera_by_id_same_id_is_noop(qtbot, capture_manager):
    capture_manager.setCameraById("cam-1")
    with qtbot.assertNotEmitted(capture_manager.currentDeviceIdChanged):
        capture_manager.setCameraById("cam-1")


def test_stop_current_session_clears_selection(qtbot, capture_manager):
    capture_manager.setCameraById("cam-1")
    with qtbot.waitSignals([capture_manager.currentDeviceIdChanged, capture_manager.cameraActiveChanged]):
        capture_manager.stopCurrentSession()

    assert capture_manager.currentDeviceId == ""
    assert capture_manager.cameraActive is False


def test_start_recording_rejects_empty_device_id(capture_manager):
    capture_manager.errorOccurred = MagicMock()
    capture_manager.startRecordingForDevice("", "/tmp/out")
    capture_manager.errorOccurred.assert_not_called()  # Empty id returns early without error.


def test_start_recording_rejects_empty_path(qtbot, capture_manager):
    with qtbot.waitSignal(capture_manager.errorOccurred, timeout=1000):
        capture_manager.startRecordingForDevice("cam-1", "")


def test_start_recording_rejects_insufficient_space(qtbot, capture_manager):
    storage = MagicMock()
    storage.minFreeSpaceGb = 100
    storage.free_space_gb_for_path.return_value = 1.0
    capture_manager._storage_manager = storage

    with qtbot.waitSignal(capture_manager.errorOccurred, timeout=1000):
        capture_manager.startRecordingForDevice("cam-1", "/tmp/out")


def test_video_inputs_changed_starts_sessions_for_new_devices(qtbot, device_manager):
    manager = CaptureSessionManager(device_manager)
    device_manager._devices = [MediaDevice(device_id="cam-1", description="Cam 1", is_default=False)]

    with qtbot.waitSignal(manager.sessionStarted, timeout=5000):
        device_manager.videoInputsChanged.emit()

    assert "cam-1" in manager._workers
    manager.stopAll()


def test_stop_all_clears_state(qtbot, capture_manager):
    capture_manager.setCameraById("cam-1")
    capture_manager.stopAll()
    assert capture_manager.currentDeviceId == ""
    assert capture_manager.cameraActive is False


def test_worker_recording_state_change_updates_manager_state(capture_manager):
    capture_manager._recording_states["cam-1"] = False
    capture_manager._recording_folders["cam-1"] = "/tmp/out"
    capture_manager._active_files["cam-1"] = "/tmp/out/seg.mp4"

    capture_manager._on_worker_recording_state_changed("cam-1", False)

    assert capture_manager._recording_states["cam-1"] is False
    assert "cam-1" not in capture_manager._recording_folders
    assert "cam-1" not in capture_manager._active_files


def test_segment_started_tracks_active_file(capture_manager):
    capture_manager._on_segment_started("cam-1", "/tmp/out/seg.mp4")
    assert capture_manager._active_files["cam-1"] == "/tmp/out/seg.mp4"


def test_segment_finalized_emits_signal(qtbot, capture_manager):
    with qtbot.waitSignal(capture_manager.segmentFinalized, timeout=1000):
        capture_manager._on_segment_finalized("cam-1", "/tmp/out/final.mp4")
