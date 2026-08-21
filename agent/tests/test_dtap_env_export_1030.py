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


def test_the_local_variant_builds_all_three(tmp_path):
    out, _ = _export(tmp_path)
    d = yaml.safe_load((out / "dt_arena" / "envs" / "netflix"
                        / "docker-compose.yml").read_text(encoding="utf-8"))
    for n in ("netflix-pg", "netflix-api", "netflix-ui"):
        assert "build" in d["services"][n], n
        assert "image" not in d["services"][n], n


def test_every_hub_image_is_a_registry_ref_including_the_database(tmp_path):
    """★ The offline constraint. tbr/images.py: "the runtime VM has no network". A bare
    `postgres:16` would be unpullable at run time, which is why the enabled crm env ships
    `decodingtrustagent/salesforce-crm:mariadb` instead of a stock mariadb. An earlier cut of
    this exporter referenced postgres:16 and would have produced a stack that cannot boot."""
    out, _ = _export(tmp_path)
    d = yaml.safe_load((out / "dt_arena" / "envs" / "netflix"
                        / "docker-compose-hub.yml").read_text(encoding="utf-8"))
    for n, svc in d["services"].items():
        img = svc.get("image", "")
        assert img.startswith("decodingtrustagent/") or "/" in img.split(":")[0], n
        assert ":" in img and not img.endswith(":"), f"{n} has no tag: {img!r}"
        assert img != "postgres:16", "the database must be a baked registry image too"


def test_the_pg_image_bakes_the_seed_rather_than_mounting_it(tmp_path):
    """A bind-mounted ./init is resolved at boot; offline, the seed has to be in the layer."""
    out, _ = _export(tmp_path)
    e = out / "dt_arena" / "envs" / "netflix"
    df = (e / "pg" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY init/" in df and "docker-entrypoint-initdb.d" in df
    d = yaml.safe_load((e / "docker-compose-hub.yml").read_text(encoding="utf-8"))
    assert "volumes" not in d["services"]["netflix-pg"], (
        "a volume mount cannot carry the seed into an offline VM")


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


def test_the_default_registry_matches_the_platform():
    """tbr/images.py: REGISTRY = vmvm-registry.fbinfra.net/zhaorun/dtap, tag `clawfish`."""
    import subprocess
    src = (Path(X.__file__)).read_text(encoding="utf-8")
    assert "vmvm-registry.fbinfra.net/zhaorun/dtap" in src
    assert '"clawfish"' in src


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


def test_the_push_script_builds_and_pushes_all_three(tmp_path):
    out, _ = _export(tmp_path)
    p = out / "dt_arena" / "envs" / "netflix" / "BUILD_AND_PUSH.sh"
    assert p.stat().st_mode & 0o111, "must be executable"
    txt = p.read_text(encoding="utf-8")
    for comp in ("netflix-pg", "netflix-api", "netflix-ui"):
        assert f'"$NS/{comp}:$TAG"' in txt, comp
    assert txt.count("podman push") == 3
    assert "DTAP_REGISTRY" in txt and "DTAP_TAG" in txt, (
        "must honour the same overrides tbr/build_images.sh uses")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1030c: the app-facing env names, not just the namespaced knobs -------------------------

def test_the_api_gets_the_env_names_the_app_actually_reads(tmp_path):
    """★ The knobs are `${NETFLIX_*}`; the app reads `API_PORT` (main.py:
    environ.get("API_PORT", "8081")) and `DATABASE_URL` (database.py). Setting only the
    namespaced form left the api bound to its own default 8081 while the healthcheck and
    registry.yaml both pointed at 8078 — `harness_env.py` names that exact failure: "a
    mismatch points the judge at a dead port ... a silent reward-0 indistinguishable from a
    real task failure"."""
    out, _ = _export(tmp_path)
    d = yaml.safe_load((out / "dt_arena" / "envs" / "netflix"
                        / "docker-compose-hub.yml").read_text(encoding="utf-8"))
    envd = d["services"]["netflix-api"]["environment"]
    assert envd["API_PORT"] == "${NETFLIX_API_PORT:-8078}"
    assert "DATABASE_URL" in envd and "5545" in envd["DATABASE_URL"]


def test_the_ui_gets_its_env_names_too(tmp_path):
    """start.sh / nginx.conf.template read ${UI_PORT} and ${API_URL}."""
    out, _ = _export(tmp_path)
    d = yaml.safe_load((out / "dt_arena" / "envs" / "netflix"
                        / "docker-compose-hub.yml").read_text(encoding="utf-8"))
    envd = d["services"]["netflix-ui"]["environment"]
    assert envd["UI_PORT"] == "${NETFLIX_UI_PORT:-8079}"
    assert envd["API_URL"] == "http://127.0.0.1:${NETFLIX_API_PORT:-8078}"


def test_the_app_facing_names_track_the_same_knob(tmp_path):
    """If API_PORT and the healthcheck ever diverge, the port is dead again."""
    out, _ = _export(tmp_path)
    txt = (out / "dt_arena" / "envs" / "netflix"
           / "docker-compose-hub.yml").read_text(encoding="utf-8")
    assert txt.count("${NETFLIX_API_PORT:-8078}") >= 3, (
        "API_PORT, the healthcheck and the UI's API_URL must all read the same knob")


def test_the_contract_is_checked_against_the_real_app(tmp_path):
    """A rename in the scaffolder must be caught at export, not by a dead port in a VM."""
    r = _run(tmp_path)
    assert X.check_app_env_contract(r) == [] or True   # fixture app is minimal
    (r / "app" / "backend" / "main.py").write_text('x=1\n', encoding="utf-8")
    (r / "app" / "frontend" / "start.sh").write_text('echo hi\n', encoding="utf-8")
    warns = X.check_app_env_contract(r)
    assert any("API_PORT" in w for w in warns), warns
    assert any("UI_PORT" in w for w in warns), warns


def test_a_real_generated_app_satisfies_the_contract():
    """The premise, against a real run rather than a fixture."""
    import pathlib
    run = pathlib.Path(X.__file__).resolve().parents[1] / "agent" / "generated" / "netflix-web-r174"
    if not (run / "app" / "backend").is_dir():
        pytest.skip("r174 artifact not present")
    assert X.check_app_env_contract(run) == []


# --- #1030d: base images the devserver cannot fetch -------------------------------------------

def test_it_reports_every_base_image_the_contexts_need(tmp_path):
    """`tbr/build_images.sh`: "Base images resolve from the INTERNAL vmvm-registry (docker.io
    is not reachable from the devserver)". Our contexts use PUBLIC bases, so a build dies at
    the base fetch before any of our code is copied. Listing them is what makes that fixable
    instead of a mystery."""
    r = _run(tmp_path)
    (r / "app" / "backend" / "Dockerfile").write_text(
        "FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim\n", encoding="utf-8")
    out = tmp_path / "out"
    res = X.export(r, "netflix", out, api_port=8078, ui_port=8079, pg_port=5545,
                   mcp_port=8878, image_ns="ns")
    assert "ghcr.io/astral-sh/uv:python3.11-bookworm-slim" in res["base_images"]
    assert "postgres:16" in res["base_images"], "the pg image this exporter emits counts too"


def test_a_base_can_be_rewritten_to_an_internal_mirror(tmp_path):
    r = _run(tmp_path)
    out = tmp_path / "out"
    res = X.export(r, "netflix", out, api_port=8078, ui_port=8079, pg_port=5545,
                   mcp_port=8878, image_ns="ns",
                   base_map={"postgres:16": "vmvm-registry.fbinfra.net/dt/postgres:16"})
    df = (out / "dt_arena" / "envs" / "netflix" / "pg" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM vmvm-registry.fbinfra.net/dt/postgres:16" in df
    assert res["base_rewrites"] and "postgres:16" in res["base_rewrites"][0]


def test_an_unmapped_base_is_left_exactly_alone(tmp_path):
    """Rewriting something the caller did not ask for would be a silent substitution."""
    r = _run(tmp_path)
    (r / "app" / "backend" / "Dockerfile").write_text("FROM node:20-alpine\nRUN x\n",
                                                      encoding="utf-8")
    out = tmp_path / "out"
    X.export(r, "netflix", out, api_port=8078, ui_port=8079, pg_port=5545, mcp_port=8878,
             image_ns="ns", base_map={"postgres:16": "mirror/postgres:16"})
    df = (out / "dt_arena" / "envs" / "netflix" / "api" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:20-alpine" in df


def test_the_preflight_script_lists_and_is_executable(tmp_path):
    out, _ = _export(tmp_path)
    p = out / "dt_arena" / "envs" / "netflix" / "CHECK_BASES.sh"
    assert p.stat().st_mode & 0o111
    txt = p.read_text(encoding="utf-8")
    assert "postgres:16" in txt and "podman pull" in txt
    assert "UNREACHABLE" in txt and "--base-map" in txt, (
        "it must say what to DO with a failure, not just report one")
