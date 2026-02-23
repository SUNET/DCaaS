"""Ironic / Metal3 integration for bare metal node management."""

import base64
import logging

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

from app.config import settings

logger = logging.getLogger(__name__)

BAREMETALHOST_API_VERSION = "metal3.io/v1alpha1"
BAREMETALHOST_KIND = "BareMetalHost"


class Metal3Client:
    """Client for creating BareMetalHost resources and BMC secrets in Kubernetes."""

    def __init__(self) -> None:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()

        self.custom_api = k8s_client.CustomObjectsApi()
        self.core_api = k8s_client.CoreV1Api()
        self.namespace = settings.metal3_namespace

    def _bmc_secret_name(self, device_name: str) -> str:
        return f"{device_name}-bmc-secret"

    def secret_exists(self, device_name: str) -> bool:
        """Check if the BMC secret already exists."""
        try:
            self.core_api.read_namespaced_secret(
                name=self._bmc_secret_name(device_name),
                namespace=self.namespace,
            )
            return True
        except k8s_client.exceptions.ApiException as e:
            if e.status == 404:
                return False
            raise

    def create_bmc_secret(
        self, device_name: str, username: str, password: str
    ) -> None:
        """Create a Kubernetes Secret with BMC credentials for Metal3."""
        secret_name = self._bmc_secret_name(device_name)

        if self.secret_exists(device_name):
            logger.info("BMC secret %s already exists, skipping", secret_name)
            return

        secret = k8s_client.V1Secret(
            metadata=k8s_client.V1ObjectMeta(
                name=secret_name,
                namespace=self.namespace,
            ),
            type="Opaque",
            data={
                "username": base64.b64encode(username.encode()).decode(),
                "password": base64.b64encode(password.encode()).decode(),
            },
        )

        self.core_api.create_namespaced_secret(
            namespace=self.namespace, body=secret
        )
        logger.info("Created BMC secret %s", secret_name)

    def baremetalhost_exists(self, device_name: str) -> bool:
        """Check if a BareMetalHost resource already exists."""
        try:
            self.custom_api.get_namespaced_custom_object(
                group="metal3.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="baremetalhosts",
                name=device_name,
            )
            return True
        except k8s_client.exceptions.ApiException as e:
            if e.status == 404:
                return False
            raise

    def create_baremetalhost(
        self,
        device_name: str,
        boot_mac: str,
        bmc_ip: str,
    ) -> None:
        """Create a BareMetalHost custom resource."""
        if self.baremetalhost_exists(device_name):
            logger.info("BareMetalHost %s already exists, skipping", device_name)
            return

        bmh = {
            "apiVersion": BAREMETALHOST_API_VERSION,
            "kind": BAREMETALHOST_KIND,
            "metadata": {
                "name": device_name,
                "namespace": self.namespace,
            },
            "spec": {
                "online": False,
                "bootMACAddress": boot_mac,
                "bmc": {
                    "address": f"ipmi://{bmc_ip}",
                    "credentialsName": self._bmc_secret_name(device_name),
                },
                "automatedCleaningMode": "disabled",
            },
        }

        self.custom_api.create_namespaced_custom_object(
            group="metal3.io",
            version="v1alpha1",
            namespace=self.namespace,
            plural="baremetalhosts",
            body=bmh,
        )
        logger.info("Created BareMetalHost %s", device_name)
