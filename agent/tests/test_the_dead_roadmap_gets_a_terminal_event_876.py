r"""#876: auditing #864's "does not abort" — the deferral preserved silence, not the run.

Fifth deferral audited. #864 declined to abort on an empty roadmap because *"aborting on an
unknown root trades one silent failure for a louder wrong one"*.

★ **That assumed a non-abort path exists.** It does not:

| | |
|---|---|
| `set_roadmap` call sites in the whole codebase | **1** (orchestrator.py:1370) |
| retries / recovery paths | **none** |
| what #864's own message says | *"this run will open no kickoff meeting and its lanes will never wake"* |

The run is already lost when the readback comes back empty. What the deferral preserved was not
the run — it was the **silence**.

**Still not raising.** The enclosing handler (orchestrator.py:1137–2490) routes an exception into
`_enter_project_phase('implement', …)` — remediation that cannot help when no lane was ever woken.
Emitting the terminal event directly gets the diagnostic without the futile phase.

**What it buys.** `progress_events.jsonl` for the 7 dead runs holds exactly `generation_start` +
`phase_start` and nothing else — which is why the corpus census read them as *"killed, cause
unknown"* for nine days, and why finding them took an artifact-tree census plus a log dig. A
`generation_error` turns the same state into a **named failure in the one artifact every run
leaves behind**.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch


def _span():
    """The readback block, anchored between its marker and the loop it guards."""
    src = inspect.getsource(orch)
    start = src.index("#864: VERIFY the seed")
    end = src.index("for _m_idx, _milestone in enumerate(milestones", start)
    return src[start:end]


def test_the_readback_block_is_findable():
    """Non-vacuity."""
    assert "#864: VERIFY the seed" in inspect.getsource(orch)


def test_both_events_are_emitted():
    span = _span()
    assert "EventType.PHASE_ERROR" in span
    assert "EventType.GENERATION_ERROR" in span


def test_the_terminal_event_names_the_consequence():
    """An operator reading `generation_error` needs to know the run was dead, not merely slow."""
    span = _span()
    assert "no kickoff will open" in span and "no lane will wake" in span


def test_generation_error_is_the_type_the_census_keys_on():
    """★ The whole point: it must be a TERMINAL type, or the run stays unclassifiable. The corpus
    census distinguishes runs by exactly these strings."""
    assert orch.EventType.GENERATION_ERROR.value == "generation_error"
    assert orch.EventType.PHASE_ERROR.value == "phase_error"


def test_it_still_does_not_raise():
    """★ Deliberate, and for a sharper reason than #864 gave. Raising reaches the outer handler,
    which enters a remediation phase that cannot help when no lane was ever woken — futile work,
    not a fix. The diagnostic is what was missing, not the abort."""
    span = _span()
    assert "raise" not in span
    assert "sys.exit" not in span


def test_the_emits_cannot_break_the_run():
    """Both are wrapped: a progress sink that throws must not become the failure it reports."""
    span = _span()
    assert span.count("except Exception") >= 2


def test_the_premise_that_there_is_no_recovery_still_holds():
    """★ Non-vacuity for the audit's finding. If a retry or a second `set_roadmap` ever appears,
    'the run is already lost' stops being true and this ticket must be re-read."""
    src = inspect.getsource(orch)
    calls = re.findall(r"\.set_roadmap\(", src)
    assert len(calls) == 1, f"set_roadmap is called {len(calls)}x — a recovery path may exist now"


def test_the_loop_it_guards_still_contains_the_kickoff():
    """The severity claim rests on this: an empty roadmap is fatal only because `start_kickoff`
    lives inside the loop over it."""
    src = inspect.getsource(orch)
    assert src.index("run_kickoff.start_kickoff(") > src.index(
        "for _m_idx, _milestone in enumerate(milestones")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
