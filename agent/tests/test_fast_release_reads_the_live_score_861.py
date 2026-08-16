r"""#861: the release escape read the high-water merge, not what the app scored.

Found by finally opening the population I had walked past three times — the 94 of 151 runs with no
`generation_complete`. The first census said they die early. That was an **instrument artifact**:
`logs/progress_events.jsonl` holds only 4-5 lines even for r134 (which validated multi-milestone)
and r148 (which cut a release), so "last event = phase_start, 2 events, 0 minutes" described the
file, not the runs.

Rebuilt from the artifact tree, the picture inverts:

    of the 94 non-completed runs -- 70 reached the VISUAL GATE, 17 the frontend, 7 the backend

**74% got all the way to visual judging and then never finished.** The dominant failure is the
visual/delivery loop not terminating, not an early crash. And the two populations differ where it
counts:

    best similarity p50   completed 0.78    stuck 0.62      (the bar is 0.65)

`verdict.json` carries **two** averages, and the gap between them is the finding:

| | |
|---|---|
| runs recording both (r145-r151, `_live` is recent) | 7 |
| **merged >= 0.65 while live < 0.65** | **5 of 7** — r146, r147, r148, r150, r151 |
| median `merged - live` | **+0.068**, max **+0.505** |

`blocking_average` is #500's high-water merge across judged rounds. `blocking_average_live` is
what the current capture scored. ★ **visual_fidelity's own ranking already knows the difference**
— `better_state_available_641` ranks on `_live` and says why: *"`blocking_average` is #500's
[merge]"*. #558's fast-release escape took the other one.

**r148 is in that list, and r148 released v1.0.0 with the SPA throwing on every route.** #750's
`app_dead` veto catches the rendering half; this catches the score half.

★ Why the fix is free: #558's own docstring establishes that fast_release is *"a strict SUBSET of
the states the wall-clock escape would eventually release anyway"*. Declining it delays a release;
it can never prevent one. That is also why an absent `_live` declines rather than falls back.
"""
import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch


_BASE = dict(avg_release=True, coverage_ok=True, avg_release_rounds=2, avg_stable_rounds=2,
             avg_min=0.65, deferred_since=None, now=0.0, escape_s=1e9,
             total_judgments=0, total_cap=99, attempts=0, attempt_cap=99,
             plateau_cap=0, plateau_rounds=0, plateau_min_s=0)


def _d(**kw):
    return orch._visual_release_decision(**{**_BASE, **kw})


def test_an_honest_pass_still_fast_releases():
    """Non-vacuity and non-regression: #558's whole value is cutting 40-60 minutes off a run that
    genuinely cleared the bar. If this stops firing, the fix is a wall-clock tax, not a guard."""
    assert _d(blocking_average=0.70, blocking_average_live=0.70) == "fast_release"


def test_an_inflated_merge_no_longer_releases():
    """The measured case: 5 of the 7 runs that record both numbers sit exactly here."""
    assert _d(blocking_average=0.70, blocking_average_live=0.59) == "defer"


@pytest.mark.parametrize("live", [0.649, 0.50, 0.12, 0.0])
def test_any_live_score_below_the_bar_declines(live):
    assert _d(blocking_average=0.90, blocking_average_live=live) == "defer"


def test_a_missing_live_score_declines():
    """★ Fail closed, because declining is free — the wall-clock escape still releases. A fallback
    to the merged value would reinstate the exact defect for every pre-`_live` gate result."""
    assert _d(blocking_average=0.90, blocking_average_live=None) == "defer"


def test_the_live_score_alone_is_not_enough():
    """Both must clear. The merge is still a real signal about stability across rounds; #861 adds
    a condition, it does not swap one number for the other."""
    assert _d(blocking_average=0.50, blocking_average_live=0.90) == "defer"


def test_declining_the_fast_path_never_blocks_a_release():
    """★ The safety property the whole fix rests on, asserted rather than trusted: with the fast
    path denied, every other escape still fires."""
    inflated = dict(blocking_average=0.90, blocking_average_live=0.10)
    assert _d(deferred_since=0.0, now=1e6, escape_s=2400, **inflated) == "release"
    assert _d(total_judgments=99, total_cap=10, **inflated) == "release"
    assert _d(attempts=99, attempt_cap=3, **inflated) == "release"


def test_the_app_dead_veto_still_dominates():
    """#750 is placed first on purpose and must keep beating an honest fast-release too."""
    assert _d(blocking_average=0.90, blocking_average_live=0.90, app_dead=True) == "defer"


def test_the_gate_result_carries_the_live_number():
    """The plumbing half. A guard reading a key nobody populates is #737's shape — it would decline
    every fast release for the wrong reason and look like a working guard."""
    class _G:
        avg_pass_rounds = 2
        app_dead_750 = False
        last_result = {"blocking_average": 0.70, "blocking_average_live": 0.59,
                       "min_similarity": 0.65, "coverage": {"blocking_judged": 3}}
    args = orch._visual_fast_release_args(_G())
    assert args["blocking_average_live"] == 0.59, args
    assert args["blocking_average"] == 0.70, args


def test_the_two_numbers_are_not_the_same_field():
    """Non-vacuity for the premise: if the writer ever aliases them, this fix silently becomes a
    no-op and the corpus measurement above stops meaning anything."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf)
    assert '"blocking_average_live": _live_average' in src
    assert src.count("blocking_average_live") >= 4


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
