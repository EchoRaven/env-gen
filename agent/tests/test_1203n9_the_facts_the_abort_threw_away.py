r"""#1203n9: the aborted validation had the numbers; the summary reported None/None.

`run_test_user_validation` assembles its summary at the END of one try, so an exception at any
step discards everything the earlier steps collected. #1203n6/#1203n8 established what those
steps are and that they had run: all 6 ERROR reports in r189/r190/r191 carry a populated `api`
and `mcp`. The delivery line still read

    TEST-USER validation (v1.0.0): ERROR — None/None journey steps passed; ...

while the counts sat in the report file on disk.

MEASURED, per report:

    run              version   steps  passed   mcp tools    complete
    tiktok-web-r189  1.0.0       0      0         6/9         False
    tiktok-web-r190  1.0.0       7      5        11/12        False
    tiktok-web-r190  1.1.0       7      5        20/20        True
    tiktok-web-r190  1.2.0       9      6        30/30        True
    tiktok-web-r191  1.0.0       0      0         6/6         True
    tiktok-web-r191  1.1.0       0      0        22/16        True

3 of 6 gain real counts, and r190's 2-to-3 failing steps per report are the findings the
journey actually made -- `POST /api/comments -> 404` among them. r189's MCP surface was 6 of
9 tools and nothing said so.

FACTS ONLY. `api_steps`, `api_passed` and `mcp_complete` are measurements. `broken` and
`missing` are verdicts the ladder never reached, and #883 says "could not tell" must not be
dressed as an answer -- so they are not synthesised, and the verdict stays ERROR.

ABSENT IS NOT ZERO (#1203d3). `api_steps == 0` is a claim -- "the journey had nothing to
drive" -- which #1203jc's branch then explains in those words. An error that fired before the
journey ran must therefore produce NO `api_steps` key, not a zero.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.test_user_validation import (
    collected_facts_1203n9 as facts,
    describe_non_pass_1038,
)

# The six ERROR reports, as they are on disk.
_CORPUS = [
    ("r189 1.0.0", {"api": {"steps": []}, "mcp": {"complete": False, "tools_found": 6,
                                                  "tools_expected": 9}}, 0, 0, False),
    ("r190 1.0.0", {"api": {"steps": [{"ok": True}] * 5 + [{"ok": False}] * 2},
                    "mcp": {"complete": False}}, 7, 5, False),
    ("r190 1.1.0", {"api": {"steps": [{"ok": True}] * 5 + [{"ok": False}] * 2},
                    "mcp": {"complete": True}}, 7, 5, True),
    ("r190 1.2.0", {"api": {"steps": [{"ok": True}] * 6 + [{"ok": False}] * 3},
                    "mcp": {"complete": True}}, 9, 6, True),
    ("r191 1.0.0", {"api": {"steps": []}, "mcp": {"complete": True}}, 0, 0, True),
    ("r191 1.1.0", {"api": {"steps": []}, "mcp": {"complete": True}}, 0, 0, True),
]


class TheCountsComeBack(unittest.TestCase):
    def test_every_error_report_in_the_corpus(self):
        for name, report, steps, passed, complete in _CORPUS:
            with self.subTest(report=name):
                got = facts(report)
                self.assertEqual(got.get("api_steps"), steps)
                self.assertEqual(got.get("api_passed"), passed)
                self.assertEqual(got.get("mcp_complete"), complete)

    def test_r190s_line_stops_saying_none_over_none(self):
        """The symptom: the delivery line reads `summ["api_passed"]`/`summ["api_steps"]`."""
        summ = {"verdict": "ERROR", "error": "ImportError: x"}
        summ.update(facts(_CORPUS[1][1]))
        self.assertEqual((summ.get("api_passed"), summ.get("api_steps")), (5, 7))

    def test_r189s_incomplete_mcp_surface_is_named_again(self):
        summ = {"verdict": "ERROR", "error": "ImportError: x"}
        summ.update(facts(_CORPUS[0][1]))
        msg = describe_non_pass_1038(summ, _CORPUS[0][1]["mcp"])
        self.assertIn("MCP surface INCOMPLETE", msg)
        self.assertIn("6/9", msg)

    def test_a_complete_surface_is_not_reported_as_incomplete(self):
        summ = {"verdict": "ERROR", "error": "ImportError: x"}
        summ.update(facts(_CORPUS[2][1]))
        self.assertNotIn("MCP surface INCOMPLETE",
                         describe_non_pass_1038(summ, _CORPUS[2][1]["mcp"]))


class AbsentIsNotZero(unittest.TestCase):
    def test_no_api_key_means_no_api_claim(self):
        got = facts({"mcp": {"complete": True}})
        self.assertNotIn("api_steps", got)
        self.assertNotIn("api_passed", got)

    def test_no_mcp_key_means_no_mcp_claim(self):
        got = facts({"api": {"steps": []}})
        self.assertNotIn("mcp_complete", got)

    def test_an_mcp_without_a_complete_field_makes_no_claim(self):
        self.assertNotIn("mcp_complete", facts({"mcp": {"note": "mcp check error: boom"}}))

    def test_a_steps_field_that_is_not_a_list_makes_no_claim(self):
        for bad in ("nope", 7, {"a": 1}, None):
            with self.subTest(steps=repr(bad)):
                self.assertNotIn("api_steps", facts({"api": {"steps": bad}}))

    def test_an_empty_report_claims_nothing(self):
        self.assertEqual(facts({}), {})

    def test_the_not_walked_sentence_only_appears_for_a_real_zero(self):
        """#1203jc's branch asserts WHY there were no steps. It must not fire on absence."""
        absent = {"verdict": "ERROR", "error": "x"}
        absent.update(facts({"mcp": {"complete": True}}))
        self.assertNotIn("API JOURNEY NOT WALKED", describe_non_pass_1038(absent, {}))
        real_zero = {"verdict": "ERROR", "error": "x"}
        real_zero.update(facts({"api": {"steps": []}}))
        self.assertIn("API JOURNEY NOT WALKED", describe_non_pass_1038(real_zero, {}))


class NoJudgementIsSynthesised(unittest.TestCase):
    """#883: the ladder never ran, so `broken`/`missing` are not ours to invent."""

    def test_no_verdict_keys_are_added(self):
        got = facts(_CORPUS[1][1])
        for key in ("broken", "missing", "verdict", "api_failed", "api_missing",
                    "ui_walk_ran_1203je"):
            self.assertNotIn(key, got)

    def test_the_keys_are_exactly_the_three_measurements(self):
        self.assertEqual(set(facts(_CORPUS[1][1])),
                         {"api_steps", "api_passed", "mcp_complete"})

    def test_the_verdict_stays_error_end_to_end(self):
        import pathlib
        import tempfile
        from env_generator.llm_generator.multi_agent.runtime import test_user_validation as T
        with tempfile.TemporaryDirectory() as d:
            rep = T.run_test_user_validation(
                pathlib.Path(d), object(), version="1.0.0",
                base_url="http://127.0.0.1:9", compose_file=None, llm=None)
        summ = rep.get("summary") or {}
        self.assertEqual(summ.get("verdict"), "ERROR")
        # This abort happens BEFORE the journey, so there is nothing to carry -- the negative
        # control for the whole ticket.
        self.assertNotIn("api_steps", summ)
        self.assertTrue(str(summ.get("error") or "").strip())


class TheAbortPathActuallyUsesIt(unittest.TestCase):
    """The POSITIVE end-to-end. The class above only had the negative control (an abort before
    the journey, which carries nothing), and mutation N91 -- deleting the `.update(...)` from
    the except handler -- came back MISSED on it: a suite of negatives is blind to the call
    site existing. The rule this repo records as
    `a-name-i-reached-for-that-did-not-exist`: a real call needs a case that expects True.

    Drives the real `run_test_user_validation`: health check answered, journey canned, MCP
    check raising. So `report["api"]` is set and `report["mcp"]` is not -- the partial carry.
    """

    def _run(self):
        import pathlib as _p
        import tempfile
        from unittest import mock
        from env_generator.llm_generator.multi_agent.runtime import test_user_validation as T
        steps = [{"ok": True}] * 5 + [
            {"action": "create comments", "method": "POST", "path": "/api/comments",
             "status": 404, "ok": False},
            {"ok": False}]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(T, "_http", lambda *a, **k: {"status": 200}), \
                mock.patch.object(T, "_api_test_user",
                                  lambda *a, **k: {"steps": steps, "actor": "alpha"}), \
                mock.patch.object(T, "_mcp_test_user",
                                  side_effect=RuntimeError("mcp probe exploded")):
            return T.run_test_user_validation(
                _p.Path(d), [{"method": "GET", "path": "/api/videos"}], version="1.0.0",
                base_url="http://127.0.0.1:9", compose_file=None, llm=None)

    def test_the_error_summary_carries_the_journey_counts(self):
        summ = (self._run().get("summary") or {})
        self.assertEqual(summ.get("verdict"), "ERROR")
        self.assertEqual(summ.get("api_steps"), 7)
        self.assertEqual(summ.get("api_passed"), 5)

    def test_the_delivery_line_names_numbers_instead_of_none(self):
        """#1203qn: ask the function heal_pipeline asks, rather than composing the line
        here -- this test used to assemble that clause itself from the two counts, so a change to
        the real clause was invisible to it."""
        from env_generator.llm_generator.multi_agent.runtime.test_user_validation import (
            journey_steps_clause_1203qn)
        summ = (self._run().get("summary") or {})
        line = journey_steps_clause_1203qn(summ)
        self.assertEqual(line, "5/7 journey steps passed")
        self.assertNotIn("None", line)

    def test_a_journey_that_never_started_says_so_1203qn(self):
        """The state #1203d3 emits no key for. It must not reach the log as None/None --
        r191 printed that nine times."""
        from env_generator.llm_generator.multi_agent.runtime.test_user_validation import (
            journey_steps_clause_1203qn)
        for summ in ({}, None, {"verdict": "ERROR"}, {"api_steps": 7}, {"api_passed": 5}):
            line = journey_steps_clause_1203qn(summ)
            self.assertNotIn("None", line)
            self.assertIn("no journey step counts were recorded", line)

    def test_a_journey_that_drove_nothing_is_still_a_measurement_1203qn(self):
        """0/0 is a CLAIM the journey earned; it must not be folded into the absent case."""
        from env_generator.llm_generator.multi_agent.runtime.test_user_validation import (
            journey_steps_clause_1203qn)
        self.assertEqual("0/0 journey steps passed",
                         journey_steps_clause_1203qn({"api_steps": 0, "api_passed": 0}))

    def test_the_step_that_never_ran_claims_nothing(self):
        """MCP raised, so there is no `complete` to carry -- absent, not False."""
        self.assertNotIn("mcp_complete", (self._run().get("summary") or {}))

    def test_the_reason_is_still_the_mcp_failure(self):
        summ = (self._run().get("summary") or {})
        self.assertIn("mcp probe exploded", str(summ.get("error")))
        self.assertIn("mcp probe exploded", describe_non_pass_1038(summ, {}))


class ItNeverRaises(unittest.TestCase):
    def test_hostile_shapes(self):
        for bad in (None, "nope", 7, [], object()):
            with self.subTest(report=repr(bad)):
                self.assertEqual(facts(bad), {})

    def test_a_step_entry_that_is_not_a_mapping(self):
        got = facts({"api": {"steps": ["nope", 7, None, {"ok": True}]}})
        self.assertEqual((got["api_steps"], got["api_passed"]), (4, 1))


if __name__ == "__main__":
    unittest.main()
