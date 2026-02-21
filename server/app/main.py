"""DCaaS Onboarding API — FastAPI application."""

import logging
from contextlib import asynccontextmanager
from typing import Any

from cachetools import TTLCache
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.auth.oidc import validate_token
from app.config import settings
from app.integrations.netbox import NetboxClient
from app.models import (
    DeviceRoleRef,
    DeviceTypeRef,
    LocationRef,
    RackRef,
    RegisterServerRequest,
    RegisterServerResponse,
    ServerListItem,
    ServerStatusResponse,
    SiteRef,
)
from app.workflow import get_server_status, list_servers, register_server

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Reference-data cache (populated lazily)
_ref_cache: TTLCache = TTLCache(maxsize=64, ttl=settings.reference_cache_ttl)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s", settings.app_name)
    yield
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Server registration
# ---------------------------------------------------------------------------


@app.post(
    "/api/v1/servers/register",
    response_model=RegisterServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    req: RegisterServerRequest,
    claims: dict[str, Any] = Depends(validate_token),
):
    """Register a new bare-metal server.

    Orchestrates: Netbox device → OpenBao secret → Kea DHCP → Metal3 BMH.
    """
    logger.info(
        "Registration requested by %s for %s",
        claims.get("sub", "unknown"),
        req.device_name(),
    )
    result = await register_server(req)

    if result.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": f"Registration failed: {result.error}",
                "steps": result.steps.model_dump(),
            },
        )
    return result


@app.get("/api/v1/servers", response_model=list[ServerListItem])
async def servers_list(
    _claims: dict[str, Any] = Depends(validate_token),
):
    """List recently registered servers."""
    return [
        ServerListItem(
            id=s.id,
            device_name=s.device_name,
            status=s.status,
            site=s.site,
            rack=s.rack,
            position=s.position,
            created_at=s.created_at,
        )
        for s in list_servers()
    ]


@app.get("/api/v1/servers/{server_id}/status", response_model=ServerStatusResponse)
async def server_status(
    server_id: str,
    _claims: dict[str, Any] = Depends(validate_token),
):
    """Get detailed provisioning status for a single server."""
    srv = get_server_status(server_id)
    if srv is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return srv


# ---------------------------------------------------------------------------
# Reference data (proxied from Netbox, cached)
# ---------------------------------------------------------------------------


def _netbox() -> NetboxClient:
    """Lazily-initialised Netbox client singleton."""
    if "netbox_client" not in _ref_cache:
        _ref_cache["netbox_client"] = NetboxClient()
    return _ref_cache["netbox_client"]


@app.get("/api/v1/reference/sites", response_model=list[SiteRef])
async def ref_sites(_claims: dict[str, Any] = Depends(validate_token)):
    key = "sites"
    if key not in _ref_cache:
        _ref_cache[key] = _netbox().get_sites()
    return _ref_cache[key]


@app.get("/api/v1/reference/locations", response_model=list[LocationRef])
async def ref_locations(
    site: str,
    _claims: dict[str, Any] = Depends(validate_token),
):
    key = f"locations:{site}"
    if key not in _ref_cache:
        _ref_cache[key] = _netbox().get_locations(site)
    return _ref_cache[key]


@app.get("/api/v1/reference/racks", response_model=list[RackRef])
async def ref_racks(
    location: str,
    _claims: dict[str, Any] = Depends(validate_token),
):
    key = f"racks:{location}"
    if key not in _ref_cache:
        _ref_cache[key] = _netbox().get_racks(location)
    return _ref_cache[key]


@app.get("/api/v1/reference/device-types", response_model=list[DeviceTypeRef])
async def ref_device_types(_claims: dict[str, Any] = Depends(validate_token)):
    key = "device_types"
    if key not in _ref_cache:
        _ref_cache[key] = _netbox().get_device_types()
    return _ref_cache[key]


@app.get("/api/v1/reference/device-roles", response_model=list[DeviceRoleRef])
async def ref_device_roles(_claims: dict[str, Any] = Depends(validate_token)):
    key = "device_roles"
    if key not in _ref_cache:
        _ref_cache[key] = _netbox().get_device_roles()
    return _ref_cache[key]
