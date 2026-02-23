"""Tests for the FastAPI endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.oidc import validate_token
from app.main import app


async def _fake_auth():
    return {"sub": "test-user"}


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
            bmc_ip="10.0.100.42",
            steps=RegistrationSteps(
                netbox_device_created=True,
                netbox_interface_created=True,
                secret_stored=True,
                bmc_ip_assigned=True,
                ironic_node_created=True,
            ),
        )

        resp = client.post(
            "/api/v1/servers/register",
            json={
                "bmc_mac": "3CECEFA19CE8",
                "bmc_password": "TestPass123",
                "site": "dcoa",
                "location": "rb06",
                "rack": "rb06",
                "position": 31,
                "device_type": "supermicro-1u",
                "device_role": "k8s-worker",
                "bmc_prefix": "10.16.28.0/24",
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
                "bmc_password": "test",
                "site": "dcoa",
                "location": "rb06",
                "rack": "rb06",
                "position": 31,
                "device_type": "supermicro-1u",
                "device_role": "k8s-worker",
                "bmc_prefix": "10.16.28.0/24",
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
                "bmc_password": "TestPass123",
                "site": "dcoa",
                "location": "rb06",
                "rack": "rb06",
                "position": 31,
                "device_type": "supermicro-1u",
                "device_role": "k8s-worker",
                "bmc_prefix": "10.16.28.0/24",
            },
        )
        assert resp.status_code == 500


class TestServerList:
    @patch("app.main._netbox")
    def test_list_from_netbox(self, mock_netbox, client):
        mock_netbox.return_value.get_devices.return_value = [
            {
                "name": "dcoa-ra07u45",
                "status": "staged",
                "site": "sunetdco",
                "location": "dcoa",
                "rack": "RA07",
                "position": 45,
                "device_type": "Supermicro 1U",
                "device_role": "k8s-worker",
                "created": "2026-02-23T12:00:00Z",
            }
        ]
        # Clear cache so the mock is used
        from app.main import _ref_cache
        _ref_cache.pop("devices", None)

        resp = client.get("/api/v1/servers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "dcoa-ra07u45"
        assert data[0]["status"] == "staged"


class TestImport:
    @patch("app.main.import_server", new_callable=AsyncMock)
    def test_import_success(self, mock_import, client):
        from app.models import ImportResultItem, RegistrationSteps

        mock_import.return_value = ImportResultItem(
            device_name="dcoa-ra07u45",
            status="ok",
            steps=RegistrationSteps(
                secret_stored=True,
                bmc_ip_assigned=True,
                ironic_node_created=True,
            ),
            bmc_ip="10.16.28.78",
        )

        resp = client.post(
            "/api/v1/servers/import",
            json=[
                {
                    "device_name": "dcoa-ra07u45",
                    "bmc_mac": "3CECEFA19CE8",
                    "bmc_password": "secret123",
                    "bmc_ip": "10.16.28.78",
                }
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["device_name"] == "dcoa-ra07u45"
        assert data[0]["status"] == "ok"
        assert data[0]["steps"]["secret_stored"] is True

    def test_import_invalid_mac(self, client):
        resp = client.post(
            "/api/v1/servers/import",
            json=[
                {
                    "device_name": "test",
                    "bmc_mac": "invalid",
                    "bmc_password": "secret",
                }
            ],
        )
        assert resp.status_code == 422

    def test_import_missing_required_field(self, client):
        resp = client.post(
            "/api/v1/servers/import",
            json=[{"device_name": "test", "bmc_mac": "3CECEFA19CE8"}],
        )
        assert resp.status_code == 422

    @patch("app.main.import_server", new_callable=AsyncMock)
    def test_import_batch(self, mock_import, client):
        from app.models import ImportResultItem, RegistrationSteps

        mock_import.side_effect = [
            ImportResultItem(
                device_name="server1",
                status="ok",
                steps=RegistrationSteps(secret_stored=True),
            ),
            ImportResultItem(
                device_name="server2",
                status="failed",
                steps=RegistrationSteps(),
                error="Connection refused",
            ),
        ]

        resp = client.post(
            "/api/v1/servers/import",
            json=[
                {"device_name": "server1", "bmc_mac": "AABBCCDDEEFF", "bmc_password": "p1"},
                {"device_name": "server2", "bmc_mac": "112233445566", "bmc_password": "p2"},
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["status"] == "ok"
        assert data[1]["status"] == "failed"
        assert data[1]["error"] == "Connection refused"


class TestImportWebSocket:
    @patch("app.main.import_server", new_callable=AsyncMock)
    def test_ws_streams_results(self, mock_import, client):
        from app.models import ImportResultItem, RegistrationSteps

        mock_import.side_effect = [
            ImportResultItem(
                device_name="server1",
                status="ok",
                steps=RegistrationSteps(secret_stored=True),
                bmc_ip="10.0.0.1",
            ),
            ImportResultItem(
                device_name="server2",
                status="failed",
                steps=RegistrationSteps(),
                error="Connection refused",
            ),
        ]

        with client.websocket_connect("/api/v1/servers/import/ws") as ws:
            ws.send_json([
                {"device_name": "server1", "bmc_mac": "AABBCCDDEEFF", "bmc_password": "p1"},
                {"device_name": "server2", "bmc_mac": "112233445566", "bmc_password": "p2"},
            ])

            results = []
            for _ in range(2):
                results.append(ws.receive_json())

            done = ws.receive_json()
            assert done == {"done": True}

        names = {r["device_name"] for r in results}
        assert names == {"server1", "server2"}
        assert any(r["status"] == "ok" for r in results)
        assert any(r["status"] == "failed" for r in results)

    def test_ws_validation_error(self, client):
        with client.websocket_connect("/api/v1/servers/import/ws") as ws:
            ws.send_json([
                {"device_name": "test", "bmc_mac": "invalid", "bmc_password": "p1"},
            ])

            msg = ws.receive_json()
            assert "error" in msg


class TestServerStatus:
    def test_not_found(self, client):
        resp = client.get("/api/v1/servers/nonexistent/status")
        assert resp.status_code == 404
