"""#1202fk: lane time cannot exceed the seconds a process existed to spend it.

The no-convergence abort computes its budget as `now - first_decline_ts`, a
WALL-CLOCK difference over a PERSISTED stamp, so a run stopped overnight is
billed for the night. #1202eq/#1202fi credit each resume's own downtime, but a
stamp carrying gaps from before that fix is never repaid: tiktok-r96, with the
credit finally applied, still aborted on "1540min of lane time". r41 and r96
became unresumable that way.

The bound fixes it without touching the stamp -- and reads from the ledger file
rather than restored state, so it carries none of the ordering hazard that made
#1202fd and #1202fi ship inert.
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.run_budget import RunBudget  # noqa: E402

ORCH = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
        / "orchestrator.py").read_text(encoding="utf-8")


def _orch_with(cumulative):
    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
    d = Path(tempfile.mkdtemp())
    if cumulative is not None:
        (d / "run_budget.json").write_text(
            json.dumps({"usage": {}, "cumulative_1202cg": cumulative}), encoding="utf-8")
    o = types.SimpleNamespace(_budget=RunBudget(d, None))
    o._lane_time_1202fk = types.MethodType(Orchestrator._lane_time_1202fk, o)
    return o


class TestTheBound(unittest.TestCase):

    def test_an_overnight_gap_is_bounded_to_real_alive_time(self):
        """r96's arithmetic: 1540 minutes billed, ~60 minutes ever alive."""
        o = _orch_with({"alive_total": 3600.0})
        self.assertEqual(o._lane_time_1202fk(1540 * 60), 3600.0)

    def test_a_genuinely_churning_run_is_still_caught(self):
        """The abort's whole purpose. 90 minutes billed, 90 minutes alive -> unchanged."""
        o = _orch_with({"alive_total": 5400.0})
        self.assertEqual(o._lane_time_1202fk(5400.0), 5400.0)

    def test_the_bound_never_inflates(self):
        o = _orch_with({"alive_total": 99999.0})
        self.assertEqual(o._lane_time_1202fk(120.0), 120.0)

    def test_an_unreadable_ledger_leaves_the_backstop_armed(self):
        """Refusing to abort on a missing file would disarm the fail-fast."""
        self.assertEqual(_orch_with(None)._lane_time_1202fk(9999.0), 9999.0)
        self.assertEqual(_orch_with({})._lane_time_1202fk(9999.0), 9999.0)

    def test_a_nonsense_bound_is_ignored(self):
        for bad in ({"alive_total": 0}, {"alive_total": -5}, {"alive_total": "x"}):
            self.assertEqual(_orch_with(bad)._lane_time_1202fk(9999.0), 9999.0)

    def test_it_never_raises(self):
        o = _orch_with({"alive_total": 10.0})
        self.assertIsInstance(o._lane_time_1202fk(1.0), float)


class TestWiring(unittest.TestCase):

    def test_the_decision_uses_the_bounded_value(self):
        i = ORCH.index("_lane1202fk = self._lane_time_1202fk(")
        j = ORCH.index("FWVAL_NO_DELIVER_ABORT_S", i)
        self.assertIn("_lane1202fk >", ORCH[i:j + 40])

    def test_the_message_reports_the_number_it_decided_on(self):
        """Reporting the raw wall clock beside a bounded decision is #1023's mistake."""
        # The f-string, not the prose: this sentence appears in two comments above the
        # code that builds it, and a plain search lands on the first of them.
        i = ORCH.index('f"delivery never SUCCEEDED in "')
        seg = ORCH[i:ORCH.index("of lane time", i) + 20]
        self.assertIn("_lane1202fk", seg)
        self.assertNotIn("_now2 - self._fwdeliver_first_decline_ts", seg)


class TestTheLedgerCarriesIt(unittest.TestCase):

    def test_alive_accumulates_across_runs(self):
        d = Path(tempfile.mkdtemp())
        b1 = RunBudget(d, None)
        b1.write_process_wall_1202ez(600.0)
        b1.write({"max_wall_sec": 1.0, "max_ticks": 1}, 1000.0, 400.0, 1, "finished")
        b2 = RunBudget(d, None)      # a second process over the same dir
        b2.write({"max_wall_sec": 1.0, "max_ticks": 1}, 2000.0, 50.0, 1, "running")
        cum = json.loads((d / "run_budget.json").read_text(encoding="utf-8"))["cumulative_1202cg"]
        # the previous run's larger clock (600 process wall, not 400 loop) plus this one's
        self.assertEqual(cum["alive_before_this_run"], 600.0)
        self.assertEqual(cum["alive_total"], 650.0)


if __name__ == "__main__":
    unittest.main()
