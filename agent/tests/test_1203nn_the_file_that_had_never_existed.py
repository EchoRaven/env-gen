r"""#1203nn: the gate said no run has EVER had a tasks/tasks.yaml. Two of them do.

`delivery_gate` publishes `matrix_skipped_reason` on every evaluation where
`task_suite_exists` is false. Its text read

    no tasks/tasks.yaml (0 of 172 runs have ever had one) — ...

and that parenthesis is false. MEASURED: 2 of the corpus's 106 run trees carry the file,
tiktok-web-r74 and tiktok-web-r92 (both July 2026). The string ships **8,698 times across 83
run logs** -- 467 of them in r190 and 96 in r191 -- so it is not a stale comment, it is a
sentence the framework tells its readers thousands of times per run.

The claim that DOES survive is about the FLAG rather than the file: `task_suite_exists` is
false in 0 of 8,556 gate evaluations across the 83 runs that record it. And the producer clause
survives too: neither file came from `save_task_suite`, which dumps `{name, description,
tasks}` with `default_flow_style=False`. r74 carries `version:`/`suite:` keys and an
inline-flow `headers: {X-Tenant-Id: ...}` that that dump cannot emit; r92 has no `name` at all.
Both were hand-written through a generic write tool.

WHY THE DISTINCTION IS LOAD-BEARING, not pedantry. Enforcement keys on a bare `.exists()`, so
ANY file at that path turns three gate checks on whatever its content is -- and two lanes wrote
one unprompted. 95 of the corpus's 1,514 `ok: true` evaluations (6.3%) carry `api_smoke_pass`
or `ui_smoke_pass` false at the same time, and every one of those would start blocking. Read as
"the file cannot exist", that is invisible; read correctly, it is a latent tightening.

DELIBERATELY UNCHANGED (#647, and #1202w6 -- a gate change gets verified on a live run first):
the verdict, the `.exists()` test, and the three checks. 0 of the 83 runs that record the flag
has the file, so there is no measured condition to harden against. Only the sentence moved.

★ A GREEN TEST WAS PINNING THE FALSEHOOD. `test_the_task_suite_branch_is_dead_1024.py` asserted
`"0 of 172 runs" in r` with the justification "It has never happened in any run" -- the same
false belief, held in place by a passing assertion. Its criterion is corrected in that file,
which already warns about exactly this shape one function earlier.
"""
import ast
import inspect
import pathlib
import unittest

import yaml

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


def _reason_string() -> str:
    """The assigned string, read through the AST so no COMMENT can satisfy an assertion.

    #943 and the `my-comment-quotes-the-code` trap: the fix's own comment quotes the false
    sentence verbatim (in capitals, to make it findable), so any assertion that greps the
    SOURCE for its absence would be fed by the explanation of the fix. Evaluate the literal.
    """
    tree = ast.parse(inspect.getsource(dg))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", "") == "matrix_skipped_reason" for t in node.targets):
            continue
        # `"" if task_suite_exists else (<implicitly concatenated string>)`
        val = node.value
        if isinstance(val, ast.IfExp):
            val = val.orelse
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            return val.value
    raise AssertionError("no `matrix_skipped_reason` string assignment found")


class TheFalseClauseIsGone(unittest.TestCase):
    def test_it_no_longer_claims_no_run_ever_had_the_file(self):
        self.assertNotIn("ever had one", _reason_string())

    def test_it_does_not_carry_the_old_172_count(self):
        self.assertNotIn("0 of 172 runs", _reason_string())

    def test_the_assertion_reads_the_literal_not_the_source(self):
        """Non-vacuity for the helper: the source DOES contain the false sentence (the fix's
        own comment quotes it), so a source-text assertion would be satisfied by the comment
        and the two assertions above would prove nothing."""
        src = inspect.getsource(dg)
        self.assertIn("EVER HAD ONE", src.upper(),
                      "the comment that quotes the false sentence is gone -- re-check that "
                      "the assertions above still read the literal rather than the source")
        self.assertNotIn("ever had one", _reason_string())


class EverythingLoadBearingSurvives(unittest.TestCase):
    def test_it_still_names_the_missing_file(self):
        self.assertIn("no tasks/tasks.yaml", _reason_string())

    def test_it_still_scopes_the_absence_to_this_run(self):
        self.assertIn("THIS run", _reason_string())

    def test_it_still_separates_evaluated_from_enforced(self):
        r = _reason_string()
        self.assertIn("ARE evaluated", r)
        self.assertIn("NOT ENFORCED", r)
        self.assertNotIn("were NOT evaluated", r)     # #1024's contradiction

    def test_it_still_names_all_three_gated_checks(self):
        r = _reason_string()
        for tok in ("validation_api_smoke_missing", "validation_ui_smoke_missing",
                    "validation_retry_pending"):
            with self.subTest(check=tok):
                self.assertIn(tok, r)

    def test_it_keeps_the_producer_clause(self):
        self.assertIn("save_task_suite", _reason_string())

    def test_it_carries_a_population_level_fact(self):
        """"not this run" alone is what #1024 added the structural half for."""
        self.assertIn("0 of 8,556 recorded gate evaluations", _reason_string())

    def test_it_says_the_two_trees_were_not_written_by_the_producer(self):
        self.assertIn("neither written by the", _reason_string())


class ItSaysHowEnforcementTurnsOn(unittest.TestCase):
    """The part a reader needs: the flag is a bare `.exists()`, not a framework decision."""

    def test_the_message_says_existence_is_what_enforces(self):
        self.assertIn("keys on the file EXISTING", _reason_string())

    def test_the_gate_really_keys_on_bare_existence(self):
        """Behaviour, so the sentence cannot drift from the code it describes."""
        self.assertIn('task_suite_exists = (output_dir / "tasks" / "tasks.yaml").exists()',
                      inspect.getsource(dg))


class TheVerdictIsUntouched(unittest.TestCase):
    """#647/#1202w6 -- the repair is to a sentence, not to a gate."""

    def _assignment_block(self) -> str:
        src = inspect.getsource(dg)
        i = src.index("matrix_skipped_reason = ")
        return src[i:src.index("if task_suite_exists:", i)]

    def test_the_reason_computation_appends_nothing(self):
        self.assertNotIn("failed_checks.append", self._assignment_block())

    def test_the_three_checks_are_still_gated_on_the_flag(self):
        src = inspect.getsource(dg)
        tree = ast.parse(src)
        found = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                    and node.test.id == "task_suite_exists"):
                dump = ast.dump(node)
                found = [t for t in ("validation_api_smoke_missing",
                                     "validation_ui_smoke_missing",
                                     "validation_retry_pending") if t in dump]
                break
        self.assertEqual(sorted(found), sorted(["validation_api_smoke_missing",
                                                "validation_ui_smoke_missing",
                                                "validation_retry_pending"]),
                         "the enforcement branch moved or stopped gating all three")

    def test_the_reason_is_empty_when_a_suite_exists(self):
        tree = ast.parse(inspect.getsource(dg))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", "") == "matrix_skipped_reason"
                            for t in node.targets)):
                self.assertIsInstance(node.value, ast.IfExp)
                self.assertIsInstance(node.value.body, ast.Constant)
                self.assertEqual(node.value.body.value, "")
                return
        raise AssertionError("no `matrix_skipped_reason` assignment found")


class WhatTheCorpusSays(unittest.TestCase):
    """The two measurements the correction rests on. Skipped where the tree is absent."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = pathlib.Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_at_least_one_run_tree_has_the_file(self):
        """The claim 'no run has ever had one' is refuted by the tree itself."""
        have = sorted(p.parts[-3] for p in self.corpus.glob("*/tasks/tasks.yaml"))
        if not have:
            self.skipTest("the runs that carry the file are no longer on this disk")
        self.assertTrue(have, have)

    def test_no_such_file_matches_the_producers_output_shape(self):
        """`save_task_suite` dumps {name, description, tasks}. A file lacking `name` cannot
        have come from it, which is why the producer clause stays."""
        checked = 0
        for p in self.corpus.glob("*/tasks/tasks.yaml"):
            try:
                doc = yaml.safe_load(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            checked += 1
            with self.subTest(run=p.parts[-3]):
                self.assertNotIn("name", doc,
                                 "%s looks like save_task_suite output after all -- the "
                                 "producer clause needs re-checking" % p.parts[-3])
        if not checked:
            self.skipTest("no parseable tasks.yaml on this disk")

    def test_the_flag_was_never_true_in_a_recorded_evaluation(self):
        """The surviving half of the original claim, re-measured over the bigger corpus."""
        import json
        total = true_ = 0
        for f in self.corpus.glob("*/logs/delivery_gate.jsonl"):
            for ln in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                vr = d.get("validation_runtime")
                if not isinstance(vr, dict) or "task_suite_exists" not in vr:
                    continue
                total += 1
                if vr.get("task_suite_exists") is True:
                    true_ += 1
        if not total:
            self.skipTest("no gate ledgers with the flag on this disk")
        self.assertEqual(true_, 0,
                         "a run DID have an active task suite -- enforcement has started "
                         "firing and the 6.3%% blast radius is now live, not latent")


if __name__ == "__main__":
    unittest.main()
