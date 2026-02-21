"""Tests for the FastAPI endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.oidc import validate_token
from app.main import app


async def _fake_auth():
    return {"sub": "test-user", "groups": ["onboarding-operators"]}


@pytest.fixture
def client():
    """Create a test client with auth bypassed."""
    app.dependency_overrides[validate_token] = _fake_auth
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestHealthCheck:
    def test_healthz(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestRegistration:
    @patch("app.main.register_server", new_callable=AsyncMock)
    def test_register_success(self, mock_register, client):
        from app.models import DeviceStatus, RegisterServerResponse, RegistrationSteps

        mock_register.return_value = RegisterServerResponse(
            id="test-uuid",
            status=DeviceStatus.registered,
            device_name="dcoa-rb06u31",
            netbox_id=1234,
            ipmi_ip="10.0.100.42",
            steps=RegistrationSteps(
                netbox_device_created=True,
                netbox_interface_created=True,
                secret_stored=True,
                ipmi_ip_assigned=True,
                ironic_node_created=True,
            ),
        )

        resp = client.post(
            "/api/v1/servers/register",
            json={
                "bmc_mac": "3CECEFA19CE8",
                "ipmi_password": "TestPass123",
                "site": "dcoa",
                "location": "rb06",
                "rack": "rb06",
                "position": 31,
                "device_type": "supermicro-1u",
                "device_role": "k8s-worker",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["device_name"] == "dcoa-rb06u31"
        assert data["steps"]["netbox_device_created"] is True
        assert data["steps"]["ironic_node_created"] is True

    def test_register_invalid_mac(self, client):
        resp = client.post(
            "/api/v1/servers/register",
            json={
                "bmc_mac": "invalid",
                "ipmi_password": "test",
                "site": "dcoa",
                "location": "rb06",
                "rack": "rb06",
                "position": 31,
                "device_type": "supermicro-1u",
                "device_role": "k8s-worker",
            },
        )
        assert resp.status_code == 422

    @patch("app.main.register_server", new_callable=AsyncMock)
    def test_register_failure_returns_500(self, mock_register, client):
        from app.models import DeviceStatus, RegisterServerResponse, RegistrationSteps

        mock_register.return_value = RegisterServerResponse(
            id="test-uuid",
            status=DeviceStatus.failed,
            device_name="dcoa-rb06u31",
            error="Netbox connection refused",
            steps=RegistrationSteps(netbox_device_created=False),
        )

        resp = client.post(
            "/api/v1/servers/register",
            json={
                "bmc_mac": "3CECEFA19CE8",
                "ipmi_password": "TestPass123",
                "site": "dcoa",
                "location": "rb06",
                "rack": "rb06",
                "position": 31,
                "device_type": "supermicro-1u",
                "device_role": "k8s-worker",
            },
        )
        assert resp.status_code == 500


class TestServerList:
    def test_list_empty(self, client):
        resp = client.get("/api/v1/servers")
        assert resp.status_code == 200
        assert resp.json() == []


class TestServerStatus:
    def test_not_found(self, client):
        resp = client.get("/api/v1/servers/nonexistent/status")
        assert resp.status_code == 404
