"""#502 (netflix r80, 2026-08-05) — deliver-tail wedged on a STALE build:* checklist.
r80 reached the deliver tail with the ONLY blocker = verification_checklist_not_ready (all
4 build:* recorded failure though api_smoke PASSED — 15 endpoints, docker_up ok, 0 build
errors). maybe_refresh_stale_build_checklist (#120/#492) reset the api_smoke attempt counter
3× so a re-validation would re-record FRESH build:* truth — but _fwval_can_early_return
returned True for a checklist-only failure set (a passing run existed + business_chain wasn't
blocking), so maybe_run EARLY-RETURNED before the re-run could happen → #492's reset was
wasted → build:* stayed stale-failure → final gate raise → main() returned 1, no release.

FIX: verification_checklist_not_ready, like business_chain_failing, IS fixable by re-running
validation (RunValidationTool re-records build:* — success on a built app, honest failure
otherwise), so it must ALSO keep the loop running. These tests lock the early-return decision:
a checklist-only (or business_chain-only) blocker must NOT early-return; a clean/other-blocker
set is unchanged."""
from env_generator.llm_generator.multi_agent.orchestrator import _fwval_can_early_return


def test_no_passing_run_never_early_returns():
    assert _fwval_can_early_return(False, []) is False
    assert _fwval_can_early_return(False, ["verification_checklist_not_ready"]) is False


def test_clean_gate_early_returns():
    # passing run + no failed checks → nothing to do → may stop.
    assert _fwval_can_early_return(True, []) is True
    assert _fwval_can_early_return(True, None) is True


def test_checklist_blocker_keeps_loop_running():
    # THE #502 bug: a stale verification_checklist_not_ready is re-validation-fixable →
    # must NOT early-return (so #492's counter reset actually drives a re-record).
    assert _fwval_can_early_return(True, ["verification_checklist_not_ready"]) is False


def test_business_chain_blocker_still_keeps_loop_running():
    # pre-existing behavior preserved.
    assert _fwval_can_early_return(True, ["business_chain_failing"]) is False


def test_either_revalidation_fixable_blocker_keeps_running():
    assert _fwval_can_early_return(
        True, ["business_chain_failing", "verification_checklist_not_ready"]) is False


def test_non_revalidation_fixable_blocker_still_early_returns():
    # ui_page_unwired is NOT fixable by re-validation → early-return unchanged (the loop
    # must not spin docker on a blocker re-validation can't clear).
    assert _fwval_can_early_return(True, ["deliverability_ui_page_unwired"]) is True
    assert _fwval_can_early_return(
        True, ["deliverability_ui_page_unwired", "deliverability_ui_flow_missing"]) is True


def test_checklist_blocker_mixed_with_non_fixable_still_runs():
    # if the checklist blocker is present, keep running even alongside a non-fixable one
    # (re-validation clears the checklist; the other blocker has its own heal path).
    assert _fwval_can_early_return(
        True, ["verification_checklist_not_ready", "deliverability_ui_page_unwired"]) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
