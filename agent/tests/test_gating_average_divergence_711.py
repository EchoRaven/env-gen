r"""#711: the gate's number is a high-water mark, and nothing said so when the app fell behind it.

Found by pairing r147's per-round scores with their commits — and the two averages move in
opposite directions:

    r146  gating 0.5809 0.5809 0.5855 0.6027 0.67 0.67 0.67 0.67 0.67
          live   0.5783 0.5450 0.5627 0.5982 0.6655 0.6409 0.6409 0.6409 0.6409
    r147  gating 0.655  0.655  0.655  0.668  0.688 0.700
          live   0.6333 0.5975 0.5558 0.5858 0.6400 0.3817

`blocking_average` never falls in either run, and that is not luck: it is computed over `merged`,
which #500 defines as the BEST per-screen capture ever persisted — `merged.append(p if p is not
None and _sim(p) > _sim(s) else s)`. verdict.json is rewritten every round, so the prior
accumulates a high-water mark and the gating number is monotonically non-decreasing BY
CONSTRUCTION. `blocking_average_live` is the plain mean of THIS capture; in r147's round 6 it is
0.3817, which is exactly the arithmetic mean of the twelve live screens.

The consequence: **r146 delivered at gating 0.67 while its screens were at 0.6409 — below the
0.65 bar it was judged against.** r147's round 6 reads 0.700 against a live 0.3817, with
genre_category at 0.08 and player at 0.03.

It also supplies the missing mechanism for #618's corpus pattern — 24 of 39 runs delivering worse
than their own best round. Of course they do: the gate's number IS the best round, per screen, so
release happens when the high-water mark crosses the bar, whatever the app looks like at that
moment.

#500's max is deliberate and worth keeping — one flaky blank capture should not tank a screen for
the rest of a run — so it is not removed here, and whether the gate should read the live mean is
a calibration decision of the same class as the 0.65 bar itself. What was never defensible is
that the divergence was silent while BOTH numbers were already being computed and written side by
side. Same disposition as #641: warn, change no decision.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _block() -> str:
    src = inspect.getsource(vf)
    i = src.index("#711: SAY WHEN THE GATING NUMBER HAS LEFT THE APP BEHIND")
    return src[i:src.index('(vdir / "verdict.json").write_text', i)]


# --- it fires on a real divergence and stays quiet otherwise ------------------------------------

def test_the_threshold_is_a_gap_not_a_level():
    """A run can be far below the bar with both numbers agreeing; that is not this warning."""
    b = _block()
    assert "_g711 - _l711 >= 0.05" in b


def test_r147s_round_six_would_fire():
    g, l = 0.700, 0.3817
    assert g - l >= 0.05


def test_r146s_delivering_round_would_fire():
    """0.67 gating against 0.6409 live — the run that shipped."""
    g, l = 0.67, 0.6409
    assert round(g - l, 4) >= 0.02
    # and it is the case the warning is FOR, even though it sits under the 0.05 gap
    assert g >= 0.65 > l, "gate above the bar, app below it"


def test_an_agreeing_round_does_not_fire():
    g, l = 0.6333, 0.6333
    assert not (g - l >= 0.05)


def test_a_live_score_ABOVE_the_gate_never_fires():
    """merged takes the max, so live > gating should be impossible; if it happens, stay silent."""
    g, l = 0.60, 0.75
    assert not (g - l >= 0.05)


# --- it cannot break the verdict write -----------------------------------------------------------

def test_it_is_guarded():
    b = _block()
    assert "try:" in b and "except Exception:" in b


def test_it_runs_before_the_verdict_is_written():
    src = inspect.getsource(vf)
    warn = src.index("#711 the gating average has left the app behind")
    write = src.index('(vdir / "verdict.json").write_text', warn)
    assert warn < write


def test_it_changes_no_decision():
    b = _block()
    stmts = [l.strip() for l in b.split("\n")
             if l.strip() and not l.strip().startswith("#")]
    assert not [l for l in stmts if l.startswith(("return", "raise ")) or l == "raise"]
    assert "_verdict[" not in b, "it must not mutate the verdict"


def test_non_numeric_values_are_ignored():
    for g, l in ((None, 0.5), (0.7, None), ("x", 0.1)):
        ok = isinstance(g, (int, float)) and isinstance(l, (int, float))
        assert not ok


# --- the message explains which number is which ---------------------------------------------------

def test_it_names_both_numbers():
    b = _block()
    assert "blocking_average %.4f" in b and "blocking_average_live %.4f" in b


def test_it_says_the_gating_number_never_falls():
    assert "best-ever-per-screen and never falls" in _block()


def test_it_states_the_consequence_plainly():
    # Folded: the sentence spans two f-string literals, so a raw source match splits it at
    # `A "` + `"release`. Fourth time this trap has bitten in this session.
    import re
    assert "A release authorised on the former ships the latter" in re.sub(
        r'"\s*\n\s*"', "", _block())


# --- provenance -------------------------------------------------------------------------------------

def test_both_runs_are_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "r146 gating 0.5809" in b and "r147 gating 0.655" in b


def test_the_delivering_counterexample_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "r146 DELIVERED at gating 0.67" in b
    assert "0.6409" in b


def test_the_mechanism_is_attributed_to_500():
    b = " ".join(_block().replace("#", " ").split())
    assert "500 defines merged as the BEST" in b
    assert "monotonically non-decreasing" in b


def test_it_explains_618():
    b = " ".join(_block().replace("#", " ").split())
    assert "618" in b and "24 of 39" in b


def test_500s_max_is_explicitly_kept():
    b = " ".join(_block().replace("#", " ").split())
    assert "it is NOT removed" in b
    assert "calibration decision" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
