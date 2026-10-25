from backend.models import MediaDevice, VideoFormat


def test_video_format_creation():
    fmt = VideoFormat(
        resolution="1920x1080",
        width=1920,
        height=1080,
        min_frame_rate=15.0,
        max_frame_rate=30.0,
        pixel_format="Format_YUV420P",
    )
    assert fmt.width == 1920
    assert fmt.height == 1080
    assert fmt.max_frame_rate == 30.0


def test_media_device_defaults():
    device = MediaDevice(device_id="cam-1", description="Camera One", is_default=False)
    assert device.device_id == "cam-1"
    assert device.description == "Camera One"
    assert device.is_default is False
    assert device.photo_resolutions == []
    assert device.video_formats == []


def test_media_device_with_video_format():
    fmt = VideoFormat(
        resolution="1280x720",
        width=1280,
        height=720,
        min_frame_rate=10.0,
        max_frame_rate=60.0,
        pixel_format="Format_ARGB32",
    )
    device = MediaDevice(
        device_id="cam-2",
        description="Camera Two",
        is_default=True,
        photo_resolutions=["1280x720"],
        video_formats=[fmt],
    )
    assert device.is_default is True
    assert device.video_formats[0].resolution == "1280x720"


def test_media_device_serialization():
    device = MediaDevice(device_id="cam-3", description="Camera Three", is_default=False)
    data = device.model_dump()
    assert data["device_id"] == "cam-3"
    assert "photo_resolutions" in data
    assert "video_formats" in data
