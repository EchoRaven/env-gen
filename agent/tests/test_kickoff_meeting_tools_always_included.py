"""Round-8d Fix #5 regression: kickoff meeting primitives MUST be in
the agent's always-include action tool set so the per-step ranker
cannot drop them.

Background (round-8d-bis smoke surfaced this AFTER Fix #2-bis +
Fix #4 landed):

- Fix #2-bis (bridge msg_type mirror) made the urgent-event handler
  fire on kickoff_request → all 4 attendees finally entered LLM turns.
- Fix #4 (allowed_set) let finalize_kickoff register endpoints/tables
  under actor='orchestrator'.
- But the LLM ranker in
  ``action.py:_apply_hub_focus -> tooling.py:_stage_tool_names ->
   rank_tool_names(limit=10)`` was DROPPING
  ``workhub_add_meeting_decision`` from the per-step tool surface,
  preferring semantically similar tools like ``workhub_register_ui_page``
  / ``workhub_task``. All 4 attendees called focus_hub("workhub") and
  saw 10 workhub WRITE tools — but the one tool their
  kickoff_response_prompt macro explicitly instructs them to call
  (``workhub_add_meeting_decision``) wasn't in those 10.
- Result: frontend agent called `finish()` with
  ``"Blocked in kickoff response: documented
  workhub_add_meeting_decision tool is not exposed in the current
  toolset after focusing WorkHub"``. The other 3 attendees showed
  the same "called register_ui_page/task instead" pattern.

Fix #5 adds the three kickoff meeting primitives —
``workhub_create_meeting``, ``workhub_add_meeting_decision``,
``workhub_close_meeting`` — to
``BaseAgent._HUB_REGISTRATION``, which is folded into
``ACTION_STAGE_ALWAYS_INCLUDE`` for the "communicate" / "edit_code" /
"deliver" / "action" stages. Same rationale as the original
``_HUB_REGISTRATION`` set: agents that need to write hub state for a
specific instruction MUST see the tool unconditionally, the ranker
cannot drop it.

These tests pin the always-include contract closed-by-construction so
a future edit that drops any of the meeting tools from
_HUB_REGISTRATION fires loudly.
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

from multi_agent.agents.base import EnvGenAgent  # noqa: E402


# ---------------------------------------------------------------------------
# _HUB_REGISTRATION class attribute pins.
# ---------------------------------------------------------------------------


def test_hub_registration_includes_kickoff_meeting_primitives():
    """Closed-by-construction pin: all 3 kickoff meeting primitives MUST
    be in the _HUB_REGISTRATION set so the per-step LLM ranker (which
    truncates to ~10 tools) cannot drop them. Round-8d-bis: dropping
    even one of these reopens the "blocked in kickoff response" regression."""
    hub_reg = EnvGenAgent._HUB_REGISTRATION
    assert "workhub_create_meeting" in hub_reg, (
        "round-8d Fix #5: workhub_create_meeting must be in _HUB_REGISTRATION "
        "so the orchestrator can author the kickoff meeting page itself "
        "(start_kickoff calls this under the hood, but the orchestrator "
        "lane MAY also create follow-on Mn meetings — keep the tool reachable)."
    )
    assert "workhub_add_meeting_decision" in hub_reg, (
        "round-8d Fix #5: workhub_add_meeting_decision MUST be in "
        "_HUB_REGISTRATION. This is the CORE tool the "
        "kickoff_response_prompt macro instructs each attendee to call. "
        "If the ranker drops it, attendees finish() blocked and the "
        "round-8d-bis 'tool not exposed' regression returns."
    )
    assert "workhub_close_meeting" in hub_reg, (
        "round-8d Fix #5: workhub_close_meeting must be in "
        "_HUB_REGISTRATION. finalize_kickoff calls this under the hood, "
        "but the orchestrator lane may also close meetings during "
        "fallback or recovery; the tool must stay reachable."
    )
    assert "workhub_get_document" in hub_reg, (
        "round-8g Fix #B: workhub_get_document MUST be in _HUB_REGISTRATION. "
        "Multi-round phase-aware meetings (comment + reply phases) need "
        "to READ the meeting document to see other attendees' drafts and "
        "comments. Smoke #9-bis (2026-06-02 23:40) caught backend finishing "
        "reply phase early with 'workhub_get_document tool is not available' — "
        "same ranker-drops-it pattern as the Fix #5 write side."
    )


# ---------------------------------------------------------------------------
# ACTION_STAGE_ALWAYS_INCLUDE rolls _HUB_REGISTRATION into 4 stages.
# Confirm the meeting primitives transitively make it into all 4.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage",
    ["communicate", "edit_code", "deliver", "action"],
)
def test_meeting_primitives_always_included_per_stage(stage):
    """Every action stage that folds in _HUB_REGISTRATION MUST see the
    kickoff meeting primitives. This is the user-facing guarantee: in
    these stages the LLM ranker CAN'T drop them regardless of
    semantic-similarity heuristics."""
    always = EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE[stage]
    assert "workhub_add_meeting_decision" in always, (
        f"round-8d Fix #5: workhub_add_meeting_decision must be in "
        f"ACTION_STAGE_ALWAYS_INCLUDE[{stage!r}] (folded via "
        "_HUB_REGISTRATION). Without this the per-step ranker drops it "
        "during attendee kickoff_response → 'tool not exposed' regression."
    )


def test_meeting_primitives_count_pin():
    """Source-pin: exactly the 3 kickoff meeting primitives the
    kickoff coordinator needs (create / add_decision / close). If a
    new meeting tool is added in the future, the test should explicitly
    decide whether it joins the always-include set or not — failing
    here forces that decision."""
    hub_reg = EnvGenAgent._HUB_REGISTRATION
    meeting_tools = {n for n in hub_reg if "meeting" in n}
    assert meeting_tools == {
        "workhub_create_meeting",
        "workhub_add_meeting_decision",
        "workhub_close_meeting",
    }, (
        f"round-8d Fix #5: _HUB_REGISTRATION should contain exactly the "
        f"3 kickoff meeting primitives. Found: {meeting_tools}. "
        "If a new meeting tool is added, decide whether it joins the "
        "always-include set and update this pin."
    )


# ---------------------------------------------------------------------------
# Source-inspection guard: pin the _HUB_REGISTRATION set literally
# contains the kickoff meeting tool names. This protects against a
# future edit that renames or otherwise breaks the set's contents
# without changing its semantics.
# ---------------------------------------------------------------------------


def test_source_pins_meeting_tools_in_hub_registration():
    """Source-inspection guard."""
    import inspect
    src = inspect.getsource(EnvGenAgent)
    # Locate the _HUB_REGISTRATION literal in the source.
    assert "_HUB_REGISTRATION" in src
    # The set literal should contain the meeting primitive names.
    for name in (
        "workhub_create_meeting",
        "workhub_add_meeting_decision",
        "workhub_close_meeting",
    ):
        assert f'"{name}"' in src or f"'{name}'" in src, (
            f"round-8d Fix #5 source-pin: {name!r} must appear in the "
            "_HUB_REGISTRATION literal in agents/base.py. Removing it "
            "re-opens the 'tool not exposed in kickoff response' "
            "regression observed in the 2026-06-02 20:11 smoke run."
        )


# ---------------------------------------------------------------------------
# Round-8d Fix #6: meeting_tools bundle MUST be granted to every kickoff
# attendee profile in agents_config.yaml, otherwise _HUB_REGISTRATION's
# always-include flag can't surface tools that aren't in the agent's
# bundle to begin with.
#
# The 3 meeting primitives live in a NARROW dedicated bundle
# (tool_bundles.py:_bundle_meeting_tools) "so profiles that need meeting
# authoring (e.g. orchestrator running the kickoff sub-protocol) can
# subscribe without re-granting the broad WorkHub write surface, and
# so the bundle's caller-set is auditable in agents_config.yaml." But
# the round-7 + round-8c kickoff refactor created the
# kickoff_response_prompt macro instructing attendees to call
# workhub_add_meeting_decision — without granting them the meeting_tools
# bundle. Confirmed in the round-8d-bis 20:47 diagnostic smoke:
# design's selected_names included 5 workhub writes (from workhub_tools
# bundle) but NOT the 3 meeting tools (from meeting_tools bundle).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def attendee_profiles():
    """Load the 4 kickoff attendee profiles from agents_config.yaml."""
    import yaml
    cfg_path = (
        LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml"
    )
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    return cfg["profiles"]


@pytest.mark.parametrize("profile_name", ["backend", "frontend", "verifier"])
def test_attendee_profile_includes_meeting_tools_bundle(attendee_profiles, profile_name):
    """Each of the 3 kickoff attendees MUST have meeting_tools in their
    tool_bundles list. Without it, the kickoff_response_prompt macro's
    instruction to call workhub_add_meeting_decision fails because the
    tool isn't even in the agent's bundle — _HUB_REGISTRATION's
    always-include can only pull from tools already in the bundle."""
    profile = attendee_profiles.get(profile_name)
    assert profile is not None, f"profile {profile_name!r} missing from agents_config.yaml"
    bundles = profile.get("tool_bundles", [])
    assert "meeting_tools" in bundles, (
        f"round-8d Fix #6: profile {profile_name!r} must list "
        "'meeting_tools' in its tool_bundles. Without this, the agent's "
        "tool_schema_map does NOT contain workhub_create_meeting / "
        "workhub_add_meeting_decision / workhub_close_meeting, and the "
        "_HUB_REGISTRATION always-include set in agents/base.py cannot "
        "rescue them (rank_tool_names line 203 filters always_include "
        "against candidate_names — tools not in the bundle never enter "
        "candidate_names). This is what the round-8d-bis 20:47 "
        f"diagnostic smoke proved by logging selected_names. Current "
        f"bundles: {bundles}"
    )


def test_meeting_tools_bundle_requires_workhub_category(attendee_profiles):
    """meeting_tools bundle requires the 'workhub' tool_category (per
    tool_bundles.py:TOOL_BUNDLE_REQUIREMENTS). The attendees already
    have workhub in their tool_categories — this test guards against a
    future edit that drops the category and breaks the bundle silently.
    (design profile was retired in the 2026-06-02 kickoff-refactor.)"""
    for profile_name in ("backend", "frontend", "verifier"):
        profile = attendee_profiles[profile_name]
        cats = set(profile.get("tool_categories", []))
        assert "workhub" in cats, (
            f"round-8d Fix #6 prereq: {profile_name!r} must include "
            "'workhub' in tool_categories so meeting_tools bundle "
            f"passes its category gate. Current: {sorted(cats)}"
        )


# ---------------------------------------------------------------------------
# Round-8g Fix #E: orchestrator chairs the kickoff and the facilitator
# turn (kickoff_facilitation_prompt) instructs the LLM to call
# workhub_add_meeting_decision to record the facilitator_note. This
# requires the meeting_tools bundle in the orchestrator profile, same
# class as Fix #6 for the attendees.
#
# Smoke #9-quintus (2026-06-03 00:09 - 00:28) caught the regression:
# orchestrator's facilitator agentic loop ran for 19 minutes calling
# check_inbox/finish/check_inbox/finish repeatedly while claiming
# "the required WorkHub meeting-decision tool is unavailable in the
# current toolset" — accurate self-report because the tool wasn't in
# the orchestrator's bundle at all. The driver timed out at 1200s.
# ---------------------------------------------------------------------------


def test_orchestrator_profile_includes_meeting_tools_bundle(attendee_profiles):
    """The orchestrator MUST have meeting_tools in its tool_bundles list
    because _handle_kickoff_facilitate_request renders the
    kickoff_facilitation_prompt macro which instructs the LLM to record
    ONE workhub_add_meeting_decision (section='facilitator_note', ...).
    Without this bundle, the orchestrator's facilitator turn cannot
    write the structured decision the driver polls for, and the
    meeting hangs at the facilitator phase until the 1200s driver
    timeout fires (graceful failure but useless run)."""
    orchestrator = attendee_profiles.get("orchestrator")
    assert orchestrator is not None, "orchestrator profile missing from agents_config.yaml"
    bundles = orchestrator.get("tool_bundles", [])
    assert "meeting_tools" in bundles, (
        "round-8g Fix #E: orchestrator profile must list 'meeting_tools' "
        "in its tool_bundles. Without this, the LLM facilitator turn "
        "renders the kickoff_facilitation_prompt macro but cannot call "
        "workhub_add_meeting_decision — the tool isn't even in the "
        "orchestrator's tool_schema_map. Closed-by-construction Fix #D "
        "(_ensure_facilitator_note auto-escalate) DOES still fire on "
        "loop exit, but only after the orchestrator's LLM burns "
        "max_steps=20 of degenerate 'tool unavailable' iterations and "
        "the driver hits its 1200s timeout. The clean fix is to grant "
        f"the bundle. Current bundles: {bundles}"
    )
    # Sanity: tool_categories must include 'workhub' so the bundle's
    # category gate passes — mirror of the attendee guard above.
    cats = set(orchestrator.get("tool_categories", []))
    assert "workhub" in cats, (
        f"round-8g Fix #E prereq: orchestrator must include 'workhub' "
        f"in tool_categories so meeting_tools bundle passes its "
        f"category gate. Current: {sorted(cats)}"
    )
