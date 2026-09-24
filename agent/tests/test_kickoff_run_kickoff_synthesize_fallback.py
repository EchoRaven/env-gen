"""Round-8c regression tests for ``run_kickoff.synthesize_fallback``.

The round-8a reviewer flagged a missing T=1200s circuit-breaker in
the kickoff coordinator; round-8b confirmed that the gap *was* the
first integration break (no driver + no attendee turn). Round-8c folds
the timeout/fallback into the Python driver and surfaces it through a
dedicated module-level helper so the driver stays small and the
fallback behaviour is independently testable.

These tests pin the fallback's contract closed-by-construction:

  * the helper MUST emit ``kickoff_failed`` with ``kickoff_fallback_used``
    set on the event payload (so external watchers can distinguish a
    timeout-driven abort from a clean kickoff_failed coming out of
    finalize_kickoff's partial_failure path);
  * the returned receipt MUST carry ``phase="timeout_fallback"`` so the
    orchestrator driver inspects-and-aborts rather than mistakenly
    continuing into delivery-gate checks;
  * a workhub.add_meeting_decision failure during the fallback MUST NOT
    mask the underlying timeout — the receipt is the source of truth;
  * an eventhub.publish_event failure during the fallback MUST NOT mask
    the timeout either — the receipt remains valid.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.kickoff import run_kickoff  # noqa: E402


class _RecordingEventhub:
    def __init__(self, raise_on_publish: bool = False) -> None:
        self.published: List[Dict[str, Any]] = []
        self._raise = raise_on_publish

    def publish_event(self, **kwargs: Any) -> None:
        if self._raise:
            raise RuntimeError("eventhub down")
        self.published.append(kwargs)


class _RecordingWorkhub:
    def __init__(self, raise_on_decision: bool = False) -> None:
        self.decisions: List[Dict[str, Any]] = []
        self._raise = raise_on_decision

    def add_meeting_decision(self, **kwargs: Any) -> Dict[str, Any]:
        if self._raise:
            raise RuntimeError("workhub down")
        self.decisions.append(kwargs)
        return {"id": f"dec-{len(self.decisions)}"}

    def list_meeting_decisions(self, **kwargs: Any) -> List[Dict[str, Any]]:
        return list(self.decisions)


class _Hubs:
    def __init__(
        self,
        eventhub: _RecordingEventhub,
        workhub: _RecordingWorkhub,
    ) -> None:
        self.eventhub = eventhub
        self.workhub = workhub


def _handle() -> Dict[str, Any]:
    return {
        "meeting_id": "mtg-1",
        "milestone_index": 1,
        "expected_attendees": ["design", "backend", "frontend", "verifier"],
        "started_at": 1000.0,
        "phase": "awaiting_decisions",
    }


def _last_synthesis_awaiting() -> Dict[str, Any]:
    return {
        "status": "awaiting",
        "missing": ["frontend", "verifier"],
        "milestone_index": 1,
    }


def _last_synthesis_conflict() -> Dict[str, Any]:
    return {
        "status": "conflict",
        "findings": [{"check": "api_vs_frontend", "status": "fail"}],
        "revisers": {"design": [{"check": "api_vs_frontend"}]},
        "milestone_index": 1,
    }


def test_fallback_emits_kickoff_failed_with_fallback_used_flag():
    eh = _RecordingEventhub()
    wh = _RecordingWorkhub()
    receipt = run_kickoff.synthesize_fallback(
        hubs=_Hubs(eh, wh),
        kickoff_handle=_handle(),
        last_synthesis=_last_synthesis_awaiting(),
    )

    assert receipt["phase"] == "timeout_fallback"
    assert receipt["kickoff_fallback_used"] is True
    assert receipt["missing"] == ["frontend", "verifier"]
    assert receipt["last_status"] == "awaiting"

    # kickoff_failed was emitted with the same flag on the payload so
    # external EventHub watchers can distinguish timeout-fallback from a
    # finalize_kickoff partial-failure (both emit kickoff_failed; only
    # the timeout case carries kickoff_fallback_used=True).
    assert len(eh.published) == 1
    event = eh.published[0]
    assert event["event_type"] == "kickoff_failed"
    payload = event["payload"]
    assert payload["meeting_id"] == "mtg-1"
    assert payload["milestone_index"] == 1
    assert payload["reason"] == "timeout"
    assert payload["last_status"] == "awaiting"
    assert payload["missing"] == ["frontend", "verifier"]
    assert payload["kickoff_fallback_used"] is True
    assert payload["timeout_sec"] == run_kickoff.KICKOFF_TIMEOUT_SEC
    assert event["recipients"] == [
        "design", "backend", "frontend", "verifier",
    ]
    assert event["caller"] == "orchestrator"
    assert event["source_hub"] == "orchestrator"

    # The fallback also stamps a phase_transition decision on the
    # meeting so persisted artifacts reflect the timeout (not only the
    # in-flight event). This is the closed-by-construction guard
    # against "silently degraded run".
    phase_decisions = [
        d for d in wh.decisions
        if isinstance(d.get("decision"), dict)
        and d["decision"].get("section") == "phase_transition"
    ]
    assert phase_decisions, (
        "fallback MUST record a phase_transition decision so the "
        "persisted meeting page surfaces the timeout"
    )
    pd_content = phase_decisions[-1]["decision"].get("content", {})
    assert pd_content.get("phase") == "timeout_fallback"


def test_fallback_preserves_conflict_findings_on_emitted_event():
    """If the driver hits conflict (cross-check fail) and falls through to
    the helper rather than dispatching revisers (M1 first-cut), the
    findings MUST land on the event payload so an external observer can
    see WHY the kickoff aborted."""
    eh = _RecordingEventhub()
    receipt = run_kickoff.synthesize_fallback(
        hubs=_Hubs(eh, _RecordingWorkhub()),
        kickoff_handle=_handle(),
        last_synthesis=_last_synthesis_conflict(),
    )
    assert receipt["findings"] == [
        {"check": "api_vs_frontend", "status": "fail"}
    ]
    assert receipt["last_status"] == "conflict"
    payload = eh.published[0]["payload"]
    assert payload["findings"] == [
        {"check": "api_vs_frontend", "status": "fail"}
    ]
    assert payload["last_status"] == "conflict"


def test_fallback_survives_eventhub_failure():
    """Eventhub down during fallback emission MUST NOT mask the timeout.

    The receipt is the contract — driver inspects receipt.phase. An
    exception escaping the helper would leave the orchestrator stuck in
    its poll loop waiting for an event that never came.
    """
    eh = _RecordingEventhub(raise_on_publish=True)
    wh = _RecordingWorkhub()
    receipt = run_kickoff.synthesize_fallback(
        hubs=_Hubs(eh, wh),
        kickoff_handle=_handle(),
        last_synthesis=_last_synthesis_awaiting(),
    )
    assert receipt["phase"] == "timeout_fallback"
    assert receipt["kickoff_fallback_used"] is True
    # No event was published (eventhub raised) but the phase_transition
    # decision still landed.
    assert eh.published == []
    pd = [
        d for d in wh.decisions
        if isinstance(d.get("decision"), dict)
        and d["decision"].get("section") == "phase_transition"
    ]
    assert pd, "phase_transition still must land even if eventhub fails"


def test_fallback_survives_workhub_failure():
    """Workhub down during phase_transition recording MUST NOT mask the
    timeout. The event is still emitted; the receipt remains valid."""
    eh = _RecordingEventhub()
    wh = _RecordingWorkhub(raise_on_decision=True)
    receipt = run_kickoff.synthesize_fallback(
        hubs=_Hubs(eh, wh),
        kickoff_handle=_handle(),
        last_synthesis=_last_synthesis_awaiting(),
    )
    assert receipt["phase"] == "timeout_fallback"
    assert wh.decisions == []  # workhub raised; nothing landed
    assert len(eh.published) == 1  # event still emitted
    assert eh.published[0]["event_type"] == "kickoff_failed"


@pytest.mark.parametrize("bad_handle", [
    None, {}, {"meeting_id": ""},
    {"meeting_id": "mtg-1", "milestone_index": 0},  # 0 is not 1-based
])
def test_fallback_rejects_malformed_kickoff_handle(bad_handle):
    """Phantom-default sniff: a bad handle MUST raise loudly. The
    orchestrator driver passes the handle from start_kickoff verbatim;
    a malformed value there is a bug, not a "soft" failure."""
    with pytest.raises((ValueError, TypeError)):
        run_kickoff.synthesize_fallback(
            hubs=_Hubs(_RecordingEventhub(), _RecordingWorkhub()),
            kickoff_handle=bad_handle,
            last_synthesis=_last_synthesis_awaiting(),
        )


def test_fallback_rejects_malformed_last_synthesis():
    with pytest.raises(ValueError, match="last_synthesis"):
        run_kickoff.synthesize_fallback(
            hubs=_Hubs(_RecordingEventhub(), _RecordingWorkhub()),
            kickoff_handle=_handle(),
            last_synthesis="not-a-mapping",  # type: ignore[arg-type]
        )


def test_module_constants_exported_for_driver():
    """The driver reads KICKOFF_POLL_INTERVAL_SEC and KICKOFF_TIMEOUT_SEC
    via the module so tests can monkey-patch without touching
    orchestrator.py. Pin both in the public surface."""
    assert "KICKOFF_POLL_INTERVAL_SEC" in run_kickoff.__all__
    assert "KICKOFF_TIMEOUT_SEC" in run_kickoff.__all__
    assert "synthesize_fallback" in run_kickoff.__all__
    assert run_kickoff.KICKOFF_TIMEOUT_SEC == 1200.0
    assert run_kickoff.KICKOFF_POLL_INTERVAL_SEC > 0.0
