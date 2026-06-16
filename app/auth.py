"""Authentication & multi-tenancy for the Env Forge backend.

Mirrors ``agentsuite_server.dependencies.auth`` (the task-gen pattern) so this
service shares the platform's auth model and config:

  - JWT:     Authorization: Bearer <token>   (validated locally, HS256)
  - API key: X-API-Key: <api_key>            (validated via virtue-auth)

Auth is OFF by default for local dev (``AGENTSUITE_AUTH_ENABLED=false``), in
which case every request runs as ``DEFAULT_DEV_USER`` (admin, ``dev-tenant``).

Env Forge is **admin-only** and **strictly tenant-isolated**: unlike the
platform's ``tenant_filter`` (where admins see every tenant), here even admins
only ever see their *own* tenant's environments — each user hosts their own
projects and cannot see anyone else's (no cross-tenant information leakage).

Config (same env vars as agentsuite_server):
  AGENTSUITE_AUTH_ENABLED   "true"/"1"/"yes" to require auth (default off)
  AGENTSUITE_JWT_SECRET     shared HS256 secret used to verify access tokens
  AGENTSUITE_VIRTUE_AUTH_URL  base URL of the virtue-auth service (API keys)
"""
from __future__ import annotations

import logging
import os
from enum import Enum

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import false

logger = logging.getLogger(__name__)


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


AUTH_ENABLED = _flag("AGENTSUITE_AUTH_ENABLED")
JWT_SECRET = os.environ.get("AGENTSUITE_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
VIRTUE_AUTH_URL = os.environ.get("AGENTSUITE_VIRTUE_AUTH_URL", "").rstrip("/")

if AUTH_ENABLED and not JWT_SECRET:
    logger.warning(
        "AGENTSUITE_JWT_SECRET is not set — JWT auth disabled, only API key auth is available"
    )

security = HTTPBearer(auto_error=False)


# ── AuthContext ───────────────────────────────────────────────────────────────


class AuthType(str, Enum):
    JWT = "jwt"
    API_KEY = "api_key"


class AuthContext(BaseModel):
    """Authentication context passed throughout a request."""

    user_id: str
    tenant_id: str
    username: str = ""
    roles: list[str] = []
    is_admin: bool | None = None
    token: str
    auth_type: AuthType = AuthType.JWT
    permissions: dict | None = None
    scope: str | None = None
    key_id: str | None = None

    model_config = ConfigDict(frozen=True)


DEFAULT_DEV_USER = AuthContext(
    user_id="dev-user",
    tenant_id="dev-tenant",
    username="dev-user",
    roles=[],
    is_admin=True,
    token="",
    auth_type=AuthType.JWT,
)


# ── validators ──────────────────────────────────────────────────────────────


def _unauth(detail: str, code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": f'Bearer error="{code}"'},
    )


def _validate_jwt(token: str) -> AuthContext:
    """Validate a JWT locally (HS256, shared secret). Distinguishes expired /
    bad-signature / malformed so the frontend can refresh vs force-logout."""
    if not JWT_SECRET:
        logger.error("AGENTSUITE_JWT_SECRET is not configured but JWT auth was attempted")
        raise _unauth("JWT auth unavailable: server misconfigured", "server_misconfigured")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise _unauth("Token expired", "token_expired")
    except jwt.InvalidSignatureError:
        logger.warning("JWT validation failed: invalid signature")
        raise _unauth("Invalid token signature", "invalid_signature")
    except jwt.DecodeError:
        raise _unauth("Malformed token", "invalid_token")
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise _unauth("Invalid token", "invalid_token")

    user_id = payload.get("sub")
    if not user_id:
        raise _unauth("Invalid token: missing sub", "invalid_token")

    return AuthContext(
        user_id=user_id,
        tenant_id=payload.get("tenant_id", ""),
        username=payload.get("username", ""),
        roles=payload.get("roles", []),
        is_admin=payload.get("is_admin"),
        token=token,
        auth_type=AuthType.JWT,
    )


async def _validate_api_key(api_key: str) -> AuthContext:
    """Validate an API key via the virtue-auth service."""
    if not VIRTUE_AUTH_URL:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth service not configured")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.post(
                f"{VIRTUE_AUTH_URL}/api/v1/auth/verify-api-key",
                json={"api_key": api_key},
            )
        if resp.status_code != 200:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        info = resp.json()
        if not info.get("valid"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, info.get("error", "Invalid API key"))
        return AuthContext(
            user_id=info.get("user_id", ""),
            tenant_id=info.get("tenant_id", ""),
            is_admin=info.get("is_admin"),
            token=api_key,
            auth_type=AuthType.API_KEY,
            permissions=info.get("permissions"),
            scope=info.get("scope"),
            key_id=info.get("key_id"),
        )
    except HTTPException:
        raise
    except httpx.ConnectError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth service unavailable")
    except httpx.TimeoutException:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Auth service timeout")
    except Exception as e:
        logger.error(f"API key validation error: {e}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key verification failed")


# ── FastAPI dependencies ──────────────────────────────────────────────────────


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> AuthContext:
    """Resolve the auth context from a JWT or API key. API key wins when both
    are present. Returns ``DEFAULT_DEV_USER`` when auth is disabled."""
    if not AUTH_ENABLED:
        return DEFAULT_DEV_USER
    try:
        if x_api_key:
            auth_ctx = await _validate_api_key(x_api_key)
        elif credentials:
            auth_ctx = _validate_jwt(credentials.credentials)
        else:
            raise _unauth(
                "Missing authentication: provide Authorization header or X-API-Key",
                "missing_auth",
            )
        request.state.auth_ctx = auth_ctx
        return auth_ctx
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Authentication failed: {e}")
        raise _unauth("Authentication failed", "invalid_token")


def require_admin(auth: AuthContext) -> None:
    """Env Forge is admin-only. ``DEFAULT_DEV_USER`` is admin, so dev mode passes."""
    if not auth.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")


async def current_admin(user: AuthContext = Depends(get_current_user)) -> AuthContext:
    """Dependency for every /env-forge endpoint: authenticate + enforce admin.

    Also fail closed on a tenantless token: a credential with no ``tenant_id``
    can't be scoped to a tenant, so (under real auth) it is rejected outright
    rather than risk matching the empty-tenant ("") rows of unowned envs."""
    require_admin(user)
    if AUTH_ENABLED and not user.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tenant in credentials")
    return user


# ── multi-tenant scoping (strict — even admins are tenant-isolated) ───────────


def scope_query(stmt, column, auth: AuthContext):
    """Restrict a SELECT to the caller's tenant. No admin bypass: each admin
    only sees their own tenant's rows. Disabled-auth (dev) sees everything.

    A tenantless caller (empty ``tenant_id``) matches nothing — never the ""
    rows of orphan/unowned environments."""
    if not AUTH_ENABLED:
        return stmt
    if not auth.tenant_id:
        return stmt.where(false())
    return stmt.where(column == auth.tenant_id)


def owns(env, auth: AuthContext) -> bool:
    """True if ``env`` belongs to the caller's tenant (or auth is off).

    Both a tenantless caller and an unowned (empty-tenant) env match nothing,
    so orphan environments are never visible across — or without — a tenant."""
    if not AUTH_ENABLED:
        return True
    if env is None:
        return False
    env_tenant = getattr(env, "tenant_id", "") or ""
    if not auth.tenant_id or not env_tenant:
        return False
    return env_tenant == auth.tenant_id


def assert_env_access(env, auth: AuthContext):
    """Return ``env`` if the caller may access it; else 404 (don't reveal that
    an environment in another tenant exists)."""
    if env is None or not owns(env, auth):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    return env
