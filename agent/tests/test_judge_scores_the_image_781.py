r"""#781: the judge marked down chrome the reference does not show.

`player` fails the visual bar in 46% of r99+ runs, and the complaint is the same every time.
Across 40 judged records the word `scrub` appears in **39**, alongside:

    "bottom-left controls: missing skip-back and skip-forward buttons around the pause button"
    "bottom-right controls: missing next-episode and CC/subtitles icons next to fullscreen"

**The reference shows an AD playing.** Back arrow, flag/report, an `Ad 12` badge, pause, volume,
"All American begins after ads", fullscreen — and a Netflix ad view has no scrubber, no skip, no
CC and no next-episode control. The framework's own decomposition finds exactly those eight
components and no more, in **53 of 53 runs**: the decomposition is right, and the judge is scoring
against its prior of what a Netflix player looks like rather than against the image in front of
it.

The instructions invited it. They said *"Weigh component completeness and layout most heavily"*
and never defined completeness. For a screen from a famous product, an undefined completeness
bar is the model's training data.

This is the second judge error found in one sitting — item 104 recorded the first, where
`browse_by_languages` was marked down for having one language dropdown when the built page has
two `<select>` elements and the screenshot shows both. **A deviation is evidence, not ground
truth**, and #778's case rested partly on deviations, so the caveat matters beyond this screen.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


T = vf._JUDGE_INSTRUCTIONS


# --- the new rule -------------------------------------------------------------------------------

def test_completeness_is_defined_by_the_image():
    assert "COMPLETENESS IS DEFINED BY THE REFERENCE IMAGE, NOT BY THE PRODUCT" in T


def test_a_control_the_reference_lacks_is_not_missing():
    assert "A control the reference does not show is NOT missing" in T


def test_it_names_the_recognisable_product_trap():
    """The failure mode is specific to a screen the model recognises."""
    assert "even when the real product has it" in T
    assert "instantly recognisable" in T


def test_partial_states_are_scored_as_themselves():
    """The player reference is an ad view; the modal and loading cases are the same shape."""
    assert "an ad playing, a modal open, a loading view" in T
    assert "score the implementation against THAT state" in T


def test_the_missing_list_must_be_pointable():
    """`missing` feeds remediation tasks, so an invented entry costs the lane a round."""
    assert "Never list under `missing` an element you cannot point to in the first image" in T


# --- nothing else moved ----------------------------------------------------------------------------

def test_the_original_instructions_survive():
    for keep in ("You are a strict UI-fidelity reviewer",
                 "IGNORE differences in user-generated content",
                 "judge the DESIGN",
                 "Weigh component completeness and layout most heavily",
                 "Respond with ONLY a JSON object"):
        assert keep in T, keep


@pytest.mark.parametrize("var", ["{name}", "{route}", "{rubric_block}"])
def test_the_template_variables_are_intact(var):
    """The instructions are `.format()`ed; a broken placeholder breaks every judgment."""
    assert var in T


def test_the_json_braces_are_still_escaped():
    """Doubled braces survive .format(); a single one raises at judge time."""
    assert '"dimensions": {{' in T
    assert T.count("{{") == T.count("}}")


def test_it_still_formats():
    out = T.format(name="player", route="/watch/1", rubric_block="- layout: ...")
    assert "player" in out and "/watch/1" in out
    assert "{" in out and "}" in out, "the JSON example must survive as literal braces"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
