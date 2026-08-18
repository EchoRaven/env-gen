r"""#924: #894's timeline promised four stages and recorded two — neither of the first two.

`record_stage_894`'s own worked example opens:

    generation_start
    phase_start   Agent Workflow
    stage         reference_compile  ok        3020 images
    stage         design_prep        ok        12 screens
    stage         milestone_plan     ok        1 milestone
    <nothing>                                  <- kickoff never started

…and its punchline is *"the absence of the next line IS the diagnosis"*. Only `milestone_plan` and
`database_scaffold` were ever wired. **Every one of the seven runs it cites — r19, r35, r38, r42,
r44, r136, r140 — died before `milestone_plan`**, so for the exact class the ticket was written for
the timeline was entirely blank and diagnosed nothing.

★ Surfaced by watching r154: six minutes in, mid-`decompose_reference`, `grep -c "STAGE "` on the
live log returned **0**. That is the span the dead runs died in.

#924 wires the two the example names. The absence of a line can only be a diagnosis if the lines
before it exist.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch
from env_generator.llm_generator.multi_agent.runtime import scaffolder as sc
from env_generator.llm_generator.multi_agent.runtime import stage_contract as stc


def _recorded_stage_names():
    """The stage labels this codebase actually records, read from the call sites."""
    names = set()
    for mod in (orch, sc):
        try:
            tree = ast.parse(inspect.getsource(mod))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None) or ""
            if not name.startswith("record_stage_894") and not name.startswith("_rs924"):
                continue
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                names.add(a.value)
    return names


def test_every_stage_the_docstring_promises_is_recorded():
    """★ The defect: the example named three and two of them were fiction."""
    doc = inspect.getdoc(stc.record_stage_894) or ""
    promised = {m for m in ("reference_compile", "design_prep", "milestone_plan") if m in doc}
    assert promised, "the worked example vanished — re-read this ticket before trusting it"
    missing = promised - _recorded_stage_names()
    assert not missing, f"named in the timeline example but never recorded: {sorted(missing)}"


def test_the_prekickoff_span_is_covered():
    """★ The point. The seven cited runs all died before `milestone_plan`; a timeline that starts
    there cannot say where they stopped."""
    names = _recorded_stage_names()
    assert "reference_compile" in names
    assert "design_prep" in names


def test_the_stages_already_wired_are_untouched():
    """Non-regression: #924 adds boundaries, it does not move the existing ones."""
    names = _recorded_stage_names()
    assert {"milestone_plan", "database_scaffold"} <= names


def test_the_new_records_cannot_break_the_run():
    """Both sit on the critical path before kickoff. An observability call that raises there
    would manufacture the very failure the timeline exists to report (#827's shape)."""
    src = inspect.getsource(orch)
    for anchor in ('_rs924("reference_compile"', '_rs924b("design_prep"'):
        i = src.index(anchor)
        window = src[max(0, i - 300):i + 200]
        assert "except Exception:" in window, anchor


def test_the_recorder_still_tolerates_a_missing_value():
    """`reference_compile` passes `getattr(self, "_reference_images", None)` — which is None on a
    run that never compiled any. That must record as EMPTY, not raise."""
    stc.reset_said_891()
    stc.record_stage_894("reference_compile", "reference images", None)
    stc.record_stage_894("design_prep", "screens", [])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
