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

    def get_devices(self) -> list[dict]:
        """List all devices, most recently created first."""
        devices = self.api.dcim.devices.all()
        result = []
        for d in devices:
            result.append({
                "name": d.name,
                "status": d.status.value if d.status else "unknown",
                "site": d.site.slug if d.site else "",
                "location": d.location.slug if d.location else "",
                "rack": d.rack.name if d.rack else "",
                "position": int(d.position) if d.position else None,
                "device_type": f"{d.device_type.manufacturer.name} {d.device_type.model}" if d.device_type else "",
                "device_role": d.role.name if d.role else "",
                "created": str(d.created) if d.created else None,
            })
        result.sort(key=lambda x: x["created"] or "", reverse=True)
        return result

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

    def create_bmc_interface(self, device_id: int, mac_address: str) -> tuple[int, bool]:
        """Create a BMC interface on a device. Returns (interface_id, created)."""
        existing = list(
            self.api.dcim.interfaces.filter(device_id=device_id, name="bmc")
        )
        if existing:
            logger.info("BMC interface already exists on device %d", device_id)
            return existing[0].id, False

        iface = self.api.dcim.interfaces.create(
            device=device_id,
            name="bmc",
            type="1000base-t",
            mac_address=mac_address,
        )
        logger.info("Created BMC interface %d on device %d", iface.id, device_id)
        return iface.id, True

    def get_prefixes(self) -> list[dict]:
        """List all prefixes with role 'bmc'."""
        return [
            {"prefix": str(p.prefix), "description": p.description or str(p.prefix)}
            for p in self.api.ipam.prefixes.filter(role="bmc")
        ]

    def get_tenants(self) -> list[dict]:
        """List all tenants."""
        return [
            {"slug": t.slug, "name": t.name}
            for t in self.api.tenancy.tenants.all()
        ]

    def allocate_bmc_ip(self, device_name: str, interface_id: int, bmc_prefix: str, tenant: str = "") -> tuple[str | None, bool]:
        """Allocate the next available IP from the given prefix and assign it to the BMC interface.

        Returns (ip_address, created). If the IP already exists, created is False.
        Returns (None, False) if allocation fails due to permissions.
        """
        # Check if the interface already has IPs assigned
        iface = self.api.dcim.interfaces.get(interface_id)
        if iface and iface.count_ipaddresses and iface.count_ipaddresses > 0:
            # Try to read the actual IP
            existing = list(
                self.api.ipam.ip_addresses.filter(interface_id=interface_id)
            )
            if existing:
                ip = str(existing[0].address).split("/")[0]
                logger.info("IP %s already assigned to interface %d", ip, interface_id)
                return ip, False
            # Interface has IPs but we can't read them (likely missing ipam.view_ipaddress)
            logger.warning(
                "Interface %d has %d IP(s) but token lacks read permission, skipping allocation",
                interface_id, iface.count_ipaddresses,
            )
            return None, False

        prefix = self.api.ipam.prefixes.get(prefix=bmc_prefix)
        if prefix is None:
            raise ValueError(f"BMC prefix '{bmc_prefix}' not found in Netbox")

        ip_data = {
            "description": f"{device_name} BMC",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": interface_id,
        }
        if tenant:
            ip_data["tenant"] = {"slug": tenant}
        available = prefix.available_ips.create(ip_data)
        ip = str(available.address).split("/")[0]
        logger.info("Allocated IP %s for %s", ip, device_name)
        return ip, True

    def update_device_status(self, device_id: int, status: str) -> None:
        """Update a device's status in Netbox."""
        device = self.api.dcim.devices.get(device_id)
        device.status = status
        device.save()
        logger.info("Updated device %d status to %s", device_id, status)
