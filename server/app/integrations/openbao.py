"""OpenBao (Vault-compatible) integration for BMC credential storage."""

import logging

import hvac

from app.config import settings

logger = logging.getLogger(__name__)


class OpenBaoClient:
    """Client for storing and retrieving BMC credentials in OpenBao."""

    def __init__(self) -> None:
        self.client = hvac.Client(url=settings.openbao_url)
        self._authenticate()

    def _authenticate(self) -> None:
        """Authenticate using AppRole."""
        if settings.openbao_role_id and settings.openbao_secret_id:
            self.client.auth.approle.login(
                role_id=settings.openbao_role_id,
                secret_id=settings.openbao_secret_id,
            )
            logger.info("Authenticated to OpenBao via AppRole")

    def secret_exists(self, device_name: str) -> bool:
        """Check if a secret already exists for this device."""
        try:
            result = self.client.secrets.kv.v2.read_secret_version(
                path=f"bmc/{device_name}",
                mount_point=settings.openbao_mount_point,
            )
            return result is not None
        except hvac.exceptions.InvalidPath:
            return False

    def store_credentials(
        self, device_name: str, password: str, bmc_mac: str, username: str = "ADMIN"
    ) -> None:
        """Store BMC credentials in OpenBao at secret/data/bmc/{device_name}."""
        if self.secret_exists(device_name):
            logger.info("Secret for %s already exists, skipping", device_name)
            return

        self.client.secrets.kv.v2.create_or_update_secret(
            path=f"bmc/{device_name}",
            secret={
                "username": username,
                "password": password,
                "bmc_mac": bmc_mac,
            },
            mount_point=settings.openbao_mount_point,
        )
        logger.info("Stored BMC credentials for %s", device_name)

    def read_credentials(self, device_name: str) -> dict | None:
        """Read BMC credentials for a device."""
        try:
            result = self.client.secrets.kv.v2.read_secret_version(
                path=f"bmc/{device_name}",
                mount_point=settings.openbao_mount_point,
            )
            return result["data"]["data"]
        except hvac.exceptions.InvalidPath:
            return None
