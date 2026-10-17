from pydantic import BaseModel

class MediaDevice(BaseModel):
    device_id: str
    description: str
    is_default: bool