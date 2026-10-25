from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaRecorder

from backend.capture_session_worker import (
    CaptureSessionWorker,
    _sanitize_filename,
)


def test_sanitize_filename_with_special_characters():
    assert _sanitize_filename("USB Camera (Live)") == "usb-camera-live"


def test_sanitize_filename_with_multiple_spaces():
    assert _sanitize_filename("  My   Camera  ") == "my-camera"


def test_sanitize_filename_empty():
    assert _sanitize_filename("!!!") == "camera"


def test_generate_output_path_uses_folder_and_suffix(temp_folder):
    worker = CaptureSessionWorker("cam-1")
    worker._camera_device = MagicMock()
    worker._camera_device.description.return_value = "Test Camera"

    path = worker._generate_output_path(str(temp_folder))
    path_obj = Path(path)

    assert path_obj.parent == temp_folder
    assert path_obj.suffix == ".mp4"
    assert path_obj.name.startswith("test-camera_")


def test_set_video_sink_ignores_wrong_device_id(qtbot):
    worker = CaptureSessionWorker("cam-1")
    sink = MagicMock()
    worker.setVideoSink("cam-2", sink)
    assert worker._video_sink is None


def test_clear_video_sink_ignores_wrong_device_id(qtbot):
    worker = CaptureSessionWorker("cam-1")
    worker._video_sink = MagicMock()
    worker.clearVideoSink("cam-2")
    assert worker._video_sink is not None


def test_start_recording_ignores_wrong_device_id(qtbot):
    worker = CaptureSessionWorker("cam-1")
    with qtbot.assertNotEmitted(worker.errorOccurred):
        worker.startRecording("cam-2", "/tmp/out")


def test_start_recording_rejects_invalid_path(qtbot):
    worker = CaptureSessionWorker("cam-1")
    with qtbot.waitSignal(worker.errorOccurred, timeout=1000):
        worker.startRecording("cam-1", "")


def test_stop_recording_sets_stop_requested(qtbot):
    worker = CaptureSessionWorker("cam-1")
    worker.stopRecording("cam-1")
    assert worker._stop_requested is True


def test_recorder_state_change_emits_recording_started(qtbot):
    worker = CaptureSessionWorker("cam-1")
    worker._recorder = MagicMock()

    with qtbot.waitSignal(worker.recordingStateChanged, timeout=1000):
        worker._on_recorder_state_changed(QMediaRecorder.RecorderState.RecordingState)

    assert worker._is_recording is True


def test_recorder_state_change_emits_recording_stopped(qtbot):
    worker = CaptureSessionWorker("cam-1")
    worker._recorder = MagicMock()
    worker._stop_requested = True
    worker._is_recording = True

    with qtbot.waitSignal(worker.recordingStateChanged, timeout=1000):
        worker._on_recorder_state_changed(QMediaRecorder.RecorderState.StoppedState)

    assert worker._is_recording is False


def test_recorder_error_emits_error_and_stops_recording(qtbot):
    worker = CaptureSessionWorker("cam-1")
    worker._recorder = MagicMock()
    worker._is_recording = True

    with qtbot.waitSignals([worker.errorOccurred, worker.recordingStateChanged], timeout=1000):
        worker._on_recorder_error(QMediaRecorder.Error.ResourceError, "disk full")

    assert worker._is_recording is False


def test_stop_emits_stopped_signal(qtbot):
    worker = CaptureSessionWorker("cam-1")
    worker._recorder = MagicMock()
    worker._camera = MagicMock()
    worker._session = MagicMock()

    with qtbot.waitSignal(worker.stopped, timeout=1000):
        worker.stop()

    assert worker._is_recording is False
