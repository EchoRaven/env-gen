r"""#872: the same uncapped retry loop, on the largest stuck population.

#870 bounded milestone planning, #871 the reference compile. Sweeping the **post-kickoff** path —
31 awaited calls after `start_kickoff` — leaves one that matters more than either, because it sits
where most runs actually die.

★ **70 of the 94 non-completed corpus runs reach the visual gate and never terminate** (item 190).
r151 sat there for 116 minutes. The judge call is:

    resp = await client.chat([Message.user_multimodal(parts)], temperature=0.0, max_tokens=8000)

`utils.llm` caps one completion at 240s (FIX #187) and its retry layer re-rolls with no cap on the
count, so one screen is 240s × N. **This runs once per SCREEN — ~12 per round** — and the gate's
escapes (`escape_s` wall-clock, attempt cap, plateau) are evaluated only **between** rounds, in
`_visual_release_decision`. A round that runs long cannot be escaped from while it runs.

Every other timeout in that module is a browser, HTTP or compose bound; the judge had none.

**No new branch was needed.** `asyncio.TimeoutError` is an `Exception`, so it lands in the handler
three lines below and becomes the existing `judge_error` verdict — which #142 already treats as
TRANSIENT and refuses to cache, so the screen is re-judged next round rather than pinned at 0.0.
Timing out lands on a path the code already takes, which is the same property that made #870 and
#871 safe.

**Bounded, not solved.** A round of 12 screens is now ≤ 12 × the ceiling instead of unbounded.

★ **The per-ROUND cap is not merely deferred — it would be actively harmful, and the reason is
sharper than the "policy decision" first written here.** A budget that stops starting screens
leaves them out of `results`, and an absent screen is `unjudged`:

    "an owned screen that was never judged is a FAILURE, not a skip"
    visual_gate_verdict -> {"passed": False, "reason": "N declared screen(s) were never judged"}

So a per-round cap converts a SLOW run into a PERMANENTLY FAILING one — every round would drop the
same tail of screens and fail on them.

★ That boundary is also exactly why #872 is safe. `judged` is built as
`{r["name"] for r in results}`, so a screen counts as judged if it appears **at all**. A timeout
returns a real verdict — `{"similarity": 0.0, …, "judge_error": True}` — so the screen is judged
with a bad score, not skipped, and #142 refuses to cache it. **Judged-and-0.0 is recoverable next
round; unjudged is not.**
"""
import asyncio
import time
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _span():
    """The judge call, anchored between its own marker and the handler it falls into."""
    src = inspect.getsource(vf)
    start = src.index("#872: bound the judge call")
    end = src.index("judge_error marks a TRANSIENT", start)
    return src[start:end]


def test_the_judge_call_is_findable():
    """Non-vacuity: every case below reads this span."""
    src = inspect.getsource(vf)
    assert "#872: bound the judge call" in src
    assert "Message.user_multimodal(parts)" in src


def test_the_call_is_bounded():
    span = _span()
    assert "_asyncio.wait_for(" in span
    assert "_judge_timeout_s_872" in span


def test_a_timeout_lands_in_the_existing_transient_handler():
    """★ The safety property. No new branch: `asyncio.TimeoutError` is an `Exception`, and the
    handler already produces a `judge_error` verdict."""
    assert issubclass(asyncio.TimeoutError, Exception)
    src = inspect.getsource(vf)
    start = src.index("#872: bound the judge call")
    tail = src[start:src.index("similarity", src.index("judge call failed", start))]
    assert "except Exception as exc:" in tail
    assert "judge call failed" in tail


def test_a_timed_out_screen_is_not_cached_as_zero():
    """#142's rule is what makes the fallback harmless: a transient 0.0 must not pin a healthy
    screen for the milestone. If that ever changes, this ceiling starts costing scores."""
    src = inspect.getsource(vf)
    assert "must never cache it" in src
    assert "frozen 0.0 would pin a healthy screen" in src


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
    t = vf._judge_timeout_s_872()
    assert watchdog < t <= 2 * watchdog, (watchdog, t)
    assert t > 588.9, "r153's slowest real completion must still fit"


def test_the_floor_survives_a_hostile_env():
    src = inspect.getsource(vf)
    assert "llm_ceiling_898(" in src   # #898: the floor lives in the helper now
    assert "ENVGEN_JUDGE_TIMEOUT_S" in src


def test_a_round_is_now_finite_but_still_long():
    """★ States the limit rather than overselling the fix. Twelve screens at the ceiling is 60
    minutes — bounded, and still longer than most runs should spend in one round. The per-ROUND
    cap is the stronger fix and is a policy decision (partial verdicts change `coverage`), so it
    is recorded, not smuggled in."""
    # ★ #898 corrected the model this asserted. 12 x the per-call ceiling is 9000s now, but the
    # round is not bounded by that any more: #892 caps the ROUND directly, and that cap is what a
    # reader should check. The per-call ceiling only bounds ONE screen.
    import re as _re
    src = inspect.getsource(vf)
    assert _re.search(r"_round_budget_892 = max\(", src), "#892's round cap must still exist"
    assert vf._judge_timeout_s_872() > 588.9, "one honest slow call must still fit"
    span = _span()
    # case-insensitive: the comment writes it as "ONCE PER SCREEN" and an exact-case anchor is a
    # test that breaks on prose, not on behaviour — the same slip as #859's docstring match.
    assert "per screen" in span.lower()


def test_the_escapes_it_unblocks_are_still_between_rounds():
    """Non-vacuity for the premise: the gate's wall-clock escape cannot fire mid-round, which is
    why a long round is unescapable and why bounding the call matters at all."""
    from env_generator.llm_generator.multi_agent import orchestrator as orch
    dec = inspect.getsource(orch._visual_release_decision)
    assert "escape_s" in dec and "deferred_since" in dec


def test_the_other_timeouts_in_the_module_are_not_llm_bounds():
    """The judge was the omission, not one of a set. Every pre-existing timeout here is a browser,
    HTTP or compose bound."""
    src = inspect.getsource(vf)
    others = [m.group(0) for m in re.finditer(r"timeout[_s]*\s*[=:]\s*\d+", src)]
    assert others, "non-vacuity: the module does carry other timeouts"
    assert not any("judge" in src[max(0, src.index(o) - 120):src.index(o)].lower()
                   for o in others if o != f"timeout=_judge_timeout_s_872")



def test_a_timed_out_screen_stays_in_the_results():
    """★ The invariant #872's safety rests on, pinned because breaking it looks like an
    optimisation.

    `judged` is `{r["name"] for r in results}`. A timeout must produce a VERDICT (score 0.0,
    `judge_error: True`) so the screen counts as judged; dropping it instead would make it
    `unjudged`, and `visual_gate_verdict` fails deterministically on those — *"an owned screen
    that was never judged is a FAILURE, not a skip"*. Skipping a slow screen would therefore turn
    a slow run into a permanently failing one, which is also why the per-round cap is not
    attempted."""
    src = inspect.getsource(vf)
    assert 'judged = {str(r.get("name") or "") for r in rs}' in src
    assert "never judged is a FAILURE, not a skip" in src
    j = src.index("judge call failed")
    verdict = src[j - 200:j + 220]
    assert '"similarity": 0.0' in verdict and '"judge_error": True' in verdict

# --------------------------------------------------------------------------- #915b: DRIVEN

def _tiny_png(dirpath, name):
    f = dirpath / name
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return str(f)


def _run_judge_against(chat_impl, monkeypatch, ceiling=0.05):
    """Drive the REAL `judge_screen_pair` — reference image, screenshot, provider client and all —
    with the ceiling lowered. `_judge_timeout_s_872` is a module-level accessor (that is what
    #898/#901 made it), so lowering it here exercises the real `wait_for`, the real
    `except Exception`, and the real verdict construction.

    ★ Added because this file had exactly ONE assertion that executed anything, and it was
    `issubclass(asyncio.TimeoutError, Exception)` — a fact about Python, not about this code
    (item 262). The ceiling's whole claim is "a stalled judge becomes a transient verdict instead
    of hanging the round", and nothing had ever run it.
    """
    import tempfile
    from pathlib import Path as _P
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as _vf

    d = _P(tempfile.mkdtemp())
    screen = {"name": "player", "route": "/watch/:id", "path": _tiny_png(d, "ref.png")}
    shot = _tiny_png(d, "shot.png")

    class _Client:
        async def chat(self, *a, **k):
            return await chat_impl()

    class _LLM:
        _client = _Client()

    monkeypatch.setattr(_vf, "_judge_timeout_s_872", lambda: ceiling)
    loop = asyncio.new_event_loop()
    try:
        t0 = time.monotonic()
        out = loop.run_until_complete(_vf.judge_screen_pair(_LLM(), screen, shot))
        return out, time.monotonic() - t0
    finally:
        loop.close()


def test_a_stalled_judge_returns_a_verdict_instead_of_hanging(monkeypatch):
    """★ The ticket's actual claim, executed. r151 sat in this call for 116 minutes."""
    async def _stall():
        await asyncio.sleep(30)
    out, _ = _run_judge_against(_stall, monkeypatch)
    assert isinstance(out, dict)
    assert out["judge_error"] is True
    assert out["similarity"] == 0.0


def test_the_stall_is_actually_bounded_by_the_ceiling(monkeypatch):
    """The half a source grep cannot reach: `wait_for` must CUT the call, not merely be present.
    A 30s stub returning inside a fraction of a second is the proof."""
    async def _stall():
        await asyncio.sleep(30)
    _, elapsed = _run_judge_against(_stall, monkeypatch, ceiling=0.05)
    assert elapsed < 5.0, f"the ceiling did not cut the call: {elapsed:.1f}s"


def test_the_timeout_verdict_names_the_failure(monkeypatch):
    """It reaches the deviation list a human and the remediation prompt both read; an empty
    reason would read as a screen that was judged and found perfect."""
    async def _stall():
        await asyncio.sleep(30)
    out, _ = _run_judge_against(_stall, monkeypatch)
    assert out["deviations"] and "judge call failed" in out["deviations"][0]
    assert out["summary"] == "judge error"


def test_a_fast_judge_is_untouched_by_the_ceiling(monkeypatch):
    """Non-regression: the bound must not change the healthy path. A well-formed response still
    parses into a real verdict."""
    async def _ok():
        class _R:
            content = ('{"dimensions": {"layout": {"score": 0.9}}, "similarity": 0.9, '
                       '"deviations": [], "summary": "ok"}')
        return _R()
    out, _ = _run_judge_against(_ok, monkeypatch)
    assert not out.get("judge_error"), out
    assert out.get("similarity") == 0.9


def test_a_raising_client_still_yields_a_transient_verdict(monkeypatch):
    """The pre-existing contract the ceiling rides on: ANY failure is a transient verdict, never
    an exception into the orchestrator loop."""
    async def _boom():
        raise RuntimeError("provider exploded")
    out, _ = _run_judge_against(_boom, monkeypatch)
    assert out["judge_error"] is True and out["similarity"] == 0.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
