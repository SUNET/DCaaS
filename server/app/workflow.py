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
    2. Create device in Netbox (with BMC interface)
    3. Store BMC password in OpenBao
    4. Reserve BMC IP in Kea DHCP
    5. Create Ironic/Metal3 bare metal node
    6. Update Netbox device status to 'staged'
    """
    device_name = req.device_name()
    formatted_mac = req.formatted_mac()
    steps = RegistrationSteps()
    response = RegisterServerResponse(device_name=device_name)
    netbox_id: int | None = None
    bmc_ip: str | None = None
    warnings: list[str] = []

    try:
        # Step 1+2: Create device and BMC interface in Netbox
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
            warnings.append("BMC interface already exists, skipping creation")

        # Step 3: Store BMC credentials in OpenBao
        openbao = OpenBaoClient()
        openbao.store_credentials(
            device_name=device_name,
            password=req.bmc_password,
            bmc_mac=formatted_mac,
        )
        steps.secret_stored = True

        # Step 4: Allocate BMC IP from Netbox IPAM and push DHCP reservation to Kea
        bmc_ip, ip_created = netbox.allocate_bmc_ip(device_name, interface_id, req.bmc_prefix, req.tenant)

        if bmc_ip:
            kea = KeaClient()
            await kea.add_reservation(
                mac_address=formatted_mac,
                ip_address=bmc_ip,
                hostname=f"{device_name}-bmc",
            )
            steps.bmc_ip_assigned = True
            if not ip_created:
                warnings.append(f"BMC IP {bmc_ip} already assigned, skipping allocation")
        else:
            warnings.append("BMC IP already assigned in Netbox but could not be read (check token permissions)")
            steps.bmc_ip_assigned = True  # not failed, just pre-existing

        # Step 5: Create Ironic/Metal3 bare metal node
        metal3 = Metal3Client()
        metal3.create_bmc_secret(
            device_name=device_name,
            username="ADMIN",
            password=req.bmc_password,
        )
        metal3.create_baremetalhost(
            device_name=device_name,
            boot_mac=formatted_mac,
            bmc_ip=bmc_ip,
        )
        steps.ironic_node_created = True

        # Step 6: Update Netbox device status
        netbox.update_device_status(netbox_id, "staged")

        response.status = DeviceStatus.registered
        response.netbox_id = netbox_id
        response.bmc_ip = bmc_ip
        response.steps = steps
        response.warnings = warnings

        logger.info("Successfully registered server %s", device_name)

    except Exception as e:
        logger.exception("Registration failed for %s at steps=%s", device_name, steps)
        response.status = DeviceStatus.failed
        response.netbox_id = netbox_id
        response.bmc_ip = bmc_ip
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
        bmc_ip=response.bmc_ip,
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
    - Kea/Metal3: only if bmc_ip is known (from input or Netbox allocation)
    """
    steps = RegistrationSteps()
    warnings: list[str] = []
    bmc_ip = item.bmc_ip
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
                warnings.append("BMC interface already exists, skipping creation")

            # Allocate IP from Netbox if prefix is provided and no explicit bmc_ip
            if item.bmc_prefix and not bmc_ip:
                allocated_ip, ip_created = netbox.allocate_bmc_ip(
                    item.device_name, interface_id, item.bmc_prefix,
                    item.tenant or "",
                )
                if allocated_ip:
                    bmc_ip = allocated_ip
                    if not ip_created:
                        warnings.append(f"BMC IP {bmc_ip} already assigned, skipping allocation")
                else:
                    warnings.append("BMC IP allocation returned None (check token permissions)")
        else:
            warnings.append("Netbox fields incomplete, skipping Netbox steps")

        # Step 2: OpenBao — always
        openbao = OpenBaoClient()
        openbao.store_credentials(
            device_name=item.device_name,
            password=item.bmc_password,
            bmc_mac=formatted_mac,
        )
        steps.secret_stored = True

        # Step 3: Kea DHCP — only if bmc_ip is known
        if bmc_ip:
            kea = KeaClient()
            await kea.add_reservation(
                mac_address=formatted_mac,
                ip_address=bmc_ip,
                hostname=f"{item.device_name}-bmc",
            )
            steps.bmc_ip_assigned = True
        else:
            warnings.append("No BMC IP available, skipping Kea DHCP reservation")

        # Step 4: Metal3 — only if bmc_ip is known
        if bmc_ip:
            metal3 = Metal3Client()
            metal3.create_bmc_secret(
                device_name=item.device_name,
                username="ADMIN",
                password=item.bmc_password,
            )
            metal3.create_baremetalhost(
                device_name=item.device_name,
                boot_mac=formatted_mac,
                bmc_ip=bmc_ip,
            )
            steps.ironic_node_created = True
        else:
            warnings.append("No BMC IP available, skipping Metal3 BareMetalHost")

        return ImportResultItem(
            device_name=item.device_name,
            status="ok",
            steps=steps,
            warnings=warnings,
            bmc_ip=bmc_ip,
        )

    except Exception as e:
        logger.exception("Import failed for %s at steps=%s", item.device_name, steps)
        return ImportResultItem(
            device_name=item.device_name,
            status="failed",
            steps=steps,
            warnings=warnings,
            error=str(e),
            bmc_ip=bmc_ip,
        )
