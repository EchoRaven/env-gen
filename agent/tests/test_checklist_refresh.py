"""FIX #120 — a stale build:* failure checklist triggers a FRAMEWORK re-validation
(instagram-core-di run-38, 2026-07-09 09:57 STUCK, artifact-diagnosed).

run-38's M3: functional validation PASSED (api_smoke 08:20, RunHub run recorded),
the visual window ran its course, delivery writes committed at 09:52 — but a
run_validation at 09:37 (mid visual-churn rebuild window) FAILED transiently and
its _record_build_checks stamped all four build:* CodeHub checks = failure. Nothing
ever re-ran validation afterwards, so the checklist stayed red; the remediation for
verification_checklist_not_ready messages the VERIFIER to re-run run_validation —
LLM-dependent, and it never complied — so the deterministic no-convergence watchdog
aborted an otherwise-deliverable run at the 75min wall.

Fix: when the deliver gate declines with verification_checklist_not_ready among the
failed checks, the framework deterministically resets its own api_smoke attempt
counter (bounded per milestone) so the fast-retry re-runs validation itself — the
shared RunValidationTool then records FRESH build:* truth (success supersedes the
stale failure; a real failure re-records with fresh evidence). No LLM in the loop.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.framework_validation import (  # noqa: E402
    maybe_refresh_stale_build_checklist)


class _Orch:
    def __init__(self):
        self._framework_validation_attempts = 6      # at cap: slow post-cap cycles
        self._current_milestone_version = "1.2.0"
        self._logger = logging.getLogger("t120")


def test_refresh_fires_and_resets_attempts():
    o = _Orch()
    assert maybe_refresh_stale_build_checklist(
        o, ["verification_checklist_not_ready"]) is True
    assert o._framework_validation_attempts == 0     # fast retry re-runs api_smoke


def test_noop_without_the_blocker():
    o = _Orch()
    assert maybe_refresh_stale_build_checklist(o, ["business_chain_failing"]) is False
    assert o._framework_validation_attempts == 6


def test_budget_bounded_per_milestone():
    o = _Orch()
    fired = 0
    for _ in range(10):
        o._framework_validation_attempts = 6
        if maybe_refresh_stale_build_checklist(
                o, ["verification_checklist_not_ready"]):
            fired += 1
    assert fired == 3                                 # bounded: no refresh livelock
    # a NEW milestone gets a fresh budget
    o._current_milestone_version = "1.3.0"
    o._framework_validation_attempts = 6
    assert maybe_refresh_stale_build_checklist(
        o, ["verification_checklist_not_ready"]) is True


def test_never_raises_on_broken_orch():
    assert maybe_refresh_stale_build_checklist(object(), ["x"]) is False


def test_wired_into_deliver_decline_path():
    import inspect
    from multi_agent import orchestrator as om
    assert "maybe_refresh_stale_build_checklist" in inspect.getsource(om)
