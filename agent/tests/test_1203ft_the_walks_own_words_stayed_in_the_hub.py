r"""#1203ft: the walk said what broke, and the lane was told only which flow it was.

`#981`'s own docstring names this cost and then fixes half of it:

    "r159 spent its last hours on exactly that check with the walk's own findings (a blank
     player page, a broken POST /api/continue-watching) sitting unused in the report."

It made `deliverability_ui_flow_failed` name the failing flows. The findings are still only
pointed AT -- "open the evidence on the named flow" -- so the one sentence that says what broke
stays in the hub while the lane goes looking for it.

That sentence exists. Of the failing `validation:ui_flow:*` records in the corpus, 177 carry an
`evidence.summary` / `evidence.reason` and 66 do not, and the 177 read like:

    "Fresh comments UI flow failed after signup: posting a comment on /video/35 sent
     Authorization but POST /api/comments returned 401; bug task_07f26bcdce filed."   (r158)
    "Landing page /signup renders a blank <div id='root'></div> due to a React error thrown by
     <Routes> mounted outside a Router. Flow cannot begin."                            (r57)
    "Profile creation UI flow fails after signup: POST /api/profiles returned 401 and
     /auth/login request_failed."                                             (netflix-r30)

Why this check and not another: `deliverability_ui_flow_failed` is the corpus's second-biggest
blocker (2503 red gate records across 81 runs), and it is half of the pair -- with
`validation_ui_evidence_failed` -- that the STUCK breaker finds still open when it aborts a run.
r134, r137 and r158 each died with one or both of them failing after 75 minutes of lane time.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import remediation_dispatcher as RD  # noqa: E402

# r158's own record, verbatim.
R158 = ("Fresh comments UI flow failed after signup: posting a comment on /video/35 sent "
        "Authorization but POST /api/comments returned 401; bug task_07f26bcdce filed.")
# r57's, verbatim.
R57 = ("Landing page /signup renders a blank <div id='root'></div> due to a React error thrown "
       "by <Routes> mounted outside a Router. Flow cannot begin.")


def _orch(checks, *, boom=False):
    class _CH:
        def list_checks(self):
            if boom:
                raise RuntimeError("hub down")
            return checks
    return types.SimpleNamespace(hubs=types.SimpleNamespace(codehub=_CH()))


def _rec(flow, status="failure", summary=None, reason=None, key="evidence"):
    ev = {}
    if summary is not None:
        ev["summary"] = summary
    if reason is not None:
        ev["reason"] = reason
    return {"name": "validation:ui_flow:%s" % flow, "status": status, key: ev}


class TheWalksWordsReachTheLane(unittest.TestCase):
    def test_the_recorded_summary_is_replayed(self):
        out = RD.ui_flow_failed_evidence_1203ft(
            _orch([_rec("open_comments_from_feed", summary=R158)]),
            ["open_comments_from_feed"])
        self.assertIn("POST /api/comments returned 401", out)
        self.assertIn("open_comments_from_feed", out)
        self.assertIn("WHAT THE WALK RECORDED", out)

    def test_reason_is_read_when_there_is_no_summary(self):
        out = RD.ui_flow_failed_evidence_1203ft(
            _orch([_rec("signup_to_first_like", reason=R57)]), ["signup_to_first_like"])
        self.assertIn("mounted outside a Router", out)

    def test_several_flows_keep_the_callers_order(self):
        checks = [_rec("b", summary="B broke"), _rec("a", summary="A broke")]
        out = RD.ui_flow_failed_evidence_1203ft(_orch(checks), ["a", "b"])
        self.assertLess(out.index("A broke"), out.index("B broke"))

    def test_a_flow_with_no_recorded_words_is_simply_absent(self):
        """66 of the corpus's failing records carry nothing. Those must not produce an empty
        bullet -- the existing #981 text already names them."""
        checks = [_rec("quiet"), _rec("loud", summary="L broke")]
        out = RD.ui_flow_failed_evidence_1203ft(_orch(checks), ["quiet", "loud"])
        self.assertIn("L broke", out)
        self.assertNotIn("quiet", out)

    def test_nothing_recorded_at_all_adds_nothing(self):
        """Additive like #1176/#1177/#1182: silence leaves the existing body untouched."""
        self.assertEqual(RD.ui_flow_failed_evidence_1203ft(_orch([_rec("quiet")]), ["quiet"]), "")
        self.assertEqual(RD.ui_flow_failed_evidence_1203ft(_orch([]), ["a"]), "")
        self.assertEqual(RD.ui_flow_failed_evidence_1203ft(_orch([]), []), "")

    def test_a_passing_record_is_not_quoted(self):
        """A flow that passes has nothing to remediate, and quoting its old words would send the
        lane after a problem the hub says is gone."""
        checks = [_rec("done", status="success", summary="it worked")]
        self.assertEqual(RD.ui_flow_failed_evidence_1203ft(_orch(checks), ["done"]), "")

    def test_an_unrelated_check_is_not_quoted(self):
        checks = [{"name": "validation:ui_smoke:x", "status": "failure",
                   "evidence": {"summary": "smoke words"}},
                  {"name": "build:frontend", "status": "failure",
                   "evidence": {"summary": "build words"}}]
        self.assertEqual(RD.ui_flow_failed_evidence_1203ft(_orch(checks), ["x", "frontend"]), "")

    def test_a_hub_fault_degrades_to_names_only(self):
        self.assertEqual(
            RD.ui_flow_failed_evidence_1203ft(_orch([], boom=True), ["a"]), "")
        self.assertEqual(RD.ui_flow_failed_evidence_1203ft(None, ["a"]), "")

    def test_the_quote_is_bounded(self):
        """A P0 body is read by an agent with a context budget."""
        out = RD.ui_flow_failed_evidence_1203ft(
            _orch([_rec("big", summary="x" * 5000)]), ["big"])
        self.assertLess(len(out), 700, len(out))


class ItIsWiredIntoTheDispatch(unittest.TestCase):
    def test_the_failed_branch_calls_it_with_the_same_flow_list(self):
        import ast
        src = (LLM_DIR / "multi_agent" / "runtime" / "remediation_dispatcher.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "ui_flow_failed_evidence_1203ft"]
        self.assertEqual(len(calls), 1, "expected exactly one dispatch call")
        args = [getattr(a, "id", None) for a in calls[0].args]
        self.assertEqual(args, ["orch", "_ff"],
                         "it must be fed the same recomputed flow list #981 names")

    def test_it_is_added_to_the_same_extra_as_1176_and_1182(self):
        """Additive, not a replacement: #981's naming text and the other three diagnoses must
        all survive in the same `_extra`.

        Asserted over the ASSIGNMENT's own expression, not a byte window around the call --
        #943's ratchet is right that a window breaks when a comment grows, and the first version
        of this test failed for exactly that reason (#1177 sits past a nine-line comment)."""
        import ast
        src = (LLM_DIR / "multi_agent" / "runtime" / "remediation_dispatcher.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        mine = None
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "_extra" for t in node.targets)):
                continue
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "ui_flow_failed_evidence_1203ft" for n in ast.walk(node)):
                mine = node
                break
        self.assertIsNotNone(mine, "the call is not part of an `_extra` assignment")
        called = {n.func.id for n in ast.walk(mine)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        for sibling in ("_ui_flow_failed_extra", "auth_contradiction_1176",
                        "control_absence_contradicted_1182", "ui_smoke_refresh_1177",
                        "ui_flow_failed_evidence_1203ft"):
            self.assertIn(sibling, called, sibling)


if __name__ == "__main__":
    unittest.main()
