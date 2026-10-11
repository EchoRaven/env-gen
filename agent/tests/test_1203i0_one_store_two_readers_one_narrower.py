r"""#1203i0: the two readers of one evidence store, and this one had the narrower field list.

`ui_flow_failed_evidence_1203ft` read `evidence.summary` or `evidence.reason` and nothing
else. `_record_own_words_1203fx`, over the SAME records in the sibling branch, reads twelve
prose fields plus a composed `expected`/`actual` pair plus a `root_cause_bug` pointer -- and
its own docstring measured why: "`summary`/`reason` alone reach 222 of the 291, and the other
31 are the SAME sentence under a writer's own spelling".

Replaying that function over every failing `validation:ui_flow:*` record on disk -- the rule
#1203fx itself states, that a number about a function has to come from the function:

    failing ui_flow records                                   268
      words under `summary`/`reason` (what the old read got)  207
      nothing for the old read                                 61
        ...of which #1203fx's list reaches                     36
        genuinely nothing written down                         25

The 36 read like

    "expected FYP video renders publicly per M1 kickoff (GET /api/feed/for-you is public);
     actual GET /api/feed/for-you → 401"                                      (tiktok-r90)
    "Bundle crashes: TypeError '(void 0) is not a function' at first useState." (tiktok-r82)

-- the whole repair, written down, on the record this check blocked on, withheld from the lane
because two readers of one store each implemented half the rules (#1202fn / fp / fq / fs and
#1203f9 are the same shape). `deliverability_ui_flow_failed` is the corpus's second-biggest
blocker: 2503 red gate records across 81 runs.

The fix calls the SAME function rather than copying its field list, because #1203fx's
docstring argues against a second reader in that module and a copied tuple IS a second reader
that drifts. The test that matters most below is the agreement one.
"""
from __future__ import annotations

import ast
import inspect
import sys
import textwrap
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.delivery_gate import _record_own_words_1203fx  # noqa: E402
from multi_agent.runtime import remediation_dispatcher as _rd  # noqa: E402
from multi_agent.runtime.remediation_dispatcher import (  # noqa: E402
    ui_flow_failed_evidence_1203ft,
)


def _orch(checks, *, boom=False):
    class _CH:
        def list_checks(self):
            if boom:
                raise RuntimeError("hub down")
            return checks
    return types.SimpleNamespace(hubs=types.SimpleNamespace(codehub=_CH()))


def _rec(flow, status="failure", **evidence):
    return {"name": "validation:ui_flow:%s" % flow, "status": status,
            "evidence": dict(evidence)}


#: the writers' own spellings, as the corpus actually holds them
SHAPES = {
    "summary": {"summary": "Comments flow failed: POST /api/comments returned 401."},
    "reason": {"reason": "Login flow failed: submit control not interactable."},
    "expected_actual": {"expected": "FYP video renders publicly per M1 kickoff",
                        "actual": "GET /api/feed/for-you -> 401"},
    "failure_reason": {"failure_reason": "Bundle crashes at first useState."},
    "console_error": {"console_error": "TypeError '(void 0) is not a function'"},
    "note": {"note": "Signup posts to /auth/register but the form never clears."},
    "root_cause_hypothesis": {"root_cause_hypothesis": "Routes mounted outside a Router."},
    "failing_request": {"failing_request": "POST /api/profiles -> 401"},
    "detail": {"detail": "the submit button stayed disabled"},
    "root_cause_bug": {"root_cause_bug": "task_07f26bcdce"},
    "nothing": {"run_id": "run_bac34e9bd5", "screenshot": "s.png"},
}


class TheWordsTheOldReadCouldNotSee(unittest.TestCase):

    def test_an_expected_actual_pair_now_reaches_the_lane(self):
        """The biggest of the 36: two fields the writer split one sentence across."""
        out = ui_flow_failed_evidence_1203ft(
            _orch([_rec("fyp_feed_logged_out", **SHAPES["expected_actual"])]),
            ["fyp_feed_logged_out"])
        assert "FYP video renders publicly" in out, out
        assert "401" in out, out

    def test_a_console_error_now_reaches_the_lane(self):
        out = ui_flow_failed_evidence_1203ft(
            _orch([_rec("fyp_feed", **SHAPES["console_error"])]), ["fyp_feed"])
        assert "(void 0) is not a function" in out, out

    def test_a_root_cause_bug_pointer_reaches_the_lane(self):
        out = ui_flow_failed_evidence_1203ft(
            _orch([_rec("profile", **SHAPES["root_cause_bug"])]), ["profile"])
        assert "task_07f26bcdce" in out, out

    def test_a_record_with_nothing_written_down_is_still_silent(self):
        """The 25: no field list can invent what the writer never wrote, and the caller must
        print the flow name alone exactly as before."""
        out = ui_flow_failed_evidence_1203ft(
            _orch([_rec("explore", **SHAPES["nothing"])]), ["explore"])
        assert out == "", out


class TheTwoReadersMustAgree(unittest.TestCase):
    """★ The assertion that keeps this fixed: for every shape the corpus holds, the words the
    ui_flow_failed branch hands the lane are the words `_record_own_words_1203fx` finds. A
    future field added to one reader and not the other turns this red."""

    def test_every_shape_agrees(self):
        for name, ev in SHAPES.items():
            rec = _rec("flow_x", **ev)
            mine = ui_flow_failed_evidence_1203ft(_orch([rec]), ["flow_x"])
            theirs = _record_own_words_1203fx(dict(rec))
            if theirs:
                assert theirs[:120] in mine, (name, theirs, mine)
            else:
                assert mine == "", (name, mine)

    def test_the_branch_does_not_keep_its_own_field_list(self):
        """A copied tuple is a second reader that drifts — the defect, re-created."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(ui_flow_failed_evidence_1203ft)))
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        # the fallback keeps `summary`/`reason` for the case where the import fails; anything
        # BEYOND those two would be a copy of #1203fx's list.
        copied = [s for s in literals
                  if s in ("failure_reason", "note", "notes", "root_cause_hypothesis",
                           "root_cause", "failing_request", "console_error", "detail",
                           "message", "expected", "actual", "root_cause_bug")]
        assert copied == [], "the field list was copied instead of called: %r" % (copied,)

    def test_it_calls_the_shared_function(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(ui_flow_failed_evidence_1203ft)))
        names = {n.name for imp in ast.walk(tree) if isinstance(imp, ast.ImportFrom)
                 for n in imp.names}
        assert "_record_own_words_1203fx" in names, names


class WhatItMustNotChange(unittest.TestCase):

    def test_a_summary_still_works(self):
        out = ui_flow_failed_evidence_1203ft(
            _orch([_rec("comments", **SHAPES["summary"])]), ["comments"])
        assert "POST /api/comments returned 401" in out, out

    def test_passing_records_are_still_skipped(self):
        out = ui_flow_failed_evidence_1203ft(
            _orch([_rec("ok_flow", status="success", summary="all good")]), ["ok_flow"])
        assert out == "", out

    def test_only_the_named_flows_are_quoted(self):
        """★ Pre-existing code, and the `flow not in names` test inside the collecting loop
        is a PERFORMANCE filter, not a correctness one: removing it survives every test here,
        correctly, because the emit step is `[... for f in names if f in said]` and iterates
        the names. Recorded rather than fixtured around -- the third equivalent mutation
        today, after #1203hx's difference direction and #1203hy's `_meta` skip."""
        checks = [_rec("wanted", summary="the wanted sentence"),
                  _rec("other", summary="the other sentence")]
        out = ui_flow_failed_evidence_1203ft(_orch(checks), ["wanted"])
        assert "the wanted sentence" in out, out
        assert "the other sentence" not in out, out

    def test_a_dead_hub_is_still_silent_not_an_exception(self):
        assert ui_flow_failed_evidence_1203ft(_orch([], boom=True), ["x"]) == ""

    def test_no_named_flows_is_silent(self):
        assert ui_flow_failed_evidence_1203ft(_orch([_rec("a", summary="s")]), []) == ""

    def test_the_fallback_still_reads_summary_if_the_import_fails(self):
        """The import is guarded; the guard must not silence a record that the old read
        would have handled."""
        import builtins
        orig = builtins.__import__

        def no_gate(name, *a, **k):
            if "delivery_gate" in name:
                raise ImportError("gate module unavailable")
            return orig(name, *a, **k)
        builtins.__import__ = no_gate
        try:
            out = ui_flow_failed_evidence_1203ft(
                _orch([_rec("comments", **SHAPES["summary"])]), ["comments"])
        finally:
            builtins.__import__ = orig
        assert "POST /api/comments returned 401" in out, out


if __name__ == "__main__":
    unittest.main()
