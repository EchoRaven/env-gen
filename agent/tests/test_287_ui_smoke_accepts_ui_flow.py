"""FIX #287 — the ui_smoke gate must accept a passing ui_flow as UI evidence (tiktok r70/r71, live).

Two places in the framework judge "has the UI actually been exercised", with DIFFERENT check
sets:
  - deliverability._has_passing_ui_evidence uses
    _UI_EVIDENCE_CHECKS = {ui_flow, ui_smoke, ui_page_reachable, test_user}  → accepts ui_flow
  - delivery_gate.ui_smoke_pass uses {ui_smoke, ui_page_reachable}          → rejects ui_flow

The verifier's prompt STEP 2 says "run the browser ui_smoke/ui_flow checks". In r71 it drove
the browser (browser_navigate succeeded) and wrote 11 PASSING validation:ui_flow records — but
no validation:ui_smoke record (it collapsed the two dimensions and dropped ui_smoke). So
_has_passing_ui_evidence was True while ui_smoke_pass was False → validation_ui_smoke_missing
blocked delivery. r68/r70/r71 all fail-fast aborted there, r71 with the ENTIRE rest of the gate
green.

A passing ui_flow is STRICTLY STRONGER evidence than ui_smoke: walking a page's interaction flow
proves the page rendered (a blank/fallback page has no controls to drive). And the gate's own
remediation text states the goal is merely "at least one passed UI smoke check" — i.e. real UI
evidence exists, which a passing ui_flow is. So ui_smoke_pass must accept ui_flow too, matching
_has_passing_ui_evidence. The ui_flow DIMENSION keeps its own separate gate (ui_flow_missing /
_failed), so this doesn't let a flow defect through.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.delivery_gate import _ui_smoke_pass  # noqa: E402


def _rec(check, status="passed"):
    return {"status": status, "metadata": {"check": check}}


def test_passing_ui_flow_now_counts_as_ui_smoke():
    """The r71 wedge: 11 passing ui_flow, zero ui_smoke → must pass."""
    assert _ui_smoke_pass([_rec("ui_flow")]) is True


def test_ui_smoke_and_ui_page_reachable_still_count():
    assert _ui_smoke_pass([_rec("ui_smoke")]) is True
    assert _ui_smoke_pass([_rec("ui_page_reachable")]) is True


def test_failed_ui_flow_does_not_count():
    assert _ui_smoke_pass([_rec("ui_flow", "failed")]) is False


def test_no_ui_evidence_at_all_is_false():
    """A backend-only / blank-UI app still trips the gate."""
    assert _ui_smoke_pass([_rec("api_smoke")]) is False
    assert _ui_smoke_pass([]) is False


def test_non_dict_rows_are_ignored():
    assert _ui_smoke_pass(["junk", None, _rec("ui_flow")]) is True
    assert _ui_smoke_pass(["junk", None]) is False


def test_matches_has_passing_ui_evidence_check_set():
    """The two judgements must not diverge on ui_flow again."""
    from multi_agent.runtime.deliverability import _UI_EVIDENCE_CHECKS
    # every check ui_smoke_pass accepts must be a recognized UI-evidence check
    for check in ("ui_smoke", "ui_page_reachable", "ui_flow"):
        assert check in _UI_EVIDENCE_CHECKS
        assert _ui_smoke_pass([_rec(check)]) is True
