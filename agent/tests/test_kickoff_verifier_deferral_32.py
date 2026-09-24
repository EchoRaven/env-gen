"""PROPOSAL #32 — kickoff robustness: defer a non-submitting DEFERRABLE attendee.

Run #31 died because the verifier never authored section='verifier' → try_synthesize
'awaiting' → kickoff_failed. The verifier's section is derivable (predicate floor from
the frontend user_flows) and its real work (chains) is post-impl, so a stalled kickoff
should DEFER it (record a decision ATTRIBUTED agent='verifier' — _missing_attendees
counts by the decision's `agent` field) and re-synthesize, instead of failing. An
ESSENTIAL attendee (backend) missing is NOT deferred → honest fail.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.kickoff_driver import (  # noqa: E402
    KickoffDriver, _DEFERRABLE_KICKOFF_ATTENDEES)
from multi_agent.runtime import kickoff_driver as kd  # noqa: E402


_HANDLE = {"meeting_id": "page_x", "milestone_index": 1,
           "expected_attendees": ["backend", "frontend", "verifier"]}


class _Orch:
    def __init__(self):
        self.decisions = []  # (decision, agent)
        wh = SimpleNamespace(add_meeting_decision=self._add)
        self.hubs = SimpleNamespace(workhub=wh)
        self._logger = SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None)
        self._authored = False

    def _add(self, meeting_id, decision=None, agent="", milestone_index=None):
        self.decisions.append((decision, agent))
        return {"ok": True}

    def _author_kickoff_docs(self, synth):
        self._authored = True


class VerifierDeferral(unittest.TestCase):
    def test_constant_is_verifier_only(self):
        self.assertIn("verifier", _DEFERRABLE_KICKOFF_ATTENDEES)
        self.assertNotIn("backend", _DEFERRABLE_KICKOFF_ATTENDEES)
        self.assertNotIn("frontend", _DEFERRABLE_KICKOFF_ATTENDEES)

    def test_missing_verifier_is_deferred_attributed_to_verifier_then_finalizes(self):
        orch = _Orch()
        # try_synthesize: 1st call awaiting(missing=[verifier]); 2nd (after defer) ready
        synth_seq = [
            {"status": "awaiting", "missing": ["verifier"]},
            {"status": "ready", "reconciled_added": [], "reconciled_normalized": []},
        ]
        with mock.patch.object(kd.KickoffDriver, "__init__", lambda self, o: setattr(self, "_orch", o)):
            drv = KickoffDriver(orch)
        with mock.patch("multi_agent.runtime.kickoff.run_kickoff.try_synthesize",
                        side_effect=synth_seq) as ts, \
             mock.patch("multi_agent.runtime.kickoff.run_kickoff.finalize_kickoff",
                        return_value={"receipt": "ok"}) as fin:
            receipt = drv._attempt_reconciled_finalize(_HANDLE, "initial_stall")
        self.assertEqual(receipt, {"receipt": "ok"}, "should finalize after deferring verifier")
        self.assertEqual(ts.call_count, 2, "must re-synthesize after the defer")
        self.assertTrue(fin.called)
        # LOAD-BEARING: the injected decision is attributed agent='verifier'
        self.assertEqual(len(orch.decisions), 1)
        decision, agent = orch.decisions[0]
        self.assertEqual(agent, "verifier")
        self.assertEqual(decision.get("section"), "verifier")
        self.assertTrue(decision.get("content", {}).get("deferred"))

    def test_missing_ESSENTIAL_backend_is_NOT_deferred_honest_fail(self):
        orch = _Orch()
        with mock.patch.object(kd.KickoffDriver, "__init__", lambda self, o: setattr(self, "_orch", o)):
            drv = KickoffDriver(orch)
        with mock.patch("multi_agent.runtime.kickoff.run_kickoff.try_synthesize",
                        return_value={"status": "awaiting", "missing": ["backend"]}) as ts, \
             mock.patch("multi_agent.runtime.kickoff.run_kickoff.finalize_kickoff") as fin:
            receipt = drv._attempt_reconciled_finalize(_HANDLE, "initial_stall")
        self.assertIsNone(receipt, "a missing ESSENTIAL section must NOT be deferred")
        self.assertEqual(orch.decisions, [], "no deferral injected for backend")
        self.assertEqual(ts.call_count, 1, "no re-synthesize (no defer)")
        self.assertFalse(fin.called)

    def test_mixed_missing_with_essential_is_NOT_deferred(self):
        orch = _Orch()
        with mock.patch.object(kd.KickoffDriver, "__init__", lambda self, o: setattr(self, "_orch", o)):
            drv = KickoffDriver(orch)
        with mock.patch("multi_agent.runtime.kickoff.run_kickoff.try_synthesize",
                        return_value={"status": "awaiting", "missing": ["frontend", "verifier"]}):
            receipt = drv._attempt_reconciled_finalize(_HANDLE, "initial_stall")
        self.assertIsNone(receipt)
        self.assertEqual(orch.decisions, [], "frontend is essential → no deferral")


if __name__ == "__main__":
    unittest.main()
