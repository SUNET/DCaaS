"""OIDC JWT authentication for the onboarding API."""

import logging
from typing import Any

import httpx
from cachetools import TTLCache
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

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


async def _validate_jwt(token: str) -> dict[str, Any]:
    """Validate a JWT and return its claims."""
    jwks = await _get_jwks()
    unverified_header = jwt.get_unverified_header(token)

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
    return claims


async def validate_token(request: Request) -> dict[str, Any]:
    """Validate authentication from Bearer header or session cookie.

    Checks in order:
    1. Authorization: Bearer <token> header
    2. onboarding_session signed cookie (BFF flow)
    3. 401 if neither is present

    Returns the decoded token claims.
    """
    if not settings.oidc_issuer:
        # Auth disabled (development mode)
        logger.warning("OIDC issuer not configured — authentication disabled")
        return {"sub": "dev-user"}

    # 1. Try Bearer token
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:]
        try:
            claims = await _validate_jwt(token)
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {e}",
            )
        _check_authorization(claims)
        return claims

    # 2. Try session cookie
    cookie = request.cookies.get("onboarding_session")
    if not cookie:
        logger.debug("No session cookie present")
    elif not settings.session_secret:
        logger.warning("Session cookie found but no session_secret configured")
    if cookie and settings.session_secret:
        from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

        serializer = URLSafeTimedSerializer(settings.session_secret)
        try:
            data = serializer.loads(cookie, max_age=8 * 3600)
            id_token = data.get("id_token")
            if id_token:
                claims = await _validate_jwt(id_token)
                _check_authorization(claims)
                return claims
        except (BadSignature, SignatureExpired) as e:
            logger.warning("Session cookie invalid: %s", e)
        except JWTError as e:
            logger.warning("Session JWT validation failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid session token: {e}",
            )

    # 3. No valid credentials
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def _check_authorization(claims: dict[str, Any]) -> None:
    """Enforce allowed-users list."""
    if settings.allowed_users.strip():
        allowed = [u.strip() for u in settings.allowed_users.split(",") if u.strip()]
        sub = claims.get("sub", "")
        if sub not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User not in allowed-users list",
            )
