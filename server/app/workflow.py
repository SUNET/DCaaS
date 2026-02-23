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
        ipmi_ip = netbox.allocate_ipmi_ip(device_name, interface_id, req.ipmi_prefix)

        kea = KeaClient()
        await kea.add_reservation(
            mac_address=formatted_mac,
            ip_address=ipmi_ip,
            hostname=f"{device_name}-bmc",
        )
        steps.ipmi_ip_assigned = True

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
