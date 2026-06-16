"""run_validation tool (§6 framework-driven api_smoke) — unit coverage.

The tool is the verifier's SINGLE deterministic validation action: it resolves the
business contract from the LIVE RegistryHub (wired via set_agent), runs the deterministic
api_smoke runner once, and returns a structured verdict. These tests pin:

  * it ships in the verification bundle (so the verifier actually gets it),
  * set_agent binds the live hub registry,
  * the business filter excludes infra/auth/oauth/spine endpoints (kind-routed, not
    path-listed),
  * an empty contract yields a not_ready failure (defer, don't false-pass),
  * a runner PASS / FAIL flows through as structured data (a FAIL is a verdict, not
    a tool error).
"""

import asyncio
import os
import sys
import types

LLM = os.path.join(os.path.dirname(__file__), "..", "env_generator", "llm_generator")
sys.path.insert(0, os.path.abspath(LLM))


def _run(coro):
    return asyncio.run(coro)

from tools.validation_tools import RunValidationTool, create_validation_tools  # noqa: E402
from tools.verification_tools import create_verification_tools  # noqa: E402


def _chains_base():
    """tmp project dir satisfying run_validation's chains precondition."""
    import tempfile, json as _json
    from pathlib import Path as _P
    base = tempfile.mkdtemp(prefix="rvtc_")
    d = _P(base) / "shared" / "hubs"; d.mkdir(parents=True, exist_ok=True)
    (d / "registryhub_verification_chains.json").write_text(_json.dumps({
        "t": {"name": "t", "steps": [
            {"method": "GET", "path": "/api/x", "expect": [200]}]}}))
    return base


def _fake_agent(endpoints, base_dir="generated/x", chains=True):
    class _Api:
        def get_endpoints(self):
            return endpoints

    # run_validation is tool-blocked until verification chains exist (round 35
    # behavioral fix) — tests provide the precondition in a real tmp dir.
    if chains:
        import tempfile, json as _json
        from pathlib import Path
        base_dir = tempfile.mkdtemp(prefix="rvt_")
        d = Path(base_dir) / "shared" / "hubs"; d.mkdir(parents=True, exist_ok=True)
        (d / "registryhub_verification_chains.json").write_text(_json.dumps({
            "t": {"name": "t", "steps": [
                {"method": "GET", "path": "/api/x", "expect": [200]}]}}))
    hubs = types.SimpleNamespace(base_dir=base_dir, registryhub=_Api())
    return types.SimpleNamespace(agent_id="verifier", _hubs=hubs)


def test_ships_in_verification_bundle():
    names = [getattr(t, "NAME", None) for t in create_verification_tools(workspace=None)]
    assert "run_validation" in names


def test_run_validation_is_force_offered_in_validation_stages():
    """Regression: the per-round ranker only offers ~10 of ~150 tools. Unless
    run_validation is in the always-include _VALIDATION_FLOW set, the ranker
    crowds it out and the verifier never sees it (the smoke-2026-06-06 stall:
    256 workhub_list_tasks loops, 0 run_validation calls, verifier reported
    'I don't have the tooling'). Pin it to run_checks/deliver/action always-include."""
    from multi_agent.agents.base import EnvGenAgent  # noqa: E402

    assert "run_validation" in EnvGenAgent._VALIDATION_FLOW
    for stage in ("run_checks", "deliver", "action"):
        assert "run_validation" in EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE[stage], stage


def test_factory_returns_tool():
    tools = create_validation_tools(workspace=None)
    assert any(getattr(t, "NAME", None) == "run_validation" for t in tools)


def test_set_agent_binds_live_hub_and_project_dir():
    t = RunValidationTool(workspace=None)
    assert t._project_dir() is None  # no hub, no workspace
    t.set_agent(_fake_agent({}, base_dir="generated/notes", chains=False))
    assert str(t._project_dir()) == "generated/notes"


def test_business_filter_is_kind_routed_not_path_listed():
    eps = {
        "biz1": {"method": "GET", "path": "/api/notes", "kind": None, "state": "implemented"},
        "biz2": {"method": "POST", "path": "/api/notes", "kind": "business", "state": "implemented"},
        "health": {"method": "GET", "path": "/health", "kind": "infra", "state": "implemented"},
        "login": {"method": "POST", "path": "/auth/login", "kind": "auth", "state": "implemented"},
        "jwks": {"method": "GET", "path": "/.well-known/jwks.json", "kind": "oauth", "state": "implemented"},
    }
    t = RunValidationTool(workspace=None)
    t.set_agent(_fake_agent(eps))
    biz = t._business_endpoints(t._project_dir())
    paths = sorted({e["path"] for e in biz})
    assert paths == ["/api/notes"]  # both /api/notes rows, no infra/auth/oauth


def test_empty_contract_is_not_ready():
    t = RunValidationTool(workspace=None)
    t.set_agent(_fake_agent({}))  # no endpoints registered yet
    res = _run(t.execute())
    assert res.success is False
    # not_ready metadata signals "defer + retry", not a hard error
    assert getattr(res, "metadata", {}).get("not_ready") is True or "not ready" in (res.error or "").lower()


def test_runner_pass_flows_through(monkeypatch):
    import tools.validation_tools as vt

    def _fake_runner(project_dir, biz, **kw):
        return {"passed": True, "summary": "all api_smoke checks passed",
                "checks": [{"name": "docker_up", "status": "pass", "detail": ""}],
                "backend_port": 3001}

    monkeypatch.setattr(vt, "_import_runner", lambda: _fake_runner)
    t = RunValidationTool(workspace=None)
    t.set_agent(_fake_agent({"b": {"method": "GET", "path": "/api/x", "kind": None, "state": "implemented"}}))
    res = _run(t.execute())
    assert res.success is True
    assert res.data["passed"] is True
    assert "verdict" not in res.data  # PASS has no fail-verdict marker
    assert res.data["endpoints_tested"] == 1


def test_records_one_contract_test_per_endpoint(monkeypatch):
    """The api_smoke evidence the delivery gate audits is a framework
    CONSEQUENCE of the one call — not a hand-driven per-endpoint loop."""
    import tools.validation_tools as vt

    def _fake_runner(project_dir, biz, **kw):
        return {"passed": True, "summary": "ok", "checks": [], "backend_port": 3001,
                "endpoints": [
                    {"id": "GET:/api/x", "method": "GET", "path": "/api/x",
                     "status_code": 200, "reachable": True, "error": None, "trace": "GET .. -> 200"},
                    {"id": "POST:/api/x", "method": "POST", "path": "/api/x",
                     "status_code": 503, "reachable": False, "error": None, "trace": "POST .. -> 503"},
                ]}

    monkeypatch.setattr(vt, "_import_runner", lambda: _fake_runner)

    recorded = []

    class _Api:
        def get_endpoints(self):
            return {"GET:/api/x": {"method": "GET", "path": "/api/x", "kind": None, "state": "implemented"}}

        def record_api_test(self, endpoint_id, result, evidence=None, agent="verifier"):
            recorded.append((endpoint_id, result["passed"], agent))
            return {"id": endpoint_id}

    hubs = types.SimpleNamespace(base_dir=_chains_base(), registryhub=_Api())
    agent = types.SimpleNamespace(agent_id="verifier", _hubs=hubs)
    t = vt.RunValidationTool(workspace=None)
    t.set_agent(agent)
    res = _run(t.execute())
    assert res.data["contract_tests_recorded"] == 2
    # Recorded with FRAMEWORK authority (agent="") — the role-gate's system
    # fallthrough — so the evidence lands whether the verifier or orchestrator
    # invoked the deterministic procedure.
    assert ("GET:/api/x", True, "") in recorded
    assert ("POST:/api/x", False, "") in recorded


def test_records_runhub_run_for_delivery_gate(monkeypatch):
    """run_validation records a RunHub run (record_run + per-endpoint probes +
    completed/fail_count) — the canonical evidence compute_deliverability audits
    (blocker #1). This is what lets a healthy app reach delivery when the
    verifier LLM won't validate."""
    import tools.validation_tools as vt

    def _fake_runner(project_dir, biz, **kw):
        return {"passed": True, "summary": "ok", "checks": [], "backend_port": 3001,
                "endpoints": [
                    {"id": "GET:/api/x", "method": "GET", "path": "/api/x",
                     "status_code": 200, "reachable": True, "error": None, "trace": "GET .. -> 200"},
                    {"id": "POST:/api/x", "method": "POST", "path": "/api/x",
                     "status_code": 201, "reachable": True, "error": None, "trace": "POST .. -> 201"},
                ]}

    monkeypatch.setattr(vt, "_import_runner", lambda: _fake_runner)

    runs = {}
    probes = []
    statuses = []

    class _RunHub:
        def record_run(self, branch, generated_dir, agent=""):
            runs["run"] = {"id": "run_abc", "branch": branch, "agent": agent}
            return runs["run"]

        def record_probe(self, run_id, probe, agent=""):
            probes.append((run_id, probe["verdict"], agent))
            return {}

        def update_run_status(self, run_id, status, agent="", **fields):
            statuses.append((run_id, status, fields.get("fail_count"), agent))
            return {}

    class _Api:
        def get_endpoints(self):
            return {"GET:/api/x": {"method": "GET", "path": "/api/x", "kind": None, "state": "implemented"}}

        def record_api_test(self, *a, **k):
            return {}

    hubs = types.SimpleNamespace(base_dir=_chains_base(), registryhub=_Api(), runhub=_RunHub())
    t = vt.RunValidationTool(workspace=None)
    t.set_agent(types.SimpleNamespace(agent_id="orchestrator", _hubs=hubs))  # orchestrator, NOT verifier
    res = _run(t.execute())

    assert res.data["runhub_run_id"] == "run_abc"
    assert len(probes) == 2 and all(v == "pass" for _, v, _ in probes)
    assert all(agent == "" for _, _, agent in probes)  # framework authority
    assert statuses == [("run_abc", "completed", 0, "")]  # fail_count=0 → gate-passing run


def test_runhub_run_not_recorded_when_validation_failed(monkeypatch):
    import tools.validation_tools as vt

    def _fake_runner(project_dir, biz, **kw):
        return {"passed": False, "summary": "FAILED: backend_health", "checks": [],
                "backend_port": 3001, "endpoints": []}

    monkeypatch.setattr(vt, "_import_runner", lambda: _fake_runner)
    called = {"record_run": 0}

    class _RunHub:
        def record_run(self, *a, **k):
            called["record_run"] += 1
            return {"id": "x"}

    class _Api:
        def get_endpoints(self):
            return {"b": {"method": "GET", "path": "/api/x", "kind": None, "state": "implemented"}}

        def record_api_test(self, *a, **k):
            return {}

    hubs = types.SimpleNamespace(base_dir=_chains_base(), registryhub=_Api(), runhub=_RunHub())
    t = vt.RunValidationTool(workspace=None)
    t.set_agent(types.SimpleNamespace(agent_id="orchestrator", _hubs=hubs))
    res = _run(t.execute())
    assert res.data["runhub_run_id"] is None
    assert called["record_run"] == 0  # no completed run recorded on a failed validation


def test_runner_fail_is_a_verdict_not_an_error(monkeypatch):
    import tools.validation_tools as vt

    def _fake_runner(project_dir, biz, **kw):
        return {"passed": False, "summary": "FAILED: backend_health",
                "checks": [{"name": "backend_health", "status": "fail", "detail": "boom"}],
                "backend_port": 3001}

    monkeypatch.setattr(vt, "_import_runner", lambda: _fake_runner)
    t = RunValidationTool(workspace=None)
    t.set_agent(_fake_agent({"b": {"method": "GET", "path": "/api/x", "kind": None, "state": "implemented"}}))
    res = _run(t.execute())
    # A real FAIL is surfaced as ok-data with verdict=fail so the verifier records
    # + routes it, rather than as a tool error that reads like the tool broke.
    assert res.success is True
    assert res.data["passed"] is False
    assert res.data["verdict"] == "fail"
