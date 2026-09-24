"""#1202fd: downtime must not count as deferral progress.

#1202ce persists `*_deferred_since` deliberately, so a run most of the way to an
escape keeps what it earned. They are ABSOLUTE timestamps, and every release
decision escapes on `(now - deferred_since) > escape_s` -- so a run that was DEAD
between two processes is credited with that death.

netflix-r41, live: killed 09-04, resumed 09-06, visual gate released with "escape
after 196153s deferred / 1 attempts". plateau was 0 and attempts 1, so neither
other escape fired -- the wall-clock one did, on 54.5 hours of which most was a
stopped process. An escape means DELIVER ANYWAY, below threshold.
"""
import sys
import time
import types
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

ORCH_SRC = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
            / "orchestrator.py").read_text(encoding="utf-8")


class _Orch:
    """The shift is pure attribute arithmetic; bind the real method to a stand-in."""

    def __init__(self):
        import logging
        self._logger = logging.getLogger("test_1202fd")

    @classmethod
    def with_method(cls):
        from env_generator.llm_generator.multi_agent.orchestrator import (
            Orchestrator)
        o = cls()
        o._shift_deferral_clocks_1202fd = types.MethodType(
            Orchestrator._shift_deferral_clocks_1202fd, o)
        return o


class TestDowntimeIsNotDeferral(unittest.TestCase):

    def setUp(self):
        self.o = _Orch.with_method()
        self.now = time.time()

    def test_every_persisted_clock_moves_by_the_downtime(self):
        gap = 190000.0
        for f in ("_pages_gate_deferred_since", "_tu_squad_deferred_since",
                  "_rc_deferred_since", "_tu_browser_deferred_since"):
            setattr(self.o, f, self.now - 200000.0)
        self.o._shift_deferral_clocks_1202fd(gap)
        for f in ("_pages_gate_deferred_since", "_tu_squad_deferred_since",
                  "_rc_deferred_since", "_tu_browser_deferred_since"):
            elapsed = self.now - getattr(self.o, f)
            self.assertAlmostEqual(elapsed, 10000.0, delta=1.0,
                                   msg="%s still counts the downtime" % f)

    def test_the_visual_gate_clock_moves_too(self):
        """It lives on _vf_gate, not in the attribute list -- r41's was the one that fired."""
        self.o._vf_gate = types.SimpleNamespace(deferred_since=self.now - 196153.0)
        self.o._shift_deferral_clocks_1202fd(190000.0)
        self.assertAlmostEqual(self.now - self.o._vf_gate.deferred_since, 6153.0, delta=1.0)

    def test_earned_deferral_survives(self):
        """#1202ce's whole point: do not make a run earn its progress again."""
        self.o._pages_gate_deferred_since = self.now - 5000.0   # 5000s earned before death
        self.o._shift_deferral_clocks_1202fd(3000.0)            # 3000s dead
        self.assertAlmostEqual(self.now - self.o._pages_gate_deferred_since, 2000.0, delta=1.0)

    def test_an_unset_clock_is_left_unset(self):
        """None means 'not deferring' -- shifting it would invent a deferral."""
        self.o._pages_gate_deferred_since = None
        self.o._shift_deferral_clocks_1202fd(1000.0)
        self.assertIsNone(self.o._pages_gate_deferred_since)

    def test_it_never_raises(self):
        self.o._vf_gate = None
        self.o._pages_gate_deferred_since = "not a number"
        self.o._shift_deferral_clocks_1202fd(1000.0)
        self.assertEqual(self.o._pages_gate_deferred_since, "not a number")

    def test_the_credit_records_the_gap_for_later(self):
        """The clocks do not exist at credit time -- #1202ce restores them much later."""
        i = ORCH_SRC.index("def _credit_downtime_1202eq")
        j = ORCH_SRC.index("\n    def ", i + 10)
        self.assertIn("self._downtime_gap_1202fd = _gap", ORCH_SRC[i:j])

    def test_the_shift_runs_after_the_clocks_are_restored(self):
        """As first committed the shift ran ~450 lines BEFORE the restore and moved
        nothing: r41's third resume logged "#1202eq credited 1562s" with no shift beside
        it. Ordering is the whole correctness of this fix, so it is pinned."""
        # CALL sites, not definition sites: a method body can sit anywhere in the file.
        # Measuring the definition is what made my first draft of this assertion pass on
        # broken ordering.
        credit_call = ORCH_SRC.index("self._credit_downtime_1202eq()")
        restore = ORCH_SRC.index("restore_gate_counters_1202ce(self, _mkey)")
        shift = ORCH_SRC.index("self._shift_deferral_clocks_1202fd(_gap_1202fd)")
        self.assertLess(credit_call, restore, "the gap must be measured before the restore")
        self.assertLess(restore, shift, "the shift must run AFTER the clocks exist")

    def test_the_gap_is_consumed_once(self):
        """A later milestone restore must not re-apply the same downtime."""
        i = ORCH_SRC.index("self._shift_deferral_clocks_1202fd(_gap_1202fd)")
        j = ORCH_SRC.index("\n", ORCH_SRC.index("_downtime_gap_1202fd = None", i))
        self.assertIn("_downtime_gap_1202fd = None", ORCH_SRC[i:j + 1])

    def test_the_shift_covers_every_clock_1202ce_restores(self):
        """#1202ce's field list is the authority on which clocks survive a resume."""
        from env_generator.llm_generator.multi_agent.runtime.milestone_resume import (
            _GATE_FIELDS_1202CE)
        i = ORCH_SRC.index("def _shift_deferral_clocks_1202fd")
        body = ORCH_SRC[i:ORCH_SRC.index("\n    def ", i + 10)]
        for f in _GATE_FIELDS_1202CE:
            if f.endswith("_deferred_since"):
                self.assertIn(f, body, "%s survives a resume but is never shifted" % f)


if __name__ == "__main__":
    unittest.main()
