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
from typing import Optional  # noqa: E402  (used above the file's own typing import)

import re
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Dict, List


# ──────────────────────────────────────────────────────────────────────────────
# Business-endpoint selection + deterministic tool naming
# ──────────────────────────────────────────────────────────────────────────────

# Endpoint kinds that are NOT business operations (the orchestrator-registered
# fixed surface). Anything with one of these kinds is excluded from the MCP tool
# projection — they are protocol/infra, driven by the harness/UI, not the agent.
# #853: this said "the orchestrator-registered fixed surface" and then re-listed a SUBSET of it,
# missing `control`/`control_plane`/`health`. The consequence here is the sharpest of the four
# copies: a `control` endpoint would be projected as an MCP TOOL, handing an agent `reset` or
# `init-tenant`. Zero live exposure (the 864 real control-surface records all carry `infra`),
# but "excluded from the tool projection" has to mean the whole surface it names.
from .kickoff.contract import FIXED_ENDPOINT_KINDS as _NON_BUSINESS_KINDS


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


def _qp_match_key_1202xr(method: Any, path: Any) -> str:
    """(METHOD, path) collapsed so a handler and the contract match even when they
    spell a path parameter differently -- r137 registered `/api/videos/{video_id}/
    comments` while an earlier record spelled it `{id}`."""
    p = re.sub(r":(\w+)", r"{\1}", str(path or ""))
    p = re.sub(r"\{[^}]*\}", "{}", p).rstrip("/") or "/"
    return str(method).upper() + " " + p


def _a_args_1202xr(fn):
    return list(fn.args.args)


def _a_defaults_1202xr(fn):
    a = fn.args
    return [None] * (len(a.args) - len(a.defaults)) + list(a.defaults)


_SCALAR_ANNOTATIONS_1202XR = ("str", "int", "float", "bool", "UUID", "date", "datetime")


def _is_scalar_annotation_1202xr(node: Any) -> bool:
    """Does this annotation make a defaulted parameter a QUERY parameter to FastAPI?

    ``str``, ``int``, ``str | None``, ``Optional[int]`` yes; ``dict``, ``dict | None``,
    ``Request``, a model class, or no annotation at all, no. The distinction is the whole
    point: a body parameter carries the same `= None` default and must not become a query
    argument."""
    import ast

    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in _SCALAR_ANNOTATIONS_1202XR
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip().strip("\"'") in _SCALAR_ANNOTATIONS_1202XR
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        parts = (node.left, node.right)
        return (any(_is_scalar_annotation_1202xr(p) for p in parts)
                and all(_is_scalar_annotation_1202xr(p)
                        or (isinstance(p, ast.Constant) and p.value is None)
                        for p in parts))
    if isinstance(node, ast.Subscript):
        head = getattr(node.value, "id", "") or getattr(node.value, "attr", "")
        if head == "Optional":
            return _is_scalar_annotation_1202xr(node.slice)
    return False


def backend_query_params_1202xr(output_dir: Any) -> Dict[str, List[str]]:
    """{match key -> ordered query-parameter names} read from the IMPLEMENTED handlers.

    A tool that cannot be given the parameter its endpoint filters on is a tool that
    cannot do the job it is named for: the delivered netflix-r30 server exposes
    ``async def get_search() -> str`` calling ``/api/search`` bare, so the agent this
    surface exists for can list but never search, filter or paginate. Measured over the
    corpus when this was written: 462 of 1,760 projected tools -- 26%, across 94 runs --
    drop at least one query parameter their own backend declares, r137 (the newest run)
    among them.

    NEITHER the registry NOR the compiled spec models query parameters (no run carries a
    `query_params` field on an endpoint record, and no spec endpoint carries one), so the
    handlers are the only source. Read like the DDL check reads models.py: AST over the
    written backend, never a regex over text.

    TWO FORMS, because FastAPI has two. An explicit ``Query(...)`` default is one; a bare
    scalar default is the other, and it is the one the lanes actually write for the tool
    that needed this most -- netflix-r30's ``search_titles(q: str = "", kind: str | None =
    None, limit: int = 50)`` declares six query parameters and not one ``Query(...)``.
    Reading only the explicit form found 0 of them and left ``get_search()`` argumentless,
    which is the delivered defect this exists to fix. Corpus: 403 further parameters in 83
    runs come from the bare form.

    The bare form is admitted on the ANNOTATION, never on the default alone, because that
    is what separates a query parameter from a request body: ``body: dict | None = None``
    has the same default shape and is a BODY. Measured over the corpus, the annotation
    predicate rejects 932 ``dict`` and 305 ``dict | None`` parameters, every
    ``Annotated[..., Header(...)]`` and every ``Request`` -- and no run in the corpus
    writes ``Annotated[..., Query()]``, so that third spelling is deliberately not
    guessed at here; it would need its own measurement.

    Best-effort and ADDITIVE by construction -- no backend yet (kickoff's first pass),
    an unparseable module, or handlers with no ``Query(...)`` default all yield {}, and
    the rendered server is then byte-identical to what it was before this existed."""
    import ast

    out: Dict[str, List[str]] = {}
    try:
        be = Path(output_dir) / "app" / "backend"
        files = sorted(be.glob("*.py")) if be.is_dir() else []
    except Exception:
        return out
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue          # one unparseable module must not blind the others
        # `from fastapi import Query as _Q` is a style the corpus actually uses
        # (tiktok-r61 writes `limit: int = _Q(20, ge=1, le=100)`), and matching the
        # name `Query` alone reads those as "no query parameters at all". Resolved by
        # the IMPORT rather than by widening to "any call default", which would swallow
        # `Body(...)` and `Header(...)` -- the two things that must not become query
        # arguments.
        query_names = {"Query"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and str(node.module or "").startswith("fastapi"):
                for al in node.names:
                    if al.name == "Query" and al.asname:
                        query_names.add(al.asname)

        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes = []
            for d in fn.decorator_list:
                if (isinstance(d, ast.Call)
                        and getattr(d.func, "attr", "") in ("get", "post", "put",
                                                            "delete", "patch")
                        and d.args and isinstance(d.args[0], ast.Constant)
                        and isinstance(d.args[0].value, str)):
                    routes.append((d.func.attr, d.args[0].value))
            if not routes:
                continue
            # A name the path binds is a PATH parameter on every route this handler
            # serves, so it is excluded across all of them, not per route.
            bound = set()
            for _m, _p in routes:
                bound |= set(re.findall(r"\{(\w+)", str(_p)))
            names: List[str] = []
            for x, d in list(zip(_a_args_1202xr(fn), _a_defaults_1202xr(fn))) + list(
                    zip(fn.args.kwonlyargs, fn.args.kw_defaults)):
                if d is None or x.arg in bound or x.arg in names:
                    continue
                if isinstance(d, ast.Call):
                    if getattr(d.func, "id", "") in query_names:
                        names.append(x.arg)      # explicit form
                    continue                     # Depends/Body/Header/... are not queries
                if isinstance(d, ast.Constant) and _is_scalar_annotation_1202xr(x.annotation):
                    names.append(x.arg)          # bare scalar default
            if not names:
                continue
            for meth, path in routes:
                key = _qp_match_key_1202xr(meth, path)
                have = out.setdefault(key, [])
                for n in names:
                    if n not in have:
                        have.append(n)
    return out


def _renderable_query_args_1202xr(names: Any, path_params: List[str]) -> List[str]:
    """The subset of a handler's query parameters that can become tool arguments.

    Excluded, each for a reason that would otherwise emit code that does not run or
    that silently shadows: a name that is not a plain identifier or is a Python
    keyword (``def get_x(from: str | None = None)`` is a SyntaxError), ``body``
    (the write tools' own argument), and a name the path already binds."""
    import keyword

    taken = set(path_params) | {"body"}
    out: List[str] = []
    for n in (names or []):
        n = str(n)
        if n in taken or n in out:
            continue
        if keyword.iskeyword(n) or not n.isidentifier():
            continue
        out.append(n)
    return out


def _body_fields_note_1202xt(ep: Mapping[str, Any]) -> str:
    """One line naming the fields the contract says this write takes, or "".

    FastMCP builds a tool's input schema from the SIGNATURE and its description from the
    DOCSTRING. Every projected write takes `body: dict | None = None`, which is
    `{"type": "object"}` with no properties -- so an agent handed this surface must guess
    the field names. It cannot: the delivered r137 exposes `post_auth_signup` whose
    contract states username, email, password and display_name and whose tool says only
    "POST /api/auth/signup". Corpus: 280 of the 357 write tools whose contract HAS a
    request schema surface none of it, r137 (6 of 11), r135 (4 of 5) and netflix-r30
    among them.

    THE DOCSTRING, NOT THE SIGNATURE. Turning the contract's fields into typed arguments
    would make the tool's call shape a promise about the handler, and the two diverge as a
    matter of record -- `/auth/register` alone has three sources disagreeing about its
    response. Naming the fields costs nothing if the handler wants others; typing the
    arguments would turn that divergence into a rejected call.

    No cap: measured over the corpus's 1,968 request schemas the field count is 1-7 for all
    but 16, the largest being 21, and a truncated field list is worse than none for the one
    job this has (#1034 -- a cut list has to say it was cut, and here there is nothing to
    cut). Non-string type values are reported as what they are (48 nested objects, 5 bools
    across the corpus) rather than guessed at."""
    req = (ep.get("schema") or {}).get("request") if isinstance(ep.get("schema"), Mapping) else None
    if not isinstance(req, Mapping) or not req:
        return ""
    parts: List[str] = []
    for name, typ in req.items():
        _n = _one_line_1202xt(name)
        if not _n:
            continue
        if isinstance(typ, Mapping):
            _t = "object"
        elif isinstance(typ, (list, tuple)):
            _t = "array"
        elif isinstance(typ, str):
            _t = _one_line_1202xt(typ) or "?"
        else:
            _t = _one_line_1202xt(str(typ)) or "?"
        parts.append("%s (%s)" % (_n, _t))
    return ("Body fields: " + ", ".join(parts)) if parts else ""


def _one_line_1202xt(text: Any) -> str:
    """Collapse a contract string to something a docstring can hold verbatim.

    The values come from the contract, so they can carry a quote or a newline; a `"` would
    close the triple-quoted docstring and a newline would break the one-line note."""
    return " ".join(str(text or "").replace('"', "'").split())


def render_tool(ep: Dict[str, Any], alias: Optional[str] = None,
                query_params: Any = None) -> str:
    """Render one ``@mcp.tool`` async function projecting a backend endpoint.

    Built with plain string templating (NOT an f-string) so the generated
    f-string ``f"{API_BASE_URL}{path}"`` and dict literals survive verbatim.

    ``query_params`` (#1202xr) is the endpoint's query-parameter names, from
    ``backend_query_params_1202xr``. They are rendered as OPTIONAL arguments and
    only the ones the caller actually passes reach the backend, so a tool with
    query parameters behaves exactly as it did before when none are supplied.
    Omitted/empty → the previous output, byte for byte."""
    method = str(ep["method"]).upper()
    path = str(ep["path"])
    op = alias or tool_op_id(method, path)
    params = _path_params(path)
    fpath = _to_fstring_path(path)
    is_write = method in ("POST", "PUT", "PATCH")
    qargs = _renderable_query_args_1202xr(query_params, params)

    args = [f"{p}: str" for p in params]
    if is_write:
        args.append("body: dict | None = None")
    args += [f"{q}: str | None = None" for q in qargs]
    sig = ", ".join(args)
    call_kw = ", json=(body or {})" if is_write else ""
    # The dict is built into a local, and a path parameter may legally be named
    # anything -- including the local. Then the f-string path would interpolate the
    # DICT and the tool would request a URL nobody serves, silently.
    qlocal = "_params"
    while qlocal in params or qlocal in qargs:
        qlocal += "_q"
    if qargs:
        call_kw += ", params=" + qlocal

    doc = ep.get("summary") or f"{method} {path}"
    doc = doc.replace('"', "'")
    # #1202xt: name the body fields the contract states, for the agent that has to send them.
    if is_write:
        _bodynote = _body_fields_note_1202xt(ep)
        if _bodynote:
            doc = doc.rstrip() + ". " + _bodynote
    lines = [
        "@mcp.tool()",
        "async def " + op + "(" + sig + ") -> str:",
        '    """' + doc + '"""',
        "    try:",
    ]
    if qargs:
        pairs = ", ".join('"%s": %s' % (q, q) for q in qargs)
        lines.append("        " + qlocal + " = {k: v for k, v in {" + pairs
                     + "}.items() if v is not None}")
    lines += [
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
    # #1202sa: named after the ENV, never after whoever ran the generator -- this default
    # registers a real user row in the delivered app's database, so the generator's own
    # company has no business appearing on a profile the app then lists.
    email = os.getenv("DEV_USER_EMAIL", "dev@__ENV_NAME__.local")
    password = os.getenv("DEV_USER_PASSWORD", "dev-local-password")
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
                        tool_aliases: Optional[Dict[str, str]] = None) -> List[tuple]:
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


def _scrubbed_1202mi(text: str, filename: str) -> str:
    """Strip framework ticket tags and past-run names from the comments and
    docstrings of Python written into the generated app. Applied on EVERY such
    write path, not only the ones that leak today: this template is currently
    clean, and a policy that holds on five of six paths is the shape of defect
    `#1202mg` was about. Never raises."""
    try:
        from .provenance_scrub import scrub_provenance_1202mi
        return scrub_provenance_1202mi(text, filename)
    except Exception:
        return text


def render_mcp_server(endpoints: Dict[str, Any], env_name: str = "app",
                      tool_aliases: Optional[Dict[str, str]] = None,
                      query_params: Optional[Dict[str, List[str]]] = None) -> str:
    """Render the full ``main.py``: fixed skeleton + one tool per business
    endpoint. Deterministic — same contract in, byte-identical server out.

    #1202xs: ``tool_aliases`` reaches the RENDERED FILE, not only the registry
    records. ``write_mcp_server`` took the aliases, handed them to
    ``mcp_tool_records`` and dropped them here, so a contract whose spec binds
    semantic tool names registered ``search_places`` while the served file defined
    ``get_places`` — googlemaps-r16 shipped 26 of its 41 registered tool names
    absent from the server they name. Both halves now derive from one call.

    #1202xr: ``query_params`` is ``backend_query_params_1202xr``'s map, keyed by
    ``_qp_match_key_1202xr``. Empty/omitted → unchanged output."""
    title = env_name.replace("_", " ").replace("-", " ").title()
    header = (_SKELETON_HEADER
              .replace("__ENV_UPPER__", env_name.upper())
              .replace("__ENV_TITLE__", title)
              .replace("__ENV_NAME__", env_name))
    qp = query_params or {}
    tools = "\n".join(
        render_tool(ep, alias=name,
                    query_params=qp.get(_qp_match_key_1202xr(ep.get("method"),
                                                             ep.get("path"))))
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
                     tool_aliases: Optional[Dict[str, str]] = None,
                     query_params: Optional[Dict[str, List[str]]] = None
                     ) -> List[Dict[str, Any]]:
    """The tool registration records (one per business endpoint) the
    orchestrator feeds to ``mcp_registry.register_mcp_tool``.

    #1202xr: the record states the SERVED tool's inputs, query parameters included.
    These records and the rendered file are the two halves of one projection, and
    #1202xs is what happens when one half is built from an input the other was not:
    googlemaps-r16 registered 26 tool names its own server does not define. So both
    halves take the same ``tool_aliases`` and the same ``query_params``."""
    qp = query_params or {}
    recs: List[Dict[str, Any]] = []
    for ep, name in _resolve_tool_names(endpoints, tool_aliases):
        method, path = str(ep["method"]).upper(), str(ep["path"])
        _pp = _path_params(path)
        recs.append({
            "tool_name": name,  # collision-free across the whole contract
            "method": method,
            "path": path,
            "schema": {
                "input": {"path_params": _pp,
                          "query_params": _renderable_query_args_1202xr(
                              qp.get(_qp_match_key_1202xr(method, path)), _pp),
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
                     tool_aliases: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Author ``<output_dir>/mcp_server/<env>/{main.py, pyproject.toml, start.sh}``.

    Like the DB DDL (and unlike the AS modules), this projects from the
    post-kickoff contract, so it is an untracked ``output_dir`` write — agentsuite
    pool launches it as a subprocess; no agent worktree imports it. Idempotent.
    Returns ``{"main_py", "tool_count", "server_dir", "tools": [records]}``."""
    output_dir = Path(output_dir)
    server_dir = output_dir / "mcp_server" / env_name
    server_dir.mkdir(parents=True, exist_ok=True)

    # ONE read, both halves: the rendered server and the records it is registered
    # under must describe the same tool.
    _qp = backend_query_params_1202xr(output_dir)

    main_py = server_dir / "main.py"
    main_py.write_text(
        _scrubbed_1202mi(
            render_mcp_server(endpoints, env_name, tool_aliases=tool_aliases,
                              query_params=_qp),
            main_py.name),
        encoding="utf-8")
    (server_dir / "pyproject.toml").write_text(
        _PYPROJECT.replace("__ENV_NAME__", env_name), encoding="utf-8")
    (server_dir / "start.sh").write_text(_START_SH, encoding="utf-8")

    records = mcp_tool_records(endpoints, tool_aliases=tool_aliases,
                               query_params=_qp)
    return {
        "main_py": main_py,
        "server_dir": server_dir,
        "tool_count": len(records),
        "tools": records,
    }


__all__ = [
    "backend_query_params_1202xr",
    "business_endpoints",
    "tool_op_id",
    "render_tool",
    "render_mcp_server",
    "mcp_tool_records",
    "write_mcp_server",
]
