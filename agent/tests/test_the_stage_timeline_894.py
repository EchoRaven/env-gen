r"""#894: one line per stage boundary, in the log that survives the run.

Written from what this session actually cost. `progress_events.jsonl` is the only artifact every
run leaves, and for the 7 runs of item 190 it held **two lines** — `generation_start` and
`phase_start` — so *"where did this run stop"* was not answerable from it. I rebuilt an
artifact-tree census **four times** to answer that, and the answer each time was one boundary.

    generation_start
    phase_start   Agent Workflow
    stage         reference_compile  ok   3020 images
    stage         design_prep        ok   12 screens
    stage         milestone_plan     ok   1 milestone
    <nothing>                             <- kickoff never started

★ **Emitting on SUCCESS is the part that makes it work.** A log that only speaks on failure cannot
tell "this stage was fine" from "this stage never ran" — and that ambiguity is precisely what made
those 7 runs cost a census instead of a read. The absence of the next line IS the diagnosis.

### two defects I put in while writing it, and how they were caught

1. `_dp_started_894 = True` — a variable set and never read. A seam, in the change that was
   supposed to make things observable.
2. `event_type=getattr(orch, "_EventType_894", None)` — always `None`, so the emit never fired:
   a **writer with no reader**, the exact class this session keeps finding. Then the import that
   replaced it (`from ..progress import ...`) was also wrong — `progress` is a TOP-LEVEL module —
   and it raised inside the `try/except` that wraps every observability call.

★ **The guard around an observability call hides bugs in the observability call.** Compiling
proves nothing here; the only check that works is driving it with a spy sink and asserting the
event came out, which is what `test_the_emit_actually_fires` does.
"""
import inspect
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import stage_contract as sc


@pytest.fixture(autouse=True)
def _fresh_899():
    """★ #899's dedup makes these order-dependent without a reset: two parametrized cases whose
    count normalises to the same value share a signature, so the second is silently deduped and
    its spy sees nothing. A say-once is a hidden fixture dependency — the correction is to reset,
    not to weaken the dedup."""
    sc.reset_said_891()
    yield
    sc.reset_said_891()


class _Spy:
    def __init__(self):
        self.seen = []

    def emit(self, et, msg, data):
        self.seen.append((getattr(et, "value", et), msg, data))


def test_the_emit_actually_fires():
    """★ The only check that catches a broken observability path — compiling does not, because
    every call site wraps this in try/except."""
    from progress import EventType
    spy = _Spy()
    sc.record_stage_894("database_scaffold", "tables", {"a": 1, "b": 2},
                        progress=spy, event_type=EventType.PHASE_START)
    assert len(spy.seen) == 1
    _t, msg, data = spy.seen[0]
    assert _t == "phase_start" and msg == "stage: database_scaffold"
    assert data["count"] == 2 and data["ok"] is True and data["stage"] == "database_scaffold"


def test_success_is_recorded_not_just_failure(caplog):
    """The property the whole ticket rests on."""
    with caplog.at_level(logging.INFO):
        sc.record_stage_894("design_prep", "screens", 12)
    assert "STAGE design_prep ok" in caplog.text and "12 screens" in caplog.text


def test_an_empty_stage_is_marked(caplog):
    with caplog.at_level(logging.INFO):
        sc.record_stage_894("database_scaffold", "tables", {}, ok=False,
                            detail="the app will start with no tables.")
    assert "EMPTY" in caplog.text and "no tables" in caplog.text


@pytest.mark.parametrize("count,want", [(3, 3), ([1, 2], 2), ({"a": 1}, 1), (None, None),
                                        ("nope", None), (object(), None)])
def test_the_count_is_derived_safely(count, want):
    """A stage that hands it something odd must still produce a line."""
    spy = _Spy()
    from progress import EventType
    sc.record_stage_894("s", "things", count, progress=spy, event_type=EventType.PHASE_START)
    assert spy.seen[0][2]["count"] == want


def test_it_never_raises():
    """The run must not depend on its own narration."""
    class _Boom:
        def emit(self, *a, **k):
            raise RuntimeError("sink down")
    from progress import EventType
    sc.record_stage_894("s", "t", 1, progress=_Boom(), event_type=EventType.PHASE_START)


def test_it_is_wired_at_real_boundaries():
    """A helper nobody calls is the defect it was written to prevent."""
    from env_generator.llm_generator.multi_agent import orchestrator as orch
    from env_generator.llm_generator.multi_agent.runtime import scaffolder
    assert "record_stage_894" in inspect.getsource(orch)
    assert "record_stage_894" in inspect.getsource(scaffolder)


def test_the_scaffolder_imports_event_type_from_the_right_module():
    """★ The bug that hid inside a try/except: `progress` is top-level, not a sibling of
    `runtime`. A wrong import here is silent and the timeline simply never appears."""
    src = inspect.getsource(
        __import__("env_generator.llm_generator.multi_agent.runtime.scaffolder",
                   fromlist=["x"]))
    assert "from progress import EventType" in src
    assert "from ..progress import" not in src


def test_no_dead_variable_survived():
    """The other seam: a variable set and never read, in the change meant to aid observation."""
    from env_generator.llm_generator.multi_agent import orchestrator as orch
    assert "_dp_started_894" not in inspect.getsource(orch)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #899: measured on r153, the timeline was 34/35 duplicates -------------------------------

def test_an_unchanged_stage_is_recorded_once(caplog):
    """★ r153's real sequence: `database_scaffold` re-runs every delivery tick, so the timeline was
    10x "12 tables" then 24x "13 tables" — 32 duplicates burying the one informative line."""
    sc.reset_said_891()
    with caplog.at_level(logging.INFO):
        for _ in range(10):
            sc.record_stage_894("database_scaffold", "tables", 12)
    assert sum("STAGE database_scaffold" in r.getMessage() for r in caplog.records) == 1


def test_a_CHANGE_is_still_recorded(caplog):
    """★ The half that #845's plain say-once would have destroyed. `12 -> 13 tables` is exactly the
    line worth keeping — the contract grew, and that is a fact about the run."""
    sc.reset_said_891()
    with caplog.at_level(logging.INFO):
        for _ in range(10):
            sc.record_stage_894("database_scaffold", "tables", 12)
        for _ in range(24):
            sc.record_stage_894("database_scaffold", "tables", 13)
    msgs = [r.getMessage() for r in caplog.records if "STAGE database_scaffold" in r.getMessage()]
    assert len(msgs) == 2, msgs
    assert "12 tables" in msgs[0] and "13 tables" in msgs[1]


def test_ok_to_empty_is_a_change_worth_seeing(caplog):
    """A stage that stops producing must not be silenced by having produced before."""
    sc.reset_said_891()
    with caplog.at_level(logging.INFO):
        sc.record_stage_894("database_scaffold", "tables", 12)
        sc.record_stage_894("database_scaffold", "tables", 12, ok=False)
    assert sum("STAGE database_scaffold" in r.getMessage() for r in caplog.records) == 2


def test_different_stages_do_not_shadow_each_other(caplog):
    sc.reset_said_891()
    with caplog.at_level(logging.INFO):
        sc.record_stage_894("a", "x", 1)
        sc.record_stage_894("b", "x", 1)
    assert sum("STAGE " in r.getMessage() for r in caplog.records) == 2


def test_the_reset_clears_it():
    """A long session must not silence a later run's timeline."""
    sc.reset_said_891()
    sc.record_stage_894("s", "t", 1)
    assert sc._SEEN_899
    sc.reset_said_891()
    assert not sc._SEEN_899
