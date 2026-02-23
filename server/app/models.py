"""Pydantic models for API requests and responses."""

import re
import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class DeviceStatus(str, Enum):
    registered = "registered"
    ipmi_configured = "ipmi_configured"
    pxe_booting = "pxe_booting"
    os_installed = "os_installed"
    ansible_ready = "ansible_ready"
    failed = "failed"


class RegisterServerRequest(BaseModel):
    bmc_mac: str = Field(..., description="BMC MAC address as 12 hex characters")
    ipmi_password: str = Field(..., min_length=1, description="IPMI/BMC password")
    site: str = Field(..., description="Netbox site slug (e.g. 'dcoa')")
    location: str = Field(..., description="Netbox location slug (e.g. 'rb06')")
    rack: str = Field(..., description="Netbox rack name")
    position: int = Field(..., ge=1, le=50, description="Rack U position (bottom U)")
    device_type: str = Field(..., description="Netbox device type slug")
    device_role: str = Field(..., description="Netbox device role slug")
    ipmi_prefix: str = Field(..., description="IPMI subnet prefix (e.g. 10.16.28.0/24)")

    @field_validator("bmc_mac")
    @classmethod
    def validate_mac(cls, v: str) -> str:
        cleaned = v.replace(":", "").replace("-", "").upper()
        if not re.match(r"^[0-9A-F]{12}$", cleaned):
            raise ValueError("BMC MAC must be 12 hex characters")
        return cleaned

    def formatted_mac(self) -> str:
        """Return MAC in colon-separated format."""
        mac = self.bmc_mac
        return ":".join(mac[i : i + 2] for i in range(0, 12, 2)).lower()

    def device_name(self) -> str:
        """Generate device name: {location}-{rack}u{position}, e.g. dcoa-ra07u45."""
        return f"{self.location}-{self.rack.lower()}u{self.position}"


class RegistrationSteps(BaseModel):
    netbox_device_created: bool = False
    netbox_interface_created: bool = False
    secret_stored: bool = False
    ipmi_ip_assigned: bool = False
    ironic_node_created: bool = False


class RegisterServerResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: DeviceStatus = DeviceStatus.registered
    device_name: str
    netbox_id: int | None = None
    ipmi_ip: str | None = None
    steps: RegistrationSteps = Field(default_factory=RegistrationSteps)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class ServerStatusResponse(BaseModel):
    id: str
    device_name: str
    status: DeviceStatus
    site: str
    rack: str
    position: int
    ipmi_ip: str | None = None
    netbox_id: int | None = None
    created_at: datetime
    steps: RegistrationSteps


class ServerListItem(BaseModel):
    name: str
    status: str
    site: str
    location: str = ""
    rack: str
    position: int | None = None
    device_type: str = ""
    device_role: str = ""
    created: str | None = None


class SiteRef(BaseModel):
    slug: str
    name: str


class LocationRef(BaseModel):
    slug: str
    name: str


class RackRef(BaseModel):
    id: int
    name: str


class DeviceTypeRef(BaseModel):
    slug: str
    model: str
    manufacturer: str


class DeviceRoleRef(BaseModel):
    slug: str
    name: str
    color: str = ""


class PrefixRef(BaseModel):
    prefix: str
    description: str
