r"""#864: the roadmap seed was write-and-hope, and an empty roadmap costs the whole run.

The root-cause dig on #862's class, one step further. `start_kickoff` — the only call that opens
the kickoff meeting and broadcasts `kickoff_request` — lives **inside** the loop over
``milestones``. So an empty roadmap is not a degraded run, it is a total loss: no meeting, nothing
wakes backend/frontend/verifier, no DDL, no seed, no frontend, no capture.

★ **A perfect discriminator, found in the artifacts:**

    shared/hubs/milestones.json    7 dead runs: ABSENT — and 5 of them have only the .lock,
                                   so the store was TOUCHED and never written
                                   healthy runs: 1, 1, 2, 3 entries

r19, r35, r38, r42, r44, r136, r140 — nine days apart, 3–6% of runs, total loss each time.

The seed was already wrapped: `except Exception: self._logger.warning("milestone store seed
failed")`. Failing open there is a reasonable choice. **Nobody checked the result** — which is
#790/#792's shape exactly: a step that could not do its job reading like a step that did.

**What was eliminated on the way** (each with evidence, so the next reader does not redo it):

| hypothesis | why it is dead |
|---|---|
| the lanes' `kickoff_request` subscription is missing | present and correct for all three lanes |
| the milestone approval gate skipped every milestone | no approval store in any run → mode defaults to `auto` → always approves |
| the planner returned `[]` and wiped the default | an empty list is falsy, so `milestones` keeps the M1 synthesized at orchestrator.py:1038 |
| the in-loop re-sync emptied it | that branch only calls `mark_status`; it never reassigns |

**This does not abort.** The reason the roadmap is empty is still unidentified, and aborting on an
unknown root trades one silent failure for a louder wrong one. It makes the state legible at the
moment it becomes unrecoverable — in the log *and* in `progress_events.jsonl`, which for these
runs holds two lines and no error at all.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch


def _block():
    """The span between the seed and the loop it feeds — anchored on both, never a width."""
    src = inspect.getsource(orch)
    start = src.index("set_roadmap(milestones")
    end = src.index("for _m_idx, _milestone in enumerate(milestones", start)
    return src[start:end]


def test_the_seed_and_the_loop_are_both_findable():
    """Non-vacuity: every case below reads the span between them."""
    src = inspect.getsource(orch)
    assert "set_roadmap(milestones" in src
    assert "for _m_idx, _milestone in enumerate(milestones" in src


def test_the_seed_is_read_back():
    """Write-and-hope is the defect. The store must be asked what it actually holds."""
    assert "list_milestones()" in _block()


def test_an_empty_readback_is_an_error_not_a_warning():
    """★ The severity is the point. A warning is what the seed failure already had, and it is why
    this cost 7 runs unnoticed — the run is unrecoverable from here."""
    b = _block()
    assert "_logger.error" in b
    assert "DID NOT LAND" in b


def test_the_message_says_what_it_costs():
    """An operator seeing this needs the consequence, not just the symptom: no kickoff means no
    lanes, which is why the run will look idle rather than broken."""
    b = _block()
    assert "start_kickoff" in b and "never" in b
    assert "7 of 151" in b


def test_it_also_reaches_the_persisted_log():
    """`progress_events.jsonl` is the only artifact every run leaves. For these 7 it holds two
    lines and no error — the run looked clean in the one place anyone would look."""
    b = _block()
    assert "EventType.PHASE_ERROR" in b
    assert '"ticket": 864' in b


def test_the_readback_cannot_itself_break_the_run():
    """Both the readback and the emit are guarded. An observability call that raises here would
    manufacture the failure it exists to report."""
    b = _block()
    assert b.count("except Exception") >= 2
    assert re.search(r"try:\s*\n\s*_seeded = list\(", b), b


def test_it_does_not_abort():
    """★ Deliberate. The root of the empty roadmap is bounded but unidentified; aborting on an
    unknown root trades a silent failure for a louder wrong one. If someone later makes this
    fatal, this test fails and the reasoning has to be revisited rather than quietly reversed."""
    b = _block()
    assert "raise" not in b
    assert "return" not in b
    assert "sys.exit" not in b


def test_the_original_seed_call_is_unchanged():
    """Non-regression: #864 adds a check after the seed, it does not alter the seed."""
    src = inspect.getsource(orch)
    assert 'self.hubs.milestones.set_roadmap(milestones, agent="orchestrator")' in src
    assert "milestone store seed failed" in src


def test_the_loop_really_does_contain_the_kickoff():
    """★ The premise: an empty roadmap is fatal only because `start_kickoff` is inside the loop.
    If it ever moves out, an empty roadmap stops being a total loss and this ticket's severity
    claim is wrong."""
    src = inspect.getsource(orch)
    loop = src.index("for _m_idx, _milestone in enumerate(milestones")
    kick = src.index("run_kickoff.start_kickoff(")
    assert kick > loop, "start_kickoff moved out of the milestone loop"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
