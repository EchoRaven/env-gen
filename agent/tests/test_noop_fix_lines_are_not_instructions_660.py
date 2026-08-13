r"""#660: "FIX: None significant." was shipped to the lane as an instruction.

Mining the judge's `fix` field for framework-generated templates the way `deviations` was mined
for #655/#656/#657 — that hypothesis was WRONG and is retracted: 7781 of 8094 fix strings are
distinct, so `fix` is judge prose end to end and has no templates to trace back to an emitter.

What the same pass did surface is that **309 of 8094** fix instructions say there is nothing to
do — "None.", "No change needed.", "None significant." — and `remediation_text` emits any
truthy `fix` verbatim, so the lane reads them as work items. #649 measured the lane already
receiving a mean of 6.4 instructions per blocking screen, of which only the weakest dimension
can move the gate; these add pure dilution.

Dropping them is safe rather than blinding, and that was checked rather than assumed: **no
screen has all of its fixes in this shape (0 of 1254), and no blocking screen does either
(0 of 299)** — so nothing is ever left without an actionable line.

The first cut of the filter was wrong in the dangerous direction. Anchoring on "none|no" and
running word characters to the end matched all 309 — but **14 of those carry a real instruction
after a continuation word**, and dropping them would have silenced actual remediation:

    'No changes needed BEYOND adding missing labels.'
    'No change needed BEYOND removing the amber hero image dominating the top.'
    'No major change needed ONCE hero image renders correctly.'
    'None major BEYOND adding Kids gradient tile.'

Caught by listing every string the filter would drop and reading all of them, rather than
trusting the count. Final rule: starts with none/no, no continuation marker, and short — 295
dropped across the corpus, 27 distinct shapes, every one read and confirmed inert.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _is_noop_fix_660 as noop,
    remediation_text as rt,
)


# --- what must be dropped (verbatim from the corpus) -----------------------------------------

@pytest.mark.parametrize("text", [
    "None significant.", "None.", "No change needed.", "No change.",
    "No changes needed.", "None major.", "No copy changes needed.",
    "No major change needed.", "No major change.", "No major changes.",
    "None significant", "None", "No major color changes needed.", "None needed.",
    "No changes.", "None material.", "None required", "No copy changes required.",
    "No changes needed for chrome copy.", "None needed for palette.",
    "No changes needed to palette.",
])
def test_a_pure_noop_is_dropped(text):
    assert noop(text) is True


# --- what must NOT be dropped (also verbatim) --------------------------------------------------

@pytest.mark.parametrize("text", [
    "No changes needed beyond adding missing labels.",
    "No change needed beyond removing the amber hero image dominating the top.",
    "None significant beyond avatar art.",
    "None needed beyond user avatar art.",
    "No color changes required beyond adding missing UI.",
    "No change beyond adding missing UI in correct neutrals.",
    "No change needed beyond ensuring avatar renders.",
    "No color changes needed beyond removing the hero image tint.",
    "None significant beyond popover styling.",
    "No change beyond adding correct content.",
    "No change needed beyond removing duplicated overlay tint.",
    "No major change needed once hero image renders correctly.",
    "None major beyond adding Kids gradient tile.",
    "None significant beyond removing colored hero imagery on this page.",
])
def test_an_instruction_hiding_behind_a_continuation_word_survives(text):
    """The 14 the first cut of this filter would have silenced."""
    assert noop(text) is False


@pytest.mark.parametrize("text", [
    "No hover state on the cards — add one",
    "None of the rows have a title; add them",
    "Nothing renders: mount the page",
    "Not enough contrast — darken the overlay",
    "Add chevron-down icon next to 'Get Help'.",
])
def test_a_real_instruction_that_merely_starts_with_no_survives(text):
    assert noop(text) is False


def test_a_long_string_is_never_treated_as_a_noop():
    """Length is the backstop for a continuation word this filter has not seen."""
    assert noop("No changes " + "x" * 60) is False


def test_empty_and_malformed_input_is_safe():
    for x in ("", "   ", None):
        assert noop(x) is False


# --- the body -----------------------------------------------------------------------------

def _screen(**fixes):
    return {"min_similarity": 0.65, "summary": "x", "screens": [{
        "name": "browse", "route": "/browse", "similarity": 0.42,
        "dimensions": {k: {"score": 0.4, "notes": f"{k} note", "fix": v}
                       for k, v in fixes.items()}}]}


def test_the_noop_line_no_longer_reaches_the_lane():
    body = rt(_screen(layout="None significant.", color="Darken the overlay"), None, set())
    assert "FIX: None significant." not in body
    assert "FIX: Darken the overlay" in body


def test_the_dimension_note_is_still_shown():
    """Only the empty INSTRUCTION goes; the observation that produced the score stays."""
    body = rt(_screen(layout="None significant."), None, set())
    assert "layout note" in body


def test_a_screen_whose_fixes_are_all_noops_still_reports_itself():
    """0 of 1254 screens look like this, but the body must not collapse if one ever does."""
    body = rt(_screen(layout="None.", color="No change."), None, set())
    assert "browse" in body and "0.42" in body


def test_the_rest_of_the_body_is_unchanged():
    body = rt(_screen(layout="Darken the overlay"), None, set())
    assert body.startswith("Visual fidelity below threshold")
    assert "FIX: Darken the overlay" in body


# --- provenance -----------------------------------------------------------------------------

def test_the_measurement_and_the_near_miss_are_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf).replace("#", " ").split())
    assert "309 strings" in flat or "309 of 8094" in flat
    assert "14 of them carry a real instruction" in flat
    assert "0 of 299" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
