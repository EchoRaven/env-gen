r"""#1202bu: #728 said the same two things 382 times in one run.

netflix-r34:

    193x  #728 my_list_page (/browse/my-list) declares GET /api/titles, which shares
          no path word with its own route ...
    189x  #728 browse_home_page (/browse) declares GET /api/my-list ...

Two findings, 382 lines. The emitter loops over `crossed_page_endpoints_728` on every
deliverability_check, and the finding cannot change until a lane re-registers the page —
so every check reprints it. Same rule the repo already settled on in #1202n, #1202p,
#1202v, #1202ab and #1202au: report a STATE, not a heartbeat.

A finding that changes is news and reports again; that is what the state key is for, and
why this is not a log-once.
"""
import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

_SRC = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
        / "deliverability.py")


def _block():
    """Landmark-bounded (#943): the marker to the warning it guards."""
    src = _SRC.read_text(encoding="utf-8")
    i = src.index("#1202bu")
    j = src.index('"#728 %s (%s) declares', i)
    return src[i:j]


class CrossedEndpointWarningTests(unittest.TestCase):
    def test_the_warning_is_state_gated(self):
        self.assertIn("state_changed_1202ad", _block())

    def test_the_key_is_the_finding_set_not_a_counter(self):
        """Keyed on WHAT was found, so a changed set reports and a repeat does not."""
        b = _block()
        self.assertIn("crossed_page_endpoints_728", b)
        self.assertIn("sorted(", b)

    def test_it_still_reports_the_first_time(self):
        """Silencing a finding entirely would be worse than repeating it."""
        from multi_agent.runtime.message_format import (
            state_changed_1202ad, reset_state_memo_1202ad)
        reset_state_memo_1202ad("t1202bu")
        self.assertTrue(state_changed_1202ad("t1202bu", ("a", "b")))
        self.assertFalse(state_changed_1202ad("t1202bu", ("a", "b")))
        self.assertTrue(state_changed_1202ad("t1202bu", ("a", "b", "c")))

    def test_the_message_itself_is_unchanged(self):
        """Only the cadence changes — the text that names the cause stays."""
        src = _SRC.read_text(encoding="utf-8")
        self.assertIn("shares no path word with its own route", src)


if __name__ == "__main__":
    unittest.main()
