from datetime import datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QByteArray, QSize

from backend.device_worker import (
    DeviceWorker,
    _best_video_format,
    _decode_id,
    _largest_photo_resolution,
    _pixel_format_name,
    _to_media_device,
)
from backend.models import MediaDevice


def test_decode_id_with_valid_bytes():
    assert _decode_id(b"camera-one") == "camera-one"


def test_decode_id_with_qbytearray():
    assert _decode_id(QByteArray("camera-two".encode("utf-8"))) == "camera-two"


def test_decode_id_with_invalid_utf8():
    assert _decode_id(b"\xff\xfe") == "\ufffd\ufffd"


def test_pixel_format_name_with_name_attribute():
    fmt = MagicMock()
    fmt.name = "Format_RGB24"
    assert _pixel_format_name(fmt) == "Format_RGB24"


def test_pixel_format_name_without_name_attribute():
    fmt = object()
    assert _pixel_format_name(fmt) == str(fmt)


def test_largest_photo_resolution():
    sizes = [QSize(640, 480), QSize(1920, 1080), QSize(1280, 720)]
    result = _largest_photo_resolution(MagicMock(photoResolutions=MagicMock(return_value=sizes)))
    assert result == ["1920x1080"]


def test_largest_photo_resolution_empty():
    result = _largest_photo_resolution(MagicMock(photoResolutions=MagicMock(return_value=[])))
    assert result == []


def test_best_video_format_picks_max_resolution_then_max_frame_rate(fake_video_format):
    low_res = fake_video_format(width=1280, height=720, max_frame_rate=60.0)
    high_res_low_fps = fake_video_format(width=1920, height=1080, max_frame_rate=30.0)
    high_res_high_fps = fake_video_format(width=1920, height=1080, max_frame_rate=60.0)

    device = MagicMock()
    device.videoFormats.return_value = [low_res, high_res_low_fps, high_res_high_fps]

    result = _best_video_format(device)
    assert len(result) == 1
    assert result[0].width == 1920
    assert result[0].height == 1080
    assert result[0].max_frame_rate == 60.0


def test_best_video_format_empty():
    device = MagicMock()
    device.videoFormats.return_value = []
    assert _best_video_format(device) == []


def test_to_media_device(fake_camera_device):
    device = fake_camera_device(
        device_id="usb-cam-1",
        description="USB Camera",
        is_default=True,
    )
    media = _to_media_device(device)
    assert isinstance(media, MediaDevice)
    assert media.device_id == "usb-cam-1"
    assert media.description == "USB Camera"
    assert media.is_default is True
    assert media.photo_resolutions == ["1920x1080"]
    assert len(media.video_formats) == 1
    assert media.video_formats[0].resolution == "1920x1080"


def test_device_worker_refresh_emits_devices_changed(qtbot, patched_video_inputs, fake_camera_device):
    camera = fake_camera_device(device_id="cam-a", description="Camera A")
    patched_video_inputs([camera])

    worker = DeviceWorker()
    with qtbot.waitSignal(worker.devicesChanged, timeout=1000):
        worker._refresh()


def test_device_worker_refresh_emits_error_on_exception(qtbot, monkeypatch):
    def _bad_video_inputs():
        raise RuntimeError("enumeration failed")

    monkeypatch.setattr(
        "backend.device_worker.QMediaDevices.videoInputs",
        staticmethod(_bad_video_inputs),
    )

    worker = DeviceWorker()
    with qtbot.waitSignal(worker.errorOccurred, timeout=1000):
        worker._refresh()
