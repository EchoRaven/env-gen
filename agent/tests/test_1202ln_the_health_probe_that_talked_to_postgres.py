"""#1202ln — `run_start`'s default base_url probed whatever service got port 8000.

GROUND TRUTH (tiktok-web-r121, 2026-09-12/13). The run's compose gave 8000 to the DATABASE:

    docker/docker-compose.yml:   PGPORT: 8000      ports: - "8000:8000"

and `run_start`'s schema default sent the pre-delivery healthcheck there:

    shared/hubs/runhub_runs.json:
      {"id": "run_607bbc1fb6", "status": "aborted", "started_by": "orchestrator",
       "healthcheck": {"url": "http://localhost:8000/health", "healthy": false,
                       "attempts": 31, "elapsed_s": 60.777,
                       "last_error": "Server disconnected without sending a response."},
       "probes": []}

"Server disconnected without sending a response" is Postgres closing an HTTP request it
cannot parse — not a dead backend. The run's real API was on 3001 and answering in the same
ledger (`GET http://localhost:3001/api/feed -> 200`). SEVEN of that run's 25 RunHub runs
aborted this way, all with the identical URL.

What it cost: at 23:58:55 the delivery gate went COMPLETELY CLEAR (`failed_checks: []`). At
00:00:52 this probe aborted, the orchestrator minted
`task_p0_backend_health_abort_after_noop_fix` from it, the gate re-opened, and the run hit its
wall-clock cap at 00:24 having delivered nothing — $270.47.

#207 fixed this exact shape for the visual gate and wrote the rule down in `_resolve_app_port`
("NEVER a magic fallback ... a fixed fallback made the visual gate screenshot the WRONG app").
The rule never reached this tool, whose own `generated_dir` docstring states the same
principle — "NOT something the model can know ... never let a model guess" — one field above.
"""
import asyncio
import inspect
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.tools import run_tools as rt


R121_COMPOSE = """\
services:
  database:
    image: postgres:16
    environment:
      PGPORT: 8000
    ports:
      - "8000:8000"
  backend:
    build: ../app/backend
    ports:
      - "3001:8000"
  frontend:
    build: ../app/frontend
    ports:
      - "8081:3000"
"""


def _env(tmp_path, compose_text=R121_COMPOSE):
    d = tmp_path / "docker"
    d.mkdir(parents=True)
    (d / "docker-compose.yml").write_text(compose_text, encoding="utf-8")
    return tmp_path


def test_r121s_own_shape_resolves_to_the_backend_not_the_database(tmp_path):
    """★ The exact compose that produced the aborted runs."""
    url = rt._resolved_base_url_1202ln(_env(tmp_path))
    assert url == "http://localhost:3001", url
    assert "8000" not in url, "resolved to the DATABASE's published port — the r121 defect"


def test_no_compose_file_resolves_to_nothing(tmp_path):
    assert rt._resolved_base_url_1202ln(tmp_path) is None
    assert rt._resolved_base_url_1202ln("") is None
    assert rt._resolved_base_url_1202ln(None) is None


def test_alternate_service_names_are_tried(tmp_path):
    compose = R121_COMPOSE.replace("  backend:", "  api:")
    assert rt._resolved_base_url_1202ln(_env(tmp_path, compose)) == "http://localhost:3001"


def test_a_backendless_compose_resolves_to_nothing_rather_than_a_guess(tmp_path):
    compose = """\
services:
  database:
    ports:
      - "8000:8000"
"""
    assert rt._resolved_base_url_1202ln(_env(tmp_path, compose)) is None, (
        "with no backend service the honest answer is None — never the database's port")


# ---------------------------------------------------------------- the tool

class _FakeRunHub:
    def __init__(self):
        self.calls = []

    def start_run(self, **kw):
        self.calls.append(kw)
        return {"id": "run_test", "status": "running", "base_url": kw.get("base_url")}


class _FakeHubs:
    def __init__(self, base_dir):
        self.base_dir = str(base_dir)
        self.runhub = _FakeRunHub()


def _tool(base_dir):
    t = object.__new__(rt.RunStartTool)
    t._hubs = _FakeHubs(base_dir)
    t._agent_id = "orchestrator"
    return t


def test_the_tool_uses_the_resolved_url_and_ignores_the_models_guess(tmp_path):
    t = _tool(_env(tmp_path))
    res = asyncio.run(t._run(branch="integration",
                             base_url="http://localhost:8000"))   # the r121 guess
    assert res.success
    assert t._hubs.runhub.calls[0]["base_url"] == "http://localhost:3001", (
        "a model-supplied port must never beat the run's own compose file")


def test_the_tool_resolves_when_the_model_says_nothing(tmp_path):
    t = _tool(_env(tmp_path))
    assert asyncio.run(t._run(branch="integration")).success
    assert t._hubs.runhub.calls[0]["base_url"] == "http://localhost:3001"


def test_an_unresolvable_port_refuses_instead_of_probing_a_stranger(tmp_path):
    """★ #207's 'skip honestly'. An aborted run mints a P0 and re-opens a clear gate."""
    t = _tool(tmp_path)                       # no docker/docker-compose.yml
    res = asyncio.run(t._run(branch="integration"))
    assert res.success is False
    assert "#1202ln" in (res.error_message or "")
    assert "DATABASE" in (res.error_message or ""), (
        "the refusal must say WHY a fixed port is unsafe, or the next reader re-adds one")
    assert not t._hubs.runhub.calls, "no run may be started against an unattributable port"


def test_an_explicit_non_default_url_still_works_when_nothing_resolves(tmp_path):
    """The escape hatch stays: only the magic constant and the empty case are refused."""
    t = _tool(tmp_path)
    res = asyncio.run(t._run(branch="integration", base_url="http://localhost:3001"))
    assert res.success
    assert t._hubs.runhub.calls[0]["base_url"] == "http://localhost:3001"


def test_the_schema_no_longer_advertises_a_port_to_guess():
    spec = rt.RunStartTool.PARAMETERS["properties"]["base_url"]
    assert "default" not in spec, (
        "a schema default IS the guess — the model fills it in without knowing the port")
    assert "1202ln" in spec["description"]
    assert "Auto-resolved" in spec["description"]


def test_the_resolver_reuses_the_guarded_lookup_rather_than_copying_it():
    """#665/#1136: the copy drifts, and #1136 was that drift. #962's stranger-container
    guard must come along, not be re-implemented."""
    src = inspect.getsource(rt._resolved_base_url_1202ln)
    assert "_service_host_port" in src
    assert "docker ps" not in src and "--filter" not in src, (
        "a second hand-rolled container lookup is exactly the drift #1136 was")
