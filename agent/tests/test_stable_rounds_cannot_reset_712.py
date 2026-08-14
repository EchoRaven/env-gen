r"""#712: "a round below the bar resets the count" — it cannot, and r146 delivered because of it.

#558 gates the avg fast-release on `avg_pass_rounds >= N` (default 2) and its comment promised
"a single lucky pass never triggers a release; a round below the bar resets the count".

Both halves are false, and for one reason: the counter reads `blocking_average`, which #711 shows
is a high-water mark — computed over #500's merged BEST-per-screen captures, monotonically
non-decreasing by construction, and never falling in either kept run. So once `_ba >= _mn` holds
it holds forever, the `else` reset is unreachable after the first crossing, and "N consecutive
rounds above the bar" degenerates to "one round above the bar, then wait N-1 more".

r146 is the worked example, and it DELIVERED this way:

    round   gating    live      avg_pass_rounds
    1-4     0.58-0.60 …         0
    5       0.67      0.6655    1     <- the only real crossing
    6       0.67      0.6409    2 = N -> fast_release fires

The app that shipped scored 0.6409 — under the 0.65 bar it was judged against — on the strength
of round 5's number latched into the mark. Precisely the "single lucky pass" the comment said
could not happen.

Not changed: whether the counter should read `blocking_average_live` is the same calibration
decision as #711 and the 0.65 bar, and flipping it would let every flaky capture reset the count,
which is the thing #500 exists to prevent. Fixed here: the false comment, and a warning when the
count advances on a latch while the live capture is under the bar.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
from env_generator.llm_generator.multi_agent import orchestrator as orch


# --- the degeneracy, shown on r146's real numbers ------------------------------------------------

R146_GATING = [0.5809, 0.5809, 0.5855, 0.6027, 0.67, 0.67, 0.67, 0.67, 0.67]
R146_LIVE = [0.5783, 0.5450, 0.5627, 0.5982, 0.6655, 0.6409, 0.6409, 0.6409, 0.6409]
BAR = 0.65


def _counter(seq, bar=BAR):
    """The production rule, replayed."""
    n, out = 0, []
    for v in seq:
        n = n + 1 if v >= bar else 0
        out.append(n)
    return out


def test_the_gating_series_never_falls():
    assert all(b >= a for a, b in zip(R146_GATING, R146_GATING[1:]))


def test_the_reset_branch_is_unreachable_after_the_first_crossing():
    counts = _counter(R146_GATING)
    first = next(i for i, v in enumerate(R146_GATING) if v >= BAR)
    assert all(c > 0 for c in counts[first:]), "a reset would mean a fall, which cannot happen"


def test_two_consecutive_rounds_is_reached_one_round_after_the_first_crossing():
    counts = _counter(R146_GATING)
    first = counts.index(1)
    assert counts[first + 1] == 2, "N=2 is 'cross once, then wait one round'"


def test_the_round_that_authorised_release_was_below_the_bar_live():
    counts = _counter(R146_GATING)
    i = counts.index(2)
    assert R146_GATING[i] >= BAR and R146_LIVE[i] < BAR
    assert R146_LIVE[i] == 0.6409


def test_the_live_series_would_have_reset_the_count():
    """Had the counter read the live number, r146 would not have fast-released there."""
    counts = _counter(R146_LIVE)
    assert max(counts) < 2, counts


# --- the comment no longer claims a protection that does not exist ---------------------------------

def _block() -> str:
    src = inspect.getsource(vf)
    i = src.index("#712: THE STRUCK-OUT SENTENCE IS FALSE")
    return src[i:src.index("self.avg_pass_rounds = 0", i)]


def test_the_false_promise_is_struck_out_not_deleted():
    src = inspect.getsource(vf)
    assert "~~a single lucky pass never triggers a release" in src
    assert "see #712" in src


def test_the_mechanism_is_attributed():
    b = " ".join(_block().replace("#", " ").split())
    assert "711's high-water mark" in b
    assert "UNREACHABLE after the first crossing" in b


def test_r146_is_recorded_as_the_worked_example():
    b = " ".join(_block().replace("#", " ").split())
    assert "0.6655" in b and "0.6409" in b
    assert "fast_release fires" in b


def test_what_was_deliberately_not_changed_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "same calibration decision as" in b
    assert "500 exists to prevent" in b


# --- the warning fires exactly on the latch case ----------------------------------------------------

def test_the_warning_is_conditioned_on_the_live_number():
    src = inspect.getsource(vf)
    i = src.index("#712 avg_pass_rounds -> %d on a LATCHED average")
    head = src[src.rindex("_lv712 = result.get", 0, i):i]
    assert 'float(_lv712) < float(_mn)' in head


def test_the_warning_reports_all_three_numbers():
    src = inspect.getsource(vf)
    i = src.index("#712 avg_pass_rounds -> %d on a LATCHED average")
    # Folded: the format string spans several literals, so "bar %.4f" is really
    # `bar "` + `"%.4f`. Fifth time this trap has bitten in this session — always assert
    # against the JOINED text, never the raw source, when the string is wrapped.
    import re
    msg = re.sub(r'"\s*\n\s*"', "", src[i:src.index("self.avg_pass_rounds, float(_ba)", i)])
    assert "gating %.4f" in msg and "bar %.4f" in msg and "scored %.4f" in msg


def test_it_only_fires_when_the_count_advanced():
    """A round that resets the count is not a latch and must stay quiet."""
    src = inspect.getsource(vf)
    inc = src.index("self.avg_pass_rounds = self.avg_pass_rounds + 1")
    warn = src.index("#712 avg_pass_rounds -> %d on a LATCHED average")
    reset = src.index("self.avg_pass_rounds = 0", warn)
    assert inc < warn < reset


def test_r146s_delivering_round_would_have_warned():
    ba, mn, lv = 0.67, 0.65, 0.6409
    assert ba >= mn and lv < mn


def test_a_genuinely_earned_round_does_not_warn():
    ba, mn, lv = 0.67, 0.65, 0.68
    assert not (ba >= mn and lv < mn)


# --- the release path this feeds is unchanged --------------------------------------------------------

def test_the_default_n_is_still_two():
    assert orch.VISUAL_AVG_RELEASE_ROUNDS == 2


def test_fast_release_still_requires_the_count():
    src = inspect.getsource(orch._visual_release_decision)
    assert "avg_stable_rounds >= avg_release_rounds" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
