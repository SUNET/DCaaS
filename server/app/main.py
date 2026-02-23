"""DCaaS Onboarding API — FastAPI application."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from cachetools import TTLCache
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketException, status
from fastapi.middleware.cors import CORSMiddleware

from app.auth.oidc import validate_token
from app.auth.routes import router as auth_router
from app.config import settings
from app.integrations.netbox import NetboxClient
from app.models import (
    DeviceRoleRef,
    DeviceTypeRef,
    ImportResultItem,
    ImportServerItem,
    LocationRef,
    PrefixRef,
    RackRef,
    RegisterServerRequest,
    RegisterServerResponse,
    ServerListItem,
    ServerStatusResponse,
    SiteRef,
    TenantRef,
)
from app.workflow import get_server_status, import_server, register_server

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

app.include_router(auth_router)


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


@app.post("/api/v1/servers/import", response_model=list[ImportResultItem])
async def import_servers(
    servers: list[ImportServerItem],
    claims: dict[str, Any] = Depends(validate_token),
):
    """Bulk-import existing servers.

    Each server is processed independently; failures don't stop the batch.
    """
    logger.info(
        "Import requested by %s for %d servers",
        claims.get("sub", "unknown"),
        len(servers),
    )
    results = await asyncio.gather(*(import_server(item) for item in servers))
    return list(results)


async def _validate_ws(ws: WebSocket) -> dict[str, Any]:
    """Validate authentication for a WebSocket connection.

    Re-uses the same logic as validate_token but works with WebSocket
    objects (which expose .headers and .cookies but not Request).
    """
    if not settings.oidc_issuer:
        return {"sub": "dev-user"}

    from jose import JWTError

    from app.auth.oidc import _check_authorization, _validate_jwt

    # 1. Try Bearer token in headers (same header browsers can set via protocols)
    auth_header = ws.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:]
        try:
            claims = await _validate_jwt(token)
        except JWTError:
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
        _check_authorization(claims)
        return claims

    # 2. Try session cookie
    cookie = ws.cookies.get("onboarding_session")
    if cookie and settings.session_secret:
        from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

        serializer = URLSafeTimedSerializer(settings.session_secret)
        try:
            data = serializer.loads(cookie, max_age=8 * 3600)
            id_token = data.get("id_token")
            if id_token:
                claims = await _validate_jwt(
                    id_token, access_token=data.get("access_token")
                )
                _check_authorization(claims)
                return claims
        except (BadSignature, SignatureExpired, JWTError):
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)


@app.websocket("/api/v1/servers/import/ws")
async def import_servers_ws(ws: WebSocket):
    """Bulk-import via WebSocket — streams per-server results in real time."""
    claims = await _validate_ws(ws)
    await ws.accept()

    try:
        data = await ws.receive_json()
    except Exception:
        await ws.close(code=1003, reason="Expected JSON array")
        return

    # Validate each item through the Pydantic model
    try:
        servers = [ImportServerItem(**item) for item in data]
    except Exception as exc:
        await ws.send_json({"error": str(exc)})
        await ws.close(code=1003, reason="Validation error")
        return

    logger.info(
        "WS import requested by %s for %d servers",
        claims.get("sub", "unknown"),
        len(servers),
    )

    queue: asyncio.Queue = asyncio.Queue()

    async def _run(item: ImportServerItem):
        result = await import_server(item)
        await queue.put(result)

    tasks = [asyncio.create_task(_run(item)) for item in servers]

    sent = 0
    while sent < len(tasks):
        result = await queue.get()
        await ws.send_json(result.model_dump())
        sent += 1

    await ws.send_json({"done": True})
    await ws.close()


@app.get("/api/v1/servers", response_model=list[ServerListItem])
async def servers_list(
    _claims: dict[str, Any] = Depends(validate_token),
):
    """List devices from Netbox."""
    key = "devices"
    if key not in _ref_cache:
        _ref_cache[key] = _netbox().get_devices()
    return _ref_cache[key]


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


@app.get("/api/v1/reference/prefixes", response_model=list[PrefixRef])
async def ref_prefixes(_claims: dict[str, Any] = Depends(validate_token)):
    key = "prefixes"
    if key not in _ref_cache:
        _ref_cache[key] = _netbox().get_prefixes()
    return _ref_cache[key]


@app.get("/api/v1/reference/tenants", response_model=list[TenantRef])
async def ref_tenants(_claims: dict[str, Any] = Depends(validate_token)):
    key = "tenants"
    if key not in _ref_cache:
        _ref_cache[key] = _netbox().get_tenants()
    return _ref_cache[key]
