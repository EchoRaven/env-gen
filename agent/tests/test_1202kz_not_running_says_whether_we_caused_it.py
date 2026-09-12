"""#1202kz: `NOT RUNNING` must say whether THIS process caused it.

`is NOT RUNNING` is the corpus's most-emitted error -- 3852 times across 21 days of logs --
and all 3852 carry the same alarmed wording. Classified against this process's own preceding
compose lifecycle verb:

    1899 (49.3%)  follow our own `down`            -> EXPECTED
     525 (13.6%)  precede any start at all         -> expected
    1428 (37.1%)  follow an `up` that returned 0   -> ANOMALOUS

So the genuinely broken cases sit 2:1 underneath the ones we caused on purpose, in language
that cannot tell them apart. The corpus cycles hard enough for that to matter: 2318 `up`
against 2541 `down` across 99 runs (netflix-r30 alone: 138 up / 143 down).

This also explains a neighbouring mechanism rather than replacing it. #1202av answers "it
existed and died -- here is the exit code", and answers it for 6 of those 3852 (0.2%): a
project that was torn down leaves nothing in `ps -a` to inspect. #1202av is not broken; it is
asking a question that is usually unanswerable by then.

WHAT IS VERIFIED: the three states produce three different sentences; only teardown verbs read
as EXPECTED; a non-lifecycle verb (`build`) is not recorded; the note is actually appended to
the NOT RUNNING message rather than merely defined; and neither helper raises on junk.

WHAT IS NOT: that it can speak for any other process. RunHub drives the same compose project
from its own subprocess (#1202hn), so an empty record means "not this process", never
"nobody" -- and the wording says exactly that instead of claiming the stronger thing.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import compose_mutex as cm  # noqa: E402
from multi_agent.runtime import container_runtime as cr  # noqa: E402


class TheThreeStatesReadDifferently(unittest.TestCase):

    def setUp(self):
        cm._LAST_LIFECYCLE_1202KZ.clear()
        self.f = "/tmp/kz-%s/docker-compose.yml" % id(self)

    def test_never_started_says_so_without_claiming_nobody_did(self):
        said = cr._own_lifecycle_note_1202kz(self.f)
        self.assertIn("has not run any compose lifecycle", said)
        # must NOT claim nobody started it -- RunHub is another process
        self.assertIn("another process still might have", said)

    def test_after_our_own_down_it_reads_expected(self):
        cm.record_lifecycle_1202kz(self.f, "down")
        said = cr._own_lifecycle_note_1202kz(self.f)
        self.assertIn("EXPECTED", said)
        self.assertNotIn("ANOMALOUS", said)

    def test_after_our_own_up_it_reads_anomalous(self):
        """★ The 37% that are real."""
        cm.record_lifecycle_1202kz(self.f, "up")
        said = cr._own_lifecycle_note_1202kz(self.f)
        self.assertIn("ANOMALOUS", said)
        self.assertNotIn("EXPECTED", said)

    def test_every_teardown_verb_reads_expected(self):
        for verb in ("down", "stop", "rm", "kill"):
            cm._LAST_LIFECYCLE_1202KZ.clear()
            cm.record_lifecycle_1202kz(self.f, verb)
            self.assertIn("EXPECTED", cr._own_lifecycle_note_1202kz(self.f), verb)

    def test_a_non_lifecycle_verb_is_not_recorded(self):
        """`build` says nothing about whether the stack should be up."""
        cm.record_lifecycle_1202kz(self.f, "build")
        self.assertIsNone(cm.last_lifecycle_1202kz(self.f))

    def test_the_record_is_per_project(self):
        cm.record_lifecycle_1202kz(self.f, "down")
        self.assertIsNone(cm.last_lifecycle_1202kz(self.f + ".other"))

    def test_neither_helper_raises_on_junk(self):
        cm.record_lifecycle_1202kz(None, None)
        self.assertIsNone(cm.last_lifecycle_1202kz(None))
        self.assertIsInstance(cr._own_lifecycle_note_1202kz(None), str)


class ItIsActuallyAppended(unittest.TestCase):
    """Reachability, not presence (#1202ka): a note nothing appends says nothing."""

    def test_the_note_is_called_inside_container_id(self):
        tree = ast.parse(Path(cr.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "container_id")
        called = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                  and getattr(n.func, "id", "") == "_own_lifecycle_note_1202kz"]
        self.assertTrue(called, "the note is never appended to the NOT RUNNING message")

    def test_the_producer_is_wired_in_validation_runner(self):
        """The note can only speak if something records the verb."""
        vr = Path(cr.__file__).parent / "validation_runner.py"
        tree = ast.parse(vr.read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        imported = {a.name for n in ast.walk(tree)
                    if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertIn("record_lifecycle_1202kz", names | imported,
                      "validation_runner never records the lifecycle verb")


if __name__ == "__main__":
    unittest.main()
