"""#1203ox: the startup tool-surface line asserted an outcome it cannot know.

`validate_orphaned_tool_offerings` fires in 211 of 211 run logs (2806 lines) and said every
tool it names is "(offerable via ranking)". `rank_tool_names` caps its result at
`max(limit, len(always_include))` and fills `always_include` FIRST, so a ranked name only
lands in `max(0, limit - |always_include[stage] & granted|)` slots -- 0 for the orchestrator
in 5 of its 6 stages, and for backend / frontend / verifier / debugger / knowledge /
realism_judge / the three test users in essentially every stage.

The same function's docstring promised "a LOUD ``logger.warning``" while the body has emitted
`logger.info` since the downgrade whose comment sits three lines below it.

Every assertion here reads the AST, not a source window and not a quoted literal: this file's
own prose names the strings it is about, and a text assertion would be fed by that prose
(the trap recorded three times -- see test_1203jr / #943).
"""
from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent import tool_surface as TS


def _fn(module_src: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(module_src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError("function %r is gone from the module under test" % name)


def _logger_calls(fn: ast.AST) -> list:
    """(level, format_string) for every `logger.<level>("...", ...)` in `fn`."""
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id == "logger"):
            continue
        fmt = None
        if node.args:
            try:
                fmt = ast.literal_eval(node.args[0])
            except Exception:
                fmt = None
        out.append((f.attr, fmt if isinstance(fmt, str) else None, node))
    return out


class TheDocstringMatchesWhatTheBodyEmits(unittest.TestCase):
    def setUp(self) -> None:
        self.src = inspect.getsource(TS)
        self.fn = _fn(self.src, "validate_orphaned_tool_offerings")
        self.doc = ast.get_docstring(self.fn) or ""
        self.calls = _logger_calls(self.fn)
        self.assertTrue(self.calls, "the function logs nothing at all now")

    def test_the_per_profile_summary_is_emitted_at_the_level_the_docstring_names(self) -> None:
        # The levels actually used for the per-profile SUMMARY (debug lines are the
        # degradation paths and are not what the docstring's promise is about).
        summary = [c for c in self.calls if c[1] and "profile" in c[1] and "%d" in c[1]]
        self.assertEqual(len(summary), 1,
                         "expected exactly one per-profile summary line, got %d" % len(summary))
        level = summary[0][0]
        self.assertIn(level, self.doc,
                      "the docstring does not name the level the summary is emitted at (%r)" % level)

    def test_the_contract_paragraphs_do_not_promise_a_level_the_body_never_uses(self) -> None:
        # Only the CONTRACT paragraphs are checked -- those before the first paragraph that
        # opens with a `#<ticket>` marker. A ticket note is an annotation by convention here,
        # and a correction has to be able to QUOTE the false sentence it is correcting; the
        # first draft of this test failed on exactly that and the criterion was wrong, not
        # the docstring (#1203n8 is the same shape).
        import re as _re
        paras = [q.strip() for q in self.doc.split("\n\n")]
        contract = []
        for q in paras:
            if _re.match(r"#\d{3,4}[a-z]*\b", q):
                break
            contract.append(q)
        self.assertTrue(contract, "the docstring is nothing but ticket notes")
        body = "\n\n".join(contract)
        used = {c[0] for c in self.calls}
        for level in ("warning", "error", "critical"):
            if level in used:
                continue
            self.assertNotIn(
                "logger.%s" % level, body,
                "the docstring's contract promises logger.%s and the body never calls it"
                % level)

    def test_the_correction_is_allowed_to_quote_the_sentence_it_corrects(self) -> None:
        # The pair to the test above: if the ticket-note paragraph were also filtered for
        # unused levels, a correction could not name what it is correcting, and the honest
        # record of the defect would have to be deleted to keep the suite green.
        import re as _re
        notes = [q for q in self.doc.split("\n\n")
                 if _re.match(r"#\d{3,4}[a-z]*\b", q.strip())]
        self.assertTrue(notes, "the ticket note recording this correction is gone")
        self.assertTrue(any("logger.warning" in q for q in notes),
                        "the note no longer says which sentence was false")


class TheLineStatesTheConditionNotTheOutcome(unittest.TestCase):
    def setUp(self) -> None:
        self.src = inspect.getsource(TS)
        self.fn = _fn(self.src, "validate_orphaned_tool_offerings")
        summary = [c for c in _logger_calls(self.fn) if c[1] and "profile" in c[1] and "%d" in c[1]]
        self.assertEqual(len(summary), 1, "the per-profile summary line is gone")
        self.level, self.fmt, self.node = summary[0]

    def test_it_does_not_assert_that_the_tools_are_offerable(self) -> None:
        low = self.fmt.lower()
        # An unconditional claim is the defect: "offerable" with no qualifier in the clause.
        self.assertNotIn("(offerable via ranking)", low)
        if "offerable" in low:
            tail = low.split("offerable", 1)[1]
            self.assertIn("only", low.split("offerable", 1)[0] + tail[:40],
                          "the line says 'offerable' without qualifying it: %r" % self.fmt)

    def test_it_names_both_routes_that_could_still_reach_the_tool(self) -> None:
        low = self.fmt.lower()
        self.assertIn("slot", low, "the ranker-slot condition is not stated: %r" % self.fmt)
        self.assertIn("allowlist", low, "the allowlist route is not stated: %r" % self.fmt)

    def test_the_example_cut_still_declares_itself(self) -> None:
        # #1034: the names are capped; the cap must be visible in the rendered line.
        self.assertTrue(self.fmt.rstrip().endswith("%s%s"),
                        "the examples/ellipsis pair left the format string: %r" % self.fmt)
        self.assertEqual(len(self.node.args), 5,
                         "the summary no longer passes (profile, count, examples, ellipsis)")


class TheFactTheCommentRestsOn(unittest.TestCase):
    """If the force-offer lists shrink below the ranker limit, #1203ox's reasoning changes."""

    def test_the_force_offer_lists_are_larger_than_the_ranker_limit(self) -> None:
        from env_generator.llm_generator.multi_agent.agents.base import EnvGenAgent
        m = EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE or {}
        self.assertGreaterEqual(len(m), 5,
                                "fewer stages than expected -- this test would prove nothing")
        limits = {"communicate": 8, "deliver": 8}
        over = {st: len(names or ()) for st, names in m.items()
                if len(names or ()) >= limits.get(st, 10)}
        self.assertTrue(over, "no stage force-offers as many tools as the ranker's limit, so "
                              "'offerable via ranking' would no longer be an empty promise "
                              "anywhere -- re-read #1203ox before loosening the line")
        self.assertIn("action", over,
                      "the `action` stage no longer fills the limit by itself: %r" % over)

    def test_the_ranker_fills_always_include_first_and_caps_at_its_length(self) -> None:
        fn = _fn(inspect.getsource(TS), "rank_tool_names")
        # The cap expression must still be max(limit, len(always_include)) -- that is what
        # makes the ranked slots zero. Found by SHAPE, so renaming locals cannot hide it.
        found = []
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "max" and len(node.args) == 2):
                kinds = []
                for a in node.args:
                    if isinstance(a, ast.Name):
                        kinds.append("name")
                    elif (isinstance(a, ast.Call) and isinstance(a.func, ast.Name)
                          and a.func.id == "len"):
                        kinds.append("len")
                    else:
                        kinds.append("?")
                found.append(tuple(kinds))
        self.assertIn(("name", "len"), found,
                      "the `max(limit, len(always_include))` cap is gone from rank_tool_names; "
                      "#1203ox's slot arithmetic no longer describes this function")

    def test_the_stage_limits_are_still_the_numbers_the_comment_cites(self) -> None:
        p = (Path(TS.__file__).resolve().parent / "agents" / "runtime"
             / "step_pipeline" / "action.py")
        self.assertTrue(p.is_file(), "action.py moved: %s" % p)
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        nums = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "stage_limit"
                    and isinstance(node.value, ast.IfExp)):
                for side in (node.value.body, node.value.orelse):
                    if isinstance(side, ast.Constant) and isinstance(side.value, int):
                        nums.add(side.value)
        self.assertEqual(nums, {8, 10},
                         "the per-stage ranker limit changed to %r; #1203ox's comment cites "
                         "8-10 and its slot counts were computed against those" % sorted(nums))


class TheDetectorStillBites(unittest.TestCase):
    def test_a_force_offered_name_is_not_an_orphan(self) -> None:
        out = TS.detect_orphaned_tool_offerings(
            "p", granted_tool_categories={"t": {"cat"}},
            hint_categories=set(), always_include_names={"t"})
        self.assertEqual(out, [])

    def test_a_hinted_category_is_not_an_orphan(self) -> None:
        out = TS.detect_orphaned_tool_offerings(
            "p", granted_tool_categories={"t": {"cat"}},
            hint_categories={"cat"}, always_include_names=set())
        self.assertEqual(out, [])

    def test_neither_route_makes_it_an_orphan(self) -> None:
        out = TS.detect_orphaned_tool_offerings(
            "p", granted_tool_categories={"t": {"cat"}, "u": {"other"}},
            hint_categories={"other"}, always_include_names=set())
        self.assertEqual(out, ["t"])


if __name__ == "__main__":
    unittest.main()
