"""GATE-C1 — 404/405-as-pass → FAIL on registered-implemented endpoints.

api_smoke's reachable gate (<500) counted a 404/405 from an endpoint whose
registration claims ``status=implemented`` as a PASS → the run recorded zero
failed probes → ``functionally_validated`` lit up → the coverage/seed/visual/
ui_flow delivery gates all degraded to warnings. That made 404-as-pass the
single trigger of the "why did an app with unimplemented endpoints release"
chain (review backlog #1).

The fix is a pure predicate (``_unimplemented_route``) calibrated on
generated/instagram round47 (768 contract-test records, the released app):

  * 3 endpoints 404'd on EVERY probe only because the probe substitutes dummy
    path params (user "1" doesn't exist). The exemption is therefore
    "path CONTAINS a param" — NOT "ends with a param": GET
    /api/users/{username}/posts ends in /posts and would be a false FAIL.
  * exactly one param-less 404: GET /app/backend/ls.py — a junk registration
    claiming implemented with no route. The true positive this gate catches.
  * 405 never appeared on the working app: the path matched but the METHOD
    isn't wired → a 405 is never exempt, params or not.

Endpoints NOT yet claiming implemented (defined/implementing/revising —
later-milestone work) keep the soft <500 rule, preserving the runner's
"later-milestone endpoints stay soft" contract.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.validation_runner import (  # noqa: E402
    _unimplemented_route, run_smoke_validation)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


# ── the pure predicate ─────────────────────────────────────────────────────────

def test_implemented_paramless_404_is_flagged():
    v = _unimplemented_route("GET", "/api/feed", "implemented", 404)
    assert v is not None and "/api/feed" in v and "404" in v


def test_junk_registration_round47_true_positive():
    # the one real param-less 404 in released round47 data
    assert _unimplemented_route("GET", "/app/backend/ls.py", "implemented", 404) is not None


def test_405_is_flagged_even_on_param_path():
    # 405 = the path matched, the METHOD isn't wired — never exempt
    v = _unimplemented_route("POST", "/api/posts/{id}/comments", "implemented", 405)
    assert v is not None and "405" in v


def test_param_path_404_is_exempt_round47_calibration():
    # probe substitutes dummy ids; the parent resource may legitimately not exist
    assert _unimplemented_route("GET", "/api/users/{username}", "implemented", 404) is None
    # mid-path param (ends in /posts) — the round47 case that forbids an
    # ends-with-param-only exemption
    assert _unimplemented_route("GET", "/api/users/{username}/posts", "implemented", 404) is None
    assert _unimplemented_route("GET", "/api/conversations/{id}/messages", "implemented", 404) is None
    assert _unimplemented_route("GET", "/api/posts/:id", "implemented", 404) is None


def test_not_yet_implemented_statuses_stay_soft():
    # defined/implementing: later-milestone endpoints; revising: claim suspended
    for st in ("defined", "implementing", "revising", None, ""):
        assert _unimplemented_route("GET", "/api/feed", st, 404) is None, st


def test_other_status_codes_are_other_gates_job():
    # 2xx/4xx-validation/5xx/transport are the reachable + shape gates' job
    for sc in (200, 201, 401, 403, 422, 500, None):
        assert _unimplemented_route("GET", "/api/feed", "implemented", sc) is None, sc


# ── threading: probe loop → endpoint_results.passed → summary check ───────────

def test_probe_loop_threads_passed_and_fails_the_smoke(monkeypatch, tmp_path):
    """End-to-end through run_smoke_validation (docker + HTTP faked): a
    registered-implemented endpoint answering 404 on a param-less path keeps
    reachable=True (transport semantics unchanged) but gets passed=False, fails
    the new business_endpoints_implemented check, and fails the whole smoke."""
    import multi_agent.runtime.validation_runner as vr
    import multi_agent.runtime.chain_executor as ce

    (tmp_path / "docker").mkdir(parents=True)
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n")
    src = tmp_path / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "App.jsx").write_text('<Route path="/" element={x} />')
    (src / "Feed.jsx").write_text("apiGet('/api/feed')")

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(vr, "_compose", lambda *a, **k: _Proc())
    monkeypatch.setattr(vr, "_backend_host_port", lambda *a, **k: 3001)
    monkeypatch.setattr(vr, "_service_host_port", lambda *a, **k: 3000)
    monkeypatch.setattr(ce, "run_chains",
                        lambda *a, **k: {"broken": [], "total_steps": 1, "chains": ["c"]})

    def _fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        if ":3000/" in url:
            return {"status": 200, "body_text": "<html>", "error": None}
        if url.endswith("/health"):
            return {"status": 200, "body_text": "", "error": None}
        if "/auth/register" in url:
            return {"status": 201, "body_text": '{"access_token":"tok"}', "error": None}
        if token is None:
            return {"status": 401, "body_text": "", "error": None}
        if "/app/backend/ls.py" in url:
            return {"status": 404, "body_text": '{"detail":"Not Found"}', "error": None}
        return {"status": 200, "body_text": '{"items": []}', "error": None}

    monkeypatch.setattr(vr, "_http", _fake_http)

    eps = [
        {"id": "GET /api/feed", "method": "GET", "path": "/api/feed",
         "status": "implemented"},
        {"id": "GET /app/backend/ls.py", "method": "GET",
         "path": "/app/backend/ls.py", "status": "implemented"},
    ]
    report = run_smoke_validation(tmp_path, eps, teardown=False)

    by_id = {e["id"]: e for e in report["endpoints"]}
    assert by_id["GET /api/feed"]["passed"] is True
    junk = by_id["GET /app/backend/ls.py"]
    assert junk["reachable"] is True   # transport semantics (<500) unchanged
    assert junk["passed"] is False     # the verdict the probes/records consume

    checks = {c["name"]: c for c in report["checks"]}
    assert checks["business_endpoints_reachable"]["status"] == "pass"
    assert checks["business_endpoints_implemented"]["status"] == "fail"
    assert "/app/backend/ls.py" in checks["business_endpoints_implemented"]["detail"]
    assert report["passed"] is False


# ── threading: endpoint_results.passed → contract tests + RunHub probes ────────

def _chains_base():
    import json as _json
    import tempfile
    base = tempfile.mkdtemp(prefix="urg_")
    d = Path(base) / "shared" / "hubs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "registryhub_verification_chains.json").write_text(_json.dumps({
        "t": {"name": "t", "steps": [
            {"method": "GET", "path": "/api/x", "expect": [200]}]}}))
    return base


def test_contract_test_verdict_reads_passed_not_reachable(monkeypatch):
    """The per-endpoint evidence record must carry the GATE verdict (passed),
    not the transport fact (reachable) — else the delivery gate's audit trail
    still says pass on an unimplemented route."""
    import tools.validation_tools as vt

    def _fake_runner(project_dir, biz, **kw):
        return {"passed": False, "summary": "FAILED: business_endpoints_implemented",
                "checks": [{"name": "business_endpoints_implemented",
                            "status": "fail", "detail": "GET /app/backend/ls.py → 404"}],
                "backend_port": 3001,
                "endpoints": [
                    {"id": "GET /api/feed", "method": "GET", "path": "/api/feed",
                     "status_code": 200, "reachable": True, "passed": True,
                     "error": None, "trace": "GET .. -> 200"},
                    {"id": "GET /app/backend/ls.py", "method": "GET",
                     "path": "/app/backend/ls.py", "status_code": 404,
                     "reachable": True, "passed": False,
                     "error": None, "trace": "GET .. -> 404"},
                ]}

    monkeypatch.setattr(vt, "_import_runner", lambda: _fake_runner)
    recorded = []

    class _Api:
        def get_endpoints(self):
            return {"GET /api/feed": {"method": "GET", "path": "/api/feed",
                                      "kind": None, "status": "implemented"}}

        def record_api_test(self, endpoint_id, result, evidence=None, agent=""):
            recorded.append((endpoint_id, result["passed"]))
            return {"id": endpoint_id}

    hubs = types.SimpleNamespace(base_dir=_chains_base(), registryhub=_Api())
    t = vt.RunValidationTool(workspace=None)
    t.set_agent(types.SimpleNamespace(agent_id="orchestrator", _hubs=hubs))
    _run(t.execute())
    assert ("GET /api/feed", True) in recorded
    assert ("GET /app/backend/ls.py", False) in recorded


def test_runhub_fail_count_counts_passed_false_rows():
    """Belt + suspenders: even if a run IS recorded, a passed=False row counts
    as a failed probe — so deliverability's functionally_validated stays dark."""
    from tools.validation_tools import RunValidationTool

    probes = []
    statuses = []

    class _RunHub:
        def record_run(self, branch, generated_dir, agent=""):
            return {"id": "run_x"}

        def record_probe(self, run_id, probe, agent=""):
            probes.append(probe["verdict"])
            return {}

        def update_run_status(self, run_id, status, agent="", **fields):
            statuses.append((status, fields.get("fail_count")))
            return {}

    hubs = types.SimpleNamespace(base_dir="generated/x", runhub=_RunHub())
    t = RunValidationTool(workspace=None)
    t._hubs = hubs
    report = {"passed": True, "endpoints": [
        {"id": "a", "method": "GET", "path": "/api/a", "status_code": 200,
         "reachable": True, "passed": True, "error": None, "trace": ""},
        {"id": "b", "method": "GET", "path": "/app/backend/ls.py",
         "status_code": 404, "reachable": True, "passed": False,
         "error": None, "trace": ""},
    ]}
    run_id = t._record_runhub_run(report, "/tmp/x")
    assert run_id == "run_x"
    assert probes == ["pass", "fail"]
    assert statuses == [("completed", 1)]  # fail_count=1 → gate-rejecting run


# ── feedback loop: failed check → backend P0 task, once per milestone ──────────

class _FakeWorkHub:
    def __init__(self):
        self.tasks = []

    def create_task(self, **kw):
        self.tasks.append(kw)
        return {"id": f"task_{len(self.tasks)}"}


class _FakeBus:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


def _dispatch():
    from multi_agent.orchestrator import Orchestrator
    return Orchestrator._dispatch_unimplemented_routes


def _stub(milestone="1.0.0"):
    return types.SimpleNamespace(
        hubs=types.SimpleNamespace(workhub=_FakeWorkHub()),
        message_bus=_FakeBus(),
        _logger=logging.getLogger("test_unimpl_dispatch"),
        _current_milestone_version=milestone,
    )


def _fail_data():
    return {"checks": [{"name": "business_endpoints_implemented", "status": "fail",
                        "detail": "GET /app/backend/ls.py → 404 but registered implemented"}]}


def test_dispatches_backend_p0_once_per_milestone():
    """A hard gate with no exit deadlocks (verifier has no bug_create — TOOL-C1):
    the failure must route to the lane that can fix it. Mirrors the
    business_chain #53 dispatch: one P0 task + wake per milestone."""
    stub = _stub("1.0.0")
    _run(_dispatch()(stub, _fail_data()))
    assert len(stub.hubs.workhub.tasks) == 1
    task = stub.hubs.workhub.tasks[0]
    assert task["assignee"] == "backend"
    assert task["priority"] == "P0"
    assert "/app/backend/ls.py" in task["description"]
    # actionable both ways: implement the route OR deprecate a junk registration
    assert "registryhub_deprecate_endpoint" in task["description"]
    assert len(stub.message_bus.sent) >= 1  # urgent wake, not just a queued task

    # same milestone again (validation retries every tick) → no duplicate spam
    _run(_dispatch()(stub, _fail_data()))
    assert len(stub.hubs.workhub.tasks) == 1

    # next milestone → a fresh dispatch is allowed
    stub._current_milestone_version = "2.0.0"
    _run(_dispatch()(stub, _fail_data()))
    assert len(stub.hubs.workhub.tasks) == 2


def test_no_dispatch_when_check_passes():
    stub = _stub()
    _run(_dispatch()(stub, {"checks": [
        {"name": "business_endpoints_implemented", "status": "pass", "detail": ""}]}))
    _run(_dispatch()(stub, {"checks": []}))
    _run(_dispatch()(stub, None))
    assert stub.hubs.workhub.tasks == []
    assert stub.message_bus.sent == []
