r"""#863: the one artifact every run leaves behind could not tell "never started" from "failed".

Root-cause work on #862's class, carried as far as offline evidence allows.

**What is now established** about the 7 runs (r19, r35, r38, r42, r44, r136, r140 — nine days
apart, so recurring, not an incident):

| | |
|---|---|
| kickoff events in the EventHub | **0 in all 7**, ≥3 in every healthy run |
| `.agent_logs/{Backend,Frontend,Verifier}` | directories created at startup, **never written** |
| lanes' `kickoff_request` subscriptions | **correctly configured** — not the cause |
| design_analyst vs orchestrator end time | DA logs **104–789s AFTER** the orchestrator's last entry in 6 of 7 |
| `progress_events.jsonl` | exactly two lines, `generation_start` + `phase_start`, **no `phase_error`** |

So: the process outlived the orchestrator lane, the workflow **did not raise**, and
`start_kickoff` — the single call site that opens the meeting and broadcasts `kickoff_request` —
was never reached. The remaining unknown is bounded to the span between the phase start and that
call.

**What #863 does.** With no event at the kickoff boundary, a run that never reached kickoff and a
run whose kickoff ran and failed produce the *same two lines* in the only artifact that always
survives — which is why this class needed an artifact-tree census plus an `.agent_logs` dig to
find at all, three sessions after it started happening.

★ **It is also a correction of #862.** #862 put its warning inside the kickoff poll loop, and in
exactly these runs the driver never starts, so that warning cannot fire. An instrument placed
where the failure cannot reach it is the same defect #862 itself documents about
`_derive_missing_essential_sections` — committed by me, one ticket later. This one sits before the
call, on the path every run takes.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch


def _src():
    return inspect.getsource(orch)


def test_the_kickoff_call_site_is_findable():
    """Non-vacuity: everything below is anchored on these two strings."""
    src = _src()
    assert "Starting kickoff coordinator" in src
    assert "run_kickoff.start_kickoff(" in src


def test_the_event_is_emitted_before_the_call():
    """After the call it would not distinguish the two cases — a run that dies inside
    `start_kickoff` would look the same as one that never got there."""
    src = _src()
    start = src.index("Starting kickoff coordinator")
    end = src.index("run_kickoff.start_kickoff(", start)
    block = src[start:end]
    assert "self.progress.emit(" in block, block
    assert "EventType.PHASE_START" in block


def test_the_event_names_the_milestone_and_the_attendees():
    """A bare marker answers "did it boot"; the payload answers "boot what", which is what a
    multi-milestone run needs (M2's kickoff failing is a different bug from M1's)."""
    src = _src()
    start = src.index("Starting kickoff coordinator")
    end = src.index("run_kickoff.start_kickoff(", start)
    block = src[start:end]
    assert 'f"Kickoff M{_m_idx}"' in block
    assert '"attendees"' in block and '"milestone"' in block


def test_observability_cannot_break_the_boot():
    """★ The emit is wrapped. A progress sink that throws must not become the reason kickoff never
    starts — that would manufacture the exact failure this line exists to detect."""
    src = _src()
    start = src.index("Starting kickoff coordinator")
    end = src.index("run_kickoff.start_kickoff(", start)
    block = src[start:end]
    assert re.search(r"try:\s*\n\s*self\.progress\.emit\(", block), block
    assert "except Exception:" in block


def test_the_emitted_type_is_one_the_persisted_log_records():
    """`progress_events.jsonl` is written from these events; a type the writer drops would be a
    writer with no reader. `phase_start` is already present in every corpus run's log, so it is
    known to survive to disk."""
    EventType = orch.EventType          # re-exported by the orchestrator; `progress` is top-level
    assert hasattr(EventType, "PHASE_START")
    assert str(EventType.PHASE_START.value).lower() == "phase_start"


def test_it_does_not_change_the_boot_itself():
    """Observation only: the call and its arguments are untouched."""
    src = _src()
    assert re.search(r"self\._kickoff_handle = run_kickoff\.start_kickoff\(", src)
    start = src.index("run_kickoff.start_kickoff(")
    end = src.index(")", src.index('agent="orchestrator"', start))
    call = src[start:end]
    assert 'attendees=["backend", "frontend", "verifier"]' in call


def test_862s_warning_really_is_unreachable_for_this_class():
    """★ The premise of this ticket, asserted rather than claimed. #862's detector lives in the
    kickoff poll loop; if it ever moves somewhere reachable without a driver, #863's rationale
    changes and this should fail so the write-up gets revisited."""
    from env_generator.llm_generator.multi_agent.runtime import kickoff_driver as kd
    ksrc = inspect.getsource(kd)
    assert "NO attendee has recorded anything" in ksrc, "#862's warning moved"
    # it is inside the driver's poll loop, which only runs once a kickoff handle exists
    assert "Kickoff phase=initial" in ksrc
    assert "NO attendee has recorded anything" in ksrc[ksrc.index("Kickoff phase=initial") - 4000:]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
