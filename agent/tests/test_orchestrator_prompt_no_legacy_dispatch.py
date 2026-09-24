"""Round-8c regression tests for Fix #3: legacy orchestrator-LLM-direct
dispatch path removed from the orchestrator v3 prompt.

Round-8b smoke confirmed the kickoff coordinator was headless (no
driver, no attendee LLM turn) and the orchestrator's LLM fell through
to the legacy ``plan(add_task)`` + ``send_message(task_ready)`` pattern
its v3 prompt taught. Round-8c lands a Python driver + attendee handler
that close the headless path; this test pins the prompt-side delete
closed-by-construction so a future edit that re-introduces the legacy
teaching surfaces immediately.

Specifically:

  * The "Phase 2: Design Kickoff" / "Phase 3: Monitor Implementation"
    block no longer contains a literal example of
    ``plan(action="add_task", stage_id="design", ...)`` that the LLM
    would copy-paste at project start. Such an example, combined with
    a still-broken kickoff path, is exactly what triggered round-8b's
    silent fallthrough.
  * The peers map's ``you_call`` entries for backend/frontend (design
    was merged into frontend in round-8e.1) must explicitly contain a
    "DO NOT dispatch task_ready" rule so the LLM has a positive
    teaching that overrides any residual instinct to re-dispatch tasks
    the kickoff already created.
  * The ``inbox`` step_contract instruction must reference the new
    Python-driven coordinator + the explicit "DO NOT manually dispatch
    task_ready" guidance.
  * The mandate must mention the round-8c
    ``_drive_kickoff_to_completion`` coordinator + the "kickoff comes
    first" framing.

This is a *prompt-level* invariant: the LLM follows the prompt, so if
the prompt re-teaches the legacy pattern, the runtime fix alone is
insufficient.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


ORCH_PROMPT_PATH = (
    LLM_DIR
    / "multi_agent"
    / "prompts"
    / "v3"
    / "orchestrator_agent.j2"
)


@pytest.fixture(scope="module")
def prompt_source() -> str:
    return ORCH_PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Legacy task-graph examples MUST be removed from the "Planning" section.
# ---------------------------------------------------------------------------


def test_no_legacy_db_spec_example(prompt_source):
    """The legacy 'plan(action="add_task", stage_id="design", task_id="db_spec"...)'
    example taught the LLM to author the M1 design task tree itself.
    The kickoff coordinator (finalize_kickoff) now does this. Re-adding
    the example is the round-8b regression class."""
    assert 'task_id="db_spec"' not in prompt_source, (
        "round-8c Fix #3: 'task_id=\"db_spec\"' was a legacy example "
        "teaching the LLM to author kickoff's tasks itself; it must "
        "stay deleted."
    )
    assert 'task_id="api_spec"' not in prompt_source
    # The two implementation-stage tasks the legacy example registered:
    assert 'task_id="schema"' not in prompt_source
    assert 'task_id="release_validation",' not in prompt_source
    assert 'task_id="ui",' not in prompt_source


def test_no_legacy_implementation_task_phrasings(prompt_source):
    """The legacy block phrased database/backend/frontend task creation
    in a way the LLM would literally copy. The replacement teaching is
    the new "Planning — task authoring lives in the kickoff coordinator"
    section."""
    legacy_phrasings = [
        'task_description="Create database schema spec"',
        'task_description="Create API endpoint spec"',
        'task_description="Implement PostgreSQL schema"',
        'task_description="Implement Express API"',
        'task_description="Implement React UI"',
        'task_description="Design and execute release validation coverage"',
    ]
    for phrase in legacy_phrasings:
        assert phrase not in prompt_source, (
            f"round-8c Fix #3: legacy task example '{phrase}' must be "
            "removed — the kickoff coordinator authors these tasks now."
        )


# ---------------------------------------------------------------------------
# Positive teachings (the new "DO NOT" / "kickoff comes first" rules)
# must be PRESENT.
# ---------------------------------------------------------------------------


def test_mandate_references_kickoff_driver(prompt_source):
    """The mandate must teach the LLM that the kickoff coordinator runs
    BEFORE its first tick. Without this teaching, the LLM defaults to
    'I should plan and dispatch tasks at project start' which is the
    legacy regression shape."""
    assert "_drive_kickoff_to_completion" in prompt_source, (
        "round-8c Fix #3: mandate must reference the Python coordinator "
        "by name so the LLM has a positive teaching about why it "
        "should NOT dispatch task_ready at project start."
    )
    assert "kickoff comes first" in prompt_source.lower() or (
        "Kickoff comes first" in prompt_source
    )


def test_inbox_step_contract_forbids_redundant_task_ready(prompt_source):
    """The per-step inbox instruction must explicitly forbid the
    orchestrator from dispatching task_ready for kickoff-registered
    tasks. This is the surface where the round-8b LLM made the wrong
    call (it saw inbox events + decided to issue task_ready)."""
    # The negative teaching must be present in the inbox step contract:
    assert "DO NOT dispatch task_ready" in prompt_source, (
        "round-8c Fix #3: inbox step_contract must explicitly forbid "
        "task_ready dispatch for the M{n} kickoff task_tree — the "
        "round-8b smoke confirmed the LLM defaulted to this without "
        "a positive 'don't' teaching."
    )


@pytest.mark.parametrize("lane", ["backend", "frontend", "verifier"])
def test_peers_map_forbids_task_ready_at_project_start(prompt_source, lane):
    """Each attendee's peers.you_call entry must spell out the new
    rule that the orchestrator does NOT dispatch task_ready for
    kickoff-registered tasks. A future edit that softens "DO NOT" to
    "should usually" reopens the regression class — pin it.

    Round-8e.1: 'design' lane was merged into frontend; design is no
    longer in peers. See ``test_design_lane_not_in_peers`` below for the
    closed-by-construction guard."""
    # We allow the lane to appear in many contexts; check the lane's
    # peers row contains the don't-dispatch teaching.
    # Look for any line that contains both the lane id and the
    # "DO NOT dispatch task_ready" phrasing in proximity.
    relevant = [
        line for line in prompt_source.splitlines()
        if f'"id": "{lane}"' in line
    ]
    assert relevant, f"peers row for {lane!r} not found"
    assert any("DO NOT dispatch task_ready" in line for line in relevant), (
        f"round-8c Fix #3: peers.you_call for {lane!r} must explicitly "
        "forbid task_ready at project start — the kickoff coordinator "
        "owns initial dispatch."
    )


def test_design_lane_not_in_peers(prompt_source):
    """Round-8e.1: design lane was merged into frontend. The orchestrator
    peers map must NOT contain a 'design' peer row anymore — a future
    edit that re-adds it would re-introduce the merged-out lane.

    Closed-by-construction: assert no ``"id": "design"`` row appears in
    the prompt's peers structure."""
    design_id_lines = [
        line for line in prompt_source.splitlines()
        if '"id": "design"' in line
    ]
    assert not design_id_lines, (
        "round-8e.1: design lane was merged into frontend; the peers "
        "map must NOT have a 'design' row. Found: "
        f"{design_id_lines!r}"
    )


def test_success_criteria_no_dispatch_design_at_project_start(prompt_source):
    """The old success_criteria item "Design Agent dispatched at project
    start" reinforced the legacy pattern from the success-grading side.
    Removed in 8c."""
    assert "Design Agent dispatched at project start" not in prompt_source, (
        "round-8c Fix #3: legacy success_criteria 'Design Agent "
        "dispatched at project start' encoded the legacy ordering "
        "rule and must stay deleted."
    )
    # The new success_criteria must reference the kickoff coordinator:
    assert "Kickoff coordinator drove the M" in prompt_source, (
        "round-8c Fix #3: success_criteria must teach what 'good' "
        "looks like under the new coordinator — without that, the LLM "
        "has no positive grading rule and defaults to the legacy "
        "ordering."
    )


def test_send_message_task_ready_tool_policy_is_remediation_only(prompt_source):
    """The tool_policy entry for send_message(task_ready) used to say
    'dispatch resident lanes when their upstream is ready. Phase 2:
    design at project start.' That phrasing is exactly the legacy
    behavior. 8c rewrites it to REMEDIATION ONLY."""
    assert "REMEDIATION ONLY post-kickoff" in prompt_source, (
        "round-8c Fix #3: send_message(task_ready) tool_policy must "
        "scope to remediation only post-kickoff."
    )
    # The legacy phrasing must be GONE:
    assert "Phase 2: design at project start" not in prompt_source
    assert "Phase 3: backend/frontend AFTER design approved" not in prompt_source


# ---------------------------------------------------------------------------
# Round 8h smoke #19 follow-up — silent-lane recovery directive.
#
# Smoke #19 surfaced that the orchestrator's v3 prompt was so heavily
# anti-task_ready post-kickoff that the LLM never dispatched task_ready
# to a lane that silently failed to wake from kickoff_complete. The fix
# adds an explicit EXCEPTION (d) to the rule: when a lane has zero
# post-finalize agent_status, the orchestrator MUST dispatch.
#
# These pins guarantee a future edit can't accidentally re-tighten the
# rule and lock the orchestrator back into the smoke #19 wedge.
# ---------------------------------------------------------------------------


def test_silent_lane_recovery_exception_in_task_ready_tool_policy(prompt_source):
    """The send_message(task_ready) tool_policy entry must teach the
    silent-lane recovery exception so the LLM can act on it WITHOUT
    contradicting the post-kickoff "no redundant dispatch" rule."""
    # The exception clause itself:
    assert "silent-lane recovery" in prompt_source.lower(), (
        "round-8h smoke #19: tool_policy for task_ready must name "
        "the silent-lane recovery exception by phrase so the LLM has "
        "a positive teaching to dispatch when a lane is dark."
    )
    # The mechanism the LLM should use to detect silence:
    assert "eventhub_get_agent_status" in prompt_source, (
        "round-8h smoke #19: the prompt must point the LLM at "
        "eventhub_get_agent_status as the silence-detection mechanism — "
        "otherwise the LLM has no way to verify a lane is dark."
    )
    # The dispatch shape the LLM should use:
    assert "priority='urgent'" in prompt_source or 'priority="urgent"' in prompt_source, (
        "round-8h smoke #19: silent-lane recovery dispatches must be "
        "URGENT priority to bypass normal queue ordering."
    )


def test_inbox_step_contract_teaches_silent_lane_check(prompt_source):
    """The per-step inbox instruction must include the silent-lane
    check as a structural requirement, not optional — without this
    the LLM will read inbox + update memory_bank in a loop (smoke #19
    behavior) instead of acting."""
    inbox_lines = [
        line for line in prompt_source.splitlines()
        if '"inbox":' in line
    ]
    assert inbox_lines, "inbox step_contract row not found"
    inbox_blob = " ".join(inbox_lines)
    # The check must be named:
    assert "silent-lane recovery" in inbox_blob.lower()
    # The lanes to check (backend / frontend / verifier) must be named so
    # the LLM doesn't have to infer which lanes:
    assert "backend" in inbox_blob and "frontend" in inbox_blob and "verifier" in inbox_blob


def test_success_criteria_lists_silent_lane_recovery(prompt_source):
    """The new behavior must appear in success_criteria so the LLM
    grades its own ticks against it. Without this, the LLM has no
    feedback signal when it skips the silent-lane check."""
    assert "Silent-lane recovery" in prompt_source, (
        "round-8h smoke #19: success_criteria must list silent-lane "
        "recovery as a graded behavior so the LLM has a positive "
        "feedback rule that drives the dispatch decision."
    )
