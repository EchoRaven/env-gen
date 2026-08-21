#!/usr/bin/env python3
"""Export a generated app as a DTAP `dt_arena` environment.

WHY THIS SHAPE. DTAP leases a micro-VM per task and boots the env's compose stack with
VM-host podman, then drives a victim agent over MCP and grades environment state. An env is
therefore three things, and nothing else:

    dt_arena/envs/<env>/          the service stack (compose + per-service build context)
    dt_arena/mcp_server/<env>/    a thin FastMCP proxy over the env's HTTP API
    dt_arena/envs/registry.yaml   one entry: base URLs + health_path

Our generator already emits that shape almost exactly. Measured against
`dt_arena/envs/paypal`, the closest analog in the vendored tree:

    paypal/init/01_init.sql          <-  app/database/init/01_init.sql
    paypal/api/main.py               <-  app/backend/main.py
    paypal/paypal_ui/Dockerfile      <-  app/frontend/Dockerfile
    paypal/paypal_ui/nginx.conf...   <-  app/frontend/nginx.conf.template
    paypal/paypal_ui/start.sh        <-  app/frontend/start.sh

so this is a repackage, not a port. Two things genuinely differ and are GENERATED here rather
than copied:

  1. `network_mode: host` with `${VAR:-default}` ports. Our compose publishes fixed host ports
     (3000/8081/5432). In a micro-VM there is nothing to collide with and DTAP addresses
     services as 127.0.0.1:<port>, so the published-port form is wrong there. This also
     removes the port-collision hazard that makes our own parallel runs contaminate each other.
  2. A healthcheck on every service, with `depends_on: condition: service_healthy`. paypal's
     api waits on pg this way; without it the MCP server races a cold database.

The MCP server calls our REST API DIRECTLY. `POST /tools/call` is paypal's local convention,
not a platform requirement — `mcp_server/slack/main.py` calls `{SLACK_API}/api/v1/channels`
straight. So the generated backend needs no changes at all, and the tool list is derived
mechanically from `registryhub_endpoints.json`.

Images are NOT vendored (RESYNC.md: "Heavy container images are NOT vendored — they are
built/pushed to vmvm-registry and referenced by the compose files"). `BUILD_AND_PUSH.sh` is
emitted for that step.

Usage:
    python tools/dtap_env_export.py --run agent/generated/netflix-web-r173 --env-name netflix
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ports already claimed in dt_arena/envs/registry.yaml (read off the vendored file, 2026-08-20):
# 8025 8030 8032-8036 8038-8040 8054-8057 8060-8073 8076 8077 8453 8454, and paypal's pg on 5544.
DEFAULT_API_PORT = 8078
DEFAULT_UI_PORT = 8079
DEFAULT_PG_PORT = 5545

_SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next",
              ".pytest_cache", ".git"}
_SKIP_SUFFIX = {".pyc", ".pyo", ".log"}


def _copy_tree(src: Path, dst: Path) -> int:
    """Copy a build context, dropping the junk DTAP explicitly excludes from vendoring."""
    n = 0
    if not src.is_dir():
        return 0
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix in _SKIP_SUFFIX:
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        n += 1
    return n


def _load_endpoints(run: Path) -> List[Dict[str, Any]]:
    f = run / "shared" / "hubs" / "registryhub_endpoints.json"
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [v for k, v in raw.items() if k != "_meta" and isinstance(v, dict)]


def _tool_name(method: str, path: str) -> str:
    """`GET /api/titles/{id}/episodes` -> `get_titles_by_id_episodes`. Deterministic and
    collision-free across the corpus's 30 endpoints; a collision would silently shadow a tool,
    so `build_mcp_tools` asserts uniqueness rather than trusting this."""
    segs = []
    for seg in path.strip("/").split("/"):
        if not seg:
            continue
        if seg.startswith("{") and seg.endswith("}"):
            segs.append("by_" + seg[1:-1])
        else:
            segs.append(re.sub(r"[^a-z0-9]+", "_", seg.lower()).strip("_"))
    # drop a leading api/ — every business path carries it and it adds nothing to the name
    if segs and segs[0] == "api":
        segs = segs[1:]
    return (method.lower() + "_" + "_".join(s for s in segs if s)).rstrip("_")


def build_mcp_tools(endpoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One MCP tool per registered endpoint, with its path params extracted."""
    tools: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}
    for e in sorted(endpoints, key=lambda x: (str(x.get("path")), str(x.get("method")))):
        method = str(e.get("method") or "GET").upper()
        path = str(e.get("path") or "")
        if not path:
            continue
        name = _tool_name(method, path)
        if name in seen:
            raise ValueError(
                f"tool-name collision {name!r}: {seen[name]} and {method} {path} — the second "
                "would silently shadow the first")
        seen[name] = f"{method} {path}"
        params = re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path)
        meta = e.get("metadata") or {}
        tools.append({
            "name": name,
            "method": method,
            "path": path,
            "path_params": params,
            "auth_required": bool(meta.get("auth_required")),
            "summary": str(meta.get("summary") or f"{method} {path}")[:200],
            "has_body": method in ("POST", "PUT", "PATCH"),
        })
    return tools


def render_compose_hub(env: str, api_port: int, ui_port: int, pg_port: int, image_ns: str) -> str:
    U = env.upper()
    return f'''version: "3.8"

# {env} DTAP environment — prebuilt images from the hub, exactly as
# dt_arena/envs/paypal/docker-compose-hub.yml does it.
#
# network_mode: host is deliberate. DTAP boots this inside a leased micro-VM and addresses
# every service as 127.0.0.1:<port> (see dt_arena/envs/registry.yaml), so published-port
# mappings are both unnecessary and wrong here.
services:
  {env}-pg:
    image: postgres:16
    network_mode: host
    security_opt:
      - seccomp=unconfined
    environment:
      POSTGRES_DB: {env}
      POSTGRES_USER: sandbox
      POSTGRES_PASSWORD: sandbox
    command: ["-p", "${{{U}_PG_PORT:-{pg_port}}}"]
    volumes:
      - ./init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -p ${{{U}_PG_PORT:-{pg_port}}} -U sandbox -d {env}"]
      interval: 5s
      timeout: 3s
      retries: 30

  {env}-api:
    image: {image_ns}/{env}:api-latest
    network_mode: host
    security_opt:
      - seccomp=unconfined
    depends_on:
      {env}-pg:
        condition: service_healthy
    environment:
      {U}_PG_HOST: 127.0.0.1
      {U}_PG_PORT: ${{{U}_PG_PORT:-{pg_port}}}
      {U}_PG_DB: {env}
      {U}_PG_USER: sandbox
      {U}_PG_PASSWORD: sandbox
      {U}_API_PORT: ${{{U}_API_PORT:-{api_port}}}
      DATABASE_URL: postgresql://sandbox:sandbox@127.0.0.1:${{{U}_PG_PORT:-{pg_port}}}/{env}
    healthcheck:
      test: ["CMD-SHELL", "python -c \\"import urllib.request,sys,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('{U}_API_PORT','{api_port}')+'/health', timeout=2); sys.exit(0)\\" || exit 1"]
      interval: 3s
      timeout: 3s
      retries: 40
    restart: unless-stopped

  {env}-ui:
    image: {image_ns}/{env}:ui-latest
    network_mode: host
    security_opt:
      - seccomp=unconfined
    depends_on:
      - {env}-api
    environment:
      {U}_API_PORT: ${{{U}_API_PORT:-{api_port}}}
      {U}_UI_PORT: ${{{U}_UI_PORT:-{ui_port}}}
    restart: unless-stopped
'''


def render_compose_local(env: str, api_port: int, ui_port: int, pg_port: int) -> str:
    """Build-from-source variant, for iterating before the images are pushed."""
    hub = render_compose_hub(env, api_port, ui_port, pg_port, "IMAGE_NS")
    hub = hub.replace(f"    image: IMAGE_NS/{env}:api-latest\n",
                      "    build:\n      context: ./api\n")
    hub = hub.replace(f"    image: IMAGE_NS/{env}:ui-latest\n",
                      f"    build:\n      context: ./{env}_ui\n")
    return hub.replace("prebuilt images from the hub, exactly as",
                       "built from source (use -hub for the pushed images), mirroring")


def render_mcp_main(env: str, api_port: int, tools: List[Dict[str, Any]]) -> str:
    U = env.upper()
    lines = [
        '"""Auto-generated FastMCP proxy over the ' + env + ' environment API.',
        "",
        "Calls the env's REST API directly. `POST /tools/call` is paypal's local convention, not",
        "a platform requirement — mcp_server/slack/main.py calls `{SLACK_API}/api/v1/channels`",
        "the same way this does, so the environment needs no dispatcher endpoint.",
        '"""',
        "import os",
        "from typing import Any, Dict, Optional",
        "",
        "import httpx",
        "from fastmcp import FastMCP",
        "",
        f'API_URL = os.getenv("{U}_API_URL") or "http://127.0.0.1:" + os.getenv("{U}_API_PORT", "{api_port}")',
        f'ACCESS_TOKEN = os.getenv("{U}_ACCESS_TOKEN") or os.getenv("USER_ACCESS_TOKEN")',
        "",
        "",
        "async def _call(method: str, path: str, *, params: Optional[Dict[str, Any]] = None,",
        "                body: Optional[Dict[str, Any]] = None) -> Any:",
        '    """One retrying HTTP call. 4xx is returned to the model as a value rather than',
        "    raised: a 401/404 is a legitimate observation for a victim agent, while a 5xx or a",
        '    connection error during cold start is worth retrying."""',
        "    headers = {}",
        "    if ACCESS_TOKEN:",
        '        headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"',
        "    last: Optional[Exception] = None",
        "    for attempt in range(1, 11):",
        "        try:",
        "            async with httpx.AsyncClient(timeout=20) as client:",
        "                r = await client.request(method, f\"{API_URL}{path}\",",
        "                                         params=params, json=body, headers=headers)",
        "            if r.status_code >= 500:",
        "                raise RuntimeError(f\"{r.status_code} {r.text[:200]}\")",
        "            try:",
        "                return r.json()",
        "            except Exception:",
        '                return {"status_code": r.status_code, "text": r.text[:2000]}',
        "        except Exception as e:  # noqa: BLE001 — cold start / 5xx are retryable",
        "            last = e",
        "            import asyncio",
        "            await asyncio.sleep(min(0.5 * attempt, 3.0))",
        f'    raise RuntimeError(f"{env} env API call failed after retries: {{last}}")',
        "",
        "",
        f'mcp = FastMCP("{env.title()} MCP Server")',
        "",
    ]
    for t in tools:
        args = list(t["path_params"])
        sig = ["".join([a, ": str"]) for a in args]
        if t["has_body"]:
            sig.append("body: Optional[Dict[str, Any]] = None")
        else:
            sig.append("params: Optional[Dict[str, Any]] = None")
        # f-prefix ONLY when there is something to interpolate: a bare f"" is an F541 lint
        # error, and these files land in a repo that lints them.
        path_lit = (f'f"{t["path"]}"' if args else f'"{t["path"]}"')
        lines += [
            "@mcp.tool()",
            f"async def {t['name']}({', '.join(sig)}) -> Any:",
            f'    """{t["summary"]}"""',
            f'    path = {path_lit}',
            (f'    return await _call("{t["method"]}", path, body=body)' if t["has_body"]
             else f'    return await _call("{t["method"]}", path, params=params)'),
            "",
            "",
        ]
    lines += ['if __name__ == "__main__":', "    mcp.run()", ""]
    return "\n".join(lines)


def render_mcp_start(env: str, api_port: int, mcp_port: int) -> str:
    U = env.upper()
    return f'''#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$SCRIPT_DIR"

PORT=${{PORT:-{mcp_port}}}
export {U}_MCP_HOST=${{{U}_MCP_HOST:-localhost}}
export {U}_MCP_PORT="${{{U}_MCP_PORT:-$PORT}}"
export {U}_API_PORT="${{{U}_API_PORT:-{api_port}}}"

echo "{env} MCP  : http://${{{U}_MCP_HOST}}:${{{U}_MCP_PORT}}"
echo "{env} ENV  : http://127.0.0.1:${{{U}_API_PORT}}"

exec uv run python main.py
'''


def render_mcp_pyproject(env: str) -> str:
    return f'''[project]
name = "{env}-mcp-server"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["fastmcp>=2.0.0", "httpx>=0.27"]

[tool.uv]
package = false
'''


def render_registry_snippet(env: str, api_port: int, ui_port: int) -> str:
    return f'''  # append to dt_arena/envs/registry.yaml under `services:`
  {env}:
    api_base_url: "http://127.0.0.1:{api_port}"
    ui_base_url: "http://127.0.0.1:{ui_port}"
    health_path: "/health"
'''


def render_build_push(env: str, image_ns: str) -> str:
    return f'''#!/bin/bash
# Build + push the {env} images referenced by docker-compose-hub.yml.
# RESYNC.md: heavy images are NOT vendored — they live in the registry and the compose file
# only references them. Run this from this directory BEFORE launching a job that uses the env.
set -euo pipefail
cd "$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

NS="${{IMAGE_NS:-{image_ns}}}"

podman build -t "$NS/{env}:api-latest" ./api
podman build -t "$NS/{env}:ui-latest"  ./{env}_ui

podman push "$NS/{env}:api-latest"
podman push "$NS/{env}:ui-latest"

echo "pushed $NS/{env}:{{api,ui}}-latest"
'''


def export(run: Path, env: str, out: Path, *, api_port: int, ui_port: int, pg_port: int,
           mcp_port: int, image_ns: str) -> Dict[str, Any]:
    envs = out / "dt_arena" / "envs" / env
    mcp = out / "dt_arena" / "mcp_server" / env
    envs.mkdir(parents=True, exist_ok=True)
    mcp.mkdir(parents=True, exist_ok=True)

    counts = {
        "api": _copy_tree(run / "app" / "backend", envs / "api"),
        "ui": _copy_tree(run / "app" / "frontend", envs / f"{env}_ui"),
        "init": _copy_tree(run / "app" / "database" / "init", envs / "init"),
    }
    (envs / "docker-compose-hub.yml").write_text(
        render_compose_hub(env, api_port, ui_port, pg_port, image_ns), encoding="utf-8")
    (envs / "docker-compose.yml").write_text(
        render_compose_local(env, api_port, ui_port, pg_port), encoding="utf-8")
    bp = envs / "BUILD_AND_PUSH.sh"
    bp.write_text(render_build_push(env, image_ns), encoding="utf-8")
    bp.chmod(0o755)

    endpoints = _load_endpoints(run)
    tools = build_mcp_tools(endpoints)
    (mcp / "main.py").write_text(render_mcp_main(env, api_port, tools), encoding="utf-8")
    (mcp / "pyproject.toml").write_text(render_mcp_pyproject(env), encoding="utf-8")
    st = mcp / "start.sh"
    st.write_text(render_mcp_start(env, api_port, mcp_port), encoding="utf-8")
    st.chmod(0o755)

    (out / "registry.snippet.yaml").write_text(
        render_registry_snippet(env, api_port, ui_port), encoding="utf-8")

    return {"env": env, "files": counts, "tools": len(tools),
            "endpoints": len(endpoints), "out": str(out)}


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="a generated run dir (agent/generated/<name>)")
    ap.add_argument("--env-name", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--api-port", type=int, default=DEFAULT_API_PORT)
    ap.add_argument("--ui-port", type=int, default=DEFAULT_UI_PORT)
    ap.add_argument("--pg-port", type=int, default=DEFAULT_PG_PORT)
    ap.add_argument("--mcp-port", type=int, default=8878)
    ap.add_argument("--image-ns", default="decodingtrustagent")
    a = ap.parse_args(argv)

    run = Path(a.run)
    if not (run / "app").is_dir():
        print(f"ABORT: {run} has no app/ — not a generated run dir", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else Path("dtap_export") / a.env_name
    res = export(run, a.env_name, out, api_port=a.api_port, ui_port=a.ui_port,
                 pg_port=a.pg_port, mcp_port=a.mcp_port, image_ns=a.image_ns)
    print(json.dumps(res, indent=2))
    if not res["endpoints"]:
        print("WARNING: no registryhub_endpoints.json — 0 MCP tools generated. The env will "
              "boot but expose no tool surface.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
