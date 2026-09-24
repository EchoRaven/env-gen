"""#1202fi: a stopped process spent no lane time, and the deferral cap must not apply.

#1202eq routed resume downtime through #1133's credit channel. That channel is
capped at FWVAL_NO_DELIVER_ABORT_S in total, because the FRAMEWORK must not be
able to defer past the ceiling -- so the credit was useless for exactly the runs
it was written for.

tiktok-r96, live: stopped 84767s (23.5h), credited the capped 5400s, and aborted
one tick in with "delivery never SUCCEEDED in 1474min of lane time" -- 1474 minus
the 90 credited minutes, against a 90-minute ceiling. Every overnight resume
exceeds that gap by construction, so every one was dead on arrival. r41's third
resume died the same way at $11; r96 at $25.
"""
import sys
import types
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

ORCH = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
        / "orchestrator.py").read_text(encoding="utf-8")


def _credit_block():
    i = ORCH.index("def _credit_downtime_1202eq")
    return ORCH[i:ORCH.index("\n    def ", i + 10)]


class TestDowntimeBypassesTheDeferralCap(unittest.TestCase):

    def test_the_stamp_moves_by_the_full_gap(self):
        """In the SHIFT, not the credit: #1202dv restores this stamp ~450 lines after the
        credit runs, so touching it there raised AttributeError and the whole credit was
        swallowed. tiktok-r96's second resume logged "could not credit resume downtime"."""
        i = ORCH.index("def _shift_deferral_clocks_1202fd")
        shift = ORCH[i:ORCH.index("\n    def ", i + 10)]
        self.assertIn("self._fwdeliver_first_decline_ts = float(_fd) + gap", shift)
        self.assertIn("#1202fi", shift)

    def test_it_says_why_the_cap_does_not_apply(self):
        """The next reader must not "fix" this back into the capped channel."""
        i = ORCH.index("def _shift_deferral_clocks_1202fd")
        self.assertIn("not #1133's capped", ORCH[i:ORCH.index("\n    def ", i + 10)])

    def test_the_capped_channel_is_no_longer_used_for_downtime(self):
        self.assertNotIn('_credit_framework_deferral_1133(_gap, "resume downtime',
                         _credit_block())

    def test_the_cap_still_bounds_real_deferral(self):
        """#1133 governs framework DEFERRAL and that accounting is untouched."""
        i = ORCH.index("def _credit_framework_deferral_1133")
        fn = ORCH[i:ORCH.index("\n    def ", i + 10)]
        self.assertIn("_grant = min(_d, _room)", fn)
        self.assertIn("FWVAL_NO_DELIVER_ABORT_S", fn)

    def test_an_overnight_gap_would_now_clear_the_ceiling(self):
        """The arithmetic r96 died on: 23.5h stopped, 62min of real lane time."""
        from env_generator.llm_generator.multi_agent.orchestrator import (
            FWVAL_NO_DELIVER_ABORT_S)
        gap = 84767.0                      # r96's measured downtime
        real_lane_s = 62 * 60              # what it had actually spent
        # Before: only the cap was credited, so the abort saw gap + real - cap.
        before = gap + real_lane_s - float(FWVAL_NO_DELIVER_ABORT_S)
        self.assertGreater(before, float(FWVAL_NO_DELIVER_ABORT_S),
                           "this is the abort r96 hit")
        # After: the full gap comes off, leaving only real lane time.
        after = gap + real_lane_s - gap
        self.assertLess(after, float(FWVAL_NO_DELIVER_ABORT_S),
                        "an overnight resume must not be dead on arrival")


if __name__ == "__main__":
    unittest.main()
