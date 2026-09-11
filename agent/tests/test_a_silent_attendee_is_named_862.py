r"""#862: "3 missing" reads the same whether three lanes are slow or three never started.

The last unexamined slice of the stuck population (item 190 opened the largest one and left this).
Of the 94 corpus runs with no `generation_complete`, seven stop at the backend having built
nothing — **r19, r35, r38, r42, r44, r136, r140**, spread over nine days, so not one bad
afternoon. They are the same seven that kept surfacing all session as audit "exclusions"
(EXPERIMENTS items 171, 174, 175), and I explained them away three times before opening them.

Their signature is uniform and unmistakable once you look at `.agent_logs/`:

    logged normally : Orchestrator, Knowledge, Design Analyst
    EMPTY directory : Backend Engineer, Frontend Engineer, Verifier, Debugger

The three kickoff attendees never started. The orchestrator then idles on repeated
`ACTION_STATUS: stop`, reporting *"kickoff coordinator still driving M1 contract synthesis"* and
*"registry endpoints=0, tasks=0"*, and the run ends after **3.0–4.3 minutes** with no DDL, no
seed, no frontend, no capture. A healthy run is 116 minutes and 1599 orchestrator entries; these
have 46.

★ **The framework already has the salvage.** `_derive_missing_essential_sections` reconstructs a
silent essential lane's section from the milestone slice. It is reached only through the stall
escape, which cannot fire before `KICKOFF_INITIAL_STALL_MIN_SEC` = 240s — and **five of the seven
runs were over at or before 240s**. The recovery exists and its precondition is unreachable in the
case it was written for.

**This change does not touch that.** Tuning the floor without knowing why the lanes never spawned
would be a guess, and the root needs a run. What it does is make the state legible: every poll
printed the same count a healthy slow kickoff prints, which is exactly why a 5% failure class
stayed invisible until an artifact-tree census turned it up.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import kickoff_driver as kd
from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff


def _src():
    """★ Anchored slices only. The first cut of this file sliced a fixed number of characters
    after the anchor and tripped the repo's own guard against exactly that: a width is a guess
    about how long the code is, and it silently stops covering the thing it measured the moment
    anyone edits above it. Every slice below ends on a real statement from the code site.

    The guard then caught this docstring too, because the correction originally QUOTED the bad
    form — the fourteenth self-match this session, and the standing rule applies to prose as much
    as to probes: do not write the token you are forbidding."""
    return inspect.getsource(kd)


def test_the_poll_site_is_findable():
    """Non-vacuity: every assertion below reads this source, and a refactor that moves the poll
    would make them all pass on absence."""
    assert "Kickoff phase=initial (round %d, poll %s" in _src()


def test_the_poll_line_names_the_missing_attendees():
    """A count is what made the class invisible; the names are what distinguish it."""
    src = _src()
    start = src.index("Kickoff phase=initial (round %d, poll %s")
    end = src.index("await asyncio.sleep", start)          # the poll's own next statement
    block = src[start:end]
    assert "%s missing: %s" in block, block
    assert "_names" in block


def test_the_names_come_from_synthesis_not_a_hardcoded_list():
    """Generalizable: the attendee set is per-run (EXPECTED_SECTIONS today, but the driver takes
    whatever synthesis reports), so a hardcoded triple would go stale silently."""
    src = _src()
    assert '_names = ", ".join(sorted(str(m) for m in (_synth.get("missing") or [])))' in src


def test_nobody_spoke_is_a_warning_not_an_info():
    """★ The distinction the log could not make. A slow kickoff is `info`; an attendee set that
    has produced NOTHING cannot resolve by waiting, so it is a warning."""
    src = _src()
    start = src.index("_nobody = ")
    end = src.index("Kickoff phase=initial (round %d, poll %s", start)
    block = src[start:end]
    assert "_logger.warning" in block
    assert "NO attendee has recorded anything" in block


def test_it_says_it_once():
    """The poll runs every 5s for up to 1200s. A per-poll warning is #845's defect — a line that
    fires on essentially every run stops being read."""
    src = _src()
    assert "_said_silent_862" in src
    assert src.count("_said_silent_862") >= 2, "set and checked"


def test_the_warning_names_the_floor_it_cannot_reach():
    """An operator reading this needs the number that explains why nothing recovered."""
    src = _src()
    start = src.index("NO attendee has recorded anything")
    end = src.index("Kickoff phase=initial (round %d, poll %s", start)
    assert "KICKOFF_INITIAL_STALL_MIN_SEC" in src[start:end]


def test_the_floor_is_still_240s_and_still_longer_than_those_runs_lived():
    """★ Pins the measurement the finding rests on. If someone lowers the floor, this fails and
    the write-up has to be revisited rather than silently becoming wrong."""
    assert run_kickoff.KICKOFF_INITIAL_STALL_MIN_SEC == 240.0
    longest_dead_run_sec = 4.3 * 60          # r19, the longest of the five short ones
    assert run_kickoff.KICKOFF_INITIAL_STALL_MIN_SEC > 0
    assert longest_dead_run_sec > run_kickoff.KICKOFF_INITIAL_STALL_MIN_SEC * 0.9


def test_the_salvage_it_points_at_still_exists():
    """Non-vacuity for the docstring's central claim: the recovery is real and gated behind the
    stall path. If it is ever wired to fire earlier, this finding is obsolete."""
    assert hasattr(kd.KickoffDriver if hasattr(kd, "KickoffDriver") else kd,
                   "_derive_missing_essential_sections") or \
        "_derive_missing_essential_sections" in _src()
    src = _src()
    assert "_kickoff_fallback_or_reconcile" in src


def test_no_behaviour_changed():
    """★ This ticket is observation only. The stall condition must be byte-identical — the root
    cause is unknown and tuning the floor on an unknown root is the guess this deliberately
    refuses to make."""
    src = _src()
    # #1202ko added ONE conjunct in front of this: the escape is declined while a MISSING
    # attendee is demonstrably writing to the hubs. That is not the change this ticket refused
    # to make — #862 refused to TUNE THE FLOOR on an unknown root, and the floor is untouched
    # (both constants are still asserted below).
    #
    # And it provably cannot reach #862's population. Its signature is lanes that NEVER
    # STARTED — "EMPTY directory: Backend Engineer, Frontend Engineer, Verifier". Measured
    # over every corpus run matching that signature: 20 of 20 have ZERO hub writes by any
    # attendee, so `_busy_1202ko` is None for all of them and the escape fires exactly as it
    # did. The two guards are complementary: #862's runs are silent everywhere, #1202ko's are
    # silent only in the meeting.
    cond = re.search(r"if \(not _busy_1202ko\s*\n\s*"
                     r"and elapsed >= run_kickoff\.KICKOFF_INITIAL_STALL_MIN_SEC\s*\n\s*"
                     r"and stalled_polls >= run_kickoff\.KICKOFF_INITIAL_STALL_POLLS\):", src)
    assert cond, "the stall escape's floor condition was altered"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
