import os
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, QThread, Signal, Slot, QCoreApplication
from PySide6.QtMultimedia import QVideoSink

from backend.capture_session_manager import CaptureSessionManager
from backend.models import MediaDevice


class FakeDeviceManager(QObject):
    videoInputsChanged = Signal()

    def __init__(self, devices=None, parent=None):
        super().__init__(parent)
        self._devices = devices or []

    def video_inputs(self):
        return list(self._devices)


class FakeCaptureSessionWorker(QObject):
    sessionStarted = Signal(str)
    errorOccurred = Signal(str, str)
    sessionRestartRequested = Signal(str, str)
    fatalErrorOccurred = Signal(str, str)
    stopped = Signal(str)
    recordingStateChanged = Signal(str, bool)
    recordingPaused = Signal(str, str)
    segmentStarted = Signal(str, str)
    segmentFinalized = Signal(str, str)

    def __init__(self, device_id: str, parent=None):
        super().__init__(parent)
        self._device_id = device_id
        self._video_sink = None
        self._recording = False
        self._folder_path = None
        self._nas_host = None

    @Slot(str, QVideoSink)
    def setVideoSink(self, device_id: str, sink: QVideoSink) -> None:
        if device_id == self._device_id:
            self._video_sink = sink

    @Slot(str)
    def clearVideoSink(self, device_id: str) -> None:
        if device_id == self._device_id:
            self._video_sink = None

    @Slot()
    def initializeAndStart(self) -> None:
        self.sessionStarted.emit(self._device_id)

    @Slot(str, str, str)
    def startRecording(self, device_id: str, folder_path: str, nas_host: str = "") -> None:
        if device_id != self._device_id:
            return
        self._folder_path = folder_path
        self._nas_host = nas_host
        self._recording = True
        self.recordingStateChanged.emit(self._device_id, True)
        self.segmentStarted.emit(self._device_id, os.path.join(folder_path, "seg.mp4"))

    @Slot(str)
    def stopRecording(self, device_id: str) -> None:
        if device_id != self._device_id:
            return
        self._recording = False
        self.recordingStateChanged.emit(self._device_id, False)

    @Slot()
    def stop(self) -> None:
        if self._recording:
            self._recording = False
            self.recordingStateChanged.emit(self._device_id, False)
        self.stopped.emit(self._device_id)


@pytest.fixture
def device_manager():
    return FakeDeviceManager()


@pytest.fixture
def capture_manager(qtbot, device_manager, monkeypatch):
    monkeypatch.setattr(
        "backend.capture_session_manager.CaptureSessionWorker", FakeCaptureSessionWorker
    )
    mgr = CaptureSessionManager(device_manager)
    yield mgr
    mgr.stopAll()


def test_session_started_signal_replaces_session_ready(qtbot, device_manager, capture_manager):
    device_manager._devices = [MediaDevice(device_id="cam-1", description="Cam 1", is_default=False)]

    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        device_manager.videoInputsChanged.emit()

    assert "cam-1" in capture_manager._workers


def test_camera_error_requests_session_restart(qtbot, device_manager, capture_manager):
    device_manager._devices = [MediaDevice(device_id="cam-1", description="Cam 1", is_default=False)]
    device_manager.videoInputsChanged.emit()
    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        pass

    worker = capture_manager._workers["cam-1"]
    with qtbot.waitSignals(
        [capture_manager.errorOccurred, capture_manager.sessionStopped, capture_manager.sessionStarted],
        timeout=5000,
    ):
        worker.sessionRestartRequested.emit("cam-1", "camera error")

    assert "cam-1" in capture_manager._workers


def test_device_removal_stops_worker(qtbot, device_manager, capture_manager):
    device_manager._devices = [MediaDevice(device_id="cam-1", description="Cam 1", is_default=False)]
    device_manager.videoInputsChanged.emit()
    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        pass

    device_manager._devices = []
    with qtbot.waitSignal(capture_manager.sessionStopped, timeout=5000):
        device_manager.videoInputsChanged.emit()

    assert "cam-1" not in capture_manager._workers


def test_device_replug_restarts_worker(qtbot, device_manager, capture_manager):
    device_manager._devices = [MediaDevice(device_id="cam-1", description="Cam 1", is_default=False)]
    device_manager.videoInputsChanged.emit()
    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        pass

    device_manager._devices = []
    with qtbot.waitSignal(capture_manager.sessionStopped, timeout=5000):
        device_manager.videoInputsChanged.emit()

    device_manager._devices = [MediaDevice(device_id="cam-1", description="Cam 1", is_default=False)]
    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        device_manager.videoInputsChanged.emit()

    assert "cam-1" in capture_manager._workers


def test_auto_resume_local_recording_after_restart(qtbot, device_manager, capture_manager):
    device_manager._devices = [MediaDevice(device_id="cam-1", description="Cam 1", is_default=False)]
    device_manager.videoInputsChanged.emit()
    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        pass

    capture_manager.startRecordingForDevice("cam-1", "/tmp/out")
    with qtbot.waitSignal(capture_manager.deviceRecordingStateChanged, timeout=5000):
        pass

    assert capture_manager._desired_local_recordings.get("cam-1") == "/tmp/out"

    worker = capture_manager._workers["cam-1"]
    new_worker = None

    def on_session_started(device_id):
        nonlocal new_worker
        if device_id == "cam-1":
            new_worker = capture_manager._workers.get("cam-1")

    capture_manager.sessionStarted.connect(on_session_started)
    worker.sessionRestartRequested.emit("cam-1", "camera error")

    with qtbot.waitSignal(capture_manager.sessionStopped, timeout=5000):
        pass
    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        pass

    assert new_worker is not None

    def recording_resumed():
        return (
            capture_manager._recording_states.get("cam-1") is True
            and new_worker._folder_path == "/tmp/out"
        )

    qtbot.waitUntil(recording_resumed, timeout=5000)
    assert new_worker._recording is True
    assert new_worker._recording is True


def test_auto_resume_nas_recording_after_restart(qtbot, device_manager, capture_manager):
    nas = MagicMock()
    nas.connectionHost.return_value = "nas"
    capture_manager._nas_manager = nas

    device_manager._devices = [MediaDevice(device_id="cam-1", description="Cam 1", is_default=False)]
    device_manager.videoInputsChanged.emit()
    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        pass

    capture_manager._desired_nas_recordings["cam-1"] = "conn-1"
    capture_manager._register_nas_watch("conn-1")

    worker = capture_manager._workers["cam-1"]
    with qtbot.waitSignal(capture_manager.sessionStopped, timeout=5000):
        worker.sessionRestartRequested.emit("cam-1", "camera error")

    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        pass

    nas.mountForRecording.assert_called_once_with("conn-1", "cam-1")


def test_restart_loop_guard(qtbot, device_manager, capture_manager):
    device_manager._devices = [MediaDevice(device_id="cam-1", description="Cam 1", is_default=False)]
    device_manager.videoInputsChanged.emit()
    with qtbot.waitSignal(capture_manager.sessionStarted, timeout=5000):
        pass

    worker = capture_manager._workers["cam-1"]
    for _ in range(3):
        with qtbot.waitSignals(
            [capture_manager.sessionStopped, capture_manager.sessionStarted],
            timeout=5000,
        ):
            worker.sessionRestartRequested.emit("cam-1", "camera error")
        worker = capture_manager._workers["cam-1"]

    # Fourth restart should fail and emit an error instead of restarting.
    with qtbot.waitSignal(capture_manager.errorOccurred, timeout=5000):
        worker.sessionRestartRequested.emit("cam-1", "camera error")

    assert "cam-1" not in capture_manager._workers
