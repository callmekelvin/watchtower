from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtMultimedia import QMediaRecorder

from backend.capture_session_worker import (
    CaptureSessionWorker,
    _sanitize_filename,
)


@pytest.fixture
def capture_worker(qtbot):
    """Create a CaptureSessionWorker and ensure it is deleted after the test."""
    worker = CaptureSessionWorker("cam-1")
    yield worker
    worker.deleteLater()


def test_sanitize_filename_with_special_characters():
    assert _sanitize_filename("USB Camera (Live)") == "usb-camera-live"


def test_sanitize_filename_with_multiple_spaces():
    assert _sanitize_filename("  My   Camera  ") == "my-camera"


def test_sanitize_filename_empty():
    assert _sanitize_filename("!!!") == "camera"


def test_generate_output_path_uses_folder_and_suffix(capture_worker, temp_folder):
    capture_worker._camera_device = MagicMock()
    capture_worker._camera_device.description.return_value = "Test Camera"

    path = capture_worker._generate_output_path(str(temp_folder))
    path_obj = Path(path)

    assert path_obj.parent == temp_folder
    assert path_obj.suffix == ".mp4"
    assert path_obj.name.startswith("test-camera_")


def test_set_video_sink_ignores_wrong_device_id(capture_worker):
    sink = MagicMock()
    capture_worker.setVideoSink("cam-2", sink)
    assert capture_worker._video_sink is None


def test_clear_video_sink_ignores_wrong_device_id(capture_worker):
    capture_worker._video_sink = MagicMock()
    capture_worker.clearVideoSink("cam-2")
    assert capture_worker._video_sink is not None


def test_start_recording_ignores_wrong_device_id(qtbot, capture_worker):
    with qtbot.assertNotEmitted(capture_worker.errorOccurred):
        capture_worker.startRecording("cam-2", "/tmp/out")


def test_start_recording_rejects_invalid_path(qtbot, capture_worker):
    with qtbot.waitSignal(capture_worker.errorOccurred, timeout=1000):
        capture_worker.startRecording("cam-1", "")


def test_stop_recording_sets_stop_requested(capture_worker):
    capture_worker.stopRecording("cam-1")
    assert capture_worker._stop_requested is True


def test_recorder_state_change_emits_recording_started(qtbot, capture_worker):
    capture_worker._recorder = MagicMock()

    with qtbot.waitSignal(capture_worker.recordingStateChanged, timeout=1000):
        capture_worker._on_recorder_state_changed(QMediaRecorder.RecorderState.RecordingState)

    assert capture_worker._is_recording is True


def test_recorder_state_change_emits_recording_stopped(qtbot, capture_worker):
    capture_worker._recorder = MagicMock()
    capture_worker._stop_requested = True
    capture_worker._is_recording = True

    with qtbot.waitSignal(capture_worker.recordingStateChanged, timeout=1000):
        capture_worker._on_recorder_state_changed(QMediaRecorder.RecorderState.StoppedState)

    assert capture_worker._is_recording is False


def test_recorder_error_emits_error_stops_recording_and_triggers_fatal_signal(qtbot, capture_worker):
    capture_worker._recorder = MagicMock()
    capture_worker._is_recording = True

    with qtbot.waitSignals(
        [capture_worker.errorOccurred, capture_worker.recordingStateChanged], timeout=1000
    ):
        capture_worker._on_recorder_error(QMediaRecorder.Error.ResourceError, "disk full")

    assert capture_worker._segment_start_failed is True

    with qtbot.waitSignal(capture_worker.fatalErrorOccurred, timeout=1000):
        capture_worker._on_recorder_state_changed(QMediaRecorder.RecorderState.StoppedState)

    assert capture_worker._is_recording is False


def test_stop_emits_stopped_signal(qtbot, capture_worker):
    capture_worker._recorder = MagicMock()
    capture_worker._camera = MagicMock()
    capture_worker._session = MagicMock()

    with qtbot.waitSignal(capture_worker.stopped, timeout=1000):
        capture_worker.stop()

    assert capture_worker._is_recording is False


def test_start_next_segment_failure_emits_fatal_error(qtbot, capture_worker, tmp_path):
    # Create a file where the worker expects a folder so _ensure_output_folder fails
    # deterministically on both Unix and Windows.
    blocked_folder = tmp_path / "not_a_dir"
    blocked_folder.write_text("x")

    capture_worker._recorder = MagicMock()
    capture_worker._output_folder = str(blocked_folder)

    with qtbot.waitSignals(
        [capture_worker.errorOccurred, capture_worker.fatalErrorOccurred], timeout=1000
    ):
        capture_worker._start_next_segment()

    assert capture_worker._is_recording is False


def test_start_recording_failure_emits_fatal_error(qtbot, capture_worker, tmp_path):
    # Create a file where the worker expects a folder so _ensure_output_folder fails
    # deterministically on both Unix and Windows.
    blocked_folder = tmp_path / "not_a_dir"
    blocked_folder.write_text("x")

    capture_worker._recorder = MagicMock()

    with qtbot.waitSignals(
        [capture_worker.errorOccurred, capture_worker.fatalErrorOccurred], timeout=1000
    ):
        capture_worker.startRecording("cam-1", str(blocked_folder))
