r"""#675: two different mistakes produced one message, and it named neither.

    if not isinstance(value, list) or len(value) < min_len:
        return f"{name} must be a list of length >= {min_len}"

A value that is not a list at all and a list that is merely too short returned identical text,
and neither said what had arrived. The agent could only guess which mistake it had made.

Measured over the 249 run logs, continuing the wasted-STEPS ranking that produced #674:

    submit_retro fails 1348 times
    1128 of those (84%) are this one line for `plan_vs_reality`
    concentrated in 23 runs at a median of 40 per run

That is the tightest retry loop left in the corpus after the chain-reject one (#664). Per #257
each retry is a whole step re-sending the prompt.

The per-ITEM errors around it were already good — "plan_vs_reality[0].drift_reason must be a
non-empty string" names the index and the key — so only the length/type gate was mute. Two
copies of the same function exist; both are fixed, covering seven fields:

    retro_tools               plan_vs_reality, lessons, proposed_prompt_changes
    structured_knowledge_tools  alternatives, steps, timeline, action_items

A string is called out specifically because passing the JSON as text is the mistake this shape
invites, and the remedy for it is different from adding entries.
"""
import pytest

from env_generator.llm_generator.tools.retro_tools import _validate_list_min as retro
from env_generator.llm_generator.tools.structured_knowledge_tools import (
    _validate_str_list_min as knowledge,
)

BOTH = pytest.mark.parametrize("v", [retro, knowledge])


# --- a short list says how short ------------------------------------------------------------

@BOTH
def test_it_reports_the_actual_length(v):
    assert "got 1" in v(["a"], "plan_vs_reality", 2)


@BOTH
def test_it_says_how_many_more_are_needed(v):
    assert "Add 1 more" in v(["a"], "plan_vs_reality", 2)


@BOTH
def test_an_empty_list_is_reported_as_zero(v):
    msg = v([], "steps", 3)
    assert "got 0" in msg and "Add 3 more" in msg


# --- a non-list says what it got instead --------------------------------------------------------

@BOTH
def test_a_dict_is_named_by_type(v):
    assert "got dict" in v({"a": 1}, "steps", 3)


@BOTH
def test_None_is_named_by_type(v):
    assert "got NoneType" in v(None, "steps", 3)


@BOTH
def test_a_string_gets_the_json_as_text_hint(v):
    """The mistake this shape invites, and its remedy differs from 'add entries'."""
    msg = v('["a","b","c"]', "steps", 3)
    assert "got str" in msg
    assert "passed as TEXT" in msg
    assert "not a string containing one" in msg


@BOTH
def test_a_string_is_never_told_to_add_entries(v):
    """Telling it to add entries would send it to lengthen the string."""
    assert "Add " not in v("abc", "steps", 3)


# --- the two cases are distinguishable -----------------------------------------------------------

@BOTH
def test_the_two_mistakes_no_longer_share_a_message(v):
    assert v(["a"], "steps", 3) != v("a", "steps", 3)


@BOTH
def test_the_field_name_is_still_first(v):
    assert v(["a"], "lessons", 2).startswith("lessons ")


@BOTH
def test_the_requirement_is_still_stated(v):
    assert ">= 2 entries" in v(["a"], "lessons", 2)


# --- a valid value still passes ------------------------------------------------------------------

@BOTH
def test_exactly_the_minimum_passes(v):
    assert v(["a", "b"], "lessons", 2) is None


@BOTH
def test_more_than_the_minimum_passes(v):
    assert v(["a", "b", "c"], "lessons", 2) is None


def test_the_knowledge_copy_still_checks_item_contents():
    """Its extra per-item guard must survive the length-gate rewrite."""
    assert knowledge(["a", "  "], "steps", 2) is not None


def test_the_retro_copy_still_feeds_the_per_item_checks():
    from env_generator.llm_generator.tools.retro_tools import _validate_pvr
    err = _validate_pvr([{"plan_item": "a", "actual_outcome": "b", "drift_reason": ""},
                         {"plan_item": "a", "actual_outcome": "b", "drift_reason": "c"}])
    assert "plan_vs_reality[0].drift_reason" in err


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools import retro_tools as rt
    flat = " ".join(inspect.getsource(rt._validate_list_min).replace("#", " ").split())
    assert "1128 of those (84%)" in flat
    assert "median of 40 per run" in flat


def test_the_twin_points_at_the_measurement():
    import inspect
    from env_generator.llm_generator.tools import structured_knowledge_tools as sk
    flat = " ".join(inspect.getsource(sk._validate_str_list_min).split())
    assert "retro_tools._validate_list_min" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
