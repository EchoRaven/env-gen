r"""#655b: the capture/auth-unavailable refund was the one unbounded refund, and #655 widened it.

Second finding from cross-auditing this session's fixes against each other. Two refund branches
sit three lines apart in the fidelity tick:

    capture_unavailable / auth_unavailable  ->  self.attempts -= 1        (no bound)
    capture_transient (all-blank)           ->  bounded by _TRANSIENT_REFUND_CAP

#75a bounded the second one explicitly, "so a GENUINELY blank app can't defer forever". The
first never got the same treatment, and #655 — my own fix this session — widened its entry by
relaxing the auth wipeout from "every auth SCREEN bounced" to "every auth ROUTE bounced", which
is a strictly weaker condition (r30's shape now qualifies where it did not before).

The failure mode is #75a's, verbatim, in the auth path: a transient race clears on the re-mint
and never approaches the cap, but an app whose auth guard is actually broken satisfies the
wipeout EVERY round — so an unbounded refund means the fidelity gate never counts an attempt and
the run spins to wall-clock with no verdict and no remediation.

Now bounded by the same `_TRANSIENT_REFUND_CAP`, on its own milestone-anchored counter, and past
the cap the result flows to a real verdict exactly as the blank path does. The asymmetry predates
#655; #655 only made it easier to reach.
"""
import asyncio
import inspect
import pathlib
import types

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _tick_src():
    """The refund branch, bounded by the construct that follows it."""
    src = inspect.getsource(vf)
    i = src.index('if result.get("capture_unavailable") or result.get("auth_unavailable"):')
    return src[i:src.index("FIX #75a: EVERY judged screen", i)]


# --- the bound exists ---------------------------------------------------------------------------

def test_the_refund_is_gated_on_a_counter():
    body = _tick_src()
    assert "if self.unreachable_refunds < _TRANSIENT_REFUND_CAP:" in body


def test_the_counter_advances_with_each_refund():
    body = _tick_src()
    assert "self.unreachable_refunds += 1" in body


def test_it_reuses_the_existing_cap_rather_than_inventing_one():
    """No new tuned constant — the same bound #75a already justified."""
    body = _tick_src()
    assert "_TRANSIENT_REFUND_CAP" in body
    assert not any(tok in body for tok in ("< 3", "<= 3", "= 3"))


def test_past_the_cap_it_stops_refunding():
    body = _tick_src()
    assert "else:" in body
    tail = body[body.index("else:"):]
    assert "attempts" not in tail, "the else branch must not refund"


def test_past_the_cap_it_says_the_condition_is_persistent():
    body = _tick_src()
    assert "persistent, not transient" in body


def test_it_still_returns_either_way():
    """Both paths must skip the judgment — only the budget treatment differs."""
    body = _tick_src()
    code = [l.strip() for l in body.splitlines()
            if l.strip() and not l.strip().startswith("#")]
    assert code[-1] == "return"


# --- the counter is milestone-anchored, like #75a's -------------------------------------------------

def test_the_counter_is_initialised_beside_the_transient_one():
    src = inspect.getsource(vf)
    assert src.count("self.unreachable_refunds = 0") == 2, "both init sites, mirroring #75a"


def test_both_init_sites_also_set_the_transient_counter():
    src = inspect.getsource(vf)
    for m in range(src.count("self.unreachable_refunds = 0")):
        i = src.index("self.unreachable_refunds = 0") if m == 0 else src.index(
            "self.unreachable_refunds = 0", i + 1)
        window = src[max(0, i - 200):i]
        assert "self.transient_refunds = 0" in window


# --- the blank path is untouched --------------------------------------------------------------

def test_the_blank_refund_still_uses_its_own_counter():
    src = inspect.getsource(vf)
    assert "self.transient_refunds < _TRANSIENT_REFUND_CAP" in src


def test_the_two_counters_are_independent():
    """A run that burns its blank refunds must still get its auth refunds, and vice versa."""
    src = inspect.getsource(vf)
    assert "self.transient_refunds += 1" in src
    assert "self.unreachable_refunds += 1" in src


# --- provenance -------------------------------------------------------------------------------

def test_the_reason_matches_75a_s():
    body = _tick_src()
    assert "can't defer forever" in body


def test_the_own_goal_is_recorded():
    """#655 widened this entry; the note must say so rather than blame the older code."""
    body = _tick_src()
    assert "655 widened its entry" in body
    assert "asymmetry predates" in body or "predates #655" in body


def test_how_it_was_found_is_recorded():
    body = _tick_src()
    assert "645" in body


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: the refund, DRIVEN -----------------------------------------------------------------
#
# Every assertion above quotes a whole STATEMENT, which is nearly as strong as a structural check
# for that statement -- and still completely blind to whether it runs. Two mutations proved it:
#
#   * deleting `self.attempts = max(0, self.attempts - 1)` -- so an unreachable capture BURNS
#     one of the 3 per-source attempts while still logging "attempt refunded, will retry next
#     tick". Nothing in the file asserts the refund has an effect.
#   * putting a `return` above the whole arm, leaving every quoted statement verbatim in the
#     source and never executing any of it.
#
# `maybe_run` returns early on an unchanged app-source signature ("budget spent on this source
# state"), so `box["sig"]` has to move between ticks or every tick after the first is a no-op --
# which is how a working mechanism and a dead one come to look the same.


def _orch_1203pg(box):
    _noop = lambda *a, **k: None  # noqa: E731

    class _Bus:
        async def send(self, *a, **k):
            return None

    return types.SimpleNamespace(
        _reference_images=[{"name": "inbox", "route": "/inbox", "auth": True, "path": "x.png"}],
        _compute_app_source_signature=lambda: box["sig"],
        output_dir=str(pathlib.Path(__file__).resolve().parents[1]),
        llm=None, message_bus=_Bus(),
        _logger=types.SimpleNamespace(warning=_noop, info=_noop, error=_noop, debug=_noop),
        hubs=types.SimpleNamespace(
            workhub=types.SimpleNamespace(create_task=lambda **k: {"id": "t1"})),
    )


def _tick_1203pg(gate):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(gate.maybe_run())
    finally:
        loop.close()


def _unreachable_result():
    async def _fake(*a, **k):
        return {"passed": False, "capture_unavailable": True, "skipped": [], "screens": [],
                "summary": "capture/auth unavailable"}
    return _fake


def _gate_and_box(monkeypatch, result):
    box = {"sig": "sig0"}
    gate = vf.VisualFidelityGate(_orch_1203pg(box))
    gate.reset_for_milestone()
    monkeypatch.setattr(vf, "run_visual_fidelity", result)
    return gate, box


def test_an_unreachable_capture_really_refunds_the_attempt(monkeypatch):
    """The point of a refund: the attempt budget must be where it started."""
    gate, box = _gate_and_box(monkeypatch, _unreachable_result())
    for i in range(vf._TRANSIENT_REFUND_CAP):
        box["sig"] = "round-%d" % i
        _tick_1203pg(gate)
        assert gate.unreachable_refunds == i + 1, (i, gate.unreachable_refunds)
        assert gate.attempts == 0, (
            "an unreachable capture consumed attempt %d of 3 while claiming it was refunded"
            % gate.attempts)


def test_past_the_cap_the_attempt_is_NOT_refunded(monkeypatch):
    """The bound #655b is about: a genuinely-down app must not spin to wall-clock."""
    gate, box = _gate_and_box(monkeypatch, _unreachable_result())
    for i in range(vf._TRANSIENT_REFUND_CAP + 1):
        box["sig"] = "round-%d" % i
        _tick_1203pg(gate)
    assert gate.unreachable_refunds == vf._TRANSIENT_REFUND_CAP, gate.unreachable_refunds
    assert gate.attempts == 1, (
        "past the cap the round must cost an attempt, got attempts=%d" % gate.attempts)


def test_the_refund_counter_and_the_attempt_move_together(monkeypatch):
    """A refund that increments the counter but not the budget is the B1 mutation exactly."""
    gate, box = _gate_and_box(monkeypatch, _unreachable_result())
    box["sig"] = "one"
    _tick_1203pg(gate)
    assert (gate.unreachable_refunds, gate.attempts) == (1, 0)


def test_a_milestone_reset_clears_the_refund_budget(monkeypatch):
    """Mirrors #75a: the cap is milestone-anchored, so a new milestone starts fresh."""
    gate, box = _gate_and_box(monkeypatch, _unreachable_result())
    box["sig"] = "one"
    _tick_1203pg(gate)
    assert gate.unreachable_refunds == 1
    gate.reset_for_milestone()
    assert gate.unreachable_refunds == 0
