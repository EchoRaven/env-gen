"""PROPOSAL #25 (PASS set) — shared run-state AWARENESS.

#24 made the run-phase machine-ENFORCED (preconditions silently block out-of-phase
tool calls); #25 makes it machine-COMMUNICATED so agents have a model of where the
run is + their role, instead of just getting blocked.

PASS set (reviewer NEEDS-CHANGES → narrowed): B1 + A1 + A2/A3 + A4.
- B1: backend subscribes to the EMITTED event name `table_registered` (the old
  `table_defined` had no emitter → dead sub → backend never heard about its tables).
- A1: `current_run_phase(hubs, agent)` — DISPLAY-ONLY phase derivation mirroring the
  #24 gate SIGNALS (prefers the sticky `_kickoff_bootstrapped`); gates MUST NOT call it.
- A2/A3: hub_pulse carries a `phase` block (current phase + meaning + per-lane role)
  rendered every step (even on otherwise-empty pulses) + a once-per-transition banner
  via a per-agent monotonic last-shown-phase store.
- A4: a short shared <development_lifecycle> section in the lane prompts (not orch).

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.agents.runtime.hub_pulse import (  # noqa: E402
    current_run_phase, _pulse_phase, build_hub_pulse_prompt, collect_hub_pulse)


def _hubs(endpoints=None, tasks=None):
    eps = endpoints or {}
    rh = SimpleNamespace(
        _endpoints=SimpleNamespace(value=lambda: eps),
        get_endpoints=lambda: eps,
    )
    wh = SimpleNamespace(list_tasks=lambda: (tasks or []))
    return SimpleNamespace(registryhub=rh, workhub=wh)


def _biz(status):
    return {"path": "/notes", "status": status}


class CurrentRunPhase(unittest.TestCase):
    def test_kickoff_when_no_endpoints_no_tasks(self):
        self.assertEqual(current_run_phase(_hubs()), "KICKOFF")

    def test_implementation_when_endpoints_not_all_implemented(self):
        h = _hubs(endpoints={"e1": _biz("implemented"), "e2": _biz("defined")})
        self.assertEqual(current_run_phase(h), "IMPLEMENTATION")

    def test_implementation_when_only_tasks_exist(self):
        self.assertEqual(current_run_phase(_hubs(tasks=[{"id": "t1"}])), "IMPLEMENTATION")

    def test_validation_when_all_business_endpoints_implemented(self):
        h = _hubs(endpoints={"e1": _biz("implemented"), "e2": _biz("implemented")})
        self.assertEqual(current_run_phase(h), "VALIDATION")

    def test_prefers_sticky_kickoff_bootstrapped_flag(self):
        # agent bootstrapped but hub transiently empty → NOT KICKOFF (sticky wins)
        agent = SimpleNamespace(_kickoff_bootstrapped=True)
        self.assertEqual(current_run_phase(_hubs(), agent=agent), "IMPLEMENTATION")

    def test_never_raises(self):
        self.assertEqual(current_run_phase(SimpleNamespace()), "KICKOFF")


class PulsePhaseTransition(unittest.TestCase):
    def test_transition_banner_fires_once_and_is_monotonic(self):
        agent = SimpleNamespace(agent_id="backend_worker_1")
        # first pulse: KICKOFF, no transition (no prior)
        p1 = _pulse_phase(_hubs(), "backend_worker_1", agent)
        self.assertEqual(p1["phase"], "KICKOFF")
        self.assertIsNone(p1["transition_from"])
        # endpoints appear → IMPLEMENTATION, transition recorded ONCE
        h = _hubs(endpoints={"e1": _biz("defined")})
        p2 = _pulse_phase(h, "backend_worker_1", agent)
        self.assertEqual(p2["phase"], "IMPLEMENTATION")
        self.assertEqual(p2["transition_from"], "KICKOFF")
        # same phase next pulse → no repeat banner
        p3 = _pulse_phase(h, "backend_worker_1", agent)
        self.assertIsNone(p3["transition_from"])
        # hub transiently empties → display must NOT regress to KICKOFF
        p4 = _pulse_phase(_hubs(), "backend_worker_1", agent)
        self.assertEqual(p4["phase"], "IMPLEMENTATION")

    def test_role_text_resolves_per_lane(self):
        for aid, kw in [("backend_worker_x", "backend"), ("frontend", "frontend"),
                        ("verifier", "verifier"), ("debugger", "debugger")]:
            p = _pulse_phase(_hubs(endpoints={"e": _biz("defined")}), aid,
                             SimpleNamespace(agent_id=aid))
            self.assertTrue(p["role"], f"{kw} should have an IMPLEMENTATION role")


class RenderPhaseBlock(unittest.TestCase):
    def test_phase_renders_on_empty_pulse(self):
        # an otherwise-empty pulse must STILL show the phase (reviewer condition)
        pulse = {"phase": {"phase": "KICKOFF", "transition_from": None,
                           "meaning": "declaring the contract.", "role": "declare X"}}
        out = build_hub_pulse_prompt(pulse)
        self.assertIsNotNone(out)
        self.assertIn("📍 PHASE: KICKOFF", out)
        self.assertIn("YOUR ROLE NOW", out)

    def test_transition_banner_rendered(self):
        pulse = {"phase": {"phase": "IMPLEMENTATION", "transition_from": "KICKOFF",
                           "meaning": "build it.", "role": "write routes"}}
        out = build_hub_pulse_prompt(pulse)
        self.assertIn("▶ PHASE TRANSITION: KICKOFF → IMPLEMENTATION", out)

    def test_no_phase_no_block(self):
        self.assertIsNone(build_hub_pulse_prompt({}))

    def test_collect_wires_phase_into_report(self):
        # collect_hub_pulse touches many unrelated sub-pulses; assert the phase
        # wiring at the source level + that it accepts the agent kwarg.
        src = inspect.getsource(collect_hub_pulse)
        self.assertIn('report["phase"] = _pulse_phase(', src)
        self.assertIn("agent: Any = None", src)


class B1Subscription(unittest.TestCase):
    def test_backend_subscribes_to_emitted_table_registered(self):
        # B1: backend must subscribe to the EMITTED name (table_registered), not the
        # dead table_defined. PRE-LAUNCH AUDIT R2: the subscription moved to INBOX_ONLY
        # (informed at next pulse, no heal-loop wakeup amplification), not live.
        from multi_agent.runtime.agent_subscriptions import (
            DEFAULT_SUBSCRIPTIONS as SUBS, INBOX_ONLY_SUBSCRIPTIONS as INBOX)
        live = {evt for (_hub, evt, _pri) in (SUBS.get("backend") or [])}
        inbox = {evt for (_hub, evt, _pri) in (INBOX.get("backend") or [])}
        self.assertNotIn("table_defined", live | inbox,
                         "the dead table_defined subscription should be gone")
        self.assertIn("table_registered", inbox,
                      "backend must inbox_only-subscribe the emitted table_registered (R2)")
        self.assertNotIn("table_registered", live,
                         "table_registered must NOT be a live sub (wakeup amplification)")


class GateNonImport(unittest.TestCase):
    """Reviewer condition: current_run_phase is DISPLAY-ONLY; the #24 gates must not
    consult it (else the subtlety-1 inversion #24 avoided could return)."""

    def test_gates_do_not_reference_current_run_phase(self):
        # The guard's intent is "gates must not IMPORT or CALL the display-only helper"
        # — a docstring that NAMES it to explain why not (e.g. #28's kickoff_finalized_signal
        # contrasts itself with it) is fine and good. So check for an actual import/call,
        # not a bare mention.
        import re
        from multi_agent.agents.runtime import preconditions
        from multi_agent import workflow_policies
        for mod in (preconditions, workflow_policies):
            src = inspect.getsource(mod)
            self.assertNotIn("import current_run_phase", src,
                             f"{mod.__name__} must not import the display-only helper")
            self.assertIsNone(re.search(r"\bcurrent_run_phase\s*\(", src),
                              f"{mod.__name__} must not CALL the display-only helper")

    def test_docstring_marks_display_only(self):
        self.assertIn("DISPLAY ONLY", current_run_phase.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
