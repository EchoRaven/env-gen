"""Deterministic projection of the embedded OAuth2 Authorization Server → app/backend/.

The forgingground target env IS its own OAuth2 Authorization Server (zoom-style):
it mints RS256 access tokens whose ``sub`` claim is ``str(users.id)`` and exposes
a JWKS so resource servers verify offline. That AS is three modules:

  * ``jwt_manager.py``  — RSA-2048 keypair (persisted under ``JWT_DATA_DIR``),
    RS256 signing, JWKS document (kid ``app-oauth-key-1``).
  * ``oauth_store.py``  — psycopg3 store over the tenancy spine tables
    (``users`` / ``oauth_clients`` / ``oauth_authorization_codes``): password
    verification, dynamic client registration, single-use PKCE auth codes.
  * ``oauth_routes.py`` — the AS endpoints (``/.well-known/...``,
    ``/oauth/register|authorize|token``, ``/.well-known/jwks.json``) with the
    authorization-code + PKCE(S256) grant.

These modules are PURE INFRASTRUCTURE — byte identical for every generated env,
zero business logic. So the runtime is the SOLE owner of them, exactly like
``app/database/`` (see ``database_scaffold.py``). Having an LLM lane re-author an
OAuth2 AS every run is the textbook source of contract drift: a salt mismatch, a
missing PKCE check, a ``sub`` that isn't the user id, and the env can't mint or
verify a single token. Emitting them deterministically closes that by
construction — the only authoritative copy, always aligned with the spine.

Charter §8 (no silent fallback): the templates are shipped verbatim as
``oauth_as_templates/*.py.tmpl`` (the ``.tmpl`` suffix keeps the test runner from
importing modules whose ``jwt`` / ``psycopg`` / ``cryptography`` deps only exist
inside the generated container). A missing template is a packaging error that
raises loudly here rather than emitting a half-built AS.

The contract these modules lock with the rest of the env (do NOT let any side
drift — see ``test_oauth_scaffold.py`` + ``test_database_scaffold.py``):

  * users.id is an integer SERIAL PK; JWT ``sub`` == ``str(users.id)``.
  * password_hash == ``sha256(password + 'app_sandbox_salt_2024')`` — the same
    salt lives in ``oauth_store.py`` and the backend's ``main.py``.
  * the signing key id is ``app-oauth-key-1`` (the JWKS ``kid``).
  * the OAuth list columns (redirect_uris/grant_types/response_types) are
    JSON-encoded TEXT, not native arrays.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


# Public manifest: the three runtime-owned AS modules. Other layers key off this
# — e.g. the backend prompt's "these are provided, do NOT author them" list and
# the contract-alignment gate's infra exemptions.
AS_MODULES: List[str] = ["jwt_manager.py", "oauth_store.py", "oauth_routes.py"]

# Locked contract constants, surfaced for assertions / wiring by callers that
# must agree with the AS (the backend prompt, the database spine).
PASSWORD_SALT = "app_sandbox_salt_2024"
SIGNING_KEY_ID = "app-oauth-key-1"
DEFAULT_AUDIENCE = "app-api"
JWT_DATA_DIR = "/var/lib/app-auth"


# ── The fixed auth/OAuth contract surface (deterministic; consistency-by-
# construction). The orchestrator registers these in RegistryHub as
# status='implemented', actor='orchestrator', so the contract is COMPLETE — the
# frontend introspects real registrations instead of being told via prose, and
# the delivery gate matches a real endpoint instead of a hardcoded path-prefix
# exemption.
#
# CRUCIAL (per the contract-extract review): these are tagged ``kind`` =
# ``auth`` | ``oauth``, NOT business endpoints. They are FIXED-SPEC and return
# heterogeneous shapes (a 302 redirect, a {access_token}, a JWKS doc), so the
# frontend's response_key-keyed api.js generator MUST SKIP them — it uses the
# standard login helper for /auth/*, and never calls /oauth/* directly (the AS's
# own login page drives /oauth/authorize). The ``response`` shapes below are
# documentation of the locked contract, not a business response_key.
#
#   kind='auth'  → first-party credential endpoints the UI login helper calls.
#   kind='oauth' → OAuth2-protocol endpoints (the AS itself + MCP clients use).
AS_CONTRACT_ENDPOINTS = [
    {
        "method": "POST", "path": "/auth/register", "kind": "auth",
        "auth_required": False,
        "summary": "First-party register: create a (email, tenant_id) user + mint an RS256 token.",
        "request": {"email": "str", "password": "str", "name": "str?", "tenant_id": "str?"},
        "response": {"user": {"id": "int", "email": "str", "name": "str", "tenant_id": "str"},
                     "access_token": "str", "token_type": "Bearer", "expires_in": "int"},
    },
    {
        "method": "POST", "path": "/auth/login", "kind": "auth",
        "auth_required": False,
        "summary": "First-party login by (email, password, tenant_id) → RS256 access token.",
        "request": {"email": "str", "password": "str", "tenant_id": "str?"},
        "response": {"access_token": "str", "token_type": "Bearer", "expires_in": "int"},
    },
    {
        "method": "POST", "path": "/oauth/register", "kind": "oauth",
        "auth_required": False,
        "summary": "RFC 7591 dynamic client registration (MCP clients).",
        "response": {"client_id": "str", "redirect_uris": "list", "scope": "str"},
    },
    {
        "method": "GET", "path": "/oauth/authorize", "kind": "oauth",
        "auth_required": False,
        "summary": "OAuth2 authorize (renders the AS login page; PKCE S256 required).",
    },
    {
        "method": "POST", "path": "/oauth/authorize", "kind": "oauth",
        "auth_required": False,
        "summary": "OAuth2 authorize form post → 303 redirect with ?code=.",
    },
    {
        "method": "POST", "path": "/oauth/token", "kind": "oauth",
        "auth_required": False,
        "summary": "OAuth2 authorization_code + PKCE → RS256 access token.",
        "response": {"access_token": "str", "token_type": "Bearer", "expires_in": "int", "scope": "str"},
    },
    {
        "method": "GET", "path": "/.well-known/jwks.json", "kind": "oauth",
        "auth_required": False,
        "summary": "JWKS for offline RS256 verification (kid app-oauth-key-1).",
        "response": {"keys": "list"},
    },
    {
        "method": "GET", "path": "/.well-known/oauth-authorization-server", "kind": "oauth",
        "auth_required": False,
        "summary": "RFC 8414 authorization-server metadata.",
        "response": {"issuer": "str", "authorization_endpoint": "str", "token_endpoint": "str",
                     "jwks_uri": "str", "registration_endpoint": "str"},
    },
]

_TEMPLATE_DIR = Path(__file__).resolve().parent / "oauth_as_templates"


def _template_path(module: str) -> Path:
    """Locate the verbatim ``.py.tmpl`` source for an AS module.

    Charter §8: a missing template is a packaging defect, not something to
    paper over — raise so the run fails loudly instead of shipping a partial AS.
    """
    p = _TEMPLATE_DIR / f"{module}.tmpl"
    if not p.is_file():
        raise FileNotFoundError(
            f"oauth_scaffold: AS template {p} is missing — the embedded "
            "OAuth2 AS cannot be projected. This is a packaging error."
        )
    return p


def render_oauth_module(module: str) -> str:
    """Return the verbatim source for one AS module (``module`` ∈ AS_MODULES)."""
    if module not in AS_MODULES:
        raise ValueError(
            f"oauth_scaffold: {module!r} is not an AS module; expected one of {AS_MODULES}"
        )
    return _template_path(module).read_text(encoding="utf-8")


def _scrubbed_1202mi(text: str, filename: str) -> str:
    """See `provenance_scrub`. Never raises: OAuth scaffolding must land."""
    try:
        from .provenance_scrub import scrub_provenance_1202mi
        return scrub_provenance_1202mi(text, filename)
    except Exception:
        return text


def write_oauth_as(output_dir: Path) -> Dict[str, Any]:
    """Author the embedded OAuth2 AS modules under ``<output_dir>/app/backend/``.

    Sibling to ``database_scaffold.write_database_scaffold``: the runtime writes
    these directly into the integration tree (``output_dir``), NOT into a lane
    worktree — they are never LLM-authored, so they ride alongside the backend
    lane's ``main.py`` without a merge. Idempotent — overwrites on every call so
    the AS always reflects the current locked templates.

    Returns ``{"written": [str(path), ...]}`` (one per emitted module)."""
    output_dir = Path(output_dir)
    backend_dir = output_dir / "app" / "backend"
    backend_dir.mkdir(parents=True, exist_ok=True)

    written: List[str] = []
    for module in AS_MODULES:
        dest = backend_dir / module
        # #1202mi: measured on a real render, these three modules carry 11
        # framework tags between them and were reached by no scrub, because
        # this write goes through neither choke point.
        dest.write_text(_scrubbed_1202mi(render_oauth_module(module), module),
                        encoding="utf-8")
        written.append(str(dest))
    return {"written": written}


__all__ = [
    "AS_MODULES",
    "AS_CONTRACT_ENDPOINTS",
    "PASSWORD_SALT",
    "SIGNING_KEY_ID",
    "DEFAULT_AUDIENCE",
    "JWT_DATA_DIR",
    "render_oauth_module",
    "write_oauth_as",
]
