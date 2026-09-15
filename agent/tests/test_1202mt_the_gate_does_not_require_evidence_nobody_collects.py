"""#1202mt: `incomplete_required_tasks` must not require contract tests for unprobed surfaces.

A pending `validate_api_smoke` task blocks delivery until the endpoint has a passing contract-test
record. Those records come from `run_validation`, which probes `lifecycle.business_endpoints` —
and that excludes every /auth/, /oauth/, /api/auth/ path and the control surface as
framework-owned. RunHub's own probe skips implemented endpoints and posts `{}` to defined ones.
So a task for `POST /auth/signup` could only close by a lane marking it done by hand.

tiktok-r124's last resume aborted on `incomplete_required_tasks` with three tasks: both signup
routes (400 "email and password are required" to an empty body) and `PATCH /api/me/profile`,
which run_validation cleared 44 seconds before the abort. Across the run logs, 391 of the 442
`incomplete_required_tasks` blocker lines, in 14 runs, name an auth or oauth task.

Replayed on the final hub state of 141 runs: the exemption drops blockers in 6 runs, every one
an auth task (`_auth_register` 4, `_auth_login` 4, `_api_auth_signup` 2, `_auth_signup` 1), and
adds a blocker in none.
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.delivery_gate import incomplete_required_tasks  # noqa: E402


def _task(method, path, status="in_progress"):
    tid = f"validate.api_smoke.{method.lower()}.{path}".replace("/", "_").replace("__", "_")
    return {"id": tid, "status": status, "assignee": "verifier",
            "metadata": {"kind": "validate_api_smoke",
                         "endpoint": {"method": method, "path": path}}}


def _ep(method, path, kind=None, status="implemented"):
    rec = {"id": f"{method} {path}", "method": method, "path": path, "status": status}
    if kind:
        rec["kind"] = kind
    return rec


def _hubs(endpoints, tasks, passing=()):
    eps = {e["id"]: e for e in endpoints}
    return NS(
        workhub=NS(list_tasks=lambda: list(tasks)),
        registryhub=NS(
            get_endpoints=lambda: eps,
            get_contract_test_results=lambda e: (
                [{"endpoint_id": e, "result": {"passed": True}}] if e in passing else [])),
        schema_hub=NS(list_tables=lambda: {}))


def _ids(hubs):
    return sorted(t["id"] for t in incomplete_required_tasks(hubs))


# r124's final state, reduced to the three tasks it aborted on
R124_ENDPOINTS = [_ep("POST", "/auth/signup"), _ep("POST", "/api/auth/signup"),
                  _ep("PATCH", "/api/me/profile")]
R124_TASKS = [_task("POST", "/auth/signup"), _task("POST", "/api/auth/signup"),
              _task("PATCH", "/api/me/profile")]


def test_r124s_signup_tasks_no_longer_block():
    hubs = _hubs(R124_ENDPOINTS, R124_TASKS, passing={"PATCH /api/me/profile"})
    assert _ids(hubs) == []


def test_a_business_endpoint_without_a_passing_record_still_blocks():
    hubs = _hubs(R124_ENDPOINTS, R124_TASKS)   # nothing passed yet
    assert _ids(hubs) == ["validate.api_smoke.patch._api_me_profile"]


def test_every_framework_owned_prefix_and_kind_is_exempt():
    eps = [_ep("POST", "/oauth/token"), _ep("GET", "/oauth/authorize"),
           _ep("POST", "/api/oauth/register"), _ep("POST", "/auth/login", kind="auth")]
    tasks = [_task(e["method"], e["path"]) for e in eps]
    assert _ids(_hubs(eps, tasks)) == []


def test_a_path_that_merely_contains_auth_is_still_business():
    eps = [_ep("POST", "/api/authors"), _ep("GET", "/api/videos/{id}/authorized-viewers")]
    tasks = [_task(e["method"], e["path"]) for e in eps]
    assert len(_ids(_hubs(eps, tasks))) == 2


def test_an_unregistered_auth_task_is_not_silently_exempted():
    """The exemption reads the REGISTRY record; a task whose endpoint was never registered
    has no record to classify and keeps its old verdict."""
    tasks = [_task("POST", "/auth/signup")]
    assert _ids(_hubs([], tasks)) == ["validate.api_smoke.post._auth_signup"]


def test_implement_endpoint_tasks_are_unaffected():
    eps = [_ep("POST", "/auth/signup", status="defined")]
    tasks = [{"id": "impl.endpoint.post._auth_signup", "status": "pending", "assignee": "backend",
              "metadata": {"kind": "implement_endpoint",
                           "endpoint": {"method": "POST", "path": "/auth/signup"}}}]
    assert _ids(_hubs(eps, tasks)) == ["impl.endpoint.post._auth_signup"]
