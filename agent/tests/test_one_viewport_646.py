r"""#646: the pipeline had three viewports and no two agreed.

Sweeping the CODE axis rather than the artifacts — the tuned module constants in `runtime/` and
`agents/runtime/`, checked for a measured rationale (this codebase's convention). 17 of 37 carry
none; most are harmless vocabulary sets, but three of them are viewports, and they disagree:

    visual_fidelity._VIEWPORT      1380x900   1.533   <- the one that DECIDES the score
    test_user_runner._VIEWPORT     1280x800   1.600
    tools/browser/_manager         1280x720   1.778   <- what a lane SEES when it checks its work
    (reference set, for scale)                1.7344)

Agents drive that third one **9420 times** across the corpus — 3347 `browser_navigate` and **1332
`browser_screenshot`**, which is literally "let me look at what I just built". They were looking
at a viewport 180px shorter and 100px narrower than the one being scored. The session's recurring
shape once more: **the actor's view is not the measurement's view** (#623's label, #634's error,
#642's flag, #637's counter).

Aligned on the gate's value, because the gate is what decides. Whether 900 is the RIGHT height is
a separate open question — #644 measured the capture at 1.533 against references at 1.7344 and
parked the change, because the judge and the spec sampler want opposite corrections. Making it
ONE constant is precisely what lets that be answered once instead of three times.
"""
import pytest


def _canonical():
    from env_generator.llm_generator.tools.browser._bootstrap import CANONICAL_VIEWPORT_646
    return CANONICAL_VIEWPORT_646


# --- one value ----------------------------------------------------------------------------------

def test_the_visual_gate_uses_the_canonical_viewport():
    from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import _VIEWPORT
    assert _VIEWPORT == _canonical()


def test_the_test_user_runner_uses_it_too():
    from env_generator.llm_generator.multi_agent.runtime.test_user_runner import _VIEWPORT
    assert _VIEWPORT == _canonical()


def test_the_agent_browser_uses_it():
    """1332 explicit screenshots across the corpus were taken through this one."""
    import inspect
    from env_generator.llm_generator.tools.browser import _manager
    src = inspect.getsource(_manager)
    assert "viewport=dict(CANONICAL_VIEWPORT_646)" in src
    assert "'width': 1280, 'height': 720" not in src


def test_no_viewport_literal_survives_in_the_three_call_sites():
    """The guard: a fourth value must not creep back in."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity, test_user_runner
    from env_generator.llm_generator.tools.browser import _manager
    for mod in (visual_fidelity, test_user_runner, _manager):
        src = inspect.getsource(mod)
        for bad in ("1280, \"height\": 800", "1280, 'height': 720"):
            assert bad not in src, f"{mod.__name__} still hard-codes a viewport"


# --- each consumer gets its own copy ---------------------------------------------------------

def test_a_consumer_cannot_mutate_the_shared_constant():
    """`dict(...)` at every site — a caller that pokes its own copy must not move everyone."""
    from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import _VIEWPORT
    before = dict(_canonical())
    _VIEWPORT["height"] = 1
    try:
        assert _canonical() == before
    finally:
        _VIEWPORT["height"] = before["height"]


def test_it_is_a_plain_width_height_mapping():
    vp = _canonical()
    assert set(vp) == {"width", "height"}
    assert vp["width"] > 0 and vp["height"] > 0


# --- why this value ---------------------------------------------------------------------------

def test_it_is_the_gates_value_because_the_gate_decides():
    assert _canonical() == {"width": 1380, "height": 900}


def test_the_open_question_is_recorded_not_silently_settled():
    """#644 parked whether 900 is right. #646 must not look like an answer to it."""
    import inspect
    from env_generator.llm_generator.tools.browser import _bootstrap
    flat = " ".join(inspect.getsource(_bootstrap).replace("#", " ").split())
    assert "separate, open question" in flat and "644" in flat


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools.browser import _bootstrap
    flat = " ".join(inspect.getsource(_bootstrap).replace("#", " ").split())
    assert "9420 times" in flat and "1332 explicit screenshots" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
