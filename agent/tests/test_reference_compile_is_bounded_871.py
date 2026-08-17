r"""#871: the same uncapped retry loop, one phase earlier — and it gathers two of them.

#870 bounded milestone planning. Sweeping the rest of the **pre-kickoff critical path** (the span
between the workflow's `phase_start` and `start_kickoff`) found six awaited calls and one more
with the same exposure:

| awaited on the pre-kickoff path | bound |
|---|---|
| `_appr_decision` | internal — returns approved on timeout/error by contract |
| `author_milestone_detail` | **internal, and the claim is honoured**: `timeout_s=240.0`, *"NEVER hangs the run — the timeout is a hard safety cap"*, enforced by `while waited < timeout_s` |
| `_await_prior_milestone_delivery_drained`, `_generate_docker`, `_respawn_core_lanes` | not LLM calls |
| **`_compile_reference_materials`** | **none, end to end** |

Inside it:

    spec, _ = await asyncio.gather(
        compile_reference_spec(...),        # vision LLM call
        precompute_component_specs(...),    # vision LLM call
    )

`utils.llm._llm_hard_timeout` caps each **completion** at 240s, but its retry layer re-rolls after
every cancel with no cap on the count, so each branch is 240s × N — and `gather` waits for the
slower one. ★ This runs **before** milestone planning, so a stall costs design prep, the roadmap,
kickoff and every lane: the same total loss as #870's, one step earlier.

**The fallback already existed three lines below** — an unusable spec logs *"continuing without"*
and the run proceeds. That is what makes a ceiling safe here: timing out lands on a path the code
already takes.

★ Worth recording as a confirmation, not just a finding: `author_milestone_detail` claims *"NEVER
hangs the run"* **and enforces it**. This session has mostly found the opposite; the sweep is only
credible because it distinguishes the two.
"""
import asyncio
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import reference_materials as rm


def _src():
    return inspect.getsource(rm.compile_reference_materials)


def test_the_gather_is_findable():
    """Non-vacuity: every case below reads this function."""
    src = _src()
    assert "compile_reference_spec(" in src and "precompute_component_specs(" in src


def test_the_gather_is_bounded():
    src = _src()
    assert "wait_for(" in src
    assert "_ref_compile_timeout_s_871" in src


def test_a_timeout_continues_without_a_spec():
    """★ It must not propagate. An unusable spec is an outcome the code already handles; an
    exception here would abort a run that could have proceeded."""
    src = _src()
    assert "except _asyncio.TimeoutError:" in src
    assert "spec = None" in src


def test_the_timeout_is_reported_as_an_error():
    src = _src()
    assert "logger.error" in src and "TIMED OUT" in src


def test_the_existing_fallback_still_follows_it():
    """The ceiling is only safe because this path exists. If the 'continuing without' branch is
    ever removed, a timeout stops being harmless and this ticket must be re-read."""
    src = _src()
    assert "produced nothing usable" in src
    assert src.index("spec = None") < src.index("produced nothing usable")


def test_the_ceiling_is_calibrated_against_the_inner_watchdog():
    """★ CORRECTED at #898, against real data. This asserted the relationship using
    `_llm_hard_timeout(None, {})` = 240 — the value when `config.timeout` is UNSET. `config.py`
    sets `timeout: int = 1800`, so the live watchdog is `min(1800, 600)` = **600s**, and r153
    measured a completion at **588.9s** across 6550 calls. The old 300s ceiling sat at half the
    real cap and would have cut that call in two; the test could not see it because it read the
    default rather than the value in use — the field-location error, in the check meant to catch
    exactly this.

    Now derived, so it cannot drift out of calibration when the config moves."""
    from utils.llm import _llm_hard_timeout
    from utils.config import LLMConfig
    watchdog = _llm_hard_timeout(LLMConfig.timeout, {})
    assert watchdog == 600.0, watchdog
    t = rm._ref_compile_timeout_s_871()
    assert watchdog < t <= 2 * watchdog, (watchdog, t)
    assert t > 588.9, "r153's slowest real completion must still fit"


def test_the_floor_survives_a_hostile_env():
    """`=0` must not mean 'time out instantly and never compile'."""
    src = inspect.getsource(rm)
    assert "llm_ceiling_898(" in src   # #898: the floor lives in the helper now
    assert "ENVGEN_REF_COMPILE_TIMEOUT_S" in src


def test_wait_for_cancels_a_gather_of_two():
    """★ The construct, demonstrated on this shape: `wait_for` around a `gather` must bound the
    SLOWER branch, not just the first to finish. A stall leaves no artifact, so the mechanism has
    to be shown somewhere."""
    async def _fast():
        return "a"

    async def _slow():
        await asyncio.sleep(5)
        return "b"

    async def _run():
        try:
            return await asyncio.wait_for(asyncio.gather(_fast(), _slow()), timeout=0.05)
        except asyncio.TimeoutError:
            return None

    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        assert loop.run_until_complete(_run()) is None
    finally:
        loop.close()


def test_the_sibling_claim_on_this_path_is_actually_enforced():
    """★ The confirmation half of the sweep. `author_milestone_detail` says *"NEVER hangs the
    run"* and backs it with a real cap — recorded because this session has mostly found the
    opposite, and a sweep that cannot tell an honoured claim from an empty one is worthless."""
    from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff
    sig = inspect.signature(run_kickoff.author_milestone_detail)
    assert sig.parameters["timeout_s"].default == 240.0
    body = inspect.getsource(run_kickoff.author_milestone_detail)
    assert "NEVER hangs the run" in body
    assert "while waited < timeout_s" in body


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
