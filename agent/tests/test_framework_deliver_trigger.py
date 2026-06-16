"""Deterministic deliver trigger — orchestrator._maybe_framework_deliver (FIX #18).

The orchestrator LLM drifts: it calls deliverability_check repeatedly without ever
firing deliver_project, even when the delivery gate is fully clear (smoke #19: 30x
deliverability_check, 0 deliver_project). deliver_project itself only sets
``_project_delivered_event`` — it does NOT cut a release. So once
``_validate_delivery_gate`` reports no failed checks (a validated, gate-clear app),
the framework cuts the release + signals delivery deterministically.

These pin: gate-clear → release cut + delivered signalled; gate-blocked → nothing;
idempotent (already-delivered → no-op).
"""

import asyncio
import logging
import os
import sys
import threading
import types

LLM = os.path.join(os.path.dirname(__file__), "..", "env_generator", "llm_generator")
sys.path.insert(0, os.path.abspath(LLM))

from multi_agent.orchestrator import Orchestrator  # noqa: E402


def _orch(gate_failed_checks, *, implemented=True):
    orch = Orchestrator.__new__(Orchestrator)
    orch._logger = logging.getLogger("t")
    orch._project_delivered_event = threading.Event()
    releases = []

    class _Api:
        def get_endpoints(self):
            # one implemented business endpoint → all_business_endpoints_implemented True
            return {"GET:/api/x": {"id": "GET:/api/x", "method": "GET", "path": "/api/x",
                                    "kind": None, "status": "implemented" if implemented else "defined"}}

    class _Code:
        def create_release(self, tag, source="main", notes="", agent="codehub"):
            releases.append({"tag": tag, "source": source, "agent": agent})
            return {"id": tag, "tag": tag}

    orch.hubs = types.SimpleNamespace(registryhub=_Api(), codehub=_Code())
    orch._validate_delivery_gate = lambda: {"failed_checks": list(gate_failed_checks)}
    return orch, releases


def test_delivers_and_cuts_release_when_gate_clear():
    orch, releases = _orch([])
    asyncio.run(orch._maybe_framework_deliver())
    assert orch._project_delivered is True
    assert orch._project_delivered_event.is_set()
    assert len(releases) == 1
    assert releases[0]["agent"] == "orchestrator"  # role-gate satisfied


def test_does_not_deliver_when_gate_blocked():
    orch, releases = _orch(["contract_alignment_failed"])
    asyncio.run(orch._maybe_framework_deliver())
    assert getattr(orch, "_project_delivered", False) is False
    assert orch._project_delivered_event.is_set() is False
    assert releases == []


def test_does_not_deliver_before_endpoints_implemented():
    orch, releases = _orch([], implemented=False)
    asyncio.run(orch._maybe_framework_deliver())
    assert getattr(orch, "_project_delivered", False) is False
    assert releases == []


def test_idempotent_when_already_delivered():
    orch, releases = _orch([])
    orch._project_delivered = True
    asyncio.run(orch._maybe_framework_deliver())
    assert releases == []  # no second release


if __name__ == "__main__":
    import unittest
    unittest.main()
