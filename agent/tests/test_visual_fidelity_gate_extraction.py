"""DECOMPOSITION VisualFidelity slice B: the stateful gate moved from the
Orchestrator into runtime.visual_fidelity.VisualFidelityGate. Pins the
budget/latch/refund/judge-on-change state machine + the Orchestrator shim.

LOCAL-ONLY (agent/tests/ is gitignored per repo policy) — run for verification.
"""

import asyncio
import logging
import sys
import types
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime import visual_fidelity as vf  # noqa: E402
from multi_agent.runtime.visual_fidelity import VisualFidelityGate  # noqa: E402


def _fake_orch(sig="S1", refs=("ref.png",)):
    """Minimal orchestrator stand-in carrying just what maybe_run touches."""
    o = types.SimpleNamespace()
    o._reference_images = list(refs)
    o.output_dir = "/tmp/x"
    o.llm = object()
    o._logger = logging.getLogger("t")
    o._sig = sig
    o._compute_app_source_signature = lambda: o._sig
    o._tasks = []
    o._msgs = []
    workhub = types.SimpleNamespace(
        create_task=lambda **kw: (o._tasks.append(kw) or {"id": f"t{len(o._tasks)}"}))
    o.hubs = types.SimpleNamespace(workhub=workhub)

    async def _send(m):
        o._msgs.append(m)
    o.message_bus = types.SimpleNamespace(send=_send)
    return o


class _Patch:
    """Patch vf.run_visual_fidelity with an async stub returning a fixed result."""
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def __enter__(self):
        self._orig = vf.run_visual_fidelity

        async def stub(output_dir, refs, llm, **kw):  # #142 adds verdict_cache=
            self.calls += 1
            return self.result
        vf.run_visual_fidelity = stub
        return self

    def __exit__(self, *a):
        vf.run_visual_fidelity = self._orig


def run(coro):
    return asyncio.run(coro)


class StateMachineTests(unittest.TestCase):
    def test_no_refs_no_judge(self):
        g = VisualFidelityGate(_fake_orch(refs=[]))
        with _Patch({"passed": True}) as p:
            run(g.maybe_run())
        self.assertEqual(p.calls, 0)

    def test_pass_latches_no_rejudge(self):
        g = VisualFidelityGate(_fake_orch())
        with _Patch({"passed": True, "screens": []}) as p:
            run(g.maybe_run())
            self.assertTrue(g.passed)
            self.assertEqual(p.calls, 1)
            run(g.maybe_run())            # same sig + passed ⇒ skip
            self.assertEqual(p.calls, 1)

    def test_attempt_cap_three(self):
        o = _fake_orch()
        g = VisualFidelityGate(o)
        with _Patch({"passed": False, "screens": []}) as p:
            for _ in range(5):
                o._sig = "S1"
                g.last_judged_sig = None   # pretend pixels changed → allow judge
                run(g.maybe_run())
            self.assertLessEqual(p.calls, 3)
            self.assertGreaterEqual(g.attempts, 3)

    def test_capture_unavailable_refunds_attempt(self):
        g = VisualFidelityGate(_fake_orch())
        with _Patch({"capture_unavailable": True, "summary": "down"}) as p:
            run(g.maybe_run())
            self.assertEqual(p.calls, 1)
            self.assertEqual(g.attempts, 0)         # incremented then refunded
            self.assertEqual(g.total_judgments, 0)  # not a real verdict
            self.assertIsNone(g.last_judged_sig)

    def test_judge_on_change_skips_identical_pixels(self):
        g = VisualFidelityGate(_fake_orch())
        g.sig = "S1"
        g.last_judged_sig = "S1"   # already judged this exact source
        with _Patch({"passed": False, "screens": []}) as p:
            run(g.maybe_run())
            self.assertEqual(p.calls, 0)     # skipped (identical pixels)
            # 2026-07-08 (stale-expectation fix, long-standing baseline debt): the
            # original policy consumed an attempt on the skip; current code does
            # NOT -- an unchanged source burns neither a judgment nor an attempt
            # (the per-source budget only meters REAL verdicts), which is the
            # behavior #112/#112b's window accounting relies on.
            self.assertEqual(g.attempts, 0)
            self.assertEqual(g.total_judgments, 0)

    def test_failed_files_task_and_message(self):
        o = _fake_orch()
        g = VisualFidelityGate(o)
        with _Patch({"passed": False, "screens": [], "summary": "off"}):
            run(g.maybe_run())
        self.assertEqual(len(o._tasks), 1)
        self.assertEqual(o._tasks[0]["assignee"], "frontend")
        self.assertEqual(len(o._msgs), 1)
        self.assertEqual(g.total_judgments, 1)
        self.assertFalse(g.passed)

    def test_sig_change_resets_budget(self):
        o = _fake_orch()
        g = VisualFidelityGate(o)
        g.sig = "OLD"; g.attempts = 2; g.passed = True
        with _Patch({"passed": True, "screens": []}) as p:
            o._sig = "NEW"
            run(g.maybe_run())
            self.assertEqual(g.sig, "NEW")
            self.assertEqual(p.calls, 1)     # reset → judged again
            self.assertEqual(g.attempts, 1)  # budget reset then one attempt

    def test_reset_for_milestone(self):
        g = VisualFidelityGate(_fake_orch())
        g.deferred_since = 123.0; g.total_judgments = 5; g.attempts = 2; g.passed = True
        g.reset_for_milestone()
        self.assertIsNone(g.deferred_since)
        self.assertEqual(g.total_judgments, 0)
        # #1202nu: a NEW milestone judges a different route scope, so neither the previous
        # milestone's pass latch nor its per-source budget carries over (r125 M4 shipped with
        # zero judgments on M3's pass). Re-entering the SAME milestone keeps both.
        self.assertEqual(g.attempts, 0)
        self.assertFalse(g.passed)


class ShimDelegationTests(unittest.TestCase):
    def test_orchestrator_shim_delegates(self):
        from multi_agent.orchestrator import Orchestrator
        o = object.__new__(Orchestrator)
        called = {}

        class FakeGate:
            async def maybe_run(self):
                called["yes"] = True
        o.__dict__["_vf_gate_instance"] = FakeGate()
        run(o._maybe_run_visual_fidelity())
        self.assertTrue(called.get("yes"))

    def test_lazy_gate_cached(self):
        from multi_agent.orchestrator import Orchestrator
        o = object.__new__(Orchestrator)
        g1 = o._vf_gate
        self.assertIsInstance(g1, VisualFidelityGate)
        self.assertIs(g1, o._vf_gate)   # cached


if __name__ == "__main__":
    unittest.main()
