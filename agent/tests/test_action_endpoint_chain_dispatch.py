"""FIX #148 (run-72 M4 STUCK root, 1st occurrence recorded → pre-authorized fix):
a contract-REGISTERED action endpoint (POST /api/users/{id}/unfollow) the lane never
implemented answers the projection's deliberate 404 stub (route_projector FIX #124:
"action endpoint not implemented by the projection — the app's own handler serves
this route") — business_chain_failing then routed to the VERIFIER, which cannot add
a backend route, so the run spun 7 post-cap cycles to STUCK-abort. Mirror FIX #143
content routing: when the failing chains' broken steps carry the #124 stub
signature, dispatch the P0 to the BACKEND with the exact endpoint list.
LOCAL-ONLY (gitignored)."""
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

from multi_agent.runtime.remediation_dispatcher import RemediationDispatcher  # noqa: E402

_RUN72_BROKEN = (
    'POST /api/users/5/unfollow → 404 ({"detail":"action endpoint not implemented '
    'by the projection — the app\'s own handler serves this route"})')


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


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


class _FakeRegistryHub:
    def __init__(self, chains):
        self._chains = chains

    def get_verification_chains(self):
        return self._chains


def _stub(milestone="1.2.0", chains=None):
    hubs = types.SimpleNamespace(workhub=_FakeWorkHub())
    if chains is not None:
        hubs.registryhub = _FakeRegistryHub(chains)
    return types.SimpleNamespace(
        hubs=hubs,
        message_bus=_FakeBus(),
        _logger=logging.getLogger("test_action_endpoint_chain_dispatch"),
        _current_milestone_version=milestone,
    )


def _chains_with_broken(broken):
    return {
        "_meta": {"version": 3},
        "core_flows": {"name": "core_flows", "kind": "flow", "status": "failing",
                       "steps": [{"method": "POST", "path": "/api/users/5/unfollow"}],
                       "last_result": {"broken": list(broken), "steps": []}},
    }


def test_action_unimplemented_broken_matches_projection_stub():
    from multi_agent.runtime.remediation_dispatcher import action_unimplemented_broken
    got = action_unimplemented_broken([
        _RUN72_BROKEN,
        "POST /api/posts → 500 (Internal Server Error)",
        'GET /api/users/5 → 404 ({"detail":"User not found"})',
    ])
    assert got == [_RUN72_BROKEN], (
        "only the #124 projection-stub 404 counts — a custom 404 / 500 is a "
        "verifier-route chain failure, not a missing action route")
    assert action_unimplemented_broken([]) == []
    assert action_unimplemented_broken(None) == []


def test_business_chain_failing_action404_routes_to_backend():
    orch = _stub(chains=_chains_with_broken([_RUN72_BROKEN]))
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["business_chain_failing"]))
    assert len(orch.hubs.workhub.tasks) == 1
    t = orch.hubs.workhub.tasks[0]
    assert t["assignee"] == "backend" and t["priority"] == "P0", (
        "the #124 stub 404 means a registered action route only the BACKEND can "
        "implement — the verifier has no route-write channel (run-72 M4 STUCK)")
    assert "POST /api/users/5/unfollow" in t["description"], (
        "the P0 must carry the exact unimplemented endpoint(s)")
    assert orch.message_bus.sent
    assert orch.message_bus.sent[0].header.target_agent_id == "backend"


def test_business_chain_failing_without_action404_keeps_verifier():
    orch = _stub(chains=_chains_with_broken(
        ["POST /api/posts → 500 (Internal Server Error)"]))
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["business_chain_failing"]))
    assert len(orch.hubs.workhub.tasks) == 1
    t = orch.hubs.workhub.tasks[0]
    assert t["assignee"] == "verifier", (
        "an ordinary chain failure keeps the verifier diagnose-first route")
    msg = orch.message_bus.sent[0]
    assert msg.metadata.get("validation_phase") is True, (
        "the verifier wake still needs validation_phase=True (V29)")


def test_business_chain_failing_no_registryhub_keeps_verifier():
    orch = _stub(chains=None)  # hubs WITHOUT a registryhub — must not raise
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["business_chain_failing"]))
    assert len(orch.hubs.workhub.tasks) == 1
    assert orch.hubs.workhub.tasks[0]["assignee"] == "verifier"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
