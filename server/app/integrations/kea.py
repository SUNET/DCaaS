"""Kea DHCP integration for managing host reservations via the Control Agent REST API."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class KeaClient:
    """Client for pushing DHCP reservations to Kea Control Agent instances."""

    def __init__(self) -> None:
        self.servers = settings.kea_servers
        self.port = settings.kea_port
        self.subnet_id = settings.kea_subnet_id

    async def _send_command(
        self, server: str, command: str, arguments: dict
    ) -> dict:
        """Send a command to a Kea Control Agent instance."""
        url = f"http://{server}:{self.port}/"
        payload = {
            "command": command,
            "service": ["dhcp4"],
            "arguments": arguments,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

        # Kea returns a list of results (one per service)
        if isinstance(result, list):
            result = result[0]

        if result.get("result", -1) not in (0, 3):
            # result 0 = success, result 3 = empty (reservation already exists for some cmds)
            raise KeaError(
                f"Kea command '{command}' failed on {server}: {result.get('text', 'unknown error')}"
            )
        return result

    async def reservation_exists(self, server: str, mac_address: str) -> bool:
        """Check if a reservation already exists for the given MAC."""
        try:
            result = await self._send_command(
                server,
                "reservation-get-by-hw-address",
                {"hw-address": mac_address, "subnet-id": self.subnet_id},
            )
            hosts = result.get("arguments", {}).get("hosts", [])
            return len(hosts) > 0
        except (KeaError, httpx.HTTPError):
            return False

    async def add_reservation(
        self, mac_address: str, ip_address: str, hostname: str
    ) -> None:
        """Add a DHCP reservation to all Kea instances.

        Pushes to both ironic-conductor nodes for immediate availability.
        The shared PostgreSQL backend ensures eventual consistency regardless.
        """
        reservation = {
            "reservation": {
                "subnet-id": self.subnet_id,
                "hw-address": mac_address,
                "ip-address": ip_address,
                "hostname": hostname,
            }
        }

        errors = []
        for server in self.servers:
            try:
                if await self.reservation_exists(server, mac_address):
                    logger.info(
                        "Reservation for %s already exists on %s, skipping",
                        mac_address,
                        server,
                    )
                    continue

                await self._send_command(server, "reservation-add", reservation)
                logger.info(
                    "Added DHCP reservation on %s: %s -> %s",
                    server,
                    mac_address,
                    ip_address,
                )
            except (KeaError, httpx.HTTPError) as e:
                logger.error("Failed to add reservation on %s: %s", server, e)
                errors.append(f"{server}: {e}")

        if len(errors) == len(self.servers):
            raise KeaError(
                f"Failed to add reservation on all Kea servers: {'; '.join(errors)}"
            )


class KeaError(Exception):
    """Error communicating with Kea."""
