r"""#1202ed: nine kickoff aborts, one message, and it says "timed out".

Every `_kickoff_fallback_or_reconcile` call site passes a distinct reason -- timeout,
escalate, max_rounds, driver_wedged, consensus_not_ready, initial_stall, no_revisers,
unknown_action, provider_terminal -- and all nine return the same phase,
"timeout_fallback". The orchestrator raises on that phase with:

    "Kickoff timed out after {KICKOFF_TIMEOUT_SEC:.0f}s without a ready synthesis..."

Only one of the nine is a timeout. And this string is what `.checkpoint` stores as
`last_error` -- the only durable record a dead run leaves.

googlemaps-r15, measured:

    .checkpoint  last_error = "Kickoff timed out after 1200s ... Missing=[]
                               last_status='validation_failed'"
    log          "Facilitator escalated kickoff" at 03:38:39  (reason=escalate)
    log          kickoff_driver's own timeout line: ABSENT from the entire run
    wall clock   03:24:27 -> 03:38:41 = 854s

Wrong mechanism, and a duration that could not have elapsed: 1200s is the CAP, printed
where a measurement belongs -- the same substitution #1192b fixed for tick counts.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

GEN = THIS_DIR.parent / "env_generator" / "llm_generator"
ORCH = (GEN / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
DRIVER = (GEN / "multi_agent" / "runtime" / "kickoff_driver.py").read_text(encoding="utf-8")


def _raise_segment():
    """The abort branch only. Anchored on this fix's own marker: an earlier
    `phase == "timeout_fallback"` check guards the FIX #95 retry, and starting there
    would sweep in that retry's legitimate `KICKOFF_TIMEOUT_SEC + 600` wait."""
    i = ORCH.index("# #1202ed: SAY WHAT ACTUALLY HAPPENED")
    return ORCH[i:ORCH.index('if kickoff_receipt.get("phase") != "finalized":', i)]


def test_the_cap_is_no_longer_printed_as_the_duration():
    """1200s was KICKOFF_TIMEOUT_SEC, not what the run measured."""
    seg = _raise_segment()
    assert "KICKOFF_TIMEOUT_SEC" not in seg, (
        "the abort still reports its own ceiling as the elapsed time")


def test_the_measured_elapsed_reaches_the_message():
    seg = _raise_segment()
    assert "abort_elapsed_1202ed" in seg


def test_a_non_timeout_abort_does_not_claim_a_timeout():
    seg = _raise_segment()
    assert "not a timeout" in seg
    assert "abort_reason_1202ed" in seg


def test_a_real_timeout_still_reads_as_one():
    """The one reason of nine that IS a timeout keeps its wording."""
    seg = _raise_segment()
    assert '"Kickoff timed out after "' in seg
    assert '_why_1202ed == "timeout"' in seg


def test_every_abort_is_stamped_at_the_single_choke_point():
    i = DRIVER.index("def _kickoff_fallback_or_reconcile")
    seg = DRIVER[i:DRIVER.index("async def _dispatch_implementation_phase", i)]
    assert "abort_reason_1202ed" in seg
    assert "abort_elapsed_1202ed" in seg
    assert "warn_once_1201" in seg, "a silent guard here loses the reason invisibly (#1201)"


def test_the_reconciled_receipt_is_not_stamped():
    """A reconcile SUCCEEDS -- stamping it would label a recovery as an abort."""
    i = DRIVER.index("def _kickoff_fallback_or_reconcile")
    seg = DRIVER[i:DRIVER.index("async def _dispatch_implementation_phase", i)]
    early = seg[:seg.index("abort_reason_1202ed")]
    assert "return receipt" in early, (
        "the reconciled receipt must return before the abort stamp")


def test_all_nine_reasons_still_reach_the_stamp():
    """The vocabulary this fix exists to preserve."""
    import re
    calls = re.findall(r'_kickoff_fallback_or_reconcile\(\s*[^)]*?"([a-z_]+)"',
                       DRIVER + ORCH, re.S)
    for expected in ("timeout", "escalate", "max_rounds", "provider_terminal",
                     "driver_wedged"):
        assert expected in calls, f"{expected} no longer reaches the stamp"
    assert len(set(calls)) >= 9, f"expected >=9 distinct abort reasons, got {sorted(set(calls))}"


def test_an_unstamped_receipt_still_raises_sensibly():
    """Receipts built elsewhere must not crash the abort path."""
    seg = _raise_segment()
    assert 'or "timeout"' in seg
    assert "an unrecorded interval" in seg
