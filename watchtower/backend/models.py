from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

# OS Platform
class Platform(str, Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"

# USB Descripters from PyUSB 
class PyUSBDescripters(BaseModel):
    id_vendor: int
    id_product: int
    serial: Optional[str] = None
    manufacturer: Optional[str] = None
    product_name: Optional[str] = None
    bus: Optional[int] = None
    address: Optional[int] = None
    port_path: Tuple[int, ...] = ()