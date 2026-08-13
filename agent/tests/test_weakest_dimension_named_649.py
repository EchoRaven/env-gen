r"""#649: the lane got seven equal-looking fixes; only one of them moves the score.

Over the 412 judged screen records, the holistic `similarity` tracks the **minimum** dimension at
**r = 0.942** — higher than any single dimension (components 0.924, layout 0.910) and higher than
the unweighted mean (0.927) — with an offset of only **+0.047**. The score is *"the weakest
dimension plus a small allowance"*, not an average. On a screen whose weakest dimension is clearly
alone, improving any other one cannot move the number.

The lane was never told that:

    FIX instructions per blocking screen     mean 6.4, median 7, max 7
    weakest dimension clearly alone          211 of 299 blocking screens (71%)
    (gap >= 0.05 to the second-worst)        median gap 0.050

Seven identically-formatted asks, one of which is the gate. Naming it costs a line.

This is #619/#620 one level deeper — those told the lane the round delta and which screen it had
broken; this tells it which dimension the number is actually following. The ordering was already
worst-first (checked before writing anything, per the #636 lesson); what was missing was the
statement that the ordering has consequences.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import remediation_text as rt


def _screen(**scores):
    return {"min_similarity": 0.65, "summary": "x", "screens": [{
        "name": "browse", "route": "/browse", "similarity": 0.42,
        "dimensions": {k: {"score": v, "notes": f"{k} note", "fix": f"fix {k}"}
                       for k, v in scores.items()}}]}


def _line(body):
    return next((l for l in body.splitlines() if "score follows" in l), "")


# --- a clear weakest --------------------------------------------------------------------------

def test_it_names_the_weakest_dimension():
    line = _line(rt(_screen(layout=0.40, color=0.90, typography=0.80), None, set()))
    assert "WEAKEST" in line and "Layout structure (0.40)" in line


def test_it_says_the_others_cannot_move_the_number():
    line = _line(rt(_screen(layout=0.40, color=0.90), None, set()))
    assert "will not move it" in line


def test_the_statement_precedes_the_per_dimension_list():
    body = rt(_screen(layout=0.40, color=0.90, typography=0.80), None, set())
    assert body.index("score follows") < body.index("[Layout structure 0.40]")


def test_the_list_is_still_worst_first():
    """The ordering was already right; #649 only explains it."""
    body = rt(_screen(layout=0.40, color=0.90, typography=0.80), None, set())
    assert body.index("[Layout structure") < body.index("[Typography") < body.index("[Color")


def test_every_dimension_is_still_offered():
    """The other six are real defects worth fixing — they just will not lift the gate."""
    body = rt(_screen(layout=0.40, color=0.90, typography=0.80), None, set())
    for d in ("fix layout", "fix color", "fix typography"):
        assert d in body


# --- a tie ----------------------------------------------------------------------------------

def test_tied_weakest_dimensions_are_all_named():
    """29% of blocking screens have no clearly-alone weakest; claiming one would misdirect."""
    line = _line(rt(_screen(layout=0.40, components=0.42, color=0.90), None, set()))
    assert "WEAKEST" not in line
    assert "Layout structure" in line and "Component completeness" in line
    assert "all of them have to come up" in line


def test_the_tie_window_matches_the_measured_threshold():
    """0.05 is the median gap between worst and second-worst — the line the data draws."""
    apart = _line(rt(_screen(layout=0.40, components=0.46, color=0.9), None, set()))
    tied = _line(rt(_screen(layout=0.40, components=0.44, color=0.9), None, set()))
    assert "WEAKEST" in apart
    assert "WEAKEST" not in tied


# --- it must never break the body ----------------------------------------------------------------

def test_a_screen_with_one_dimension_says_nothing():
    assert _line(rt(_screen(layout=0.40), None, set())) == ""


def test_a_screen_with_no_dimensions_says_nothing():
    r = {"min_similarity": 0.65, "summary": "x",
         "screens": [{"name": "b", "route": "/b", "similarity": 0.4, "dimensions": {}}]}
    assert _line(rt(r, None, set())) == ""


def test_non_numeric_scores_are_ignored():
    r = {"min_similarity": 0.65, "summary": "x", "screens": [{
        "name": "b", "route": "/b", "similarity": 0.4,
        "dimensions": {"layout": {"score": "bad"}, "color": {"score": 0.9}}}]}
    assert _line(rt(r, None, set())) == ""      # only one usable score -> no claim


def test_the_rest_of_the_body_is_unchanged():
    body = rt(_screen(layout=0.40, color=0.90), None, set())
    assert body.startswith("Visual fidelity below threshold")
    assert "Fix the implemented screens to match the references:" in body


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf.remediation_text).replace("#", " ").split())
    assert "r=0.942" in flat
    assert "211 of 299" in flat and "6.4" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
