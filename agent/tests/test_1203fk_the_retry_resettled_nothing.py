r"""#1203fk: the retry promised a settled directory and nothing settled it.

`_RACE_NOTE_1202IW` has told every reader since #1202iw that "the retry below re-tars a
SETTLED directory and succeeds", and `_build_with_retry`'s own docstring says "The retry
clears it every time". Neither was implemented: the retry re-ran `docker build` immediately,
so when the lanes are writing continuously the second tar loses the same race as the first.

r159 is the bill. Its last two minutes:

    09:14:38  docker build -> rc=1   Error processing tar file(exit status 1): unexpected EOF
    09:15:07  docker build -> rc=1   (same)
    09:15:07  SOURCE-EDIT PROGRESS: ... a lane is actively editing
    09:15:59  docker build -> rc=1   (same)
    09:16:22  docker build -> rc=1   (same)

All four `build:*` CodeHub checks went to `status=failure` carrying that note; those checks
are what `verification_checklist_not_ready` reads; the orchestrator's last message was
"Delivery gate is otherwise green, but deliver_project is still refused by
verification_checklist_not_ready"; and the run hit the 7200s milestone wall cap having
delivered nothing, at $268.88.

Scope, measured rather than assumed: the race signature appears 299 times across 37 corpus
logs (#1202iw measured 26 of 423 failed builds, 6.1%), but of the SEVEN runs whose terminal
gate record carried `verification_checklist_not_ready`, r159 is the only one whose `build:*`
checks died of this race -- r144's was `Connection refused`, and the four older ones carry no
detail at all. One lost run and 299 wasted builds, so the fix is a bounded wait, not a
redesign.

Two halves:
  * the retry now settles the context first -- same condition the note always described;
  * the note stops promising a retry on the attempt where there is none. r159's four checks
    each shipped "the retry below ... succeeds" with the attempts already spent.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import validation_runner as VR  # noqa: E402

SRC = LLM_DIR / "multi_agent" / "runtime" / "validation_runner.py"


def _seq(*fingerprints):
    """A fingerprint sequence IS the scenario; the last value repeats forever."""
    box = list(fingerprints)

    def _next():
        return box.pop(0) if len(box) > 1 else box[0]
    return _next


class TheWaitIsBoundedAndHonest(unittest.TestCase):
    def _settle(self, fp, **kw):
        kw.setdefault("sample", 1.0)
        kw.setdefault("stable", 2)
        kw.setdefault("cap", 30.0)
        self.slept = []
        ticks = [0.0]

        def _sleep(s):
            self.slept.append(s)
            ticks[0] += s
        return VR._settle_build_context_1203fk(
            "ignored", fingerprint=fp, sleep=_sleep, clock=lambda: ticks[0], **kw)

    def test_a_quiet_tree_settles_immediately(self):
        settled, waited = self._settle(_seq((3, 100, 7)))
        self.assertTrue(settled)
        self.assertLessEqual(waited, 1.0)

    def test_a_tree_that_goes_quiet_settles_after_it_does(self):
        # two changes, then quiet -- r159's shape, where the lanes stop between edits
        settled, waited = self._settle(
            _seq((3, 100, 7), (3, 140, 9), (4, 200, 11), (4, 200, 11), (4, 200, 11)))
        self.assertTrue(settled)
        self.assertGreater(waited, 1.0)

    def test_a_tree_that_never_settles_gives_up_at_the_cap(self):
        """The build must still RUN. Returning settled=False is how the caller learns it is
        tarring a moving tree, which is exactly what it did before this existed."""
        n = [0]

        def _always_changing():
            n[0] += 1
            return (n[0], n[0] * 10, n[0])
        settled, waited = self._settle(_always_changing, cap=5.0)
        self.assertFalse(settled)
        self.assertLessEqual(waited, 6.0)
        self.assertGreaterEqual(waited, 5.0)

    def test_size_alone_is_enough_to_count_as_movement(self):
        """The race is a file whose SIZE changed between docker's stat and its read, so an
        editor that rewrites within one mtime granule must still read as movement."""
        settled, _ = self._settle(
            _seq((4, 100, 7), (4, 180, 7), (4, 180, 7), (4, 180, 7)), cap=30.0)
        self.assertTrue(settled)          # it settles, but only AFTER the size stopped moving
        changing = _seq((4, 100, 7), (4, 180, 7), (4, 260, 7), (4, 340, 7))
        settled2, _ = self._settle(changing, cap=3.0)
        self.assertFalse(settled2)

    def test_a_fingerprint_that_raises_never_blocks_the_build(self):
        def _boom():
            raise OSError("vanished")
        settled, waited = self._settle(_boom)
        self.assertFalse(settled)
        self.assertEqual(waited, 0.0)

    def test_a_stable_sentinel_is_not_a_quiet_tree(self):
        """(-1, -1, -1) means the fingerprint could not read the tree, and it is perfectly
        stable -- so without this the settle would report a quiet context for a directory it
        never found. That is the fallback that masks a failure, and it is the one shape where
        "nothing changed" must not mean "settled"."""
        settled, waited = self._settle(_seq((-1, -1, -1)))
        self.assertFalse(settled)
        self.assertEqual(waited, 0.0)
        self.assertEqual(self.slept, [], "it waited on a tree it could not read")

    def test_asking_for_no_stability_asks_for_no_wait(self):
        for kw in ({"stable": 1}, {"stable": 0}, {"cap": 0.0}, {"cap": -1.0}):
            settled, waited = self._settle(_seq((1, 1, 1)), **kw)
            self.assertFalse(settled, kw)
            self.assertEqual(waited, 0.0, kw)


class TheFingerprintReadsARealTree(unittest.TestCase):
    def test_it_moves_when_a_file_grows_and_not_otherwise(self):
        d = Path(tempfile.mkdtemp())
        (d / "a.js").write_text("x", encoding="utf-8")
        before = VR._context_fingerprint_1203fk(d)
        self.assertEqual(before, VR._context_fingerprint_1203fk(d))
        (d / "a.js").write_text("xxxxxxxx", encoding="utf-8")
        self.assertNotEqual(before, VR._context_fingerprint_1203fk(d))

    def test_it_skips_the_directories_docker_never_tars_from_source(self):
        """node_modules churns constantly and is not what the lanes edit; counting it would
        mean the context never settles on any real app."""
        d = Path(tempfile.mkdtemp())
        (d / "src").mkdir()
        (d / "src" / "a.js").write_text("x", encoding="utf-8")
        base = VR._context_fingerprint_1203fk(d)
        (d / "node_modules").mkdir()
        (d / "node_modules" / "junk.js").write_text("y" * 100, encoding="utf-8")
        self.assertEqual(base, VR._context_fingerprint_1203fk(d))

    def test_an_unreadable_root_is_a_sentinel_not_an_exception(self):
        self.assertEqual(VR._context_fingerprint_1203fk(None), (-1, -1, -1))


class TheNoteStopsPromisingAbsentRetries(unittest.TestCase):
    def test_the_diagnosis_is_in_every_form(self):
        for form in (VR._RACE_NOTE_1202IW,
                     VR._RACE_DIAGNOSIS_1203FK + VR._RACE_RETRY_PROMISE_1203FK,
                     VR._RACE_DIAGNOSIS_1203FK + VR._RACE_EXHAUSTED_1203FK):
            self.assertIn("#1202iw", form)
            self.assertIn("NOT a defect in the application code", form)
            self.assertIn("do not rewrite the file docker named", form)

    def test_only_the_retry_form_promises_a_retry(self):
        self.assertIn("retry", VR._RACE_RETRY_PROMISE_1203FK.lower())
        self.assertNotIn("the retry below", VR._RACE_EXHAUSTED_1203FK.lower())
        self.assertIn("no retry left", VR._RACE_EXHAUSTED_1203FK.lower())

    def test_the_backward_compatible_name_is_the_retry_form(self):
        """The corpus before this patch carries `_RACE_NOTE_1202IW`, and the retry-bearing
        wording is the one that was right in the common case."""
        self.assertEqual(VR._RACE_NOTE_1202IW,
                         VR._RACE_DIAGNOSIS_1203FK + VR._RACE_RETRY_PROMISE_1203FK)


class TheRetryLoopUsesBoth(unittest.TestCase):
    """AST over the real function, and by ORDER: a settle placed after the next capture
    settles nothing, and a wait granted on a non-race attempt is a wait on app failures."""

    def _fn(self):
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_with_retry":
                return node
        self.fail("_build_with_retry is gone")

    def test_the_settle_is_guarded_by_the_race_and_by_an_attempt_remaining(self):
        fn = self._fn()
        calls = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_settle_build_context_1203fk"]
        self.assertEqual(len(calls), 1, "expected exactly one settle call")
        guards = [n for n in ast.walk(fn)
                  if isinstance(n, ast.If) and any(c is calls[0] for c in ast.walk(n))]
        self.assertTrue(guards, "the settle is unguarded")
        names = {n.id for g in guards for n in ast.walk(g.test) if isinstance(n, ast.Name)}
        self.assertIn("_this_race_1203fk", names, "the settle is not gated on the race")
        self.assertIn("_more_1203fk", names, "the settle runs with no attempt left to use it")

    def test_the_settle_precedes_the_next_build_capture(self):
        fn = self._fn()
        settle = [n.lineno for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "_settle_build_context_1203fk"]
        capture = [n.lineno for n in ast.walk(fn)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "_compose_capture"]
        self.assertTrue(settle and capture)
        # the capture is at the TOP of the loop body, so settling later in the body means the
        # next iteration's capture follows it -- which is the property that matters
        self.assertGreater(min(settle), min(capture))

    def test_the_exhausted_wording_is_what_the_last_attempt_gets(self):
        fn = self._fn()
        used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        self.assertIn("_RACE_EXHAUSTED_1203FK", used)
        self.assertIn("_RACE_RETRY_PROMISE_1203FK", used)
        # and the choice between them is made on whether an attempt remains
        ifexps = [n for n in ast.walk(fn) if isinstance(n, ast.IfExp)]
        chosen = [n for n in ifexps
                  if {getattr(x, "id", "") for x in (n.body, n.orelse)}
                  == {"_RACE_RETRY_PROMISE_1203FK", "_RACE_EXHAUSTED_1203FK"}]
        self.assertTrue(chosen, "nothing chooses between the two wordings")
        self.assertIn("_more_1203fk",
                      {n.id for n in ast.walk(chosen[0].test) if isinstance(n, ast.Name)})


if __name__ == "__main__":
    unittest.main()
