"""OIDC BFF authentication routes.

Implements the authorization-code flow server-side so the browser never
sees the client_secret.  Session state is kept in a signed cookie.
"""

import logging
import secrets

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jose import JWTError, jwt

from app.auth.oidc import _get_jwks, _get_oidc_config
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

SESSION_COOKIE = "onboarding_session"
STATE_COOKIE = "oidc_state"
SESSION_MAX_AGE = 8 * 3600  # 8 hours


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret)


# ── Login ────────────────────────────────────────────────────────────────


@router.get("/auth/login")
async def login():
    """Redirect the browser to the SATOSA authorization endpoint."""
    oidc_config = await _get_oidc_config()
    state = secrets.token_urlsafe(32)

    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": "openid profile email",
        "state": state,
    }
    auth_url = oidc_config["authorization_endpoint"]
    qs = "&".join(f"{k}={v}" for k, v in params.items())

    response = RedirectResponse(url=f"{auth_url}?{qs}", status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        state,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=300,
    )
    return response


# ── Callback ─────────────────────────────────────────────────────────────


@router.get("/callback")
async def callback(request: Request, code: str, state: str):
    """Exchange the authorization code for tokens and set a session cookie."""
    expected_state = request.cookies.get(STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        return Response("Invalid state parameter", status_code=400)

    oidc_config = await _get_oidc_config()
    token_endpoint = oidc_config["token_endpoint"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri,
            },
            auth=(settings.oidc_client_id, settings.oidc_client_secret),
        )

    if resp.status_code != 200:
        logger.error("Token exchange failed: %s %s", resp.status_code, resp.text)
        return Response("Token exchange failed", status_code=502)

    tokens = resp.json()
    id_token = tokens.get("id_token")
    access_token = tokens.get("access_token")
    if not id_token:
        return Response("No id_token in response", status_code=502)

    # Validate the id_token before trusting it
    try:
        jwks = await _get_jwks()
        header = jwt.get_unverified_header(id_token)
        rsa_key = next(
            (k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")),
            None,
        )
        if not rsa_key:
            return Response("No matching signing key for id_token", status_code=502)

        jwt.decode(
            id_token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            access_token=access_token,
        )
    except JWTError as exc:
        logger.error("id_token validation failed: %s", exc)
        return Response("Invalid id_token", status_code=502)

    # Store tokens in a signed cookie
    session_value = _serializer().dumps(
        {"id_token": id_token, "access_token": access_token}
    )

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        session_value,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


# ── Userinfo ─────────────────────────────────────────────────────────────


@router.get("/auth/userinfo")
async def userinfo(request: Request):
    """Return decoded claims from the session cookie."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return Response(status_code=401)

    try:
        data = _serializer().loads(cookie, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return Response(status_code=401)

    id_token = data.get("id_token")
    if not id_token:
        return Response(status_code=401)

    try:
        claims = jwt.get_unverified_claims(id_token)
    except JWTError:
        return Response(status_code=401)

    return {
        "sub": claims.get("sub"),
        "name": claims.get("name", claims.get("sub", "")),
        "email": claims.get("email"),
        "groups": claims.get("groups", []),
    }


# ── Logout ───────────────────────────────────────────────────────────────


@router.post("/auth/logout")
async def logout():
    """Clear the session cookie."""
    response = Response(status_code=200)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
