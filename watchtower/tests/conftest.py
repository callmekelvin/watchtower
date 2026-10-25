import os
from pathlib import Path
from typing import Callable, List
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QByteArray, QSettings, QSize
from PySide6.QtMultimedia import QMediaDevices


@pytest.fixture
def temp_folder(tmp_path: Path) -> Path:
    """Return a temporary folder for file-based tests."""
    return tmp_path


@pytest.fixture
def ini_settings(tmp_path: Path) -> QSettings:
    """Provide an isolated INI-backed QSettings instance.

    INI format is used so tests behave the same on Linux, macOS, and Windows.
    """
    ini_path = tmp_path / "test_settings.ini"
    settings = QSettings(str(ini_path), QSettings.IniFormat)
    settings.clear()
    yield settings
    settings.sync()


@pytest.fixture
def fake_video_format() -> Callable[..., MagicMock]:
    """Factory for mocked QCameraDevice.VideoFormat-like objects."""

    def _make(
        width: int = 1920,
        height: int = 1080,
        min_frame_rate: float = 15.0,
        max_frame_rate: float = 30.0,
        pixel_format_name: str = "Format_YUV420P",
    ) -> MagicMock:
        size = QSize(width, height)
        pixel_format = MagicMock()
        pixel_format.name = pixel_format_name

        fmt = MagicMock()
        fmt.resolution.return_value = size
        fmt.minFrameRate.return_value = min_frame_rate
        fmt.maxFrameRate.return_value = max_frame_rate
        fmt.pixelFormat.return_value = pixel_format
        return fmt

    return _make


@pytest.fixture
def fake_camera_device() -> Callable[..., MagicMock]:
    """Factory for mocked QCameraDevice-like objects."""

    def _make(
        device_id: str = "camera-1",
        description: str = "Fake Camera",
        is_default: bool = False,
        photo_resolutions: List[QSize] | None = None,
        video_formats: List[MagicMock] | None = None,
    ) -> MagicMock:
        if photo_resolutions is None:
            photo_resolutions = [QSize(640, 480), QSize(1920, 1080)]
        if video_formats is None:
            fmt = MagicMock()
            size = QSize(1920, 1080)
            pixel_format = MagicMock()
            pixel_format.name = "Format_YUV420P"
            fmt.resolution.return_value = size
            fmt.minFrameRate.return_value = 15.0
            fmt.maxFrameRate.return_value = 30.0
            fmt.pixelFormat.return_value = pixel_format
            video_formats = [fmt]

        device = MagicMock()
        device.id.return_value = QByteArray(device_id.encode("utf-8"))
        device.description.return_value = description
        device.isDefault.return_value = is_default
        device.photoResolutions.return_value = photo_resolutions
        device.videoFormats.return_value = video_formats
        return device

    return _make


@pytest.fixture
def patched_video_inputs(monkeypatch) -> Callable[[List[MagicMock]], None]:
    """Replace QMediaDevices.videoInputs() with a fixed list of fake devices."""

    def _patch(devices: List[MagicMock]) -> None:
        monkeypatch.setattr(QMediaDevices, "videoInputs", staticmethod(lambda: devices))

    return _patch


def pytest_configure(config) -> None:
    """Use the offscreen Qt platform when no display is available.

    This must run before pytest-qt creates the QApplication fixture.
    """
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
