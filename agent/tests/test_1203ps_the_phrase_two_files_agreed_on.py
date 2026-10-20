r"""#1203ps: two files agreed on a sentence, and nothing made them keep agreeing.

`chain_executor` marks a cleared cross-user denial probe `kind="skipped"` and writes a note
saying why. `remediation_dispatcher._step_is_actionable_1202gx` decides whether a skipped
step is unexplained starvation (#188's class -- report it) or a row #78 already cleared (do
not), and it decided by testing that note for the exact wording. The coupling is deliberate
and its docstring says so; what it lacked was an owner.

MEASURED: 56 recorded steps in the corpus carry `kind="skipped"` AND the phrase, 1 of them
modern, so the branch is live. (My first scan of this said ZERO -- it looked for
`steps[].kind` in `registryhub_*.json` and `logs/*.jsonl`, and the notes live in
`workhub_tasks.json`, `eventhub_events.json` and `registryhub_verification_chains.json`. The
phrase is in 113 corpus files. A zero that is mine reads exactly like a zero that is the
framework's.)

Rewording the writer's string would silently flip those rows back into "fix THESE" lists --
and `test_1202gx_a_cleared_probe_is_not_a_broken_step.py` builds the note in its OWN fixture,
so it would stay green while the two files stopped agreeing.

The precedent sits 200 lines above the reader: `_route_ran_note_1052_1202wx` -- "#1052's
warning, imported rather than restated".
"""
import ast
import inspect
import unittest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as RD
from env_generator.llm_generator.multi_agent.runtime import message_format as MF

PHRASE = CE.FRESH_INTRUDER_REVERIFIED_1203PS


class TheWriterOwnsThePhrase(unittest.TestCase):

    def test_the_constant_exists_and_is_the_matched_substring(self):
        self.assertTrue(PHRASE.strip())
        self.assertIn("FRESH intruder", PHRASE)

    def test_the_note_is_BUILT_from_the_constant(self):
        """Structural, not textual: the note expression must REFERENCE the constant. An
        assertion that the phrase appears in the module source would be satisfied by the
        constant's own definition and by every comment quoting it -- including this file's
        docstring, which quotes it too."""
        tree = ast.parse(inspect.getsource(CE))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "execute_chain")
        built = []
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", "") == "note" for t in node.targets)):
                names = {getattr(x, "id", "") for x in ast.walk(node.value)
                         if isinstance(x, ast.Name)}
                if "FRESH_INTRUDER_REVERIFIED_1203PS" in names:
                    built.append(node)
        self.assertEqual(len(built), 1,
                         "the #78 note no longer builds itself from the owned constant")

    def test_no_note_in_the_writer_SPELLS_the_phrase_again(self):
        """The point of the ticket: one spelling. A second literal would drift."""
        tree = ast.parse(inspect.getsource(CE))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "execute_chain")
        literals = [c.value for c in ast.walk(fn)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and PHRASE in c.value]
        self.assertEqual(literals, [], literals)


class TheReaderImportsIt(unittest.TestCase):

    def setUp(self):
        MF._WARNED_1201.discard("remediation_dispatcher._fresh_intruder_phrase_1203ps")
        self.addCleanup(MF._WARNED_1201.discard,
                        "remediation_dispatcher._fresh_intruder_phrase_1203ps")

    def test_it_returns_the_writers_own_phrase(self):
        self.assertEqual(RD._fresh_intruder_phrase_1203ps(), PHRASE)

    def test_a_cleared_probe_is_still_not_actionable(self):
        """★ The behaviour #1202gx bought, driven through the real predicate with a note
        built the way the writer builds it."""
        note = "cross-user denial " + PHRASE + " → DENIED; the original 200 was stale"
        self.assertFalse(RD._step_is_actionable_1202gx(
            {"ok": False, "kind": "skipped", "note": note}))

    def test_a_skip_for_any_OTHER_reason_is_still_reported(self):
        """#647: narrow on purpose. Swallowing other skips would hide #188's starvation."""
        self.assertTrue(RD._step_is_actionable_1202gx(
            {"ok": False, "kind": "skipped", "note": "skipped: no seed row to act on"}))

    def test_a_failing_step_that_was_not_skipped_is_still_reported(self):
        self.assertTrue(RD._step_is_actionable_1202gx(
            {"ok": False, "kind": "broken", "note": "cross-user denial " + PHRASE}))

    def test_the_PREDICATE_calls_the_owner_rather_than_a_literal(self):
        """★ A mutation caught this missing: restating the literal in the predicate is
        behaviour-identical TODAY (the literal equals the constant), so only a STRUCTURAL
        assertion can see it -- and "one owner" is a structural property by nature. Read off
        the parse tree: the note comparison must reference the helper, and no string constant
        in the function may spell the phrase.
        """
        tree = ast.parse(inspect.getsource(RD._step_is_actionable_1202gx))
        names = {getattr(n, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertIn("_fresh_intruder_phrase_1203ps", names,
                      "the predicate no longer asks the owner for the phrase")
        spelled = [c.value for c in ast.walk(tree)
                   if isinstance(c, ast.Constant) and isinstance(c.value, str)
                   and "FRESH intruder" in c.value]
        self.assertEqual(spelled, [], spelled)

    def test_a_passing_step_is_not_work(self):
        self.assertFalse(RD._step_is_actionable_1202gx({"ok": True}))


class TheFallbackCannotSilenceEverything(unittest.TestCase):
    """★★ The sharp edge. `phrase in note` with an EMPTY phrase is true of every note, so a
    fallback of "" would silence every skipped step in the run -- the exact class #188 exists
    to surface, turned off by an import error."""

    def setUp(self):
        MF._WARNED_1201.discard("remediation_dispatcher._fresh_intruder_phrase_1203ps")
        self.addCleanup(MF._WARNED_1201.discard,
                        "remediation_dispatcher._fresh_intruder_phrase_1203ps")
        self._saved = CE.FRESH_INTRUDER_REVERIFIED_1203PS

        def _restore():
            CE.FRESH_INTRUDER_REVERIFIED_1203PS = self._saved
        self.addCleanup(_restore)
        del CE.FRESH_INTRUDER_REVERIFIED_1203PS      # make the import fail

    def test_the_fallback_is_the_literal_not_an_empty_string(self):
        got = RD._fresh_intruder_phrase_1203ps()
        self.assertTrue(got.strip(), "an empty phrase matches EVERY note")
        self.assertEqual(got, self._saved, "the fallback drifted from the owned constant")

    def test_behaviour_is_unchanged_on_the_fallback_path(self):
        note = "cross-user denial " + self._saved + " → DENIED"
        self.assertFalse(RD._step_is_actionable_1202gx(
            {"ok": False, "kind": "skipped", "note": note}))
        self.assertTrue(RD._step_is_actionable_1202gx(
            {"ok": False, "kind": "skipped", "note": "something else entirely"}))

    def test_the_fallback_says_so(self):
        said = []
        orig = MF.warn_once_1201
        MF.warn_once_1201 = lambda site, what, exc: said.append((site, what))
        try:
            RD._fresh_intruder_phrase_1203ps()
        finally:
            MF.warn_once_1201 = orig
        self.assertEqual(len(said), 1, said)
        self.assertIn("restated copy", said[0][1])


if __name__ == "__main__":
    unittest.main()
