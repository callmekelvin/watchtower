import re
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class NasProtocol(str, Enum):
    """Supported NAS protocols."""

    SMB = "smb"
    NFS = "nfs"


class NasConnection(BaseModel):
    """Persistent metadata for a NAS connection.

    Passwords are never part of this model.  They are prompted at runtime and
    kept in memory only for the duration of a mount operation.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    protocol: NasProtocol
    host: str
    share: str
    username: Optional[str] = None
    domain: Optional[str] = None
    mount_options: Optional[str] = None
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def _validate_or_generate_id(cls, value: str) -> str:
        """Treat missing/empty ids as a request for a new UUID."""
        if isinstance(value, str):
            value = value.strip()
        if not value:
            return str(uuid.uuid4())
        return value

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Host cannot be empty")
        # Allow hostnames, IPv4 addresses, and simple IPv6 literals.  Reject
        # characters that could be interpreted by a shell.
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$", value):
            raise ValueError(f"Invalid NAS host: {value}")
        return value

    @field_validator("share")
    @classmethod
    def _validate_share(cls, value: str) -> str:
        value = value.strip().lstrip("\\/").replace("\\", "/")
        if not value:
            raise ValueError("Share cannot be empty")
        if ".." in value.split("/"):
            raise ValueError(f"Invalid NAS share path: {value}")
        if re.search(r"[;&|`$\n\r]", value):
            raise ValueError(f"Invalid NAS share path: {value}")
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Connection name cannot be empty")
        return value

    def display_share(self) -> str:
        """Return a human-readable share path for UI labels."""
        if self.protocol == NasProtocol.SMB:
            return f"\\\\{self.host}\\{self.share}"
        return f"{self.host}:/{self.share}"

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary (no secrets)."""
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol.value,
            "host": self.host,
            "share": self.share,
            "username": self.username,
            "domain": self.domain,
            "mount_options": self.mount_options,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NasConnection":
        """Deserialize from a plain dictionary."""
        return cls(**data)
