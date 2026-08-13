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
import inspect

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
