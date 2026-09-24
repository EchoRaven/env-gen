"""deliver_project must re-check the LIVE gate on the final milestone (2026-07-01).

Live-reproduced (run-18 delivered M1 then died at M4; run-20 delivered M1+M2+M3 then died at M4,
BOTH via "[main-exit] shutdown watchdog fired"): on the FINAL milestone deliver_project sets the
delivered event + EXITS the coordination loop based ONLY on the LLM's self-asserted checklist. A
premature call (milestone not yet converged) then FAILS the orchestrator's post-loop hard gate ->
RuntimeError -> watchdog kills the run. Fix: GUARD 2 now re-verifies the LIVE hubs (every endpoint
'implemented' + business_chain green) and REJECTS a premature deliver so the run keeps converging.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.agent_interaction_tools import DeliverProjectTool  # noqa: E402

CHECKLIST = {"no_bugs": True, "requirements_met": True, "fully_functional": True, "docker_ok": True}


class _Event:
    def __init__(self):
        self.set_called = False

    def set(self):
        self.set_called = True


class _Agent:
    def __init__(self, hubs):
        self._hubs = hubs
        self._is_final_milestone = True
        self._milestone_progress = (4, 4)
        self._project_delivered = False
        self._project_delivered_event = _Event()


def _tool(hubs):
    return DeliverProjectTool(agent=_Agent(hubs))


def _impl_endpoints(rh, *specs):
    for m, p in specs:
        rh.register_endpoint(m, p, agent="backend", status="implemented")


def test_premature_deliver_blocked_when_business_chain_not_green(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_DELIVER_GATE", "1")
    hr = HubRegistry(tmp_path)
    _impl_endpoints(hr.registryhub, ("POST", "/auth/register"), ("POST", "/api/messages"),
                    ("GET", "/api/messages"))
    # every endpoint implemented BUT no verifier chain → business_chain_missing → premature
    tool = _tool(hr)
    res = tool.execute(confirmation="CONFIRMED", delivery_summary="done", checklist=CHECKLIST)
    assert res.success is False
    assert "business_chain" in (res.error_message or "").lower()
    assert tool.agent._project_delivered_event.set_called is False   # loop NOT exited
    assert tool.agent._project_delivered is False


def test_premature_deliver_blocked_when_endpoints_unimplemented(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_DELIVER_GATE", "1")
    hr = HubRegistry(tmp_path)
    hr.registryhub.register_endpoint("POST", "/api/messages", agent="backend", status="defined")
    res = _tool(hr).execute(confirmation="CONFIRMED", delivery_summary="d", checklist=CHECKLIST)
    assert res.success is False
    assert "implemented" in (res.error_message or "").lower()


class _NoBlockers:
    blockers = []


class _UnwiredBlocker:
    # the exact run-31/32 killer: a registered ui_page not wired in App.jsx
    blockers = ["ui_page 'outlook_read_email' declared but unusable: route not wired in App.jsx"]


def test_ready_deliver_succeeds_and_signals(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_DELIVER_GATE", "1")
    # GUARD 2b sweeps the full deliverability aggregator; a bare test workspace has no
    # RunHub run / app tree, so stub it green — the aggregator has its own tests.
    from multi_agent.runtime import deliverability as _dl
    monkeypatch.setattr(_dl, "compute_deliverability", lambda *a, **k: _NoBlockers())
    hr = HubRegistry(tmp_path)
    rh = hr.registryhub
    _impl_endpoints(rh, ("POST", "/auth/register"), ("POST", "/api/messages"),
                    ("GET", "/api/messages"))
    rh.register_verification_chain("flow", steps=[
        {"method": "POST", "path": "/api/messages", "expect": [201]},
        {"method": "GET", "path": "/api/messages", "expect": [200]}], agent="verifier")
    rh.record_chain_result("flow", {"broken": []}, agent="verifier")   # -> passing + full coverage
    tool = _tool(hr)
    res = tool.execute(confirmation="CONFIRMED", delivery_summary="done", checklist=CHECKLIST)
    assert res.success is True, res.error_message
    assert tool.agent._project_delivered_event.set_called is True     # loop exits -> post-loop cuts release
    assert tool.agent._project_delivered is True


def test_env_disabled_restores_old_behaviour(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_DELIVER_GATE", "0")
    hr = HubRegistry(tmp_path)
    hr.registryhub.register_endpoint("POST", "/api/messages", agent="backend", status="defined")
    res = _tool(hr).execute(confirmation="CONFIRMED", delivery_summary="d", checklist=CHECKLIST)
    assert res.success is True                                        # guard off → self-asserted deliver


def test_checklist_still_enforced(tmp_path):
    # the pre-existing self-asserted checklist guard is unchanged
    hr = HubRegistry(tmp_path)
    res = _tool(hr).execute(confirmation="CONFIRMED", delivery_summary="d",
                            checklist={"no_bugs": True})   # missing required checks
    assert res.success is False
    assert "failed checks" in (res.error_message or "").lower()


def test_deliver_blocked_on_unwired_ui_page(tmp_path, monkeypatch):
    """GUARD 2b (#39, runs 31+32): endpoints implemented + chains green but a ui_page is
    unwired → deliver_project must be REJECTED (the post-loop gate would kill the run)."""
    monkeypatch.setenv("ENVGEN_DELIVER_GATE", "1")
    from multi_agent.runtime import deliverability as _dl
    monkeypatch.setattr(_dl, "compute_deliverability", lambda *a, **k: _UnwiredBlocker())
    hr = HubRegistry(tmp_path)
    rh = hr.registryhub
    _impl_endpoints(rh, ("POST", "/auth/register"), ("POST", "/api/messages"),
                    ("GET", "/api/messages"))
    rh.register_verification_chain("flow", steps=[
        {"method": "POST", "path": "/api/messages", "expect": [201]},
        {"method": "GET", "path": "/api/messages", "expect": [200]}], agent="verifier")
    rh.record_chain_result("flow", {"broken": []}, agent="verifier")
    tool = _tool(hr)
    res = tool.execute(confirmation="CONFIRMED", delivery_summary="done", checklist=CHECKLIST)
    assert res.success is False
    assert "declared but unusable" in (res.error_message or "")
    assert tool.agent._project_delivered is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
