r"""#680: the visual remediation task carried every blocking screen in full — up to 126 KB.

#679 traced check_inbox (187.3M chars, 46.7% of the 401M the per-run tool_io_rollup
tables account for) back to task descriptions.
This is where those descriptions come from, and it is the largest single object the system
produces:

    447 visual remediation tasks, median 8 screens and 57,815 chars, max 15 and 126,047
    432 of the 447 exceed 20 KB and hold 99% of their 28.2M chars
    `description` is 77.8% of ALL task bytes — 31.6M of 41M across 12,836 tasks
    the biggest single one: 977 lines, 92% unique, 13 screens, 126,047 chars

The loop walked `result["screens"]` in JUDGE order and emitted all of them. Two changes, and the
order matters more than the cap:

    sort worst-first   the screens furthest below the bar are what the gate waits on
    cap at 4           half the median screen count; 51% of the bytes, measured over the same 447

Capping loses nothing because remediation is RE-ISSUED every round — 447 tasks over ~100 runs,
about 4.5 per run — so a screen that does not fit this round leads the next. What WOULD lose work
is capping without ordering, which is the #662 shape one level up: there the 10-line measured-diff
window was filled in list order; here it was the screen list.

The deferred screens are named with their scores rather than silently dropped, and the text says
it is a sequencing decision, not a claim that they are fine.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _screens(n, base=0.90, step=0.05):
    return [{"name": f"s{i}", "route": f"/r{i}", "similarity": round(base - step * i, 2),
             "passed": False, "dimensions": {"layout": {"score": 0.3, "notes": "n", "fix": "f"}},
             "deviations": []} for i in range(n)]


def _text(screens, **kw):
    return vf.remediation_text({"min_similarity": 0.65, "summary": "x", "screens": screens},
                               None, kw.pop("latched", set()), **kw)


def _headings(out):
    import re
    return [h for h in re.findall(r"## (\S+)", out) if h.startswith("s")]


# --- worst-first ------------------------------------------------------------------------------

def test_the_screens_furthest_below_the_bar_come_first():
    out = _text(_screens(9))
    assert _headings(out) == ["s8", "s7", "s6", "s5"]


def test_judge_order_no_longer_decides():
    """The original loop emitted in result order; the worst screen could be last."""
    scr = _screens(6)
    scr.reverse()
    assert _headings(_text(scr))[0] == "s5"


def test_a_tie_does_not_crash():
    scr = _screens(6, step=0.0)
    assert len(_headings(_text(scr))) == 4


# --- the cap ------------------------------------------------------------------------------------

def test_at_most_four_screens_are_emitted():
    assert len(_headings(_text(_screens(15)))) == 4


def test_fewer_than_four_are_all_emitted():
    assert len(_headings(_text(_screens(3)))) == 3


def test_exactly_four_produces_no_deferral():
    assert "Not in this round" not in _text(_screens(4))


def test_a_single_screen_is_unchanged():
    out = _text(_screens(1))
    assert _headings(out) == ["s0"]
    assert "Not in this round" not in out


# --- nothing is silently dropped ------------------------------------------------------------

def test_the_deferred_screens_are_counted():
    assert "Not in this round (5 more below the bar)" in _text(_screens(9))


def test_the_deferred_screens_are_named_with_their_scores():
    out = _text(_screens(9))
    assert "s0 (0.90)" in out and "s4 (0.70)" in out


def test_it_says_they_lead_the_next_round():
    assert "they lead the next one" in _text(_screens(9))


def test_it_says_this_is_ordering_not_a_pass():
    out = _text(_screens(9))
    assert "ordered behind the screens above" in out


# --- the existing exclusions still apply ----------------------------------------------------------

def test_a_passed_screen_is_still_excluded():
    scr = _screens(6)
    scr[5]["passed"] = True          # the worst one
    assert "s5" not in _headings(_text(scr))


def test_a_latched_screen_is_still_excluded():
    """#129: a sticky-passed screen must not be re-worked."""
    assert "s5" not in _headings(_text(_screens(6), latched={"s5"}))


def test_a_latched_screen_is_not_listed_as_deferred_either():
    out = _text(_screens(9), latched={"s0"})
    assert "s0 (" not in out


def test_no_blocking_screen_at_all_produces_no_screen_sections():
    scr = _screens(3)
    for r in scr:
        r["passed"] = True
    assert _headings(_text(scr)) == []


# --- the body of a kept screen is untouched ---------------------------------------------------

def test_a_kept_screen_still_carries_its_dimension_lines():
    out = _text(_screens(9))
    assert "[Layout structure 0.30]" in out
    assert "FIX: f" in out


def test_the_header_is_unchanged():
    assert _text(_screens(9)).startswith("Visual fidelity below threshold")


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(vf.remediation_text).replace("#", " ").split())
    assert "median 8 screens and 57,815 chars" in flat
    assert "77.8% of ALL task bytes" in flat


def test_why_capping_is_safe_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(vf.remediation_text).split())
    assert "RE-ISSUED every round" in flat
    assert "capping WITHOUT ordering" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
