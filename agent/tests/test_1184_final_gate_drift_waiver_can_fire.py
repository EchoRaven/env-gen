"""#1184 — the #139 final-gate drift waiver had never once fired.

It exists for one situation: the milestone gate evaluates fully clear, every release is cut,
and then the FINAL gate fails on hub state a lane mutated during the multi-minute delivery
tail. It could not fire in that situation, because it was defined as
REVALIDATION_FIXABLE_CHECKS — which answers a different question ("can re-running validation
clear this?": chains, checklists). What actually fails at the final gate is something else.

Measured across seven netflix runs, the final gate rejected on first evaluation three times:

    r17  ['validation_ui_evidence_failed']   a stale ui_smoke record; the app worked
    r18  ['validation_ui_evidence_failed']   the #1181 label collision; the app worked
    r20  ['unresolved_failed_tasks']         a task that failed 30s AFTER DELIVER_PROJECT,
                                             reporting its own work already moot

Three for three outside the set; three runs ended; the waiver logged nothing in any of them.
r20 stopped with $73 and 26 minutes still available.

The tests that matter most here are the negative ones: widening the set must not weaken the
preconditions that make the waiver safe.
"""
import time

import pytest

from env_generator.llm_generator.multi_agent.orchestrator import (
    FINAL_GATE_DRIFT_CLASSES, REVALIDATION_FIXABLE_CHECKS, _final_gate_drift_waiver as waive,
)

NOW = time.time()
FRESH = NOW - 60.0


@pytest.mark.parametrize("failed", [
    ["unresolved_failed_tasks"],                       # r20
    ["validation_ui_evidence_failed"],                 # r17, r18
    ["business_chain_failing"],                        # the original class, unchanged
    ["validation_ui_evidence_failed", "unresolved_failed_tasks"],
])
def test_tail_drift_on_a_cleared_milestone_is_waived(failed):
    assert waive(FRESH, failed, NOW) is True


@pytest.mark.parametrize("failed", [
    ["docker_build_failed"],
    ["contract_alignment_failed"],
    ["backend_code_missing"],
    ["unresolved_failed_tasks", "docker_build_failed"],   # one structural disqualifies all
])
def test_structural_failures_are_never_waived(failed):
    assert waive(FRESH, failed, NOW) is False


def test_the_preconditions_still_do_the_work():
    assert waive(None, ["unresolved_failed_tasks"], NOW) is False, "milestone never cleared"
    assert waive(NOW - 1000.0, ["unresolved_failed_tasks"], NOW) is False, "outside the window"
    assert waive(FRESH, [], NOW) is False, "an empty failure set is not a waiver"


def test_the_revalidation_set_is_not_widened_with_it():
    """The two constants answer different questions; #1184 decoupled them. Re-running
    validation cannot clear a failed WorkHub task or rewrite a ui_smoke record, so those
    names must NOT leak into the revalidation path."""
    assert REVALIDATION_FIXABLE_CHECKS == frozenset(
        {"business_chain_failing", "verification_checklist_not_ready"})
    assert "unresolved_failed_tasks" not in REVALIDATION_FIXABLE_CHECKS
    assert "validation_ui_evidence_failed" not in REVALIDATION_FIXABLE_CHECKS
    assert REVALIDATION_FIXABLE_CHECKS < FINAL_GATE_DRIFT_CLASSES


def test_the_set_covers_every_final_gate_rejection_we_have_seen():
    """The three observed first-evaluation failure sets, verbatim from the run logs."""
    for observed in (["validation_ui_evidence_failed"], ["unresolved_failed_tasks"]):
        assert set(observed) <= FINAL_GATE_DRIFT_CLASSES, (
            f"{observed} ended a run whose milestone gate had already cleared")
