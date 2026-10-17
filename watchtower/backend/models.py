from pydantic import BaseModel

# Video Format for Camera Device
class VideoFormat(BaseModel):
    resolution: str
    width: int
    height: int
    min_frame_rate: float
    max_frame_rate: float
    pixel_format: str

# Camera Device
class MediaDevice(BaseModel):
    device_id: str
    description: str
    is_default: bool
    photo_resolutions: list[str] = []
    video_formats: list[VideoFormat] = []
