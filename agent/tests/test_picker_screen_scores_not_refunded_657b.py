r"""#657b: #657 silently moved profile-picker screens from "refunded" to "scored 0.0".

Found by cross-auditing this session's fixes against each other rather than against the corpus —
the #645 shape, where one of my own fixes shadowed another. Six landed in `visual_fidelity.py`
(#655, #656, #657, #660, #661, #662) and two of them meet here:

    #657  split picker-stuck screens out of `_blank_screens` into `_picker_screens`, because
          "the SPA never hydrated" was the wrong diagnosis — it hydrated and rendered the
          who's-watching chooser.
    #542a `_blocking_average` refunds a screen ONLY when `blank is True`.

The record still sets `"blank": screen["name"] in _blank_screens`, so after #657 a picker screen
carries `blank: False` with `similarity: 0.0` — it went from EXCLUDED from the gating average to
counting as a hard zero. #657 neither intended nor mentioned that, and the suite stayed green
because no test crossed the two.

The new behaviour is kept deliberately. #657's own diagnosis is that profile selection does not
persist, which is an application defect rather than a capture glitch; an app whose every route
lands on the chooser is unusable, so it must score and block. Refunding it would ship exactly
that. What was missing is that the choice was visible — this file makes it so.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _rec(name, blank_list, picker_list):
    """The record shape the capture loop builds for an uncaptured screen."""
    return {"name": name, "route": "/x", "similarity": 0.0, "passed": False,
            "dimensions": {}, "blank": name in blank_list, "advisory": False}


# --- the two treatments are distinct and deliberate ------------------------------------------

def test_a_picker_screen_is_not_flagged_blank():
    assert _rec("s", blank_list=[], picker_list=["s"])["blank"] is False


def test_a_blank_screen_is_still_flagged_blank():
    assert _rec("s", blank_list=["s"], picker_list=[])["blank"] is True


def test_a_picker_screen_COUNTS_in_the_gating_average():
    """The behaviour #657 changed by accident and #657b keeps on purpose."""
    picker = _rec("picker", blank_list=[], picker_list=["picker"])
    good = {"name": "ok", "similarity": 0.80, "passed": True, "advisory": False, "blank": False}
    assert vf._blocking_similarity_average([good, picker]) == pytest.approx(0.40)


def test_a_blank_screen_is_still_refunded():
    """#542a's transient exclusion must be untouched."""
    blank = _rec("blank", blank_list=["blank"], picker_list=[])
    good = {"name": "ok", "similarity": 0.80, "passed": True, "advisory": False, "blank": False}
    assert vf._blocking_similarity_average([good, blank]) == pytest.approx(0.80)


def test_the_two_differ_on_exactly_this_axis():
    """Same 0.0, same absent capture — only the refund differs."""
    good = {"name": "ok", "similarity": 0.80, "passed": True, "advisory": False, "blank": False}
    picker = vf._blocking_similarity_average([good, _rec("p", [], ["p"])])
    blank = vf._blocking_similarity_average([good, _rec("b", ["b"], [])])
    assert picker < blank


# --- the diagnosis #657 fixed is still the one delivered ------------------------------------------

def test_the_picker_deviation_does_not_blame_hydration():
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index("never got past the PROFILE PICKER")
    assert "never hydrated" not in src[i:src.index("#657b", i)]


def test_the_picker_deviation_names_the_real_ask():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert "make profile selection persist" in src


def test_the_blank_deviation_is_unchanged():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert "the SPA never hydrated after ~5s re-poll" in src


# --- the two lists stay separate ------------------------------------------------------------

def test_the_capture_keeps_two_lists():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert "_picker_screens" in src and "_blank_screens" in src


def test_the_blank_flag_reads_only_the_blank_list():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert '"blank": screen["name"] in _blank_screens' in src


def test_the_wipeout_test_counts_only_blanks():
    """#656's majority-blank refund must not silently absorb picker screens either."""
    src = inspect.getsource(vf.run_visual_fidelity)
    assert "_blank_wipeout_656(results, _blank_screens, shots)" in src


# --- provenance -------------------------------------------------------------------------------

def _note():
    """The #657b note, bounded by the construct that follows it — not a fixed width."""
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index("#657b")
    return src[i:src.index("elif screen[", i)]


def test_the_interaction_is_recorded():
    note = _note()
    assert "542a" in note and "refunds ONLY" in note


def test_the_decision_to_keep_it_is_recorded():
    note = _note()
    assert "kept deliberately" in note
    assert "would ship exactly that" in note


def test_how_it_was_found_is_recorded():
    """The method is the durable part: cross-audit the session's fixes against each other."""
    assert "645" in _note()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
