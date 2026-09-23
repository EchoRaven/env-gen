r"""#1202su: a failing ui_flow record is retired by its NAME, and the remediation never said so.

`_ui_evidence_breadth_739` keeps the latest record per name (`#757`) and only then asks
whether any is failing. So a passing walk of the same page under a DIFFERENT name does not
retire the failure — and the remediation text said "re-run the walk (run_validation)", which
is exactly what the verifier does before recording under whatever name that walk used.

Measured over the 40 most recent corpus runs (`shared/hubs/codehub_checks.json` +
`registryhub_ui_pages.json`), all three numbers recomputed for this item:

  * 66 failing `validation:ui_flow:*` records across 24 runs; **27 (40%)** name a flow that
    is not a declared ui_page, so no walk will ever produce that name again;
  * in **15 of those 24 runs** a ui_flow PASS was recorded AFTER the failure under a
    different name and the failure still stood — tiktok-r130's newest pass is 52 s after it
    (12 passes, 1 stuck failure), googlemaps-r16 has 11 stuck records, and the 4-milestone
    SUCCESS run gmrun4 shipped with one;
  * **62 of 66 (93%)** carry no `metadata.url`, which is why `#1202fq`'s route-keyed
    supersede — written for this exact latch — cannot match them either.

Three domains (tiktok / netflix / googlemaps), so it is not env-specific.

`validation_ui_evidence_failed` is the most frequent last-tick blocker in the corpus
(7 of the last 16 runs), which is why this is the text worth getting right.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402


class _Orch:
    """Records in the shape `get_validation_results` really returns (#193 normalizes
    `evidence.metadata` up to `metadata` and canonicalizes success -> passed)."""

    def __init__(self, records):
        self._records = records

    def _get_validation_results(self, limit=100):
        return list(self._records)


def _rec(flow, status):
    return {"task_id": f"ui_flow:{flow}", "name": f"validation:ui_flow:{flow}",
            "status": status, "metadata": {"check": "ui_flow", "flow": flow}}


def test_it_says_the_passes_recorded_under_other_names_do_not_retire_this_one():
    orch = _Orch([_rec("signup_modal_auth", "failed"),
                  _rec("for_you_feed", "passed"),
                  _rec("explore_grid_page", "passed")])
    txt = rd.name_keyed_supersede_1202su(orch, ["signup_modal_auth"])
    assert "signup_modal_auth" in txt
    assert "2 passing ui_flow record(s) under OTHER names" in txt
    assert "explore_grid_page" in txt and "for_you_feed" in txt


def test_it_names_the_tool_the_verifier_actually_has():
    """The class of defect this whole batch keeps finding: telling a lane to call something
    that does not exist. The agent-facing tool is `codehub_record_check`; the hub METHOD
    `record_validation_result` is not in any lane's toolset."""
    from tools import hub_tools
    txt = rd.name_keyed_supersede_1202su(
        _Orch([_rec("signup_modal_auth", "failed"), _rec("for_you_feed", "passed")]),
        ["signup_modal_auth"])
    assert "codehub_record_check(" in txt
    assert "record_validation_result(" not in txt
    names = {getattr(obj, "NAME", None) for obj in vars(hub_tools).values()
             if isinstance(obj, type)}
    assert "codehub_record_check" in names, "the tool named in the remediation must exist"
    assert "validation:ui_flow:signup_modal_auth" in txt, (
        "and the check NAME must be the colon-prefixed form the gate reads")


def test_it_asks_for_the_url_that_makes_the_route_supersede_possible():
    """93% of failing records carry no `metadata.url`, so #1202fq is inert on them."""
    txt = rd.name_keyed_supersede_1202su(
        _Orch([_rec("a_flow", "failed"), _rec("b_flow", "passed")]), ["a_flow"])
    assert "'url'" in txt and "metadata" in txt
    # the key #1202fq reads is `metadata.url` on the NORMALIZED record
    src = inspect.getsource(rd)
    assert "url" in src[src.index("def name_keyed_supersede_1202su"):][:4000]


def test_it_is_silent_when_there_is_nothing_to_say():
    """No failing names, no passing records, or only passes under the SAME names — in each
    case the note would be noise, and the generic text stands."""
    assert rd.name_keyed_supersede_1202su(_Orch([_rec("a", "passed")]), []) == ""
    assert rd.name_keyed_supersede_1202su(_Orch([_rec("a", "failed")]), ["a"]) == ""
    assert rd.name_keyed_supersede_1202su(_Orch([_rec("a", "failed"), _rec("a", "passed")]),
                                          ["a"]) == ""


def test_any_fault_leaves_the_generic_remediation_standing():
    class _Boom:
        def _get_validation_results(self, limit=100):
            raise RuntimeError("hub down")
    assert rd.name_keyed_supersede_1202su(_Boom(), ["a"]) == ""
    assert rd.name_keyed_supersede_1202su(None, ["a"]) == ""


def test_both_failing_ui_branches_carry_it():
    """`validation_ui_evidence_failed` and `deliverability_ui_flow_failed` are the same
    evidence store read by two checks — #1202fn/fp/fq/fs are a whole batch of one of them
    getting a rule the other did not. Wire both, or repeat that."""
    src = inspect.getsource(rd)
    i = src.index('if name == "validation_ui_evidence_failed":')
    j = src.index('if name == "deliverability_ui_flow_missing":')
    block = src[i:j]
    assert block.count("name_keyed_supersede_1202su(orch, _fp)") == 1
    assert block.count("name_keyed_supersede_1202su(orch, _ff)") == 1


def test_the_note_counts_what_it_lists():
    """#1034: a count and the list it summarises must be the same collection."""
    orch = _Orch([_rec("bad", "failed")] + [_rec(f"ok{i}", "passed") for i in range(7)])
    txt = rd.name_keyed_supersede_1202su(orch, ["bad"])
    assert "7 passing ui_flow record(s)" in txt
    assert "(+3 more not shown)" in txt, "the cut at 4 must be declared, not silent"
