"""#1188 — a standing guard that no gate diagnosis silently falls out of the dispatch path.

This is #1178's lesson made permanent. That defect was not a broken helper: the helper was
fine and the PATH was dead, so #982's page list, #1043's auth-root hint and #1176/#1177 all
produced nothing while every task body stayed at exactly 789 characters. Nothing failed;
nothing was logged; the richer text was simply never composed.

The wiring is proven live — r21's remediation bodies measured 1437 and 2900 characters
against that 789-character base — so what needs guarding now is that each diagnosis STAYS
composed into `_extra` in both branches that carry it. An audit found #1177 attached to the
ui-evidence branch but not the ui_flow branch while its three siblings were on both; that is
the shape this test exists to catch.
"""
import inspect
import re

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd

_SRC = inspect.getsource(rd)

_DIAGNOSES = (
    "auth_contradiction_1176",              # contract auth vs a public route
    "ui_smoke_refresh_1177",                # a record run_validation cannot rewrite
    "control_absence_contradicted_1182",    # "the control is missing" about a declared control
    "two_step_login_1185",                  # the first submit is not the login
)


def _branch(check, next_check):
    i = _SRC.index(f'if name == "{check}":')
    return _SRC[i:_SRC.index(f'if name == "{next_check}":', i)]


def test_every_diagnosis_is_composed_in_the_ui_evidence_branch():
    branch = _branch("validation_ui_evidence_failed", "deliverability_ui_flow_failed")
    for fn in _DIAGNOSES:
        assert f"{fn}(orch, _fp)" in branch, f"{fn} dropped out of the ui-evidence branch"
    assert "_ui_evidence_failed_extra(_fp)" in branch, "the #982 base text must stay"


def test_every_diagnosis_is_composed_in_the_ui_flow_branch():
    branch = _branch("deliverability_ui_flow_failed", "deliverability_ui_flow_missing")
    for fn in _DIAGNOSES:
        assert f"{fn}(orch, _ff)" in branch, f"{fn} dropped out of the ui_flow branch"
    assert "_ui_flow_failed_extra(_ff)" in branch


def test_each_diagnosis_is_defined_and_self_gating():
    """Every one must return "" rather than raise when it does not apply — the dispatcher
    swallows exceptions, so a raising helper would degrade to generic text invisibly."""
    for fn in _DIAGNOSES:
        f = getattr(rd, fn, None)
        assert callable(f), f"{fn} is wired but not defined"
        assert f(None, ["nothing"]) == "", f"{fn} must be silent (not raise) with no orch"
        assert f(object(), []) == "", f"{fn} must be silent for an empty page list"


def test_the_producer_still_reads_a_real_orchestrator_api():
    """#1178 itself: the page list feeding all of the above must come from a name that
    exists on the real Orchestrator, not a plausible-looking one.

    #1203fx moved the fetch into `_ui_evidence_report_1203fx` so its two consumers cannot
    drift apart the way #1178's copy did. The guard follows it instead of being relaxed: the
    shared fetch must still reach a real attribute, AND the page producer must still reach
    the shared fetch -- otherwise a future edit could satisfy this test with a fetch nothing
    calls."""
    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
    fetch = inspect.getsource(rd._ui_evidence_report_1203fx)
    m = re.search(r'getattr\(orch, "(_get_validation_results)"', fetch)
    assert m, "the shared fetch must reach for _get_validation_results first"
    assert hasattr(Orchestrator, m.group(1))
    for consumer in (rd._ui_evidence_failed_pages, rd.ui_evidence_failed_evidence_1203fx):
        src = inspect.getsource(consumer)
        assert "_ui_evidence_report_1203fx(orch)" in src, (
            f"{consumer.__name__} must go through the shared fetch, not its own copy")
    # and the two keys they read are the two the gate actually returns
    from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
    _rep = dg._ui_evidence_breadth_739([
        {"name": "validation:ui_flow:checkout", "status": "failed",
         "metadata": {"check": "ui_flow", "flow": "checkout"},
         "evidence": {"summary": "the submit control was not interactable"}},
    ])
    assert _rep.get("pages_failed") == ["checkout"], _rep
    assert _rep.get("words_failed") == {
        "checkout": "the submit control was not interactable"}, _rep


# #1203fx: diagnoses that belong to ONE branch on purpose. #1188 exists because #1177 was
# missing from a branch by oversight, so a one-branch diagnosis has to be declared as a
# decision -- and the declaration has to be falsifiable, or it is just a comment. Each entry
# is (function, the branch it belongs to, the branch it must stay OUT of, why).
_BRANCH_LOCAL_1203FX = (
    ("ui_evidence_failed_evidence_1203fx", "validation_ui_evidence_failed",
     "deliverability_ui_flow_failed",
     "the ui_flow branch already carries its records' words through #1203ft"),
    ("ui_flow_failed_evidence_1203ft", "deliverability_ui_flow_failed",
     "validation_ui_evidence_failed",
     "it reads codehub's validation:ui_flow:<flow> rows, which cannot see ui_smoke records"),
)


def test_the_one_branch_diagnoses_stay_on_their_own_branch():
    ui_ev = _branch("validation_ui_evidence_failed", "deliverability_ui_flow_failed")
    ui_fl = _branch("deliverability_ui_flow_failed", "deliverability_ui_flow_missing")
    where = {"validation_ui_evidence_failed": ui_ev, "deliverability_ui_flow_failed": ui_fl}
    for fn, belongs, excluded, why in _BRANCH_LOCAL_1203FX:
        assert f"{fn}(orch," in where[belongs], f"{fn} fell out of its own branch"
        assert fn not in where[excluded], (
            f"{fn} appeared on the {excluded} branch; {why}, so the sentence would print "
            f"twice under two headings")
        f = getattr(rd, fn, None)
        assert callable(f), f"{fn} is wired but not defined"
        assert f(None, ["nothing"]) == "", f"{fn} must be silent (not raise) with no orch"
        assert f(object(), []) == "", f"{fn} must be silent for an empty page list"
