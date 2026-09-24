"""FIX #75a — visual-capture blank-shell detect + BOUNDED transient refund (outlook run-62).

A page that reached networkidle but is still an un-hydrated SPA shell was screenshotted,
judged 0.00, and BURNED one of the 3 per-source visual attempts with no refund → the budget
exhausted → the 900s deferral escape. Now such all-blank captures are refunded, BOUNDED by
_TRANSIENT_REFUND_CAP (milestone-anchored) so a genuinely-blank app still becomes a real 0.00
verdict + remediation and cannot defer forever. A PARTIAL-blank capture (some real verdicts)
is NOT refunded — its real sibling verdicts + remediation must flow. LOCAL-ONLY (gitignored).
"""

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.visual_fidelity as vf  # noqa: E402


def _mock_orch():
    _noop = lambda *a, **k: None  # noqa: E731
    logger = types.SimpleNamespace(warning=_noop, info=_noop, error=_noop, debug=_noop)
    workhub = types.SimpleNamespace(create_task=lambda **k: {"id": "t1"})
    hubs = types.SimpleNamespace(workhub=workhub)

    class _Bus:
        async def send(self, *a, **k):
            return None
    return types.SimpleNamespace(
        _reference_images=[{"name": "inbox", "route": "/inbox", "auth": True, "path": "x.png"}],
        _compute_app_source_signature=lambda: "sig1",
        output_dir=str(ROOT), llm=None, _logger=logger, hubs=hubs, message_bus=_Bus(),
    )


def _run(gate):
    loop = asyncio.new_event_loop()  # fresh loop per call — isolated from other async tests
    try:
        loop.run_until_complete(gate.maybe_run())
    finally:
        loop.close()


def test_all_blank_capture_is_refunded_up_to_cap_then_becomes_real_verdict(monkeypatch):
    orch = _mock_orch()
    gate = vf.VisualFidelityGate(orch)
    gate.reset_for_milestone()

    async def _fake_run(*a, **k):
        # every judged screen blank ⇒ no shots ⇒ capture_transient True
        return {"passed": False, "capture_transient": True, "screens": [],
                "summary": "blank shell", "skipped": []}
    monkeypatch.setattr(vf, "run_visual_fidelity", _fake_run)

    cap = vf._TRANSIENT_REFUND_CAP
    for i in range(cap):
        _run(gate)
        assert gate.transient_refunds == i + 1, (i, gate.transient_refunds)
        assert gate.attempts == 0, "a refunded transient must not consume an attempt"
        assert gate.total_judgments == 0, "a refund is not a real verdict"
        assert gate.last_judged_sig is None, "a refund must not latch the sig"

    # past the cap: the SAME blank result is NO LONGER refunded → it becomes a real 0.00
    # verdict (attempt consumed, real-judgment counted, remediation filed) so a truly-blank
    # app cannot defer forever.
    _run(gate)
    assert gate.transient_refunds == cap, "refunds are bounded at the cap"
    assert gate.attempts == 1, "past the cap the blank consumes a real attempt"
    assert gate.total_judgments == 1, "past the cap it is a real verdict"


def test_partial_blank_is_not_refunded(monkeypatch):
    """capture_transient is False when SOME screens produced real verdicts — those must be
    judged + remediated this tick, never discarded by a blank sibling."""
    orch = _mock_orch()
    gate = vf.VisualFidelityGate(orch)
    gate.reset_for_milestone()

    async def _fake_run(*a, **k):
        return {"passed": False, "capture_transient": False,
                "screens": [{"name": "inbox", "similarity": 0.55, "passed": False}],
                "summary": "below 0.65: inbox(0.55) [blank capture: compose]", "skipped": []}
    monkeypatch.setattr(vf, "run_visual_fidelity", _fake_run)

    _run(gate)
    assert gate.transient_refunds == 0, "partial-blank must NOT refund"
    assert gate.attempts == 1, "the real sibling verdict consumes the attempt"
    assert gate.total_judgments == 1, "the real verdict is counted + remediated"


def test_reset_for_milestone_zeroes_transient_refunds():
    orch = _mock_orch()
    gate = vf.VisualFidelityGate(orch)
    gate.transient_refunds = 2
    gate.reset_for_milestone()
    assert gate.transient_refunds == 0


def test_capture_transient_is_all_blank_only_rule():
    """Documents the amendment: transient (refundable) ⇔ every judged screen blank (no
    shots). bool(blank) alone (ANY blank) would wrongly discard real sibling verdicts."""
    def transient(blank, shots):
        return bool(blank) and not shots
    assert transient(["a", "b"], {}) is True          # all blank → refundable
    assert transient(["a"], {"b": "b.png"}) is False   # partial → judged, not refunded
    assert transient([], {"a": "a.png"}) is False      # none blank
    assert transient([], {}) is False                  # empty (routed to capture_unavailable)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
