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
    exists on the real Orchestrator, not a plausible-looking one."""
    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
    src = inspect.getsource(rd._ui_evidence_failed_pages)
    m = re.search(r'getattr\(orch, "(_get_validation_results)"', src)
    assert m, "the producer must reach for _get_validation_results first"
    assert hasattr(Orchestrator, m.group(1))
