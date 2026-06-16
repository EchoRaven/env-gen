---
name: mcp-server-bootstrap
description: Use when scaffolding a new FastMCP server for a sandbox env, or wiring an existing MCP to be reachable from mcp-gateway / Claude Desktop / Cursor / any OAuth-aware MCP client — backend lane. Symptoms: "create MCP for", "wrap X as MCP", "MCP server for env Y", "add OAuth to MCP", "RemoteAuthProvider", "mcp-gateway can't reach my MCP", "MCP returns 401 to gateway", host.docker.internal / MCP_RESOURCE_URL not resolving, MCP missing from start_all_mcps.sh. Not for tool design (env-specific) or the env's own auth/JWT server (that's env-oauth-blueprint — use it alongside when the MCP verifies env-issued JWTs); schema/tenant decisions are multi-tenancy-pattern.
---

# MCP server bootstrap

How to write the `src/mcp_server/<env>/main.py` for a new env so that
both the existing test agents AND standard OAuth-aware MCP clients
(mcp-gateway, Claude Desktop, Cursor) can use it without surprises.

Pair with `env-oauth-blueprint` (the env-side OAuth) and
`multi-tenancy-pattern` (the schema). This skill is just the MCP layer.

## First: pick the auth posture

Two valid postures; choose by who you trust to call your MCP.

```
┌─────────────────────────────────────────────────────────────┐
│  Posture 1: NAIVE TRANSPORT                                 │
│  /mcp endpoint is unauthenticated.                          │
│                                                             │
│  Tools receive a Bearer token via `arguments.access_token`  │
│  (or another field) and forward it to the env API. The MCP  │
│  itself doesn't verify anything.                            │
│                                                             │
│  Choose when: you're early-stage, the env's REST endpoints  │
│  are behind a firewall, and the MCP is just a tool          │
│  vocabulary on top of /tools/call.                          │
│                                                             │
│  Used by: gmail, calendar, googledocs, googlesheets,        │
│  googledrive, google-form, paypal-tool-injection,           │
│  atlassian-tool-injection (pre-RFC-9728 era).               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Posture 2: MCP-AS-RFC-9728-RESOURCE-SERVER                 │
│  /mcp endpoint requires a Bearer token; serves              │
│  /.well-known/oauth-protected-resource/mcp metadata.        │
│                                                             │
│  Standard OAuth-aware MCP clients (mcp-gateway, Claude      │
│  Desktop) auto-discover the env's AS and complete a full    │
│  OAuth flow.                                                │
│                                                             │
│  Choose when: you want zero-config interop with standard    │
│  MCP clients. This is the post-2026-04 default.             │
│                                                             │
│  Used by: slack, zoom, whatsapp, telegram, github,          │
│  customer_service, paypal, atlassian (post-upgrade).        │
└─────────────────────────────────────────────────────────────┘
```

**Rule of thumb**: pick posture 2. The only time posture 1 is right is
if your env API doesn't have a working AS yet (it will, eventually,
via `env-oauth-blueprint`). Posture 1 is a temporary state, not a
destination.

## Tool naming: snake_case. No exceptions.

Every `@mcp.tool()` function name must be **snake_case**:

```python
@mcp.tool()
async def create_jira_issue(...): ...   # ✅
async def createJiraIssue(...): ...      # ❌ — agents won't find this
```

Why this matters more than usual style preference: agents (Gemini 3.1
Pro, GPT, others) in practice **almost never call `discover_tools`** —
they guess tool names by convention from prior MCPs they've used in
training. Every other MCP in this codebase uses snake_case
(`send_email`, `list_channels`, `post_message`, `create_event`,
`search_opportunities`), so agents that learned on those silently fail
on any camelCase tool — the request goes out as `atlassian_create_jira_issue`
but the MCP only registered `atlassian_createJiraIssue`. Zero
tool-call counts on every task touching that env.

This bit atlassian once (28 tools renamed in commit `d45df9af`). Don't
repeat. The fastmcp framework doesn't enforce the convention — that's
on you.

**Tool parameter names**: prefer snake_case there too for the same
reason. Exception: if your env wraps an upstream API that uses
camelCase parameters and you want to keep the upstream-parity contract
(e.g. atlassian's `cloudId`, `issueIdOrKey` are kept as the real Jira
REST API names), document that decision in a comment on the offending
tool's docstring so a future cleanup pass doesn't blindly rename.

## The skeleton (posture 2)

```python
#!/usr/bin/env python3
"""
<Env> MCP Server — RFC 9728 OAuth resource server.
Verifies RS256 JWTs issued by <env>'s embedded AS at <ENV_API_URL>.
"""
import os
import sys
from typing import Any, Dict, Optional

from fastmcp import FastMCP
from fastmcp.server.auth import JWTVerifier, RemoteAuthProvider
import httpx


# ─── Config ──────────────────────────────────────────────────────────────

API_URL = os.getenv("<ENV>_API_URL", "http://localhost:<env-api-port>")
USER_ACCESS_TOKEN = os.getenv("<ENV>_USER_ACCESS_TOKEN", "")  # legacy fallback

# CRITICAL: this is what gets advertised in /.well-known/oauth-protected-resource/mcp
# AND what the MCP expects in the JWT `aud` claim. If gateway can't reach this URL,
# OAuth discovery fails and the MCP becomes unusable. See "host.docker.internal" below.
MCP_RESOURCE_URL = os.getenv("MCP_RESOURCE_URL", "http://localhost:<mcp-port>")
OAUTH_AUDIENCE = os.getenv("OAUTH_AUDIENCE", f"{MCP_RESOURCE_URL}/mcp")


# ─── Auth provider ───────────────────────────────────────────────────────

def _build_auth_provider() -> Optional[RemoteAuthProvider]:
    """Wire OAuth2 (RFC 9728 protected resource) against the env's AS.
    Set DISABLE_OAUTH=1 for STDIO transport / legacy USER_ACCESS_TOKEN flows."""
    if os.getenv("DISABLE_OAUTH", "").strip().lower() in ("1", "true", "yes"):
        return None
    verifier = JWTVerifier(
        jwks_uri=f"{API_URL.rstrip('/')}/.well-known/jwks.json",
        issuer=API_URL.rstrip("/"),
        audience=OAUTH_AUDIENCE,
        algorithm="RS256",
    )
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[API_URL.rstrip("/")],
        base_url=MCP_RESOURCE_URL,
        resource_name="<Env> MCP",
    )


_auth_provider = _build_auth_provider()
mcp = FastMCP("<Env> MCP Server", auth=_auth_provider)


# ─── Tools (forward to env API) ──────────────────────────────────────────

async def _api_call(name: str, arguments: Dict[str, Any]) -> Any:
    """Forward a tool call to the env API's /tools/call endpoint."""
    args = dict(arguments or {})
    if USER_ACCESS_TOKEN:
        args["access_token"] = USER_ACCESS_TOKEN
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(f"{API_URL}/tools/call",
                                 json={"name": name, "arguments": args})
        resp.raise_for_status()
        return resp.json().get("result")


# Above is the legacy `/tools/call` shape. For envs whose API is plain REST
# (no /tools/call wrapper — most newer envs), forward the user's JWT as
# Authorization: Bearer instead. Extract it from the incoming MCP request
# with fastmcp.server.dependencies.get_access_token():

from fastmcp.server.dependencies import get_access_token


def _bearer_from_context() -> Optional[str]:
    """Pull the user's JWT off the current MCP request, if OAuth is active.
    Returns None when DISABLE_OAUTH=1 (then fall back to a static env var)."""
    if _auth_provider is None:
        return os.getenv("USER_ACCESS_TOKEN") or None
    try:
        tok = get_access_token()
        return tok.token if tok else None
    except Exception:
        return None


def _headers() -> Dict[str, str]:
    h: Dict[str, str] = {"Accept": "application/json"}
    bearer = _bearer_from_context()
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    return h


# Then a tool just passes _headers() into its httpx call:
@mcp.tool()
async def list_things() -> Any:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_URL}/api/v1/things", headers=_headers())
        return r.json()


# ... more tools ...


# ─── Run ─────────────────────────────────────────────────────────────────

def main() -> None:
    print("Starting <Env> MCP Server...", file=sys.stderr)
    sys.stderr.flush()
    host = os.getenv("<ENV>_MCP_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "<default-mcp-port>"))
    mcp.run(transport="http", host=host, port=port)   # ← BOTH host AND port


if __name__ == "__main__":
    main()
```

Replace `<Env>` / `<ENV>` / `<env-api-port>` / `<mcp-port>` /
`<default-mcp-port>` with your env's actual values. See the
`start_all_mcps.sh` port table for the convention (22800-22815 is the
range; pick the next free one).

## CRITICAL: host=0.0.0.0 + MCP_RESOURCE_URL=host.docker.internal

The two wires that break gateway access if you forget them:

### 1. `host=` must be passed to `mcp.run`

```python
mcp.run(transport="http", port=port)               # ← WRONG, defaults to 127.0.0.1
mcp.run(transport="http", host=host, port=port)    # ← RIGHT
```

fastmcp's HTTP transport defaults to `127.0.0.1` (loopback only).
mcp-gateway runs in a Docker bridge network and reaches host
processes via `host.docker.internal` — which resolves to a real
network interface, NOT loopback. If your MCP is on `127.0.0.1` only,
gateway gets "connection refused."

**Bind to `0.0.0.0`** so the MCP listens on every interface (loopback
+ Docker's `host-gateway` route).

Three MCPs in this codebase shipped with this bug at one point
(calendar, slack, customer_service). Don't repeat.

### 2. `MCP_RESOURCE_URL` must be reachable from gateway

The MCP's RFC 9728 metadata advertises whatever you put in
`base_url=` of `RemoteAuthProvider`. If you set:

```python
base_url="http://localhost:22808"
```

then gateway's OAuth discovery fetches
`http://localhost:22808/.well-known/oauth-protected-resource/mcp` —
from inside its container. `localhost` there is the gateway's own
loopback. Connection refused.

**Fix**: set `MCP_RESOURCE_URL` to a hostname the gateway container
can resolve. The standard is `host.docker.internal`:

```bash
# In start_all_mcps.sh
MCP_RESOURCE_URL='http://host.docker.internal:22808' \
<ENV>_API_URL='http://host.docker.internal:8041' \
PORT='22808' $VENV "$MCP_DIR/<env>/main.py" &
```

This requires `127.0.0.1 host.docker.internal` in `/etc/hosts` on the
host (Docker Desktop adds it automatically; Linux servers need it
manually):

```bash
echo "127.0.0.1 host.docker.internal" | sudo tee -a /etc/hosts
```

Add this to your env setup README.

### 3. The env API URL must match too

When MCP says `authorization_servers=[API_URL]`, gateway will fetch
that URL too — same host-resolution rule applies. Pass
`<ENV>_API_URL=http://host.docker.internal:<port>` in the launch line,
not `localhost:`.

## Password-grant MCPs: lazy `_AUTO_TOKEN` bootstrap

If your MCP is a "real-user" MCP — i.e. authenticates to the env as a
specific user via `password` grant rather than `client_credentials` —
add the lazy auto-login pattern. Every MCP call goes through a single
`_resolve_token()` shim that mints (and caches) a JWT on first use, so
the agentsuite-red proxy can `DISABLE_OAUTH=1` against the MCP without
each tool call needing a pre-fetched bearer.

```python
_AUTO_TOKEN: Optional[str] = None
_AUTO_TOKEN_LOCK = asyncio.Lock()


async def _bootstrap_token() -> str:
    """Mint a JWT against the env's /auth/login using the password
    credentials in env vars. Soft-fails (logs + returns "") if the env
    is unreachable — that way the MCP tool errors are about the actual
    operation, not the bootstrap."""
    global _AUTO_TOKEN
    if _AUTO_TOKEN:
        return _AUTO_TOKEN
    async with _AUTO_TOKEN_LOCK:
        if _AUTO_TOKEN:
            return _AUTO_TOKEN
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(
                    f"{API_URL}/auth/login",
                    headers={"X-Tenant-Id": USER_TENANT},
                    json={"email": USER_EMAIL, "password": USER_PASSWORD,
                          "tenant_id": USER_TENANT},
                )
                r.raise_for_status()
                _AUTO_TOKEN = r.json().get("access_token") or ""
        except Exception as e:
            print(f"[MCP] _AUTO_TOKEN bootstrap skipped: {e}", file=sys.stderr)
            _AUTO_TOKEN = ""
        return _AUTO_TOKEN


def _resolve_token(token: Optional[str] = None) -> str:
    """Tool functions call this to obtain a Bearer. Order:
       1. explicit `access_token` argument from the tool call
       2. the lazy-bootstrapped _AUTO_TOKEN
       3. legacy USER_ACCESS_TOKEN env (for stdio mode)
    """
    return token or _AUTO_TOKEN or USER_ACCESS_TOKEN or ""
```

Reference implementations (each ~30 LOC):
`src/mcp_server/{slack,zoom,paypal,whatsapp,telegram,atlassian}/main.py`.

### Credentials env-var fallback chain

`env_server` injects generic `OAUTH_USER_EMAIL` / `OAUTH_USER_PASSWORD`
into every MCP process. Older MCPs use env-specific names
(`SLACK_OAUTH_USER_EMAIL`, etc.). Accept both, falling through:

```python
USER_EMAIL = os.getenv("OAUTH_USER_EMAIL") or _require_env("SLACK_OAUTH_USER_EMAIL")
USER_PASSWORD = os.getenv("OAUTH_USER_PASSWORD") or _require_env("SLACK_OAUTH_USER_PASSWORD")
USER_TENANT = (
    os.getenv("SLACK_OAUTH_USER_TENANT")
    or os.getenv("TENANT_ID")
    or os.getenv("X_TENANT_ID")
    or "default"
)
```

The tenant fallback chain is the same shape — `TENANT_ID` is what
`env_server` injects per task, `X_TENANT_ID` is a legacy alias, env
default ("default") is the last-resort smoke-test value.

### Bind tenant at token mint, not on subsequent calls

The env's `_require_user` (or equivalent JWT validator) trusts the
**`tenant_id` claim in the JWT** over any `X-Tenant-Id` header sent
alongside subsequent API calls. So pass `X-Tenant-Id` when minting:

```python
headers = {"Accept": "application/json"}
if USER_TENANT:                              # at the /auth/login or
    headers["X-Tenant-Id"] = USER_TENANT     # /Api/access_token call
async with httpx.AsyncClient() as client:
    r = await client.post(LOGIN_URL, headers=headers, ...)
```

If you skip this, every issued JWT carries `tenant_id="default"`, every
subsequent CRM read in a non-default tenant returns empty, and the
failure looks like data isn't being created — when really the token is
just pinned to the wrong tenant. Cost us a debugging session on
salesforce; explicit `X-Tenant-Id` at mint time is now the rule.

### Eager `/api/v1/seed-user` POST in `_store()` for google-family MCPs

For MCPs in the google-family (gmail / calendar / googledocs /
googlesheets / googledrive), after the token is minted, decode the
JWT claims and POST them to the env's `/api/v1/seed-user` endpoint:

```python
def _store(body: Dict[str, Any]) -> str:
    _token_cache["access_token"] = body["access_token"]
    ...
    # eagerly seed the local user_mirror so the env's ownership_tracker
    # / inbox lookups can resolve this user IMMEDIATELY — without
    # waiting for the lazy auto-mirror on first authenticated call.
    try:
        claims = _decode_jwt_payload(body["access_token"])
        sub = claims.get("sub")
        tid = claims.get("tenant_id") or USER_TENANT
        email = claims.get("email") or USER_EMAIL
        if sub is not None and email and AUTH_API_URL:
            httpx.post(
                f"{AUTH_API_URL}/api/v1/seed-user",
                json={"sub": sub, "tenant_id": tid, "email": email,
                      "name": claims.get("name") or email.split("@")[0]},
                timeout=5,
            )
    except Exception as e:
        print(f"[MCP] seed-user skipped: {e}", file=sys.stderr)
    return body["access_token"]
```

This is the **MCP-side complement** to google-idp's `/auth/register`
fan-out (see `env-oauth-blueprint` for the IdP side). Together they
close two races:

- (IdP side) setup.sh registers a user → IdP fans out → mirror ready
  before emails arrive.
- (MCP side) MCP authenticates first as the user → seed-user populates
  mirror immediately, so ownership tracker can attribute any email
  the agent sends *in this session*.

If your env doesn't have a mirror table (non-google-family), skip this.

## DISABLE_OAUTH=1 stopgap for proxy contracts

agentsuite-red's local proxy talks to MCPs over `127.0.0.1` and
doesn't fetch its own bearer per MCP — it assumes the MCP either
already holds a token (the `_AUTO_TOKEN` pattern above) or runs
without auth on the `/mcp` endpoint.

If you set `DISABLE_OAUTH=1` in env_server's MCP launch line,
`_build_auth_provider()` returns `None`, the `/mcp` endpoint stops
requiring a Bearer, and the proxy can call freely. The MCP itself
still authenticates to the **upstream env API** using the
`_AUTO_TOKEN`. So the chain is:

```
agent → red proxy
         │   (DISABLE_OAUTH=1: no bearer required at /mcp)
         ↓
       MCP /mcp endpoint
         │   (_AUTO_TOKEN authenticates THIS to the env)
         ↓
       env REST API
```

Always document the removal target in the comment:
```yaml
DISABLE_OAUTH: "1"  # stopgap — track removal: <upstream-issue>
```

That makes the "what's blocking removal" question explicit and
search-able. Don't ship without that comment.

## start_all_mcps.sh registration

Add a line for your MCP under the existing block. The pattern:

```bash
<ENV>_TOKEN=$(fetch_env_jwt http://localhost:<env-api-port>/auth/login)
<ENV>_API_URL='http://host.docker.internal:<env-api-port>' \
  MCP_RESOURCE_URL='http://host.docker.internal:<mcp-port>' \
  USER_ACCESS_TOKEN="${<ENV>_TOKEN:-tok_unified_dev_fixed}" \
  PORT='<mcp-port>' $VENV "$MCP_DIR/<env>/main.py" &
echo "[MCP] <Env> on <mcp-port> (token ${<ENV>_TOKEN:+fetched via login})"
```

Also export the host var at the top of the script (in the `export` block):

```bash
export <ENV>_MCP_HOST=0.0.0.0
```

## Verifying it works

```bash
# 1. MCP started + bound to 0.0.0.0
ss -tlnp 'sport = :<mcp-port>'    # should show 0.0.0.0:<mcp-port>

# 2. WWW-Authenticate header on unauth request
curl -sI http://localhost:<mcp-port>/mcp -H 'Accept: application/json'
# expect: HTTP/1.1 401 + www-authenticate: Bearer ... resource_metadata="..."

# 3. PRM advertises gateway-reachable URL
curl -s http://localhost:<mcp-port>/.well-known/oauth-protected-resource/mcp | jq
# expect: "resource": "http://host.docker.internal:<mcp-port>/mcp"

# 4. Gateway container can reach the PRM URL
docker exec mcp-gateway-api python3 -c "
import urllib.request as u
print(u.urlopen('http://host.docker.internal:<mcp-port>/.well-known/oauth-protected-resource/mcp', timeout=3).status)"
# expect: 200

# 5. Full OAuth dance via gateway
pytest tests/oauth/test_mcp_gateway_oauth_e2e.py -v -k <env>
```

If all five pass, gateway / Claude Desktop / Cursor will be able to
OAuth into your MCP zero-config.

## Add the env to the e2e test

Drop a row into `tests/oauth/test_mcp_gateway_oauth_e2e.py`'s `ENVS`
list:

```python
OAuthEnv("<env>", <mcp-port>, "<dev-email-or-username>", "<password>",
         ("<expected>", "<tool>", "<keywords>"),
         "<env>.read <env>.write"),
```

The test framework drives the full standard OAuth dance (RFC 8414 +
9728 + 7591 + 8707 + PKCE) against your MCP automatically. If your
env API follows the env-oauth-blueprint contract, no per-env code
needed in the test — just the row.

## Anti-patterns we've actually shipped (and fixed)

### ❌ Forgot `host=` in `mcp.run`

calendar/slack/customer_service all shipped without it. `mcp-gateway`
got connection-refused → looked like an unrelated infra problem. Audit:
```bash
grep -n "mcp\.run" src/mcp_server/<env>/main.py
# if no `host=`, fix.
```

### ❌ Misleading "FastMCP doesn't accept host=" comment

calendar's old code had:
```python
# FastMCP.run does not accept 'host' in some versions; bind via env if needed.
mcp.run(transport="http", port=port)
```
The comment is wrong. fastmcp >= 2.x accepts `host=`; the workaround
was probably written for an old version and stuck around. If you see a
similar comment elsewhere, delete it and pass `host=` directly.

### ❌ Hardcoded `localhost` everywhere

```python
MCP_RESOURCE_URL = "http://localhost:22808"   # ← bad
```
Make it env-var-driven so `start_all_mcps.sh` can override per-deploy:
```python
MCP_RESOURCE_URL = os.getenv("MCP_RESOURCE_URL", "http://localhost:22808")
```

### ❌ Missing `auth=` in `FastMCP(...)`

Even if you call `_build_auth_provider()`, forgetting to pass it to
`FastMCP(...)` means the auth provider is built but never installed.
The `/mcp` endpoint will be unauthenticated, the test e2e will fail
with confusing error messages.

```python
mcp = FastMCP("<Env> MCP")              # ← bad, no auth
mcp = FastMCP("<Env> MCP", auth=_auth_provider)  # ← good
```

### ❌ `**kwargs` in a `@mcp.tool()` function

fastmcp introspects each tool's signature to build a JSON schema for
the agent — and **rejects** functions with `*args` or `**kwargs`:

```python
@mcp.tool()
async def update_account(account_id: str, **kwargs) -> Any:    # ← bad
    ...
```

Crashes at import time:
```
ValueError: Functions with **kwargs are not supported as tools
```

Fix: take an explicit `attributes: Dict[str, Any]` (or list every
field you want to support):

```python
@mcp.tool()
async def update_account(account_id: str, attributes: Dict[str, Any]) -> Any:
    return await _api_patch(...)
```

Same applies to `*args`. The error references the offending
`@mcp.tool()` decorator line, but the actual problem is the
`**kwargs` parameter on the decorated function.

## Reference implementations

| Pattern | Best example |
|---|---|
| Posture 2 (RFC 9728), Postgres-backed env | `src/mcp_server/slack/main.py` |
| Posture 2, SQLite-backed env | `src/mcp_server/zoom/main.py` |
| Posture 2 with central IdP (5 google envs) | `src/mcp_server/googledocs/main.py` |
| Posture 1 (legacy, naive) | `src/mcp_server/gmail-tool-injection/main.py` (pre-upgrade) |
| Tools/call envelope pattern (REST passthrough) | `src/mcp_server/paypal-tool-injection/main.py` |

slack is the cleanest reference — copy its `_build_auth_provider` and
the `mcp.run(transport="http", host=host, port=port)` shape verbatim.
