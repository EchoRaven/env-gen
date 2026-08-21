r"""#1025: the "sole bound" on context is an overflow guard, and the comment claimed a size bound.

`step_runner` condenses when `should_condense_messages` says yes AND three gates agree. Its
paragraph used to end: *"this every-step boundary condensation is the sole bound, and it keeps
context ~28-100, far under the ~770 saturation."*

Measured over r172 — 4556 LLM requests, `gpt-5-6-sol-genai-responses`:

    messages per request     median 139    p90 573    max 1274
    over 100 messages        57% of requests
    over 400 messages        21% of requests
    "Condensing messages"    5 times in 4546 calls

The cause is arithmetic, not logic. `_pressured` is `_chars > _budget * 0.9`, and
`resolve_ctx_working_chars("gpt-5-6-sol-genai-responses")` returns 666,400 — so the gate opens
at ~599,760 chars while the MEDIAN request is 149,739 and even the 400+-message bucket medians
283,179. **The threshold sits about 4x above normal traffic**, so on this model the bound is
effectively absent.

★ This is NOT a defect in F3/F4's guards. They were added for measured reasons — condense
thrash every 2-4 steps, and a "RESUME NOW: write code" directive injected into a coordinating
lane mid-kickoff. It is a CONFLATION: `_pressured` implements *do not exceed the window*, while
the deleted sentence described *keep context small*. Only the first is implemented, and the
comment asserted the second, so nothing ever compared the claim to a run.

What it costs is wall clock, which is what actually ends runs. r172: **230,947,225 prompt
tokens against 1,030,351 completion tokens — 224:1** — over 3.34 billion content chars, ending
on `Run budget exceeded (wall-clock 7214s exceeded cap 7200s) without delivery`.

Adding a real size bound is a behaviour change with F3/F4's failure mode on the other side, so
#1025 does not change the trigger. It removes the false claim and logs the DECLINED path with
the numbers, so one run makes the threshold decidable instead of invisible.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import step_runner as sr


def _src():
    return inspect.getsource(sr)


# --- the false claim is gone -----------------------------------------------------------------

def test_the_untrue_sentence_is_removed():
    """Control: this exact phrasing asserted a bound that r172 violated in 57% of requests."""
    assert "keeps context ~28-100" not in _src()


def test_the_measurement_replaces_it():
    s = _src()
    assert "#1025" in s
    for fact in ("median 139", "p90 573", "max 1274", "666,400", "224:1"):
        assert fact in s, f"the record must carry {fact!r}"


def test_the_conflation_is_named():
    """The next reader needs to know it is an OVERFLOW guard, not a SIZE bound — that is the
    whole reason the old sentence read as true."""
    s = _src()
    assert "OVERFLOW guard" in s and "SIZE bound" in s


def test_the_f3_f4_reasons_are_preserved():
    """#1016's lesson: do not reverse a guard without knowing why it was decided. The reasons
    must stay next to the measurement that argues against its threshold."""
    s = _src()
    assert "thrash" in s
    assert "RESUME NOW" in s


# --- the trigger is unchanged ------------------------------------------------------------------

def test_the_trigger_is_NOT_changed():
    """★ #1025 measures and reports; it does not switch a behaviour on. Changing this line is a
    separate decision with F3/F4 on the other side of it."""
    s = _src()
    assert "_pressured = _chars > _budget * 0.9" in s


def test_all_three_gates_still_apply():
    s = _src()
    assert "if _phase_ok and _cooldown_ok and _pressured:" in s


# --- the decline is now auditable ----------------------------------------------------------------

def test_the_declined_path_is_logged():
    s = _src()
    i = s.index("if not (_phase_ok and _cooldown_ok and _pressured):")
    block = s[i:s.index("if _phase_ok and _cooldown_ok and _pressured:", i)]
    assert "condense DECLINED" in block
    for field in ("msgs=%d", "chars=%d", "budget=%d", "phase_ok=%s", "cooldown_ok=%s",
                  "pressured=%s"):
        assert field in block, f"the decline log must carry {field}"


def test_the_log_names_which_gate_refused():
    """"declined" without the gate is another unmeasurable line — the point is to tell
    'context is healthy' apart from 'the threshold is 4x above our traffic'."""
    s = _src()
    i = s.index("condense DECLINED")
    block = s[i:s.index("if _phase_ok and _cooldown_ok and _pressured:", i)]
    assert "phase_ok" in block and "cooldown_ok" in block and "pressured" in block


def test_the_counters_are_bound_before_the_try():
    """A raise inside the try would otherwise leave `_chars`/`_budget` unbound and the log that
    explains the decline is the first thing to break — the seam class from #1021/#1023c."""
    s = _src()
    init_b = s.index("_budget = 0")
    init_c = s.index("_chars = -1")
    try_i = s.index("from utils.model_limits import resolve_ctx_working_chars")
    assert init_b < try_i and init_c < try_i


def test_the_decline_log_cannot_raise():
    """It runs on every declined step of every agent; a formatting slip must not kill the run."""
    s = _src()
    i = s.index("condense DECLINED")
    tail = s[i:s.index("if _phase_ok and _cooldown_ok and _pressured:", i)]
    assert "except Exception:" in tail


# --- the premise, so a model change invalidates this file loudly ---------------------------------

def test_the_budget_premise_still_holds():
    """If the working budget stops being ~4x typical traffic, this file's argument changes."""
    from utils.model_limits import resolve_ctx_working_chars
    b = resolve_ctx_working_chars("gpt-5-6-sol-genai-responses")
    assert b == 666400, f"budget moved to {b} — re-measure #1025 before trusting it"
    assert b * 0.9 > 4 * 149_739, (
        "the 90% gate is no longer far above r172's median request; the finding needs redoing")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
