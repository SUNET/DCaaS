"""OIDC JWT authentication for the onboarding API."""

import logging
from typing import Any

import httpx
from cachetools import TTLCache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer()

# Cache OIDC discovery and JWKS for 1 hour
_cache: TTLCache = TTLCache(maxsize=8, ttl=3600)


async def _get_oidc_config() -> dict:
    """Fetch OIDC discovery document, cached."""
    if "oidc_config" in _cache:
        return _cache["oidc_config"]

    url = f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        config = resp.json()

    _cache["oidc_config"] = config
    return config


async def _get_jwks() -> dict:
    """Fetch JWKS from the OIDC provider, cached."""
    if "jwks" in _cache:
        return _cache["jwks"]

    config = await _get_oidc_config()
    jwks_uri = config["jwks_uri"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        jwks = resp.json()

    _cache["jwks"] = jwks
    return jwks


async def validate_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    """Validate a JWT Bearer token and enforce group membership.

    Returns the decoded token claims.
    """
    token = credentials.credentials

    if not settings.oidc_issuer:
        # Auth disabled (development mode)
        logger.warning("OIDC issuer not configured — authentication disabled")
        return {"sub": "dev-user", "groups": [settings.oidc_required_group]}

    try:
        jwks = await _get_jwks()
        unverified_header = jwt.get_unverified_header(token)

        # Find the matching key
        rsa_key: dict = {}
        for key in jwks.get("keys", []):
            if key.get("kid") == unverified_header.get("kid"):
                rsa_key = key
                break

        if not rsa_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find matching signing key",
            )

        claims = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )

    # Check group membership
    groups = claims.get("groups", [])
    if settings.oidc_required_group not in groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User not in required group '{settings.oidc_required_group}'",
        )

    return claims
