"""Registration workflow orchestrator.

Executes the multi-step server onboarding process, with each step being
idempotent so that retries skip already-completed work.
"""

import logging
from datetime import datetime, timezone

from app.integrations.kea import KeaClient
from app.integrations.metal3 import Metal3Client
from app.integrations.netbox import NetboxClient
from app.integrations.openbao import OpenBaoClient
from app.models import (
    DeviceStatus,
    ImportResultItem,
    ImportServerItem,
    RegisterServerRequest,
    RegisterServerResponse,
    RegistrationSteps,
    ServerStatusResponse,
)

logger = logging.getLogger(__name__)

# In-memory store for demo / MVP; replace with a database for production.
_registrations: dict[str, ServerStatusResponse] = {}


async def register_server(req: RegisterServerRequest) -> RegisterServerResponse:
    """Execute the full server registration workflow.

    Steps:
    1. Generate device name
    2. Create device in Netbox (with IPMI interface)
    3. Store IPMI password in OpenBao
    4. Reserve IPMI IP in Kea DHCP
    5. Create Ironic/Metal3 bare metal node
    6. Update Netbox device status to 'staged'
    """
    device_name = req.device_name()
    formatted_mac = req.formatted_mac()
    steps = RegistrationSteps()
    response = RegisterServerResponse(device_name=device_name)
    netbox_id: int | None = None
    ipmi_ip: str | None = None
    warnings: list[str] = []

    try:
        # Step 1+2: Create device and IPMI interface in Netbox
        netbox = NetboxClient()

        netbox_id, device_created = netbox.create_device(
            name=device_name,
            site=req.site,
            location=req.location,
            rack=req.rack,
            position=req.position,
            device_type=req.device_type,
            device_role=req.device_role,
        )
        steps.netbox_device_created = True
        if not device_created:
            warnings.append(f"Device already exists in Netbox (ID {netbox_id}), skipping creation")

        interface_id, iface_created = netbox.create_bmc_interface(netbox_id, formatted_mac)
        steps.netbox_interface_created = True
        if not iface_created:
            warnings.append("IPMI interface already exists, skipping creation")

        # Step 3: Store IPMI credentials in OpenBao
        openbao = OpenBaoClient()
        openbao.store_credentials(
            device_name=device_name,
            password=req.ipmi_password,
            bmc_mac=formatted_mac,
        )
        steps.secret_stored = True

        # Step 4: Allocate IPMI IP from Netbox IPAM and push DHCP reservation to Kea
        ipmi_ip, ip_created = netbox.allocate_ipmi_ip(device_name, interface_id, req.ipmi_prefix, req.tenant)

        if ipmi_ip:
            kea = KeaClient()
            await kea.add_reservation(
                mac_address=formatted_mac,
                ip_address=ipmi_ip,
                hostname=f"{device_name}-bmc",
            )
            steps.ipmi_ip_assigned = True
            if not ip_created:
                warnings.append(f"IPMI IP {ipmi_ip} already assigned, skipping allocation")
        else:
            warnings.append("IPMI IP already assigned in Netbox but could not be read (check token permissions)")
            steps.ipmi_ip_assigned = True  # not failed, just pre-existing

        # Step 5: Create Ironic/Metal3 bare metal node
        metal3 = Metal3Client()
        metal3.create_bmc_secret(
            device_name=device_name,
            username="ADMIN",
            password=req.ipmi_password,
        )
        metal3.create_baremetalhost(
            device_name=device_name,
            boot_mac=formatted_mac,
            ipmi_ip=ipmi_ip,
        )
        steps.ironic_node_created = True

        # Step 6: Update Netbox device status
        netbox.update_device_status(netbox_id, "staged")

        response.status = DeviceStatus.registered
        response.netbox_id = netbox_id
        response.ipmi_ip = ipmi_ip
        response.steps = steps
        response.warnings = warnings

        logger.info("Successfully registered server %s", device_name)

    except Exception as e:
        logger.exception("Registration failed for %s at steps=%s", device_name, steps)
        response.status = DeviceStatus.failed
        response.netbox_id = netbox_id
        response.ipmi_ip = ipmi_ip
        response.steps = steps
        response.error = str(e)

    # Persist in memory for status queries
    _registrations[response.id] = ServerStatusResponse(
        id=response.id,
        device_name=device_name,
        status=response.status,
        site=req.site,
        rack=req.rack,
        position=req.position,
        ipmi_ip=response.ipmi_ip,
        netbox_id=response.netbox_id,
        created_at=datetime.now(timezone.utc),
        steps=response.steps,
    )

    return response


def get_server_status(server_id: str) -> ServerStatusResponse | None:
    """Get the status of a registered server."""
    return _registrations.get(server_id)


def list_servers() -> list[ServerStatusResponse]:
    """List all registered servers, most recent first."""
    return sorted(
        _registrations.values(),
        key=lambda s: s.created_at,
        reverse=True,
    )


async def import_server(item: ImportServerItem) -> ImportResultItem:
    """Import a single server, running only the applicable integration steps.

    - Netbox: only if all Netbox fields are provided
    - OpenBao: always
    - Kea/Metal3: only if ipmi_ip is known (from input or Netbox allocation)
    """
    steps = RegistrationSteps()
    warnings: list[str] = []
    ipmi_ip = item.ipmi_ip
    formatted_mac = item.formatted_mac()

    try:
        # Step 1: Netbox — only if all required Netbox fields are present
        if item.has_netbox_fields():
            netbox = NetboxClient()

            netbox_id, device_created = netbox.create_device(
                name=item.device_name,
                site=item.site,
                location=item.location,
                rack=item.rack,
                position=item.position,
                device_type=item.device_type,
                device_role=item.device_role,
            )
            steps.netbox_device_created = True
            if not device_created:
                warnings.append(f"Device already exists in Netbox (ID {netbox_id}), skipping creation")

            interface_id, iface_created = netbox.create_bmc_interface(netbox_id, formatted_mac)
            steps.netbox_interface_created = True
            if not iface_created:
                warnings.append("IPMI interface already exists, skipping creation")

            # Allocate IP from Netbox if prefix is provided and no explicit ipmi_ip
            if item.ipmi_prefix and not ipmi_ip:
                allocated_ip, ip_created = netbox.allocate_ipmi_ip(
                    item.device_name, interface_id, item.ipmi_prefix,
                    item.tenant or "",
                )
                if allocated_ip:
                    ipmi_ip = allocated_ip
                    if not ip_created:
                        warnings.append(f"IPMI IP {ipmi_ip} already assigned, skipping allocation")
                else:
                    warnings.append("IPMI IP allocation returned None (check token permissions)")
        else:
            warnings.append("Netbox fields incomplete, skipping Netbox steps")

        # Step 2: OpenBao — always
        openbao = OpenBaoClient()
        openbao.store_credentials(
            device_name=item.device_name,
            password=item.ipmi_password,
            bmc_mac=formatted_mac,
        )
        steps.secret_stored = True

        # Step 3: Kea DHCP — only if ipmi_ip is known
        if ipmi_ip:
            kea = KeaClient()
            await kea.add_reservation(
                mac_address=formatted_mac,
                ip_address=ipmi_ip,
                hostname=f"{item.device_name}-bmc",
            )
            steps.ipmi_ip_assigned = True
        else:
            warnings.append("No IPMI IP available, skipping Kea DHCP reservation")

        # Step 4: Metal3 — only if ipmi_ip is known
        if ipmi_ip:
            metal3 = Metal3Client()
            metal3.create_bmc_secret(
                device_name=item.device_name,
                username="ADMIN",
                password=item.ipmi_password,
            )
            metal3.create_baremetalhost(
                device_name=item.device_name,
                boot_mac=formatted_mac,
                ipmi_ip=ipmi_ip,
            )
            steps.ironic_node_created = True
        else:
            warnings.append("No IPMI IP available, skipping Metal3 BareMetalHost")

        return ImportResultItem(
            device_name=item.device_name,
            status="ok",
            steps=steps,
            warnings=warnings,
            ipmi_ip=ipmi_ip,
        )

    except Exception as e:
        logger.exception("Import failed for %s at steps=%s", item.device_name, steps)
        return ImportResultItem(
            device_name=item.device_name,
            status="failed",
            steps=steps,
            warnings=warnings,
            error=str(e),
            ipmi_ip=ipmi_ip,
        )
