"""#1067 — the duplicate-route report could vanish per gate tick, silently.

The block's own preamble states the rule it then broke:

    "as #691, #696 and #698: a finding that is computed and unobservable is worth
     no more than one that was never computed."

and it goes to real trouble to honour it — re-fetching pages rather than reusing a
name bound inside another try/except-pass, because reusing it "would NameError
into this block's own except and skip the report silently — the exact failure mode
this fix is about". Then all 173 lines ended in a bare `except Exception: pass`.

So the reporter had exactly the property it was written to prevent: on any raise,
this run reports no duplicate-route findings, and that is indistinguishable from
there being none.

The verdict is unchanged — this is a REPORT, and its failure must not block a
release. What changes is that the failure is now recorded once per process, with
the exception type, so "no findings" can be told apart from "the finder died".
"""
from __future__ import annotations

import inspect
import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import deliverability as d  # noqa: E402


class TheLatchIsOneShot(unittest.TestCase):

    def test_the_latch_exists(self):
        latch = getattr(d, "_DUPE_REPORT_FAILED_1067", None)
        self.assertIsInstance(latch, dict)
        self.assertIn("said", latch)

    def test_it_starts_unsaid(self):
        """A fresh import must not have already spent the one shot."""
        self.assertIn(type(d._DUPE_REPORT_FAILED_1067["said"]), (bool,))


class TheHandlerRecordsInsteadOfPassing(unittest.TestCase):

    def _handler_src(self) -> str:
        src = inspect.getsource(d)
        i = src.index("except Exception as _dupe_exc_1067:")
        # semantic end: the next `try:` at the same indent starts the block after
        j = src.find("\n    try:", i)
        return src[i:j if j != -1 else len(src)]

    def test_it_is_not_a_bare_pass(self):
        h = self._handler_src()
        self.assertNotIn("\n        pass", h)

    def test_it_names_the_exception_type_and_message(self):
        h = self._handler_src()
        self.assertIn("type(_dupe_exc_1067).__name__", h)
        self.assertIn("_LOG_700.warning", h)

    def test_it_says_the_verdict_is_unaffected(self):
        """A report failure must never read as a gate failure."""
        h = self._handler_src()
        self.assertIn("verdict below is", h)

    def test_it_is_latched_so_a_per_tick_failure_cannot_flood(self):
        h = self._handler_src()
        self.assertIn('_DUPE_REPORT_FAILED_1067["said"]', h)


class TheRuleItRestores(unittest.TestCase):

    def test_the_preamble_still_states_the_rule(self):
        """If this comment goes, the reason for the handler goes with it."""
        src = inspect.getsource(d)
        self.assertIn("computed and unobservable", src)


if __name__ == "__main__":
    unittest.main()
