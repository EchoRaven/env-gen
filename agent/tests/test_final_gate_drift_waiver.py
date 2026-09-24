"""FIX #139 — a failed FINAL delivery gate is waived when the milestone gate's fully-
clear verdict is FRESH and the failure set is ONLY registry-state drift classes.

ig run-61 (log-mined, ≥3 known occurrences incl. outlook run-28/31): all 4 milestones
delivered and the milestone gate evaluated fully clear, but the post-loop final gate
re-READS mutable hub state — the verifier re-registered a chain (status='registered',
never run) 1 second before the final evaluation, business_chain_blockers flags any
non-passing chain, and a 3.4h fully-delivered run died with Status: FAILED. Structural
failures (docker/contract/build) are never waived.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.orchestrator import _final_gate_drift_waiver  # noqa: E402


def test_fresh_verdict_and_drift_only_failures_are_waived():
    assert _final_gate_drift_waiver(1000.0, ["business_chain_failing"], 1200.0)
    assert _final_gate_drift_waiver(
        1000.0, ["business_chain_failing", "verification_checklist_not_ready"], 1500.0)


def test_stale_verdict_is_not_waived():
    assert not _final_gate_drift_waiver(1000.0, ["business_chain_failing"], 2000.0)


def test_no_milestone_verdict_is_not_waived():
    assert not _final_gate_drift_waiver(None, ["business_chain_failing"], 100.0)


def test_structural_failures_are_never_waived():
    # any non-drift check in the set disqualifies the whole waiver
    assert not _final_gate_drift_waiver(
        1000.0, ["business_chain_failing", "docker_up"], 1100.0)
    assert not _final_gate_drift_waiver(1000.0, ["contract_alignment_failed"], 1100.0)


def test_empty_failure_set_is_not_a_waiver_case():
    assert not _final_gate_drift_waiver(1000.0, [], 1100.0)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
