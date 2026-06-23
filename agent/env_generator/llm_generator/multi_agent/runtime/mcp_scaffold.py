"""Deterministic projection of registered business endpoints → mcp_server/<env>/.

The forgingground target ships a SEPARATE FastMCP server per env (zoom-style):
``mcp_server/<env>/main.py`` exposes one ``@mcp.tool`` per backend business
endpoint and forwards the caller's RS256 JWT to the backend, which the embedded
AS verifies. agentsuite-red's pool launches it as a subprocess (NOT a compose
service) and discovers its tools via MCP tool-discovery.

Consistency-by-construction (the governing principle, see
``feedback_envgen_api_consistency_by_construction``): the MCP tool surface is a
1:1 projection of the RegistryHub business contract, so it CANNOT drift from the
endpoints. The runtime emits it; an LLM never re-authors an MCP server (the same
drift class as the OAuth AS — a wrong path, a missing tool, a mismatched
audience and the red-team agent can't drive the env).

Two tiers (mirrors the reference gmail/calendar/zoom servers):
  * FIXED skeleton (~90%): FastMCP instantiation + RemoteAuthProvider/JWTVerifier
    (verifies against the backend's ``/.well-known/jwks.json``), per-request JWT
    forwarding (``get_access_token`` → ``Authorization: Bearer``; NO X-Tenant-ID,
    the JWT carries tenant_id), an httpx request helper, and the ``mcp.run(http)``
    bootstrap. Identical every env.
  * PER-ENDPOINT (projected 1:1): one ``@mcp.tool`` per registered BUSINESS
    endpoint — path params become typed args, write methods take a ``body`` dict,
    the tool calls the backend path and returns the JSON.

Auth boundary (per the contract-extract review): only BUSINESS endpoints become
tools. The fixed surface (``/auth/*``, ``/oauth/*``, ``/.well-known/*``, the
tenant/health control plane — tagged ``metadata.kind`` by
``_register_contract_surface``) is NOT projected: those are protocol/infra, not
agent-drivable business operations.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List


# ──────────────────────────────────────────────────────────────────────────────
# Business-endpoint selection + deterministic tool naming
# ──────────────────────────────────────────────────────────────────────────────

# Endpoint kinds that are NOT business operations (the orchestrator-registered
# fixed surface). Anything with one of these kinds is excluded from the MCP tool
# projection — they are protocol/infra, driven by the harness/UI, not the agent.
_NON_BUSINESS_KINDS = frozenset({"auth", "oauth", "infra", "spine"})


def _endpoint_kind(ep: Dict[str, Any]) -> str:
    """Read the ``kind`` tag wherever it landed (top-level or under metadata)."""
    if ep.get("kind"):
        return str(ep["kind"]).lower()
    md = ep.get("metadata")
    if isinstance(md, dict) and md.get("kind"):
        return str(md["kind"]).lower()
    return ""


def business_endpoints(endpoints: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the BUSINESS endpoint records (kind unset), sorted deterministically.

    ``endpoints`` is RegistryHub's ``get_endpoints()`` map (id → record). Deprecated
    endpoints and the fixed auth/oauth/infra/spine surface are excluded."""
    out: List[Dict[str, Any]] = []
    for ep in (endpoints or {}).values():
        if not isinstance(ep, dict):
            continue
        if ep.get("status") == "deprecated":
            continue
        if _endpoint_kind(ep) in _NON_BUSINESS_KINDS:
            continue
        if not ep.get("method") or not ep.get("path"):
            continue
        out.append(ep)
    out.sort(key=lambda e: (str(e["path"]), str(e["method"]).upper()))
    return out


_PARAM_RE = re.compile(r"[{:](\w+)\}?")


def _path_params(path: str) -> List[str]:
    """Ordered path-parameter names: ``/api/posts/{id}`` → ``['id']``;
    ``/api/posts/:id/comments/:cid`` → ``['id', 'cid']``."""
    return [m.group(1) for m in _PARAM_RE.finditer(path)]


def _to_fstring_path(path: str) -> str:
    """Normalize a route to a python f-string body: ``:id`` → ``{id}``; a
    ``{id}`` segment is already f-string-shaped and passes through."""
    return re.sub(r":(\w+)", r"{\1}", path)


def tool_op_id(method: str, path: str) -> str:
    """Deterministic, collision-free tool name for a (method, path).

    ``GET /api/posts`` → ``get_posts``; ``POST /api/posts`` → ``post_posts``;
    ``GET /api/posts/{id}`` → ``get_posts_by_id``; ``GET /`` → ``get_root``.
    The method prefix disambiguates verbs on the same path; the leading
    ``api/``/``api/v1/`` is stripped only for readability."""
    p = path.strip("/")
    for pre in ("api/v1/", "api/"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    parts: List[str] = []
    for seg in p.split("/"):
        if not seg:
            continue
        if seg.startswith("{") or seg.startswith(":"):
            parts.append("by_" + re.sub(r"\W", "_", seg.strip("{}:")))
        else:
            parts.append(re.sub(r"\W", "_", seg))
    slug = "_".join([method.lower()] + (parts or ["root"]))
    return re.sub(r"_+", "_", slug).strip("_")


def _norm_ep_key(method: str, path: str) -> str:
    import re as _re
    norm = _re.sub(r":(\w+)", r"{\1}", str(path))
    return str(method).upper() + " " + norm


def render_tool(ep: Dict[str, Any], alias: str = None) -> str:
    """Render one ``@mcp.tool`` async function projecting a backend endpoint.

    Built with plain string templating (NOT an f-string) so the generated
    f-string ``f"{API_BASE_URL}{path}"`` and dict literals survive verbatim."""
    method = str(ep["method"]).upper()
    path = str(ep["path"])
    op = alias or tool_op_id(method, path)
    params = _path_params(path)
    fpath = _to_fstring_path(path)
    is_write = method in ("POST", "PUT", "PATCH")

    args = [f"{p}: str" for p in params]
    if is_write:
        args.append("body: dict | None = None")
    sig = ", ".join(args)
    call_kw = ", json=(body or {})" if is_write else ""

    doc = ep.get("summary") or f"{method} {path}"
    lines = [
        "@mcp.tool()",
        "async def " + op + "(" + sig + ") -> str:",
        '    """' + doc.replace('"', "'") + '"""',
        "    try:",
        '        resp = await _request("' + method + '", f"{API_BASE_URL}' + fpath + '"' + call_kw + ")",
        "        resp.raise_for_status()",
        "        return json.dumps(resp.json(), ensure_ascii=False)",
        "    except Exception as e:",
        '        return json.dumps({"error": str(e)})',
    ]
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────────
# FIXED skeleton (identical every env) — header (imports + auth + http) + footer
# ──────────────────────────────────────────────────────────────────────────────

_SKELETON_HEADER = '''"""Auto-generated FastMCP server — do NOT hand-edit.

Deterministic 1:1 projection of the registered BUSINESS endpoints (see
runtime/mcp_scaffold.py). One @mcp.tool per backend endpoint; the caller's RS256
JWT is forwarded to the backend, which the embedded OAuth2 AS verifies via JWKS.
"""
import os
import sys
import json
from typing import Optional, Dict

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token

# Backend base URL (the FastAPI app + embedded OAuth2 AS) and the MCP's own
# canonical URI. OAUTH_AUDIENCE defaults to the env-api audience the backend
# signs into UI/MCP JWTs.
API_BASE_URL = os.getenv("API_BASE_URL", os.getenv("__ENV_UPPER___API_URL", "http://localhost:8080")).rstrip("/")
MCP_RESOURCE_URL = os.getenv("MCP_RESOURCE_URL", f"http://localhost:{os.getenv('PORT', '8890')}").rstrip("/")
OAUTH_AUDIENCE = os.getenv("OAUTH_AUDIENCE", "__ENV_NAME__-api")
USER_ACCESS_TOKEN = os.getenv("USER_ACCESS_TOKEN", "")
X_TENANT_ID = os.getenv("X_TENANT_ID", "default")

# Multi-tenant default: the per-request JWT is the ONLY tenant source. Self-mint
# is confined to DISABLE_OAUTH=1 (STDIO / single-tenant dev) — in a shared MT
# process a self-minted token would silently write to the wrong tenant.
_DISABLE_OAUTH = os.getenv("DISABLE_OAUTH", "").strip().lower() in ("1", "true", "yes")

print(f"[__ENV_NAME__ MCP] API_BASE_URL={API_BASE_URL} audience={OAUTH_AUDIENCE} disable_oauth={_DISABLE_OAUTH}", file=sys.stderr)
sys.stderr.flush()


def _build_auth_provider():
    """RemoteAuthProvider verifying RS256 JWTs against the backend's JWKS.
    None in DISABLE_OAUTH dev mode (no token verification)."""
    if _DISABLE_OAUTH:
        return None
    from fastmcp.server.auth import JWTVerifier, RemoteAuthProvider
    verifier = JWTVerifier(
        jwks_uri=f"{API_BASE_URL}/.well-known/jwks.json",
        issuer=API_BASE_URL,
        audience=OAUTH_AUDIENCE,
        algorithm="RS256",
    )
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[API_BASE_URL],
        base_url=MCP_RESOURCE_URL,
        resource_name="__ENV_TITLE__ MCP",
    )


mcp = FastMCP("__ENV_TITLE__ MCP", auth=_build_auth_provider())

_DEV_TOKEN: Optional[str] = None


def _dev_token() -> Optional[str]:
    """DISABLE_OAUTH dev self-mint via the embedded AS first-party /auth.
    Registers-or-logs-in a dev user once and caches the access token."""
    global _DEV_TOKEN
    if _DEV_TOKEN:
        return _DEV_TOKEN
    email = os.getenv("DEV_USER_EMAIL", "dev@virtueai.com")
    password = os.getenv("DEV_USER_PASSWORD", "virtue")
    tid = X_TENANT_ID or "default"
    with httpx.Client(timeout=15.0) as c:
        for path in ("/auth/login", "/auth/register"):
            try:
                r = c.post(f"{API_BASE_URL}{path}", json={"email": email, "password": password, "tenant_id": tid})
                if r.status_code in (200, 201):
                    _DEV_TOKEN = r.json().get("access_token")
                    if _DEV_TOKEN:
                        return _DEV_TOKEN
            except Exception:
                pass
    return USER_ACCESS_TOKEN or None


def _resolve_token() -> Optional[str]:
    """Per-request OAuth2 JWT first; in DISABLE_OAUTH dev fall back to self-mint.
    A multi-tenant request with no per-request token fails closed."""
    try:
        tok = get_access_token()
    except Exception:
        tok = None
    if tok and getattr(tok, "token", None):
        return tok.token
    if not _DISABLE_OAUTH:
        raise PermissionError("no per-request access token on a multi-tenant request")
    return _dev_token()


def _auth_headers() -> Dict[str, str]:
    # NO X-Tenant-ID: the forwarded JWT carries the caller's tenant_id claim and
    # the backend trusts it. A process-level header would break MT isolation.
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    token = _resolve_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _request(method: str, url: str, **kw) -> httpx.Response:
    """Authed request with PER-CALL headers (each tool call may carry a
    different user's JWT — never cache auth headers on the client)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.request(method, url, headers=_auth_headers(), **kw)


# ── projected tools (1:1 with registered business endpoints) ──
'''

_SKELETON_FOOTER = '''

def main():
    port = int(os.getenv("PORT", os.getenv("MCP_PORT", "8890")))
    mcp.run(transport="http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
'''


_PYPROJECT = '''[project]
name = "__ENV_NAME__-mcp"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
  "fastmcp>=2.13.0",
  "httpx>=0.28",
  "mcp>=1.4",
  "uvicorn[standard]>=0.31",
  "websockets>=12.0",
]
'''

_START_SH = '''#!/bin/sh
# Launch the FastMCP server (agentsuite-red pool runs this as a subprocess).
set -e
export PORT="${PORT:-8890}"
export API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8080}"
exec uv run python main.py
'''


def _resolve_tool_names(endpoints: Dict[str, Any],
                        tool_aliases: Dict[str, str] = None) -> List[tuple]:
    """[(endpoint, unique_tool_name)] in contract order, GUARANTEED collision-free.

    A base name (the spec alias, else ``tool_op_id``) that repeats gets a deterministic
    numeric suffix (``_2``, ``_3``, …). This closes the real collision ``tool_op_id`` opens
    by stripping both ``api/v1/`` and ``api/`` (``/api/tenants`` and ``/api/v1/tenants`` both
    base to ``get_tenants``) — without it the server emits two same-named ``@mcp.tool``s (the
    second shadows the first) and the registry double-counts, yielding an incomplete MCP
    surface. The first occurrence keeps its base name, so non-colliding contracts are
    unchanged."""
    aliases = tool_aliases or {}
    used: set = set()
    out: List[tuple] = []
    for ep in business_endpoints(endpoints):
        base = aliases.get(_norm_ep_key(str(ep["method"]), str(ep["path"]))) \
            or tool_op_id(str(ep["method"]), str(ep["path"]))
        name, i = base, 1
        while name in used:
            i += 1
            name = f"{base}_{i}"
        used.add(name)
        out.append((ep, name))
    return out


def render_mcp_server(endpoints: Dict[str, Any], env_name: str = "app",
                      tool_aliases: Dict[str, str] = None) -> str:
    """Render the full ``main.py``: fixed skeleton + one tool per business
    endpoint. Deterministic — same contract in, byte-identical server out."""
    title = env_name.replace("_", " ").replace("-", " ").title()
    header = (_SKELETON_HEADER
              .replace("__ENV_UPPER__", env_name.upper())
              .replace("__ENV_TITLE__", title)
              .replace("__ENV_NAME__", env_name))
    tools = "\n".join(
        render_tool(ep, alias=name)
        for ep, name in _resolve_tool_names(endpoints, tool_aliases))
    return header + tools + _SKELETON_FOOTER


def spec_tool_aliases(spec: Dict[str, Any]) -> Dict[str, str]:
    """{normalized 'METHOD /path' → spec tool name} from the compiled
    reference spec — the MCP server emits the SPEC'S semantic tool names
    (get_profile_info) instead of derived ones (get_api_users_me), so the
    mcp_tool_exists gates bind by construction."""
    out: Dict[str, str] = {}
    for t in (spec or {}).get("mcp_tools") or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        ep = str(t.get("endpoint") or "").strip()
        if not name or " " not in ep:
            continue
        m, pth = ep.split(" ", 1)
        out[_norm_ep_key(m, pth.strip())] = name
    return out


def mcp_tool_records(endpoints: Dict[str, Any],
                     tool_aliases: Dict[str, str] = None) -> List[Dict[str, Any]]:
    """The tool registration records (one per business endpoint) the
    orchestrator feeds to ``mcp_registry.register_mcp_tool``."""
    recs: List[Dict[str, Any]] = []
    for ep, name in _resolve_tool_names(endpoints, tool_aliases):
        method, path = str(ep["method"]).upper(), str(ep["path"])
        recs.append({
            "tool_name": name,  # collision-free across the whole contract
            "method": method,
            "path": path,
            "schema": {
                "input": {"path_params": _path_params(path),
                          "request": ep.get("schema", {}).get("request", {})},
                "output": ep.get("schema", {}).get("response", {}),
                # The response envelope key (item|items) so consumers know the data
                # lives at response[response_key] — without it {item:{...}} and
                # {items:[...],total:N} are indistinguishable from the schema alone.
                "response_key": (ep.get("metadata", {}) or {}).get("response_key")
                or (ep.get("schema", {}) or {}).get("response_key") or "",
            },
        })
    return recs


def write_mcp_server(output_dir: Path, endpoints: Dict[str, Any],
                     env_name: str = "app",
                     tool_aliases: Dict[str, str] = None) -> Dict[str, Any]:
    """Author ``<output_dir>/mcp_server/<env>/{main.py, pyproject.toml, start.sh}``.

    Like the DB DDL (and unlike the AS modules), this projects from the
    post-kickoff contract, so it is an untracked ``output_dir`` write — agentsuite
    pool launches it as a subprocess; no agent worktree imports it. Idempotent.
    Returns ``{"main_py", "tool_count", "server_dir", "tools": [records]}``."""
    output_dir = Path(output_dir)
    server_dir = output_dir / "mcp_server" / env_name
    server_dir.mkdir(parents=True, exist_ok=True)

    main_py = server_dir / "main.py"
    main_py.write_text(render_mcp_server(endpoints, env_name), encoding="utf-8")
    (server_dir / "pyproject.toml").write_text(
        _PYPROJECT.replace("__ENV_NAME__", env_name), encoding="utf-8")
    (server_dir / "start.sh").write_text(_START_SH, encoding="utf-8")

    records = mcp_tool_records(endpoints, tool_aliases=tool_aliases)
    return {
        "main_py": main_py,
        "server_dir": server_dir,
        "tool_count": len(records),
        "tools": records,
    }


__all__ = [
    "business_endpoints",
    "tool_op_id",
    "render_tool",
    "render_mcp_server",
    "mcp_tool_records",
    "write_mcp_server",
]
