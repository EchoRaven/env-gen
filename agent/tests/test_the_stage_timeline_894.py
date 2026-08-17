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
