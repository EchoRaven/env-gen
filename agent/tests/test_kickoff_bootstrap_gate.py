"""Round 8h Stage 1 — closed-by-construction pins for
``KickoffBootstrapGate`` (replaces the retired
``ImplementationBootstrapPolicy``).

The old gate did a filesystem check for ``design/spec.{api,database,
ui}.json`` — files the (retired) design agent used to write. Post
round-8e.1 there was no writer, so the gate deadlocked every smoke
(#18 / #19 / #20 all rejected every ``task_ready`` from orchestrator
with ``design gate not ready``).

The new gate is HUB-DRIVEN: a lane is post-kickoff bootstrapped when
WorkHub has at least one task assigned to its ``agent_id``.
``finalize_kickoff`` is the only writer of that state, so the
assignment is a strict signal that the kickoff contract is live in
the hubs.

Pins:

  * legacy ``implementation_bootstrap`` kind in yaml raises loudly on
    config load (delete-don't-skip, no back-compat shim)
  * the new policy denies pre-kickoff task_ready with an informative
    reason (no tasks assigned yet)
  * it accepts post-kickoff task_ready (tasks present)
  * once bootstrapped, the sticky flag short-circuits subsequent
    checks (no hub re-read per task_ready)
  * non-orchestrator senders are still rejected with the same
    ``allowed_starters`` contract the old policy had
  * runtime wiring race (hubs not yet attached) is denied with a
    distinct reason, not silently passed
  * the new gate is wired into backend + frontend yaml profiles
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _make_message(source_agent_id: str = "orchestrator"):
    """Minimal task_ready message; the gate only reads
    message.header.source_agent_id."""
    from utils.message import BaseMessage, MessageHeader, MessagePriority
    return BaseMessage(
        header=MessageHeader(
            source_agent_id=source_agent_id,
            target_agent_id="backend",
            priority=MessagePriority.NORMAL,
        ),
        payload="x",
    )


class _FakeWorkHub:
    def __init__(self, tasks_by_assignee=None):
        self._tasks = tasks_by_assignee or {}

    def list_tasks(self, assignee=None, status=None, domain=None, plan_id=None):
        if assignee is None:
            return [t for ts in self._tasks.values() for t in ts]
        return list(self._tasks.get(assignee, []))


class _FakeJsonStore:
    """Minimal mimic of JsonStore.value() returning a dict."""
    def __init__(self, data=None):
        self._data = data or {}

    def value(self):
        return dict(self._data)


class _FakeRegistryHub:
    def __init__(self, endpoints=None):
        self._endpoints = _FakeJsonStore(endpoints or {})


class _FakeHubs:
    def __init__(self, workhub=None, registryhub=None):
        self.workhub = workhub if workhub is not None else _FakeWorkHub()
        self.registryhub = registryhub if registryhub is not None else _FakeRegistryHub()


class _FakeAgent:
    def __init__(self, agent_id="backend", hubs=None):
        self.agent_id = agent_id
        self._hubs = hubs


class LegacyKindRaisesOnConfigLoad(unittest.TestCase):
    """An agents_config.yaml block still using the old kind
    ``implementation_bootstrap`` must raise loudly so the operator
    knows to migrate to ``kickoff_bootstrap_gate``. No back-compat
    shim (charter §6.C delete-don't-skip)."""

    def test_old_kind_raises_with_migration_hint(self):
        from multi_agent.workflow_policies import create_workflow_policies
        with self.assertRaises(ValueError) as cm:
            create_workflow_policies({
                "workflow_policies": [
                    {
                        "kind": "implementation_bootstrap",
                        "allowed_starters": ["orchestrator"],
                        "required_files": ["design/spec.api.json"],
                    }
                ]
            })
        msg = str(cm.exception)
        self.assertIn("RETIRED", msg)
        self.assertIn("kickoff_bootstrap_gate", msg)
        self.assertIn("round-8e.1", msg)


class GateDeniesPreKickoff(unittest.TestCase):
    """Before kickoff fires, no endpoints in RegistryHub AND no tasks in
    WorkHub. The gate MUST deny task_ready with an informative
    reason citing the missing signals."""

    def test_no_kickoff_signal_denied(self):
        from multi_agent.workflow_policies import KickoffBootstrapGate
        gate = KickoffBootstrapGate(allowed_starters=["orchestrator"])
        agent = _FakeAgent(
            agent_id="backend",
            hubs=_FakeHubs(),  # both empty
        )
        result = gate.allow_task_ready(agent, _make_message())
        self.assertIsNotNone(result)
        allowed, reason = result
        self.assertFalse(allowed)
        self.assertIn("no kickoff-finalized signal", reason)
        self.assertIn("registryhub_endpoints=0", reason)
        self.assertIn("workhub_tasks=0", reason)
        # Flag stays false so post-finalize call retries cleanly.
        self.assertFalse(getattr(agent, "_kickoff_bootstrapped", False))


class GateAcceptsPostKickoffViaRegistryHubEndpoints(unittest.TestCase):
    """Smoke #22 follow-up: a lane that ISN'T assigned tasks by
    finalize_kickoff (e.g. Frontend post round-8e.1 — backend owns
    all kickoff-created tasks) MUST still pass the gate once RegistryHub
    has registered endpoints. The global "kickoff finalized" signal
    is sufficient — per-lane task ownership is the orchestrator's
    job, not the gate's."""

    def test_frontend_accepted_with_registryhub_endpoints_no_workhub_tasks(self):
        from multi_agent.workflow_policies import KickoffBootstrapGate
        gate = KickoffBootstrapGate(allowed_starters=["orchestrator"])
        agent = _FakeAgent(
            agent_id="frontend",  # frontend doesn't own kickoff tasks
            hubs=_FakeHubs(
                workhub=_FakeWorkHub({"backend": [{"id": "impl.endpoint.x"}]}),
                registryhub=_FakeRegistryHub({
                    "ep_post_register": {"method": "POST", "path": "/api/auth/register"},
                    "ep_get_posts": {"method": "GET", "path": "/api/posts"},
                }),
            ),
        )
        # Gate allows because RegistryHub has endpoints (kickoff finalized
        # signal), even though frontend has no WorkHub tasks.
        self.assertIsNone(gate.allow_task_ready(agent, _make_message()))
        self.assertTrue(agent._kickoff_bootstrapped)


class GateAcceptsPostKickoffViaWorkHubTasks(unittest.TestCase):
    """Either signal works — WorkHub having any task is enough.
    (Real-world: backend's implement_endpoint/implement_table tasks
    or any other kickoff-created task.)"""

    def test_workhub_tasks_present_registryhub_empty_still_allows(self):
        from multi_agent.workflow_policies import KickoffBootstrapGate
        gate = KickoffBootstrapGate(allowed_starters=["orchestrator"])
        agent = _FakeAgent(
            agent_id="frontend",
            hubs=_FakeHubs(
                workhub=_FakeWorkHub({"backend": [{"id": "t1"}, {"id": "t2"}]}),
                registryhub=_FakeRegistryHub(endpoints={}),  # empty
            ),
        )
        self.assertIsNone(gate.allow_task_ready(agent, _make_message()))
        self.assertTrue(agent._kickoff_bootstrapped)


class GateStickyFlagShortCircuits(unittest.TestCase):
    """Once flipped, the sticky flag bypasses hub checks. Kickoff
    cannot become un-finalized; re-reading the hubs on every
    task_ready would be wasteful."""

    def test_sticky_flag_skips_hub_check(self):
        from multi_agent.workflow_policies import KickoffBootstrapGate
        gate = KickoffBootstrapGate(allowed_starters=["orchestrator"])
        agent = _FakeAgent(
            agent_id="backend",
            hubs=_FakeHubs(registryhub=_FakeRegistryHub({"ep_x": {}})),
        )
        # First call: signal present, flag set.
        self.assertIsNone(gate.allow_task_ready(agent, _make_message()))
        self.assertTrue(agent._kickoff_bootstrapped)
        # Second call: even if we strip hubs, sticky flag short-circuits.
        agent._hubs = None
        self.assertIsNone(gate.allow_task_ready(agent, _make_message()))


class GateRejectsNonOrchestratorSender(unittest.TestCase):
    """``allowed_starters`` parity with the retired policy: only
    orchestrator may dispatch the FIRST task_ready. A bare-metal
    debug session that sends task_ready from "frontend" to "backend"
    should still be denied."""

    def test_non_orchestrator_denied(self):
        from multi_agent.workflow_policies import KickoffBootstrapGate
        gate = KickoffBootstrapGate(allowed_starters=["orchestrator"])
        agent = _FakeAgent(
            agent_id="backend",
            hubs=_FakeHubs(registryhub=_FakeRegistryHub({"ep_x": {}})),
        )
        result = gate.allow_task_ready(
            agent, _make_message(source_agent_id="frontend"),
        )
        self.assertIsNotNone(result)
        allowed, reason = result
        self.assertFalse(allowed)
        self.assertIn("orchestrator", reason)
        self.assertIn("frontend", reason)


class GateHandlesHubsWiringRace(unittest.TestCase):
    """``agent._hubs`` may not be set when the very first task_ready
    arrives during spawn. The gate denies with a DISTINCT reason
    (not the "no kickoff signal" path) so logs are searchable. Later
    calls (after wiring catches up) pass cleanly."""

    def test_hubs_not_attached_denied(self):
        from multi_agent.workflow_policies import KickoffBootstrapGate
        gate = KickoffBootstrapGate(allowed_starters=["orchestrator"])
        agent = _FakeAgent(agent_id="backend", hubs=None)
        result = gate.allow_task_ready(agent, _make_message())
        self.assertIsNotNone(result)
        allowed, reason = result
        self.assertFalse(allowed)
        self.assertIn("hubs not yet attached", reason)

    def test_workhub_raises_denied_with_exc_class(self):
        """Smoke #22 fix v2: gate composes a diagnostic
        ``check_results`` string showing why each signal failed. A
        hub raising during signal-evaluation gets its exception
        class name folded into the string so logs are searchable
        without leaking exception details."""
        from multi_agent.workflow_policies import KickoffBootstrapGate
        gate = KickoffBootstrapGate(allowed_starters=["orchestrator"])

        class _BoomHub:
            def list_tasks(self, **kw):
                raise RuntimeError("connection lost")

        agent = _FakeAgent(
            agent_id="backend",
            hubs=_FakeHubs(
                workhub=_BoomHub(),
                registryhub=_FakeRegistryHub(),  # explicit empty so signal A returns 0
            ),
        )
        result = gate.allow_task_ready(agent, _make_message())
        self.assertIsNotNone(result)
        allowed, reason = result
        self.assertFalse(allowed)
        # Diagnostic: BOTH signals reported (A=0 endpoints, B=raised).
        self.assertIn("registryhub_endpoints=0", reason)
        self.assertIn("workhub_tasks_err=RuntimeError", reason)


class GateWiredIntoBackendAndFrontendProfiles(unittest.TestCase):
    """Closed-by-construction: the yaml MUST list
    ``kickoff_bootstrap_gate`` under both backend and frontend
    profiles' workflow_policies, AND MUST NOT list the retired
    ``implementation_bootstrap`` anywhere."""

    def test_no_implementation_bootstrap_in_yaml(self):
        yaml_path = (
            LLM_DIR
            / "multi_agent"
            / "agents"
            / "agents_config.yaml"
        )
        content = yaml_path.read_text(encoding="utf-8")
        # Comment lines mentioning the legacy kind by name are
        # allowed (they document the retirement); enforce that no
        # ACTIVE yaml block uses the old kind. Check for the
        # config-binding form: a line starting with `- kind:`.
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- kind:"):
                self.assertNotIn(
                    "implementation_bootstrap", stripped,
                    "round 8h Stage 1: agents_config.yaml MUST NOT "
                    "have any active `- kind: implementation_bootstrap` "
                    "blocks. The kind is retired; replace with "
                    "`kind: kickoff_bootstrap_gate`."
                )

    def _load_profile(self, profile_id: str):
        from multi_agent.agents.configurable_agent import load_config
        config = load_config()
        return config["profiles"][profile_id]

    def test_backend_profile_has_kickoff_bootstrap_gate(self):
        backend = self._load_profile("backend")
        kinds = {
            (p or {}).get("kind")
            for p in (backend.get("workflow_policies") or [])
        }
        self.assertIn("kickoff_bootstrap_gate", kinds)
        self.assertNotIn("implementation_bootstrap", kinds)

    def test_frontend_profile_has_kickoff_bootstrap_gate(self):
        frontend = self._load_profile("frontend")
        kinds = {
            (p or {}).get("kind")
            for p in (frontend.get("workflow_policies") or [])
        }
        self.assertIn("kickoff_bootstrap_gate", kinds)
        self.assertNotIn("implementation_bootstrap", kinds)


if __name__ == "__main__":
    unittest.main()
