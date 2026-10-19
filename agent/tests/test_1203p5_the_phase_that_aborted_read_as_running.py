"""#1203p5: the phase that aborted was shown as running, forever.

`_phase_summary` -- the renderer behind the one page a human watches -- handled exactly two
event types, `phase_start` and `phase_complete`. `phase_error`, which the orchestrator emits
when the workflow gives up, was not one of them, so the phase kept the `"running"` its start
had set for the rest of the run and every time the page was reopened afterwards.

MEASURED over 104 runs' `progress_events.jsonl`: 66 `phase_error` events, every one of them
`Agent Workflow`, against 20 `phase_complete`. Of the runs whose workflow ended at all, most
ended in an error this view did not show.

And the event carries the answer to the question that page exists to answer. Verbatim from a
corpus record: "STUCK -- generation aborted without delivery after 14 coordination ticks:
delivery never SUCCEEDED in 148min of lane time since the contract built (now failing
['business_chain_failing', 'validation_ui_evidence_failed'])". That sentence reached
`progress_events.jsonl` and nothing else -- #1203oy's shape, one page over.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from live_monitor_server import _phase_summary  # noqa: E402

# The shape the corpus actually holds, including the sentence a reader needs.
_STUCK = ("STUCK — generation aborted without delivery after 14 coordination ticks: "
          "delivery never SUCCEEDED in 148min of lane time since the contract built "
          "(now failing ['business_chain_failing', 'validation_ui_evidence_failed'])")


def _ev(t, msg, ts, **data):
    e = {"type": t, "message": msg, "timestamp": ts}
    if data:
        e["data"] = data
    return e


class AnAbortedPhaseIsNotRunning(unittest.TestCase):
    def test_a_phase_error_is_rendered_as_failed(self):
        out = _phase_summary([_ev("phase_start", "Agent Workflow", 1),
                              _ev("phase_error", "Agent Workflow", 2, error=_STUCK)])
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["status"], "failed",
                         "an aborted phase still reads as %r" % out[0].get("status"))

    def test_the_reason_reaches_the_page(self):
        out = _phase_summary([_ev("phase_start", "Agent Workflow", 1),
                              _ev("phase_error", "Agent Workflow", 2, error=_STUCK)])
        self.assertIn("error", out[0], "the abort reason is not in the payload: %r" % out[0])
        self.assertEqual(out[0]["error"], _STUCK)

    def test_the_reason_is_not_truncated(self):
        """#1034 deliberately NOT applied: it is one sentence per run, and the part a reader
        acts on -- which checks were failing -- sits at the END."""
        out = _phase_summary([_ev("phase_start", "Agent Workflow", 1),
                              _ev("phase_error", "Agent Workflow", 2, error=_STUCK)])
        self.assertIn("business_chain_failing", out[0]["error"])
        self.assertIn("validation_ui_evidence_failed", out[0]["error"])

    def test_the_timestamp_moves_so_the_page_can_order_it(self):
        out = _phase_summary([_ev("phase_start", "Agent Workflow", 1),
                              _ev("phase_error", "Agent Workflow", 7, error=_STUCK)])
        self.assertEqual(out[0]["updatedAt"], 7)

    def test_an_error_with_no_detail_still_flips_the_status(self):
        """The status is the load-bearing half: a phase that aborted must not read as running
        even when the emitter passed no reason."""
        out = _phase_summary([_ev("phase_start", "Agent Workflow", 1),
                              _ev("phase_error", "Agent Workflow", 2)])
        self.assertEqual(out[0]["status"], "failed")
        self.assertNotIn("error", out[0], "an absent reason must not be invented")

    def test_an_error_for_a_phase_that_never_started_still_appears(self):
        """Same shape as `phase_complete`'s own handling: a terminal event for an unseen
        phase adds it rather than dropping the only record of it."""
        out = _phase_summary([_ev("phase_error", "Design Prep", 3, error="boom")])
        self.assertEqual([p["name"] for p in out], ["Design Prep"], out)
        self.assertEqual(out[0]["status"], "failed")

    def test_completion_still_wins_when_it_comes_after(self):
        """A retry that succeeds must not be left reading as failed."""
        out = _phase_summary([_ev("phase_start", "Agent Workflow", 1),
                              _ev("phase_error", "Agent Workflow", 2, error=_STUCK),
                              _ev("phase_complete", "Agent Workflow", 3)])
        self.assertEqual(out[0]["status"], "completed")

    def test_a_running_phase_is_untouched(self):
        out = _phase_summary([_ev("phase_start", "Kickoff M1", 1)])
        self.assertEqual(out[0]["status"], "running")
        self.assertNotIn("error", out[0])


if __name__ == "__main__":
    unittest.main()
