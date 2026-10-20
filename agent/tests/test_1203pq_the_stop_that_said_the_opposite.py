r"""#1203pq: the ledger said the run hit its budget, beside a sentence saying it stopped
early precisely so it would NOT hit its budget.

`_stop_status_1202ik` chose between the two stops by testing the reason sentence for the
phrase "never SUCCEEDED". Exactly one of the two fail-fast paths writes that phrase:

    DELIVERY-GATE NO-CONVERGENCE ABORT  "delivery never SUCCEEDED in {n}min of lane time ..."
    DELIVERY-GATE STUCK-ABORT           "delivery gate stuck on [...] -- no lane is making
                                         progress; failing fast instead of spinning to
                                         wall-clock."

So the deliver-stuck abort was filed as `budget_exceeded`. The site that wrote it had the
answer: its own `_write_run_budget` call two lines below passes the literal "stuck_abort".
The terminal write at the end of `run()` then recomputed the status from the sentence and
disagreed with it.

tiktok-web-r189 carries the contradiction on disk -- `status: "budget_exceeded"` beside that
sentence, with 13% of its $1000, 53% of its wall clock and 11% of its ticks unspent. It is
also the one run of the newest nine that was genuinely stopped by a framework defect rather
than by its own cap, and the recorded procedure for attributing a run's death says to set
`budget_exceeded` runs aside -- so the wrong word hid the one run worth reading.

Driven on the predicate directly: it reads only `getattr(self, ...)`, so a plain object with
the right attributes is the whole fixture. #1202ik's own docstring states the stake -- "A cap
says 'raise it or accept it'; a no-convergence abort says 'nothing converged in the time you
gave it' -- opposite advice from the same word."
"""
import ast
import inspect
import unittest

from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
from env_generator.llm_generator.multi_agent.runtime import message_format as MF

_STUCK = ("delivery gate stuck on ['deliverability_ui_flow_failed', "
          "'unresolved_failed_tasks', 'validation_ui_evidence_failed'] for 7 consecutive "
          "cycles with NO source/contract/chain change after api_smoke passed - no lane is "
          "making progress; failing fast instead of spinning to wall-clock.")
_NOCONV = ("delivery never SUCCEEDED in 243min of lane time since the contract built (now "
           "failing ['x']) - the lanes are active but not converging on a clean gate; "
           "failing fast instead of livelocking to wall-clock.")
_CAP = "wall-clock 7209s exceeded cap 7200s"


class _Stop:
    """Only what the predicate reads."""

    def __init__(self, reason="", kind=None):
        self._budget_stop_1202if = reason
        if kind is not None:
            self._budget_stop_kind_1203pq = kind


def _status(reason="", kind=None):
    return Orchestrator._stop_status_1202ik(_Stop(reason, kind))


class TheStopIsNamedByTheSiteThatKnew(unittest.TestCase):

    def setUp(self):
        MF._WARNED_1201.discard("orchestrator._stop_status_1202ik.no_kind_1203pq")
        self.addCleanup(MF._WARNED_1201.discard,
                        "orchestrator._stop_status_1202ik.no_kind_1203pq")

    def test_the_deliver_stuck_abort_is_a_stuck_abort(self):
        """★ THE TICKET, in r189's exact words."""
        self.assertEqual(_status(_STUCK, "stuck_abort"), "stuck_abort")

    def test_a_cap_is_still_a_cap(self):
        self.assertEqual(_status(_CAP, "budget_exceeded"), "budget_exceeded")

    def test_the_recorded_kind_beats_the_sentence(self):
        """The whole point: the sentence is not the witness. Driven with prose that
        contradicts the kind, so a predicate that still read the prose would fail here."""
        self.assertEqual(_status(_NOCONV, "budget_exceeded"), "budget_exceeded")
        self.assertEqual(_status(_CAP, "stuck_abort"), "stuck_abort")

    def test_the_no_convergence_abort_is_unchanged(self):
        """#1202ik's own case must keep its answer."""
        self.assertEqual(_status(_NOCONV, "stuck_abort"), "stuck_abort")

    def test_a_stop_with_no_kind_still_answers(self):
        """A third writer that forgets is a possibility, and this must not become the reason
        a run record cannot be written."""
        self.assertEqual(_status(_NOCONV), "stuck_abort")
        self.assertEqual(_status(_CAP), "budget_exceeded")

    def test_a_guess_is_not_silent(self):
        """#883/#1201: the phrase test is the thing this ticket stopped trusting, so falling
        back to it has to be audible rather than looking like an answer."""
        said = []
        orig = MF.warn_once_1201
        # EXACTLY the real signature (`exc` has no default). The first spy here allowed a
        # two-argument call, so it passed while the real `warn_once_1201` raised a TypeError
        # that the method swallowed into "budget_exceeded". A spy looser than the function it
        # stands in for tests the spy.
        MF.warn_once_1201 = lambda site, what, exc: said.append((site, what))
        try:
            _status(_STUCK)
        finally:
            MF.warn_once_1201 = orig
        self.assertEqual(len(said), 1, said)
        self.assertIn("which stop it was", said[0][1])

    def test_no_stop_at_all_is_not_a_guess(self):
        """`_stop_status_1202ik` is only consulted when a stop sentence exists, but an empty
        one must not produce a warning about a stop that never happened (#983)."""
        said = []
        orig = MF.warn_once_1201
        MF.warn_once_1201 = lambda site, what, exc: said.append(site)
        try:
            out = _status("")
        finally:
            MF.warn_once_1201 = orig
        self.assertEqual(out, "budget_exceeded")
        self.assertEqual(said, [])

    def test_it_never_raises(self):
        class _Hostile:
            @property
            def _budget_stop_kind_1203pq(self):
                raise RuntimeError("boom")

        self.assertEqual(Orchestrator._stop_status_1202ik(_Hostile()), "budget_exceeded")


class BothWritersSayWhichStopItWas(unittest.TestCase):
    """#1032: the fix is only a fix while every writer carries it.

    Structural, not textual: the assignment is located in the parse tree and its SIBLINGS
    are inspected. A version that asserted the two strings appear in the source would be
    satisfied by this file's own quoting of them, and by the comments at the sites.
    """

    def _assign_blocks(self):
        tree = ast.parse(inspect.getsource(
            __import__("env_generator.llm_generator.multi_agent.orchestrator",
                       fromlist=["x"])))
        # EVERY statement list, not just `body`: the fail-fast writer lives in an `else:`,
        # which is `If.orelse`, and the first version of this scan found ONE writer and said
        # so -- a scan that reports half the sites reads exactly like a tree with half the
        # sites in it.
        out = []
        for node in ast.walk(tree):
            for field in ("body", "orelse", "finalbody", "handlers"):
                block = getattr(node, field, None)
                if not isinstance(block, list):
                    continue
                for st in block:
                    if (isinstance(st, ast.Assign)
                            and any(getattr(tg, "attr", "") == "_budget_stop_1202if"
                                    for tg in st.targets)):
                        out.append(block)
        return out

    def test_there_are_exactly_two_writers(self):
        self.assertEqual(len(self._assign_blocks()), 2,
                         "a writer of _budget_stop_1202if was added or removed; it must also "
                         "record which stop it is")

    def test_each_writer_records_the_kind_in_the_same_block(self):
        for block in self._assign_blocks():
            kinds = [st for st in block
                     if isinstance(st, ast.Assign)
                     and any(getattr(t, "attr", "") == "_budget_stop_kind_1203pq"
                             for t in st.targets)]
            self.assertEqual(len(kinds), 1,
                             "a site sets the stop sentence without saying which stop it is: "
                             + "; ".join(ast.unparse(s)[:60] for s in block[:4]))

    def test_the_two_writers_record_DIFFERENT_kinds(self):
        """If both recorded the same word the predicate would be consistent and useless."""
        got = set()
        for block in self._assign_blocks():
            for st in block:
                if (isinstance(st, ast.Assign)
                        and any(getattr(t, "attr", "") == "_budget_stop_kind_1203pq"
                                for t in st.targets)
                        and isinstance(st.value, ast.Constant)):
                    got.add(st.value.value)
        self.assertEqual(got, {"budget_exceeded", "stuck_abort"}, got)


if __name__ == "__main__":
    unittest.main()
