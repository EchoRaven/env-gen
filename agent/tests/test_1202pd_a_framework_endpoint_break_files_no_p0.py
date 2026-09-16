"""#1202pd: a re-declared FRAMEWORK-OWNED endpoint does not dispatch a breaking-change P0.

The framework registers and serves /auth, /oauth, /.well-known, /health and the control surface.
A lane or kickoff re-declaring one changes nothing that is served, yet a dropped field minted an
URGENT message and a P0 "Fix breaking change in <endpoint>" at every consumer lane: 392 of 3,442
such tasks (11%) across 54 runs named a framework-owned endpoint, 253 of them /auth/*. A business
endpoint's breaking change is dispatched exactly as before.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _tasks_after_break(tmp_path, method, path):
    hr = HubRegistry(tmp_path)
    rh = hr.registryhub
    rh.register_endpoint(method, path, agent="backend", status="implemented",
                         schema={"response": {"id": "int", "username": "str", "avatar_url": "str"}})
    rh.register_consumer(method + " " + path, "app/frontend/src/services/api.js",
                         agent="frontend")
    rh.register_endpoint(method, path, agent="backend", status="implemented",
                         schema={"response": {"id": "int"}})         # drops two fields
    tasks = [t for t in (hr.workhub.list_tasks() or [])
             if str(t.get("title", "")).startswith("Fix breaking change")]
    return rh, tasks


def test_r124_auth_me_redeclared_files_no_p0(tmp_path):
    rh, tasks = _tasks_after_break(tmp_path, "GET", "/auth/me")
    assert tasks == [], tasks


def test_a_business_endpoint_still_files_one(tmp_path):
    rh, tasks = _tasks_after_break(tmp_path, "GET", "/api/videos")
    assert len(tasks) == 1 and tasks[0]["assignee"] == "frontend", tasks
