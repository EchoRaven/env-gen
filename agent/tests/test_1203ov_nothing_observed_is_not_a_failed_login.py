r"""#1203ov: "the walk observed nothing" and "the login failed" were the same verdict.

`_finalize_walkthrough` computes

    auth_ok = all(s["ok"] for s in steps) if steps else False

so an EMPTY step list is reported as a failed authentication. Demonstrated by running it: a
report with no steps and a report with one failing step produce BYTE-IDENTICAL output --

    no steps  -> auth_ok=False  summary="auth_ok=False; pages=1; blank=∅; ..."  signals={'auth_ok': False}
    bad step  -> auth_ok=False  summary="auth_ok=False; pages=1; blank=∅; ..."  signals={'auth_ok': False}

-- and `browser_report_unusable` is True for both. The two states have different causes and
different owners, and nothing downstream could tell them apart.

★ IT KILLED THE NEWEST RUN. r191's squad ledger says `spawned 12, completed 4, timed_out 8,
failed 0`; the browser walk therefore recorded no steps, and the delivery hold read

    browser_ui_unusable — "attempt 8; signals: auth_ok=False"

so a frontend P0 was dispatched about an app whose login was never exercised. r191 cut one
release.

MEASURED, and the cause is systemic rather than rare:
  * 730 `auth_ok=False` lines across 101 run logs; 14 of them (13 logs; 4 modern -- r183,
    r185 and r191 twice) have EVERY other signal empty, which is the signature of "nothing
    was observed";
  * over the 35 runs with a squad ledger, 169 of 399 spawned test-user agents TIMED OUT
    (42%) against only 8 outright failures; in the modern era 47 of 95 timed out (49%),
    r190 83% and r191 67%.

★ THE VERDICT DOES NOT MOVE. `auth_ok` stays False, `browser_report_unusable` is untouched,
and the signal set stays non-empty -- #883 fails closed, and #572 exists because a hold whose
message named nothing is its own defect. Only the REASON becomes correct. This file's own
comments name a FALSE "unusable" six times (lines 283, 444, 604, 649, 716, 805); not one of
them could separate these two.
"""
from __future__ import annotations

import collections
import glob
import io
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_runner import (  # noqa: E402
    _finalize_walkthrough as finalize,
    browser_report_unusable as unusable,
    browser_unusable_signals as signals)

_CORPUS = ROOT.parent / "generated"


def _report(steps, pages=None):
    return {"ran": True, "api_login_ok": False, "steps": list(steps),
            "pages": list(pages or [{"name": "home"}])}


class TheTwoStatesAreNowDistinguishable(unittest.TestCase):

    def test_the_step_count_is_recorded(self):
        self.assertEqual(finalize(_report([]))["auth_steps_1203ov"], 0)
        self.assertEqual(
            finalize(_report([{"name": "login", "ok": True}]))["auth_steps_1203ov"], 1)
        self.assertEqual(
            finalize(_report([{"ok": True}, {"ok": False}]))["auth_steps_1203ov"], 2)

    def test_no_steps_says_so_in_the_line_a_human_reads(self):
        s = finalize(_report([]))["summary"]
        self.assertIn("auth_ok=False", s)
        self.assertIn("no login steps recorded", s)

    def test_a_failed_step_is_not_dressed_as_a_missing_walk(self):
        s = finalize(_report([{"name": "login", "ok": False}]))["summary"]
        self.assertIn("auth_ok=False", s)
        self.assertNotIn("no login steps recorded", s)

    def test_a_passing_walk_says_neither(self):
        r = finalize(_report([{"name": "login", "ok": True}]))
        self.assertTrue(r["auth_ok"])
        self.assertNotIn("no login steps recorded", r["summary"])

    def test_the_signal_names_the_missing_walk(self):
        got = signals(finalize(_report([])))
        self.assertEqual(got.get("auth_walk_recorded_no_steps"), True, got)
        self.assertNotIn("auth_ok", got,
                         "the operator is still told the app's auth failed: %r" % got)

    def test_a_real_auth_failure_still_reports_auth_ok(self):
        got = signals(finalize(_report([{"name": "login", "ok": False}])))
        self.assertIn("auth_ok", got, got)
        self.assertNotIn("auth_walk_recorded_no_steps", got, got)

    def test_the_two_reports_no_longer_read_identically(self):
        """★ Non-vacuity, in the direction that matters: before this, the summaries and the
        signal dicts were byte-identical for the two shapes."""
        a = finalize(_report([]))
        b = finalize(_report([{"name": "login", "ok": False}]))
        self.assertNotEqual(a["summary"], b["summary"])
        self.assertNotEqual(signals(a), signals(b))


class TheWallDoesNotMove(unittest.TestCase):
    """#883 fails closed: a reason that got more honest must not let anything through."""

    def test_both_shapes_are_still_unusable(self):
        self.assertTrue(unusable(finalize(_report([]))))
        self.assertTrue(unusable(finalize(_report([{"name": "login", "ok": False}]))))

    def test_the_signal_set_is_never_empty_for_a_held_report(self):
        """#572: a hold whose message names nothing is its own defect -- so the no-steps case
        must REPLACE the signal, never remove it."""
        for steps in ([], [{"name": "login", "ok": False}]):
            with self.subTest(steps=len(steps)):
                r = finalize(_report(steps))
                self.assertTrue(unusable(r))
                self.assertTrue(signals(r), "held with no signal named")

    def test_a_clean_walk_is_still_usable(self):
        r = finalize(_report([{"name": "login", "ok": True}]))
        self.assertFalse(unusable(r))
        self.assertEqual(signals(r), {})

    def test_an_unrun_report_names_nothing(self):
        self.assertEqual(signals({"ran": False, "auth_steps_1203ov": 0}), {})

    def test_hostile_input_never_raises(self):
        for bad in (None, {}, {"ran": True}, {"ran": True, "steps": None}):
            with self.subTest(report=str(bad)[:30]):
                self.assertIsInstance(signals(bad if isinstance(bad, dict) else {}), dict)
                self.assertIsInstance(unusable(bad), bool)


class WhatTheCorpusSays(unittest.TestCase):

    def setUp(self):
        if not _CORPUS.is_dir():
            self.skipTest("no corpus on this disk")

    def test_half_the_modern_test_user_squad_times_out(self):
        """The throughput fact this misreports: the agents that do not finish TIME OUT, they
        do not fail -- 169 timeouts against 8 failures over 399 spawns.

        ★ I first wrote "failed is zero throughout" from a printout capped at 16 rows, every
        one of which happened to read 0. The aggregate is 8. A count read off a truncated
        view is the #1034 trap pointed at myself."""
        tot_s = tot_t = tot_f = 0
        mod_s = mod_t = 0
        runs = 0
        for f in sorted(glob.glob(str(_CORPUS / "*" / "logs"
                                      / "test_user_squad_1202wn.jsonl"))):
            run = Path(f).parents[1].name
            last = None
            for line in io.open(f, encoding="utf-8", errors="replace"):
                try:
                    last = json.loads(line)
                except Exception:
                    pass
            if not last:
                continue
            runs += 1
            s, t, fl = (int(last.get("spawned") or 0), int(last.get("timed_out") or 0),
                        int(last.get("failed") or 0))
            tot_s += s
            tot_t += t
            tot_f += fl
            m = re.search(r"r(\d+)$", run)
            if m and int(m.group(1)) >= 183:
                mod_s += s
                mod_t += t
        self.assertGreater(runs, 30, "only %d squad ledgers read" % runs)
        self.assertEqual((tot_s, tot_t, tot_f), (399, 169, 8))
        self.assertEqual((mod_s, mod_t), (95, 47))

    def test_the_signature_of_observing_nothing_is_in_the_logs(self):
        """`auth_ok=False` with every other signal empty -- 14 lines in 13 logs, 4 of them
        modern. If a future run stops producing it, this goes red and the trade-off is
        re-read with a number."""
        allempty = re.compile(r"auth_ok=False blank=\[\] console_errors=\[\] hollow=False "
                              r"login_wall=\[\] visual_mismatches=\[\]")
        logs = sorted(glob.glob(str(_CORPUS.parent / "gm_*.log")))
        if not logs:
            self.skipTest("the run logs are not beside this checkout")
        hits, files = 0, set()
        for f in logs:
            for line in io.open(f, encoding="utf-8", errors="replace"):
                if "auth_ok=False" in line and allempty.search(line):
                    hits += 1
                    files.add(f)
        self.assertGreater(len(logs), 100, "only %d run logs read" % len(logs))
        self.assertEqual((hits, len(files)), (14, 13))


if __name__ == "__main__":
    unittest.main()
