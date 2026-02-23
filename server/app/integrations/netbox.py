"""Netbox DCIM integration for device and IPAM management."""

import logging

import pynetbox

from app.config import settings

logger = logging.getLogger(__name__)


class NetboxClient:
    """Client for Netbox DCIM and IPAM operations."""

    def __init__(self) -> None:
        self.api = pynetbox.api(settings.netbox_url, token=settings.netbox_token)

    def get_sites(self) -> list[dict]:
        """List all sites."""
        return [{"slug": s.slug, "name": s.name} for s in self.api.dcim.sites.all()]

    def get_locations(self, site_slug: str) -> list[dict]:
        """List locations (rack groups) filtered by site."""
        return [
            {"slug": loc.slug, "name": loc.name}
            for loc in self.api.dcim.locations.filter(site=site_slug)
        ]

    def get_racks(self, location_slug: str) -> list[dict]:
        """List racks filtered by location."""
        return [
            {"id": r.id, "name": r.name}
            for r in self.api.dcim.racks.filter(location=location_slug)
        ]

    def get_device_types(self) -> list[dict]:
        """List all device types."""
        return [
            {
                "slug": dt.slug,
                "model": dt.model,
                "manufacturer": dt.manufacturer.name if dt.manufacturer else "",
            }
            for dt in self.api.dcim.device_types.all()
        ]

    def get_device_roles(self) -> list[dict]:
        """List all device roles."""
        return [
            {"slug": dr.slug, "name": dr.name, "color": dr.color or ""}
            for dr in self.api.dcim.device_roles.all()
        ]

    def device_exists(self, name: str) -> int | None:
        """Check if a device with this name already exists. Returns its ID or None."""
        devices = list(self.api.dcim.devices.filter(name=name))
        if devices:
            return devices[0].id
        return None

    def create_device(
        self,
        name: str,
        site: str,
        location: str,
        rack: str,
        position: int,
        device_type: str,
        device_role: str,
    ) -> tuple[int, bool]:
        """Create a device in Netbox. Returns (device_id, created).

        If a device with the same name already exists, returns its ID.
        If the rack position is already occupied, returns the occupying device's ID.
        In both cases ``created`` is False.
        """
        existing_id = self.device_exists(name)
        if existing_id is not None:
            logger.info("Device %s already exists with ID %d, skipping creation", name, existing_id)
            return existing_id, False

        rack_obj = self.api.dcim.racks.get(name=rack, location=location)
        if rack_obj is None:
            raise ValueError(f"Rack '{rack}' not found in location '{location}'")

        # Check if the position is already occupied
        occupant = list(self.api.dcim.devices.filter(rack_id=rack_obj.id, position=position))
        if occupant:
            logger.warning(
                "Position U%d in rack %s already occupied by %s (ID %d), skipping creation",
                position, rack, occupant[0].name, occupant[0].id,
            )
            return occupant[0].id, False

        device = self.api.dcim.devices.create(
            name=name,
            site={"slug": site},
            location={"slug": location},
            rack=rack_obj.id,
            position=position,
            face="front",
            device_type={"slug": device_type},
            role={"slug": device_role},
            status="planned",
        )
        logger.info("Created device %s with ID %d", name, device.id)
        return device.id, True

    def create_bmc_interface(self, device_id: int, mac_address: str) -> int:
        """Create a BMC interface on a device. Returns the interface ID."""
        existing = list(
            self.api.dcim.interfaces.filter(device_id=device_id, name="BMC")
        )
        if existing:
            logger.info("BMC interface already exists on device %d", device_id)
            return existing[0].id

        iface = self.api.dcim.interfaces.create(
            device=device_id,
            name="BMC",
            type="1000base-t",
            mac_address=mac_address,
        )
        logger.info("Created BMC interface %d on device %d", iface.id, device_id)
        return iface.id

    def allocate_ipmi_ip(self, device_name: str, interface_id: int) -> str:
        """Allocate the next available IP from the IPMI prefix and assign it to the BMC interface.

        Returns the allocated IP address (without prefix length).
        """
        existing = list(
            self.api.ipam.ip_addresses.filter(interface_id=interface_id)
        )
        if existing:
            ip = str(existing[0].address).split("/")[0]
            logger.info("IP %s already assigned to interface %d", ip, interface_id)
            return ip

        prefix = self.api.ipam.prefixes.get(prefix=settings.ipmi_prefix)
        if prefix is None:
            raise ValueError(f"IPMI prefix '{settings.ipmi_prefix}' not found in Netbox")

        available = prefix.available_ips.create(
            {
                "description": f"{device_name} BMC",
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": interface_id,
            }
        )
        ip = str(available.address).split("/")[0]
        logger.info("Allocated IP %s for %s", ip, device_name)
        return ip

    def update_device_status(self, device_id: int, status: str) -> None:
        """Update a device's status in Netbox."""
        device = self.api.dcim.devices.get(device_id)
        device.status = status
        device.save()
        logger.info("Updated device %d status to %s", device_id, status)
