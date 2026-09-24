"""Direction C (2026-06-29): the framework's deterministic validation must KEEP re-running
while the delivery gate is blocked on business_chain_failing, even after api_smoke passes —
so the framework re-validates the verifier's registered chains from the integration tree
(which always has the framework-delivered Dockerfile) instead of waiting on a flaky/idle
verifier that validated in a stale worktree (outlook-seed1 stall). Without this, maybe_run
early-returns the moment api_smoke passes → business_chain never re-validated → milestone
wedged.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.orchestrator import _fwval_can_early_return  # noqa: E402


def test_no_passing_run_never_early_returns():
    # before api_smoke passes, validation must keep running regardless of checks
    assert _fwval_can_early_return(False, []) is False
    assert _fwval_can_early_return(False, ["business_chain_failing"]) is False


def test_passing_run_and_clean_gate_is_done():
    assert _fwval_can_early_return(True, []) is True
    assert _fwval_can_early_return(True, None) is True


def test_business_chain_failing_keeps_revalidating():
    # the fix: a passing api_smoke run does NOT stop validation while business_chain fails
    assert _fwval_can_early_return(True, ["business_chain_failing"]) is False
    assert _fwval_can_early_return(True, ["api_coverage", "business_chain_failing"]) is False


def test_other_post_apismoke_blockers_do_not_keep_running():
    # ui_page_unwired / business_chain_MISSING are not fixable by re-running validation,
    # so they don't keep the framework-validation loop spinning here
    assert _fwval_can_early_return(True, ["ui_page_unwired"]) is True
    assert _fwval_can_early_return(True, ["business_chain_missing"]) is True


def test_import_wired_into_framework_validation():
    # the predicate must be importable exactly as framework_validation.maybe_run imports it
    from multi_agent.orchestrator import (  # noqa: F401
        _fwval_should_attempt, _fwval_failure_set, _fwval_stuck_decision,
        _fwval_can_early_return, FWVAL_FAST_CAP)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
