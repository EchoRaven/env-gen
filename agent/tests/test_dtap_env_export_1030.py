r"""#1030: export a generated app as a DTAP `dt_arena` environment.

DTAP leases a micro-VM per task, boots the env's compose stack with VM-host podman, drives a
victim over MCP, and grades environment state. An env is exactly three things — the service
stack, an MCP proxy, and one `registry.yaml` entry — and our generator already emits that
shape. Measured against `dt_arena/envs/paypal`, the closest analog in the vendored tree:

    paypal/init/01_init.sql             <-  app/database/init/01_init.sql
    paypal/api/main.py                  <-  app/backend/main.py
    paypal/paypal_ui/Dockerfile         <-  app/frontend/Dockerfile
    paypal/paypal_ui/nginx.conf.tmpl    <-  app/frontend/nginx.conf.template
    paypal/paypal_ui/start.sh           <-  app/frontend/start.sh

So this is a repackage. Two things genuinely differ and are GENERATED rather than copied:

  1. **`network_mode: host` + `${VAR:-default}` ports.** Our compose publishes fixed host ports
     (3000/8081/5432). DTAP addresses services as `127.0.0.1:<port>` inside the VM, so the
     published-port form is wrong there — and dropping it removes the very port-collision
     hazard that contaminates our own parallel runs.
  2. **A healthcheck on every service**, with `depends_on: condition: service_healthy`, so the
     MCP server cannot race a cold database. paypal's api waits on its pg exactly this way.

★ The MCP server calls our REST API DIRECTLY. `POST /tools/call` is paypal's local convention,
not a platform requirement — `mcp_server/slack/main.py` calls `{SLACK_API}/api/v1/channels`
straight. So the generated backend needs NO changes, and the tool list comes mechanically from
`registryhub_endpoints.json` (30 endpoints in r173 -> 30 tools).

Premises verified against real runs before relying on them:
  * `/health` is framework-emitted (`main.py:570` in r173, present in r172 too) — both the
    compose healthcheck and the registry entry depend on it.
  * ports 8078/8079 and pg 5545 are free: registry.yaml holds 8025-8077 + 8453/8454, and
    paypal's pg is on 5544.
"""
import ast
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import dtap_env_export as X  # noqa: E402


# --- a minimal generated run, in the real layout ----------------------------------------------

def _run(tmp_path, endpoints=None):
    r = tmp_path / "netflix-web-rX"
    (r / "app" / "backend").mkdir(parents=True)
    (r / "app" / "frontend" / "src").mkdir(parents=True)
    (r / "app" / "database" / "init").mkdir(parents=True)
    (r / "shared" / "hubs").mkdir(parents=True)
    (r / "app" / "backend" / "main.py").write_text("x=1\n", encoding="utf-8")
    (r / "app" / "frontend" / "Dockerfile").write_text("FROM node\n", encoding="utf-8")
    (r / "app" / "frontend" / "src" / "App.jsx").write_text("//\n", encoding="utf-8")
    (r / "app" / "database" / "init" / "01_init.sql").write_text("CREATE TABLE t();\n",
                                                                 encoding="utf-8")
    eps = endpoints if endpoints is not None else [
        {"method": "GET", "path": "/api/titles", "metadata": {"summary": "list titles"}},
        {"method": "GET", "path": "/api/titles/{id}/episodes", "metadata": {}},
        {"method": "POST", "path": "/api/my-list", "metadata": {"auth_required": True}},
        {"method": "DELETE", "path": "/api/my-list/{id}", "metadata": {}},
    ]
    (r / "shared" / "hubs" / "registryhub_endpoints.json").write_text(
        json.dumps({"_meta": {"version": 1}, **{f"e{i}": e for i, e in enumerate(eps)}}),
        encoding="utf-8")
    return r


def _export(tmp_path, **kw):
    out = tmp_path / "out"
    res = X.export(_run(tmp_path, kw.pop("endpoints", None)), "netflix", out,
                   api_port=8078, ui_port=8079, pg_port=5545, mcp_port=8878,
                   image_ns="decodingtrustagent", **kw)
    return out, res


# --- the layout dt_arena requires ---------------------------------------------------------------

def test_it_emits_the_three_things_an_env_is(tmp_path):
    out, _ = _export(tmp_path)
    assert (out / "dt_arena" / "envs" / "netflix" / "docker-compose-hub.yml").is_file()
    assert (out / "dt_arena" / "mcp_server" / "netflix" / "main.py").is_file()
    assert (out / "registry.snippet.yaml").is_file()


def test_the_paypal_path_mapping_is_reproduced(tmp_path):
    """The mapping this whole exporter rests on, asserted rather than assumed."""
    out, _ = _export(tmp_path)
    e = out / "dt_arena" / "envs" / "netflix"
    assert (e / "init" / "01_init.sql").is_file()
    assert (e / "api" / "main.py").is_file()
    assert (e / "netflix_ui" / "Dockerfile").is_file()


def test_build_junk_is_not_copied(tmp_path):
    r = _run(tmp_path)
    (r / "app" / "frontend" / "node_modules" / "x").mkdir(parents=True)
    (r / "app" / "frontend" / "node_modules" / "x" / "big.js").write_text("//", encoding="utf-8")
    (r / "app" / "backend" / "m.pyc").write_text("", encoding="utf-8")
    out = tmp_path / "out"
    X.export(r, "netflix", out, api_port=8078, ui_port=8079, pg_port=5545, mcp_port=8878,
             image_ns="ns")
    assert not list((out / "dt_arena" / "envs" / "netflix" / "netflix_ui").rglob("node_modules"))
    assert not list((out / "dt_arena" / "envs" / "netflix" / "api").rglob("*.pyc"))


# --- the two things that must NOT be copied verbatim ---------------------------------------------

def test_compose_uses_host_networking_not_published_ports(tmp_path):
    """★ Our compose publishes 3000/8081/5432. In a micro-VM that is both unnecessary and the
    source of the collision hazard; DTAP addresses 127.0.0.1:<port>."""
    out, _ = _export(tmp_path)
    d = yaml.safe_load((out / "dt_arena" / "envs" / "netflix"
                        / "docker-compose-hub.yml").read_text(encoding="utf-8"))
    for name, svc in d["services"].items():
        assert svc.get("network_mode") == "host", name
        assert "ports" not in svc, f"{name} publishes ports; host networking makes that wrong"


def test_every_service_has_a_healthcheck_or_waits_for_one(tmp_path):
    out, _ = _export(tmp_path)
    d = yaml.safe_load((out / "dt_arena" / "envs" / "netflix"
                        / "docker-compose-hub.yml").read_text(encoding="utf-8"))
    assert "healthcheck" in d["services"]["netflix-pg"]
    assert "healthcheck" in d["services"]["netflix-api"]
    dep = d["services"]["netflix-api"]["depends_on"]["netflix-pg"]
    assert dep["condition"] == "service_healthy", (
        "the api must wait on a HEALTHY pg or the MCP server races a cold database")


def test_ports_are_overridable_with_defaults(tmp_path):
    out, _ = _export(tmp_path)
    txt = (out / "dt_arena" / "envs" / "netflix"
           / "docker-compose-hub.yml").read_text(encoding="utf-8")
    assert "${NETFLIX_API_PORT:-8078}" in txt
    assert "${NETFLIX_PG_PORT:-5545}" in txt


def test_the_local_variant_builds_instead_of_pulling(tmp_path):
    out, _ = _export(tmp_path)
    d = yaml.safe_load((out / "dt_arena" / "envs" / "netflix"
                        / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "build" in d["services"]["netflix-api"]
    assert "image" not in d["services"]["netflix-api"]
    assert d["services"]["netflix-pg"]["image"] == "postgres:16", "pg is never built"


# --- the MCP proxy --------------------------------------------------------------------------------

def test_one_tool_per_registered_endpoint(tmp_path):
    out, res = _export(tmp_path)
    assert res["tools"] == res["endpoints"] == 4
    src = (out / "dt_arena" / "mcp_server" / "netflix" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert {"get_titles", "get_titles_by_id_episodes", "post_my_list",
            "delete_my_list_by_id"} <= fns, sorted(fns)


def test_the_generated_proxy_is_valid_python(tmp_path):
    out, _ = _export(tmp_path)
    ast.parse((out / "dt_arena" / "mcp_server" / "netflix"
               / "main.py").read_text(encoding="utf-8"))


def test_path_params_become_arguments_and_interpolate(tmp_path):
    out, _ = _export(tmp_path)
    src = (out / "dt_arena" / "mcp_server" / "netflix" / "main.py").read_text(encoding="utf-8")
    assert "async def get_titles_by_id_episodes(id: str" in src
    assert 'path = f"/api/titles/{id}/episodes"' in src


def test_a_paramless_path_is_not_a_pointless_fstring(tmp_path):
    """A bare f"" is an F541 lint error, and these files land in a repo that lints."""
    out, _ = _export(tmp_path)
    src = (out / "dt_arena" / "mcp_server" / "netflix" / "main.py").read_text(encoding="utf-8")
    assert 'path = "/api/titles"' in src
    assert 'path = f"/api/titles"' not in src


def test_writes_take_a_body_and_reads_take_params(tmp_path):
    out, _ = _export(tmp_path)
    src = (out / "dt_arena" / "mcp_server" / "netflix" / "main.py").read_text(encoding="utf-8")
    assert "async def post_my_list(body: Optional[Dict[str, Any]] = None)" in src
    assert "async def get_titles(params: Optional[Dict[str, Any]] = None)" in src


def test_a_tool_name_collision_is_refused_not_shadowed(tmp_path):
    """★ Two endpoints mapping to one name would silently shadow each other — the loader would
    expose whichever came last and the other would be untestable."""
    with pytest.raises(ValueError, match="collision"):
        X.build_mcp_tools([{"method": "GET", "path": "/api/my-list"},
                           {"method": "GET", "path": "/api/my_list"}])


# --- the registry entry, and the premises it rests on ------------------------------------------

def test_the_registry_entry_matches_the_contract(tmp_path):
    out, _ = _export(tmp_path)
    txt = (out / "registry.snippet.yaml").read_text(encoding="utf-8")
    body = yaml.safe_load(txt)
    assert body["netflix"]["api_base_url"] == "http://127.0.0.1:8078"
    assert body["netflix"]["health_path"] == "/health"


def test_the_default_ports_do_not_collide_with_the_registry():
    """registry.yaml holds 8025-8077 and 8453/8454; paypal's pg is 5544. If those move, this
    file's chosen defaults must move too."""
    assert X.DEFAULT_API_PORT == 8078 and X.DEFAULT_UI_PORT == 8079
    assert X.DEFAULT_PG_PORT == 5545


def test_no_endpoints_yields_no_tools_and_says_so(tmp_path):
    """An env that boots but exposes nothing is the silent-failure shape — the caller warns."""
    out, res = _export(tmp_path, endpoints=[])
    assert res["tools"] == 0
    ast.parse((out / "dt_arena" / "mcp_server" / "netflix"
               / "main.py").read_text(encoding="utf-8"))


def test_the_push_script_is_executable_and_pushes_both_images(tmp_path):
    out, _ = _export(tmp_path)
    p = out / "dt_arena" / "envs" / "netflix" / "BUILD_AND_PUSH.sh"
    assert p.stat().st_mode & 0o111, "must be executable"
    txt = p.read_text(encoding="utf-8")
    assert "netflix:api-latest" in txt and "netflix:ui-latest" in txt
    assert "podman push" in txt


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
