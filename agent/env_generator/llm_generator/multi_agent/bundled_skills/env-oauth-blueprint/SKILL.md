---
name: env-oauth-blueprint
description: Use when the backend lane is putting OAuth/JWT identity on a sandbox env that lacks it (slack/paypal/atlassian/zoom or any new env), or extending an env's auth (refresh tokens, scopes, third-party /oauth/authorize flow, multi-tenant tokens), designing an env's users/identity schema, choosing AS topology (embedded vs the centralized Google IdP), or wiring an MCP to authenticate against an env. Symptoms: env has no /auth/login, MCP can't mint a JWT, RS rejects/accepts the wrong aud, OAuth contract test (validation:api_smoke / build:backend_start, recorded via codehub_record_check) fails on token shape. Triggers on "add OAuth/login to X", "JWT for X", "auth for the X env", "design auth for", "users table for X env", "authenticate the X MCP". Not the MCP server itself (mcp-server-bootstrap) nor tenant scoping (multi-tenancy-pattern).
---

# OAuth blueprint for a sandbox env

For when you're putting OAuth on a new env (slack, paypal, your-favorite-saas)
or extending an existing one. The Google family's `google-idp` is one
*instance* of this blueprint — this skill is the **template**.

For the operational details of the live Google IdP system (debug recipes,
how to maintain it, how to add a new Google env), see the worked-example
pointers at the bottom of this skill and your env's `google-idp` setup.

## First: pick the AS topology

Two options. The choice is mechanical — do not deliberate:

- **Google-family env** (gmail, calendar, drive, googledocs,
  googlesheets, googleform, …) → **Topology B (centralized)**. Join
  the existing `src/google-idp` AS so the new env shares Google's
  cross-product SSO with its siblings.
- **Anything else** (slack, paypal, atlassian, hospital, sweep,
  linear, notion, …) → **Topology A (embedded)**. Stand up the AS
  inside the env's own FastAPI process.

```
┌─────────────────────────────────────────────────────────────┐
│  Topology A: EMBEDDED            ← default for new envs     │
│  one container holds AS + RS                                │
│                                                             │
│      <env>-backend                                          │
│      ├─ /auth/login, /oauth/token       ← AS endpoints     │
│      ├─ /tools/call, /api/v1/*           ← RS endpoints    │
│      └─ users table (single source)                         │
│                                                             │
│  Pro: simplest ops; one container, one DB, no shared secret.│
│  Con: each env reimplements OAuth; no SSO across envs.      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Topology B: CENTRALIZED        ← only for the Google family│
│  shared AS serves N RS envs                                 │
│                                                             │
│      auth-server          <env-1>-backend   <env-2>-backend │
│      ├─ /auth/*           ├─ /tools/call    ├─ /api/...     │
│      └─ users, clients,   ├─ users_mirror   ├─ users_mirror │
│         tokens, consents  └─ business data  └─ business     │
│             ↓ HS256 JWT (shared OAUTH_JWT_SECRET) ↓        │
│                                                             │
│  Used by: 5 Google envs + google-form, via src/google-idp.  │
│  Justified: Google's real-world SSO across products is the  │
│  modeled behavior, so the topology reflects the real        │
│  service. A new Google-family env joins this AS rather than │
│  spinning up its own.                                       │
│  ⚠ Don't use this for non-Google envs. Pick Topology A      │
│    instead — a centralized AS for an unrelated single env   │
│    is wasted infrastructure.                                │
└─────────────────────────────────────────────────────────────┘
```

Sections below labeled "Topology A" / "embedded" are for new
non-Google envs. Sections labeled "Topology B" / "centralized" are
for adding a new env to the existing google-idp AS (or maintaining
what's there).

## What goes in the JWT (claim contract)

This is the most important decision — once MCPs / RS verify against a shape,
changing it is a coordinated migration. Recommended baseline:

```json
{
  "iss": "<env>-auth",
  "sub": "<user_id>",
  "aud": ["<env>-api"],
  "tenant_id": "<tenant>",
  "email": "<user@example.com>",
  "name": "<display name>",
  "scope": "<env>.read <env>.write",
  "client_id": "<env>-mcp",
  "jti": "<uuid>",
  "iat": ...,
  "exp": ...
}
```

Notes:
- `aud` is an **array** even with one element — RFC 7519 allows it and lets
  you later issue cross-env JWTs without changing the schema.
- `tenant_id` even if you don't have multi-tenancy yet — costs nothing,
  saves a migration later.
- `scope` even if you don't enforce it yet — same reasoning.
- `iss` should be unique per AS (so RS can `claims["iss"] == "<env>-auth"` check).

## ⚠️ Anti-pattern: don't put `access_token` on the users table

The pre-IdP sandbox had a `users.access_token TEXT UNIQUE` column — each user
had one fixed opaque string used as their Bearer token. **Don't replicate
this.** Three reasons:

1. **JWTs are stateless** — they carry their own expiry/scope/aud. No table
   lookup needed for verification (only signature + iss + aud check).
   Per-request DB hit is wasteful.
2. **Rotation is impossible** — one column means one valid token at a time.
   Want refresh? Multiple sessions? Short-lived tokens? You'll be redesigning
   anyway.
3. **Revocation is per-token, not per-user** — if you need it, build
   `oauth_access_tokens(jti, user_id, expires_at, revoked)` as a separate
   table keyed on `jti`. JWT carries its `jti`; revoke flips the row.
   Stateless verify, stateful revoke.

If you only need login + JWT (no revoke, no refresh), even
`oauth_access_tokens` is overkill — skip it. Stateless-only is fine
for a sandbox.

History: see `git log -p -- 'src/envs/*/init/*.sql'` for the removal commits
when we did this for the 5 Google envs.

## Schema templates

### Embedded (Topology A): single users table

```sql
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    email         TEXT NOT NULL,
    tenant_id     TEXT NOT NULL DEFAULT 'default',
    name          TEXT,
    password_hash TEXT NOT NULL,            -- bcrypt
    avatar_url    TEXT,
    created_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE(email, tenant_id)                -- multi-tenancy preserved
);

CREATE TABLE oauth_access_tokens (          -- only if you support revoke
    jti          TEXT PRIMARY KEY,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    expires_at   TIMESTAMP NOT NULL,
    revoked      BOOLEAN DEFAULT FALSE
);

CREATE TABLE oauth_refresh_tokens (         -- only if you support refresh
    refresh_token TEXT PRIMARY KEY,
    access_jti    TEXT NOT NULL,
    user_id       INTEGER REFERENCES users(id) ON DELETE CASCADE,
    expires_at    TIMESTAMP NOT NULL,
    revoked       BOOLEAN DEFAULT FALSE
);
```

### Centralized (Topology B): each RS env keeps a thin mirror

```sql
-- on the AUTH server: same `users` table as above
-- on each RS env:
CREATE TABLE users_mirror (
    id         SERIAL PRIMARY KEY,        -- local int; business FKs point here
    sub        INTEGER NOT NULL,          -- = AS user_id
    tenant_id  TEXT NOT NULL,
    email      TEXT,
    name       TEXT,
    UNIQUE(sub, tenant_id)
);
```

The mirror is **lazily upserted** on first JWT arrival — no need for the AS to
push user creates to RS envs. (See `_upsert_user_mirror` in
`src/envs/googledocs/api/main.py:118` for the working version.)

## Topology B reference: register fan-out (race fix)

Lazy upsert closes most of the gap but leaves one race window:

```
T0: client POSTs /auth/register on AS → INSERT into users
T1: setup.sh sends an email TO that user via mailpit
T2: ownership_tracker polls mailpit → looks up email in user_mirror
    → not found (no one called /api/v1/seed-user; auto-mirror only
      fires on authenticated proxy traffic, which hasn't happened)
    → email stays unowned, marked seen, never re-attributed
```

Fix (`d4465e9a` on the gmail / google-idp side): the AS's
`/auth/register` handler **fans out** a POST to each downstream env's
`/api/v1/seed-user` after the INSERT. Each downstream upserts into
its own `users_mirror`, so by the time register returns, the mirror
is consistent everywhere.

```python
# google-idp/api/main.py
_MIRROR_DOWNSTREAMS: List[Tuple[str, str, str]] = [
    ("gmail",        "GMAIL_USER_SERVICE_URL", "http://127.0.0.1:8030"),
    ("calendar",     "CALENDAR_API_URL",       "http://127.0.0.1:8032"),
    ("googledocs",   "GOOGLEDOCS_API_URL",     "http://127.0.0.1:8041"),
    ("googlesheets", "GOOGLESHEETS_API_URL",   "http://127.0.0.1:8056"),
    ("googledrive",  "GOOGLEDRIVE_API_URL",    "http://127.0.0.1:8058"),
]

async def _propagate_mirror(sub, tenant_id, email, name):
    """Fan-out POST /api/v1/seed-user. Idempotent on each receiver.
    Errors logged + swallowed so register stays successful even if
    one downstream blips."""
    body = {"sub": sub, "tenant_id": tenant_id, "email": email, "name": name}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for svc, env_var, default_url in _MIRROR_DOWNSTREAMS:
            base = os.getenv(env_var, default_url).rstrip("/")
            try:
                r = await client.post(f"{base}/api/v1/seed-user", json=body)
                if r.status_code not in (200, 201):
                    logger.warning("[mirror-sync] %s → %s: %s", svc,
                                   r.status_code, r.text[:160])
            except Exception as e:
                logger.warning("[mirror-sync] %s skipped: %s", svc, e)

@app.post("/auth/register", status_code=201)
async def auth_register(...):
    row = exec_returning("""INSERT INTO users ...""")
    await _propagate_mirror(row["id"], row["tenant_id"], row["email"],
                            row.get("name"))
    return row
```

Two important nuances:

1. **The URLs are per-deployment**. Pool deployments use 61xxx ports;
   standalone uses 22xxx; defaults in compose are the "documented"
   8030 / 8032 / 8041 / 8056 / 8058. The IdP container's
   docker-compose must accept overrides:
   ```yaml
   environment:
     GMAIL_USER_SERVICE_URL: ${GMAIL_USER_SERVICE_URL:-http://127.0.0.1:8030}
     # ... per downstream
   ```
   Whoever starts the IdP per-deployment passes the right URLs.
2. **Reset must NOT wipe `user_mirror`** in this topology. If it does,
   the mirror state can drift between `IdP.users` and
   `env.users_mirror` and the fan-out won't catch up until the next
   register. See `multi-tenancy-pattern` "Reset semantics" — applies
   here too.

The MCP-side complement (eager `/api/v1/seed-user` POST after MCP
token mint) is documented in `mcp-server-bootstrap`. Together they
close both the AS-register and the MCP-login race windows.

## Default grant type for agent-driven MCPs: `password`

Two grant types are common:

- **`client_credentials`** — service-account semantics. The MCP is the
  identity. Useful when "the agent" is just a tool wrapper, not
  acting as anyone in particular.
- **`password`** — real-user semantics. The MCP authenticates as a
  specific user via `/auth/login`. Useful for CRM-style tasks where
  the agent is "Sarah Johnson" and other operations depend on that
  identity (assigned-to, ownership, audit trail).

**Default to `password`.** Make the MCP's `mcp.yaml` entry look like
gmail's / calendar's:

```yaml
- name: <env>
  env:
    <ENV>_OAUTH_CLIENT_ID:     "<static, same every task>"
    <ENV>_OAUTH_CLIENT_SECRET: "<static, same every task>"
    <ENV>_GRANT_TYPE:          "password"           # ← default
    <ENV>_OAUTH_USER_EMAIL:    "dev@<env>.local"   # dev fallback
    <ENV>_OAUTH_USER_PASSWORD: "dev-local-password"             # dev fallback
```

Per-task config.yaml overrides `<ENV>_OAUTH_USER_EMAIL/PASSWORD`
(not the client id/secret — those are static MCP identity). Tasks
that genuinely want service-account semantics can override
`<ENV>_GRANT_TYPE: "client_credentials"` in their config.yaml — rare.

Salesforce flipped to this default in `224478ec`. Reason was the same
across CRM tasks: each task wanted "the agent is X" rather than "the
agent is the MCP itself," and `client_credentials` made the
per-task config.yaml repeat client creds 165 times for no benefit.

## Endpoints to expose

### Minimum (good enough for benchmark / test envs)
- `POST /auth/login` — body `{email, password, tenant_id}` → JWT
- `POST /auth/register` — same body + `name` → user row + 201

### Add when you need...
- **Refresh tokens** (else MCPs do full re-login per expiry) — add
  `POST /oauth/token grant_type=refresh_token`
- **Third-party apps** (else only first-party UIs/MCPs can use you) — add
  the full `/oauth/authorize` HTML flow + `/oauth/token grant_type=authorization_code`
- **Token introspection / revoke** (else can't kill tokens) — `/oauth/revoke`,
  `/oauth/introspect`
- **OAuth discovery** (lets clients self-configure) —
  `/.well-known/oauth-authorization-server`

`google-idp` exposes all of these — see `src/google-idp/api/main.py`. For a
new env, the rule of thumb: **start with `/auth/login` + `/auth/register`
only**, add the rest when an actual user complains.

## Naming conventions

Lock these in early — every part of the system encodes them.

| Concept | Pattern | Example |
|---|---|---|
| Audience | `<env>-api` | `paypal-api` |
| Scope | `<env>.<verb>` | `paypal.read`, `paypal.refund` |
| Client (UI) | `<env>-ui` (public, no secret) | `paypal-ui` |
| Client (MCP) | `<env>-mcp` (confidential, secret) | `paypal-mcp` |
| Env vars exposed to MCP | `<ENV>_OAUTH_<FIELD>` | `PAYPAL_OAUTH_USER_EMAIL` |
| Env vars on RS env (verify) | `OAUTH_JWT_SECRET`, `OAUTH_ISSUER`, `MY_AUDIENCE` | (unprefixed) |
| Redirect URI placeholder | `http://localhost:0/cb` | (same for all MCPs) |
| Tenant header | `X-Tenant-ID` | (already conventional in this repo) |

## Code: minimum viable AS (embedded)

```python
# auth.py — drop into your env's backend

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import bcrypt
from jose import jwt as jose_jwt

JWT_SECRET = os.getenv("OAUTH_JWT_SECRET", "dev-only-change-me")
ISSUER = f"{os.getenv('ENV_NAME', 'env')}-auth"
AUDIENCE = f"{os.getenv('ENV_NAME', 'env')}-api"
TTL_SEC = int(os.getenv("ACCESS_TOKEN_TTL_SEC", "3600"))


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def mint_jwt(user_id: int, email: str, name: str,
             tenant_id: str, scope: str = "") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": ISSUER,
        "sub": str(user_id),
        "aud": [AUDIENCE],
        "tenant_id": tenant_id,
        "email": email,
        "name": name,
        "scope": scope,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=TTL_SEC)).timestamp()),
    }
    return jose_jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_jwt(token: str) -> Optional[Dict[str, Any]]:
    """Returns claims dict or None. The RS-side check."""
    try:
        claims = jose_jwt.decode(
            token, JWT_SECRET, algorithms=["HS256"],
            options={"verify_aud": False},   # we manually check below
        )
    except Exception:
        return None
    if claims.get("iss") != ISSUER:
        return None
    aud = claims.get("aud", [])
    if isinstance(aud, str):
        aud = [aud]
    if AUDIENCE not in aud:
        return None
    return claims
```

## Code: FastAPI auth middleware (RS side)

```python
# in your endpoint module

from fastapi import HTTPException, Request
from auth import verify_jwt

def claims_from_request(request: Request) -> dict:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(401, "Missing Bearer token")
    claims = verify_jwt(auth_header[7:].strip())
    if not claims:
        raise HTTPException(401, "Invalid or unauthorized token")
    return claims


@app.post("/tools/call")
def tools_call(payload: dict, request: Request):
    claims = claims_from_request(request)
    user_id = int(claims["sub"])
    tenant_id = claims.get("tenant_id") or "default"
    # ... do work using (user_id, tenant_id)
```

For Topology B (centralized AS), replace `user_id = int(claims["sub"])` with a
`_upsert_user_mirror(sub, tenant_id, email, name)` call — see
`src/envs/googledocs/api/main.py:118` for the reference implementation.

## Code: MCP auto-OAuth dance

If your AS only does `/auth/login`, your MCP can just POST credentials and
get a JWT in one shot — keep it simple. If you've added the full
`/oauth/authorize` HTML flow, the MCP can drive it programmatically (no
browser needed). See `src/mcp_server/googledocs/main.py:74-110` for
`_walk_authorize` — it's ~40 lines and works against any RFC 6749 AS.

## Tests: what to write + how

The 32-test suite at `tests/oauth/test_centralized_idp.py` is the
**contract spec** for our google-idp deployment. For a new env's auth,
write the analogous **minimum 8** tests below. Anything less and you
won't notice when something silently breaks.

### Minimum coverage checklist

| # | Test name (suggested) | What it proves |
|---|---|---|
| 1 | `test_health_and_discovery` | Service is up; `/.well-known/oauth-authorization-server` advertises the right grants/algos (skip if no discovery endpoint) |
| 2 | `test_register_and_login_returns_jwt` | Round-trips identity; JWT has `iss == "<env>-auth"`, correct `aud`, `tenant_id`, `email`, `name`, `sub` |
| 3 | `test_duplicate_register_rejected` | Same email twice in same tenant → 400 |
| 4 | `test_multitenant_same_email_distinct` | Same email across 2 tenants → 2 distinct users with different `sub` |
| 5 | `test_ui_jwt_works_on_<env>` | UI-issued JWT → 200 on `/tools/call` (or equivalent RS path) |
| 6 | `test_garbage_token_rejected` | `Bearer notajwt` → 401 |
| 7 | `test_no_token_rejected` | Missing Authorization header → 401 |
| 8 | `test_wrong_aud_rejected` | JWT signed with valid secret but `aud` doesn't include this env's audience → 401 |

### Add when you've added the feature

| Trigger | Test |
|---|---|
| Refresh tokens | `test_refresh_rotation` — old refresh after rotation → 401 |
| `/oauth/authorize` HTML flow | `test_authorize_flow_happy_path` + `test_pkce_wrong_verifier_rejected` + `test_code_single_use` |
| Consent reuse | `test_consent_reuse_skips_prompt` + `test_consent_scope_superset_reprompts` |
| Revoke / introspect | `test_revoke_makes_token_inactive` |
| MCP using auto-OAuth dance | `test_<env>_mcp_auto_oauth_dance_e2e` (drives the full walk in-process; asserts JWT aud + sub mapping on RS) |
| `/api/v1/seed-user` (Topology B only) | `test_seed_user_endpoint_idempotency` |
| Tenant DELETE cascade | `test_tenant_cascade_cleans_mirror` — delete tenant → tokens via `/oauth/introspect` flip to inactive |

### Copyable test scaffolding

Put these at the top of the test file once; the test functions below all
use them:

```python
import base64, hashlib, json, os, secrets, sys
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
import requests

AUTH = os.getenv("ENV_AUTH_URL", "http://localhost:8050")   # AS base
RS   = os.getenv("ENV_API_URL",  "http://localhost:8041")   # RS base


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _jwt_claims(token: str) -> dict:
    """Decode JWT payload (no signature check — for assertions only)."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload).decode())


def _unique(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def _setup_tenant_user(tenant_id: str, email: str, password: str = "pw") -> dict:
    requests.post(f"{AUTH}/api/v1/tenants", json={"id": tenant_id})
    r = requests.post(f"{AUTH}/auth/register", json={
        "email": email, "name": email.split("@")[0].title(),
        "password": password, "tenant_id": tenant_id,
    })
    r.raise_for_status()
    return r.json()


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""

RESULTS: list = []

def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)

def _record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(Result(name, ok, detail))
```

### Worked example: tests #2 + #5 (minimum cross-env)

```python
def test_register_and_login_returns_jwt() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    r = requests.post(f"{AUTH}/auth/login",
                      json={"email": email, "password": "pw", "tenant_id": tid})
    _assert(r.status_code == 200, f"login {r.status_code}")
    body = r.json()
    _assert(body["token_type"] == "Bearer", "token_type")
    _assert(body.get("access_token"), "missing access_token")

    claims = _jwt_claims(body["access_token"])
    _assert(claims["iss"] == "<env>-auth", "iss claim")
    _assert(claims["tenant_id"] == tid, "tenant claim")
    _assert(claims["email"] == email, "email claim")
    _assert(claims["name"] == email.split("@")[0].title(), "name claim")
    _assert("<env>-api" in claims["aud"], "aud includes <env>-api")
    _record("register+login → JWT with correct claims", True)


def test_ui_jwt_works_on_env() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    token = requests.post(f"{AUTH}/auth/login",
        json={"email": email, "password": "pw", "tenant_id": tid}
    ).json()["access_token"]
    r = requests.post(f"{RS}/tools/call",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "list_things", "arguments": {}})
    _assert(r.status_code == 200, f"/tools/call: {r.status_code} {r.text}")
    _record("UI JWT → RS /tools/call", True)
```

### Wrong-aud test (the most-skipped, most-important)

```python
def test_wrong_aud_rejected() -> None:
    """Mint a JWT for a *different* aud — RS must reject."""
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)

    # Easiest path: another env's seed-issued client whose aud doesn't
    # include this env. If there's only one env, fabricate a JWT with
    # wrong aud using the shared secret (only works if you also know it):
    from jose import jwt as jose_jwt
    bad = jose_jwt.encode(
        {"iss": "<env>-auth", "sub": "1", "aud": ["wrong-api"],
         "tenant_id": tid, "email": email, "exp": 9999999999},
        os.environ["OAUTH_JWT_SECRET"], algorithm="HS256",
    )
    r = requests.post(f"{RS}/tools/call",
        headers={"Authorization": f"Bearer {bad}"},
        json={"name": "list_things", "arguments": {}})
    _assert(r.status_code == 401, f"wrong aud not rejected: {r.status_code}")
    _record("wrong-aud token → 401", True)
```

### Runner pattern (skip pytest — keep it deps-free)

```python
TESTS = [
    test_health_and_discovery,
    test_register_and_login_returns_jwt,
    test_ui_jwt_works_on_env,
    test_wrong_aud_rejected,
    # ...add as you go
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except AssertionError as e:
            RESULTS.append(Result(fn.__name__, False, str(e)))
        except Exception as e:
            RESULTS.append(Result(fn.__name__, False, f"{type(e).__name__}: {e}"))

    width = max(len(r.name) for r in RESULTS) + 2
    for r in RESULTS:
        flag = "PASS" if r.ok else "FAIL"
        print(f"{r.name:<{width}} {flag}")
        if not r.ok and r.detail:
            print(f"    → {r.detail}")
    fails = sum(1 for r in RESULTS if not r.ok)
    print(f"\n{len(RESULTS) - fails}/{len(RESULTS)} passed")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

We deliberately don't use pytest — the test file works as a single
`python3 tests/oauth/test_<env>.py` invocation against a running env stack.
No fixtures to debug, no plugin compatibility, runs in CI without extra
deps. Trade: no parallelism, no parametrization. For ~30 e2e tests, fine.

If you'd rather use pytest: just rename `test_*` functions to pytest
discovery rules (already valid) and drop the runner block. The helpers
don't depend on pytest.

## Five gotchas we hit so far

1. **Don't cache the HTTP client at module level if it bakes auth headers** —
   when JWT refresh changes the token, the cached client keeps the stale
   one. Pattern: `get_http()` returns a *fresh* client; auth headers built
   per-call by `await _get_auth_headers()`.
2. **UI image rebuilds for nginx changes** — `restart` won't do it, you need
   `docker compose build && up --force-recreate`. Burns hours when
   forgotten.
3. **Per-tenant mirror is keyed on `(sub, tenant_id)`** — the local `id` is
   a SERIAL only because business FKs already point at integer ids. Don't
   try to make it match `sub` (loses the FK invariance).
4. **Long-lived TTL means revoke is best-effort** — if you set
   `ACCESS_TOKEN_TTL_SEC = 1y` (we do, for sandbox convenience), revoke
   at the AS doesn't help — RS verifies offline. Either short TTL or RS
   calls AS `/oauth/introspect` per request.
5. **Port collisions on docker-compose** — pick a port range for your env's
   UI/API and document it in the env README. We learned this when gmail UI's
   default 8050 collided with the IdP's default 8050.

## Where to look in this repo for the worked example

*(Paths below are reference examples from the source product these envs ship into — treat them as shape, not literal paths in this repo.)*

- Single-AS-multi-RS pattern: `src/google-idp/` + the 5 `src/envs/google*`
  and `src/envs/{gmail,calendar}/` envs
- Auth scaffolding (drop-in template): `src/envs/googlesheets/api/main.py`
  lines 80-160 (smallest, cleanest)
- MCP auto-OAuth dance: `src/mcp_server/googledocs/main.py` lines 1-220
- Tests as a contract spec: `tests/oauth/test_centralized_idp.py`
  (32 e2e cases — copy 2 for any new env)
- Design rationale: `~/oauth_knowledge_transfer_docs/CENTRALIZED_GOOGLE_IDP_DESIGN.md`
- Comparison with another OAuth implementation:
  `~/oauth_knowledge_transfer_docs/OAUTH_VS_VIRTUE_AUTH.md`

For the operational details of the live Google IdP system (debug recipes,
common tasks), see your env's `google-idp` setup and the worked example above.
