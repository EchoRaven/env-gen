r"""#889: `design_prep.py` had no timeout of any kind, and it gates the whole run.

Fourth of the four generalisable fixes, done systematically rather than hot-spot by hot-spot.
Enumerated every awaited LLM call in the tree — **9** — and checked each against a `wait_for`:

| site | bound |
|---|---|
| `reference_materials:311`, `material_prep:194` | bounded by #871 at the caller (the gather) |
| `reference_materials:669` | bounded by #870 at the caller |
| `visual_fidelity` judge | bounded by #872 in place |
| `agents/base:1150`, `human_chat:123` | the agent step loop and an interactive path — different risk profile, a stall there is visible in the lane's own log |
| **`design_prep` × 4** | ★ **none, and the module contains no `timeout` at all** |

All four funnel through `_chat_ladder`, so one ceiling at that choke point bounds the module.

★ **The compounding here is the worst of the four tickets.** A ladder is up to three LLM calls;
`utils.llm` caps each completion at 240s and nothing caps the re-roll count; and `_run_analyst`
runs one ladder **per screen** (~12). Worst case was 12 × 3 × 240s × N — on the pre-kickoff
critical path, in the stage that was still logging **104–789s after the orchestrator's last
entry** in 6 of the 7 runs that died having built nothing (item 190).

Timing out returns `None`, which is this function's documented contract for every other failure
("degrades per rung"), and which #813/#819 already make audible. Fourth ticket in a row where the
ceiling lands on a path the code already takes — that is not luck, it is the precondition I now
look for before adding one.
"""
import asyncio
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import design_prep as dp


def test_the_wrapper_bounds_the_body():
    src = inspect.getsource(dp._chat_ladder)
    assert "wait_for(" in src
    assert "_chat_ladder_inner" in src
    assert "_ladder_timeout_s_889" in src


def test_the_body_is_still_reachable_and_unchanged_in_shape():
    """Non-vacuity: the ladder must still BE a ladder — three rungs, degrading."""
    assert hasattr(dp, "_chat_ladder_inner")
    body = inspect.getsource(dp._chat_ladder_inner)
    assert body.count("await client.chat(") >= 3, "the three rungs must survive"


def test_a_timeout_returns_none_not_an_exception():
    """★ The safety property: `None` is the documented outcome of every other failure here."""
    src = inspect.getsource(dp._chat_ladder)
    assert "except asyncio.TimeoutError" in src or "_asyncio.TimeoutError" in src
    assert "return None" in src
    assert "raise" not in src


def test_the_timeout_is_audible():
    src = inspect.getsource(dp._chat_ladder)
    assert "_LOG_813" in src and "TIMED OUT" in src


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
    t = dp._ladder_timeout_s_889()
    assert watchdog < t <= 2 * watchdog, (watchdog, t)
    assert t > 588.9, "r153's slowest real completion must still fit"


def test_the_floor_survives_a_hostile_env():
    src = inspect.getsource(dp)
    assert "llm_ceiling_898(" in src   # #898: the floor lives in the helper now
    assert "ENVGEN_DESIGN_LADDER_TIMEOUT_S" in src


def test_the_module_had_no_other_timeout():
    """★ Non-vacuity for the finding itself: this was not one omission among several bounds — the
    module carried none. If a second appears, the note should be re-read."""
    src = inspect.getsource(dp)
    # #898: count only numeric bounds in CODE. Two corrections got here: `timeout=` now also
    # appears in #889's own `wait_for`, and the first fix matched `timeout=1800` inside my comment
    # about config.py — the seventeenth self-match of the session, and the same rule as #847c and
    # #868: strip comments, because a quotation is not a declaration.
    import io as _io, tokenize as _tok
    code = "".join(
        tv for tt, tv, *_ in _tok.generate_tokens(_io.StringIO(src).readline)
        if tt not in (_tok.COMMENT, _tok.STRING))
    others = [m.group(0) for m in re.finditer(r"\btimeout\s*=\s*\d", code)]
    assert not others, others


def test_every_llm_call_in_the_module_goes_through_the_ladder():
    """The ceiling only covers the module because the calls funnel here. If a fifth call appears
    outside `_chat_ladder_inner`, it is unbounded again."""
    src = inspect.getsource(dp)
    inner = inspect.getsource(dp._chat_ladder_inner)
    total = src.count("await client.chat(")
    assert total == inner.count("await client.chat("), (
        "an LLM call in design_prep bypasses the bounded ladder")


def test_wait_for_actually_bounds_a_stalled_coroutine():
    """Not a mock of the ladder — a check that the construct does what the ticket claims, since a
    stall leaves no artifact to point at."""
    async def _stall():
        await asyncio.sleep(5)
        return {"nope": True}

    async def _run():
        try:
            return await asyncio.wait_for(_stall(), timeout=0.05)
        except asyncio.TimeoutError:
            return None

    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        assert loop.run_until_complete(_run()) is None
    finally:
        loop.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
