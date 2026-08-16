r"""#827: 62% of runs are killed mid-workflow and the log says only "it started".

#821's census: of 151 runs, 25 reach `generation_complete` successfully, 32 complete
unsuccessfully, and **94 are killed before any terminal event**. For those 94 the log holds
exactly two lines — `generation_start` and one `phase_start: Agent Workflow` — and nothing until
the process dies. **The majority outcome has no phase attribution at all.**

`EventType` already defines `FILE_START`, `TOOL_CALL`, `THINK_START`, `REFLECT_*`; the multi-agent
path emits none of them. Wiring those through every agent is a feature and is invasive — this is
the minimal version. The delivery-gate funnel (`_validate_delivery_gate`) already runs on every
coordination tick and every one of its six call sites passes through it, so one emit there turns a
silent 75 minutes into a per-tick record of what the gate was still failing on.

★ That is exactly what r151's post-mortem needed. It had to be reconstructed from the single abort
message, which happened to name the blockers; had it not, the run's 75 minutes would have been
unreadable. #820 was found because that message existed — not because the log was designed to
answer the question.

Deliberately narrow: `ok`, the first six `failed_checks`, and the `did_not_run` count (#793). No
payload, no per-agent detail, and it can never raise into the gate.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch
from env_generator.llm_generator.progress import EventType


def _funnel_src():
    for name in dir(orch):
        obj = getattr(orch, name)
        if inspect.isclass(obj) and hasattr(obj, "_validate_delivery_gate"):
            return inspect.getsource(obj._validate_delivery_gate)
    raise AssertionError("the gate funnel moved")


def test_the_tick_is_emitted():
    assert "self.progress.emit(" in _funnel_src()


def test_it_carries_the_verdict_not_just_a_heartbeat():
    """A bare 'tick' would prove the process was alive and nothing else; the point is to know what
    the gate was still failing on when the run was killed."""
    src = _funnel_src()
    assert '"failed_checks"' in src and '"ok"' in src
    assert '"did_not_run"' in src, "#793's count rides along"


def test_the_event_type_exists():
    """Non-vacuity: an emit against a missing enum member would raise at runtime, inside a
    try/except that would swallow it — the silence class this session catalogued."""
    assert EventType.VERIFICATION_START.value == "verification_start"


def test_it_can_never_break_the_gate():
    """It runs on the release path. Telemetry must not be able to fail a delivery decision."""
    src = _funnel_src()
    i = src.index("#827")
    blk = src[i:src.index("return _gate793", i)]
    assert "except Exception:" in blk
    assert "never let telemetry break the gate" in blk


def test_it_is_bounded():
    """The gate ticks every few minutes for over an hour; an unbounded list would make the log the
    largest artifact of a killed run."""
    assert "[:6]" in _funnel_src()


def test_the_measurement_travels_with_it():
    src = " ".join(_funnel_src().replace("#", " ").split())
    assert "94 of" in src and "151" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
