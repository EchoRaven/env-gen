"""Tests for the WorkHub meeting LLM tools (Phase C kickoff helpers).

Closed-by-construction guard:
    * Each tool round-trips success and error paths against a real
      ``HubRegistry`` (no mocks of the service layer — service-level
      identity discipline is part of the contract we want to test).
    * The ``agent`` argument MUST flow from ``self._agent_id`` set by
      ``set_agent``; we assert that an unset ``_agent_id`` is forwarded
      to the service as an empty string and triggers a ``ValueError``
      that the tool coerces to a ``ToolResult.fail`` — NEVER silently
      defaults to a phantom identity.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class WorkhubMeetingToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_meeting_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _find_tool(self, name: str, agent_id: str = "orch"):
        from tools.hub_tools import create_hub_tools
        for tool in create_hub_tools(agent_id=agent_id, hub_workspace=self.reg):
            if getattr(tool, "NAME", "") == name:
                return tool
        raise AssertionError(f"tool not found: {name}")

    # ------------------------------------------------------------------
    # WorkhubCreateMeetingTool
    # ------------------------------------------------------------------

    def test_create_meeting_success(self) -> None:
        tool = self._find_tool("workhub_create_meeting")
        result = _run_async(tool._run(
            agenda="M1 kickoff",
            attendees=["backend", "frontend"],
            milestone_index=1,
            kind="kickoff",
        ))
        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(result.data["title"], "M1 kickoff")
        self.assertEqual(result.data["kind"], "kickoff")
        self.assertEqual(result.data["status"], "open")
        self.assertEqual(result.data["created_by"], "orch")
        self.assertEqual(
            result.data["metadata"]["milestone_index"], 1,
            msg="milestone_index must be persisted in metadata",
        )
        self.assertEqual(
            result.data["metadata"]["attendees"], ["backend", "frontend"],
        )

    def test_create_meeting_empty_agenda_fails(self) -> None:
        tool = self._find_tool("workhub_create_meeting")
        result = _run_async(tool._run(
            agenda="",
            attendees=["backend"],
            milestone_index=0,
        ))
        self.assertFalse(result.success)
        self.assertIn("agenda", (result.error_message or "").lower())

    def test_create_meeting_empty_attendees_fails(self) -> None:
        tool = self._find_tool("workhub_create_meeting")
        result = _run_async(tool._run(
            agenda="x",
            attendees=[],
            milestone_index=0,
        ))
        self.assertFalse(result.success)
        self.assertIn("attendees", (result.error_message or "").lower())

    def test_create_meeting_negative_milestone_index_fails(self) -> None:
        """Round-7: tool must surface the service's ValueError on a
        negative milestone_index instead of silently coercing or
        defaulting."""
        tool = self._find_tool("workhub_create_meeting")
        result = _run_async(tool._run(
            agenda="x",
            attendees=["backend"],
            milestone_index=-1,
        ))
        self.assertFalse(result.success)
        self.assertIn("milestone_index", (result.error_message or "").lower())

    def test_create_meeting_no_phantom_agent_default(self) -> None:
        """If ``_agent_id`` is empty, the service must raise and the
        tool must surface that error — NEVER silently substitute a
        phantom identity like 'workhub'."""
        tool = self._find_tool("workhub_create_meeting", agent_id="")
        result = _run_async(tool._run(
            agenda="x",
            attendees=["backend"],
            milestone_index=0,
        ))
        self.assertFalse(result.success)
        self.assertIn("agent", (result.error_message or "").lower())

    def test_create_meeting_agent_flows_from_self_agent_id(self) -> None:
        """Verify the tool's ``_agent_id`` is the value forwarded to
        the service — set two different ids on two tool instances and
        confirm the meeting's ``created_by`` matches the per-instance
        id, not a shared default."""
        tool_a = self._find_tool("workhub_create_meeting", agent_id="orch")
        tool_b = self._find_tool("workhub_create_meeting", agent_id="backend")
        ra = _run_async(tool_a._run(agenda="A", attendees=["x"], milestone_index=0))
        rb = _run_async(tool_b._run(agenda="B", attendees=["x"], milestone_index=0))
        self.assertTrue(ra.success and rb.success)
        self.assertEqual(ra.data["created_by"], "orch")
        self.assertEqual(rb.data["created_by"], "backend")

    def test_create_meeting_tool_requires_milestone_index_in_schema(self) -> None:
        """Round-7: schema-level guard so the LLM cannot omit
        milestone_index without the harness rejecting the call."""
        tool = self._find_tool("workhub_create_meeting")
        required = tool.PARAMETERS.get("required", [])
        self.assertIn("milestone_index", required)
        self.assertIn(
            "milestone_index",
            tool.PARAMETERS.get("properties", {}),
            msg="milestone_index must be declared as a tool property",
        )

    # ------------------------------------------------------------------
    # WorkhubAddMeetingDecisionTool
    # ------------------------------------------------------------------

    def test_add_meeting_decision_success(self) -> None:
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]

        add_tool = self._find_tool("workhub_add_meeting_decision")
        result = _run_async(add_tool._run(
            meeting_id=meeting_id,
            decision={"section": "contract", "chosen": "REST"},
        ))
        self.assertTrue(result.success, msg=result.error_message)
        decisions = result.data["metadata"]["decisions"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["section"], "contract")
        self.assertEqual(decisions[0]["recorded_by"], "orch")

    def test_add_meeting_decision_unknown_meeting_fails(self) -> None:
        add_tool = self._find_tool("workhub_add_meeting_decision")
        result = _run_async(add_tool._run(
            meeting_id="page_ghost",
            decision={"section": "contract"},
        ))
        self.assertFalse(result.success)
        self.assertIn("not found", (result.error_message or "").lower())

    def test_add_meeting_decision_empty_decision_fails(self) -> None:
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]
        add_tool = self._find_tool("workhub_add_meeting_decision")
        result = _run_async(add_tool._run(
            meeting_id=meeting_id,
            decision={},
        ))
        self.assertFalse(result.success)

    def test_add_meeting_decision_milestone_index_optional(self) -> None:
        """Round-7: milestone_index is optional on the decision tool;
        when omitted the decision row has NO milestone_index key."""
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]
        add_tool = self._find_tool("workhub_add_meeting_decision")
        result = _run_async(add_tool._run(
            meeting_id=meeting_id,
            decision={"section": "contract"},
        ))
        self.assertTrue(result.success, msg=result.error_message)
        self.assertNotIn(
            "milestone_index",
            result.data["metadata"]["decisions"][0],
        )

    def test_add_meeting_decision_milestone_index_round_trip(self) -> None:
        """Round-7: when provided, milestone_index is persisted on the
        decision row."""
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]
        add_tool = self._find_tool("workhub_add_meeting_decision")
        result = _run_async(add_tool._run(
            meeting_id=meeting_id,
            decision={"section": "contract"},
            milestone_index=2,
        ))
        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(
            result.data["metadata"]["decisions"][0]["milestone_index"], 2,
        )

    def test_add_meeting_decision_no_phantom_agent_default(self) -> None:
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]
        add_tool = self._find_tool(
            "workhub_add_meeting_decision", agent_id="")
        result = _run_async(add_tool._run(
            meeting_id=meeting_id,
            decision={"section": "contract"},
        ))
        self.assertFalse(result.success)
        self.assertIn("agent", (result.error_message or "").lower())

    # Round 8h Fix #Q: tool accepts a stray ``agent=`` kwarg from the
    # LLM (the prompt example used to include it) — should be ignored
    # rather than rejected, and the canonical agent_id from
    # ``self._agent_id`` should still flow through to the workhub.
    def test_add_meeting_decision_accepts_and_ignores_agent_kwarg(self) -> None:
        """Smoke #9-sextodecimus regression: orchestrator's facilitator
        LLM called workhub_add_meeting_decision(..., agent="orchestrator")
        and the strict signature rejected the kwarg → no facilitator_note
        ever landed → Fix #D-bis fired auto-backup escalate → kickoff
        aborted. The tool now ignores the extra kwarg (forgiving)."""
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]
        add_tool = self._find_tool("workhub_add_meeting_decision")
        # Pass the LLM-supplied agent= explicitly. Pre-Fix-Q this raised
        # TypeError: "_run() got an unexpected keyword argument 'agent'".
        result = _run_async(add_tool._run(
            meeting_id=meeting_id,
            decision={"section": "contract", "v": 1},
            agent="orchestrator",   # ← Fix #Q: accepted + ignored
        ))
        self.assertTrue(result.success, msg=result.error_message)
        # Authoritative agent is self._agent_id ("orch" in the fixture),
        # NOT the LLM-supplied "orchestrator" string. Critical to ensure
        # the LLM can't impersonate.
        decisions = result.data["metadata"]["decisions"]
        self.assertEqual(decisions[0]["recorded_by"], "orch")

    def test_add_meeting_decision_ignores_other_stray_kwargs(self) -> None:
        """Belt-and-suspenders: the **_extra catch in Fix #Q should make
        the tool resilient to ANY extra LLM-supplied kwarg, not just
        agent. Forward-compat against prompt drift."""
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]
        add_tool = self._find_tool("workhub_add_meeting_decision")
        result = _run_async(add_tool._run(
            meeting_id=meeting_id,
            decision={"section": "contract"},
            agent="orchestrator",
            recorded_by="orchestrator",    # ← random stray
            note="just a note",             # ← random stray
        ))
        self.assertTrue(result.success, msg=result.error_message)

    # ------------------------------------------------------------------
    # WorkhubCloseMeetingTool
    # ------------------------------------------------------------------

    def test_close_meeting_success(self) -> None:
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]

        close_tool = self._find_tool("workhub_close_meeting")
        result = _run_async(close_tool._run(
            meeting_id=meeting_id,
            produced_artifacts=["plan_abc", "page_def"],
            metadata_extra={"verdict": "go"},
        ))
        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(result.data["status"], "closed")
        self.assertEqual(
            result.data["metadata"]["produced_artifacts"],
            ["plan_abc", "page_def"],
        )
        self.assertEqual(result.data["metadata"]["verdict"], "go")
        self.assertEqual(result.data["closed_by"], "orch")

    def test_close_meeting_empty_artifacts_allowed(self) -> None:
        """A meeting that closes with no produced artifacts is a real,
        recordable outcome (per the service docstring), not an error."""
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]
        close_tool = self._find_tool("workhub_close_meeting")
        result = _run_async(close_tool._run(
            meeting_id=meeting_id,
            produced_artifacts=[],
        ))
        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(result.data["metadata"]["produced_artifacts"], [])

    def test_close_meeting_unknown_meeting_fails(self) -> None:
        close_tool = self._find_tool("workhub_close_meeting")
        result = _run_async(close_tool._run(
            meeting_id="page_ghost",
            produced_artifacts=[],
        ))
        self.assertFalse(result.success)
        self.assertIn("not found", (result.error_message or "").lower())

    def test_close_meeting_milestone_index_optional(self) -> None:
        """Round-7: omitting milestone_index at close preserves the
        meeting's existing anchor (here: 5 from create)."""
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=5,
        ))
        meeting_id = create_result.data["id"]
        close_tool = self._find_tool("workhub_close_meeting")
        result = _run_async(close_tool._run(
            meeting_id=meeting_id, produced_artifacts=[],
        ))
        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(result.data["metadata"]["milestone_index"], 5)

    def test_close_meeting_milestone_index_round_trip(self) -> None:
        """Round-7: when provided at close, milestone_index overwrites
        the meeting's existing anchor on the closed page."""
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=5,
        ))
        meeting_id = create_result.data["id"]
        close_tool = self._find_tool("workhub_close_meeting")
        result = _run_async(close_tool._run(
            meeting_id=meeting_id,
            produced_artifacts=[],
            milestone_index=6,
        ))
        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(result.data["metadata"]["milestone_index"], 6)

    def test_close_meeting_no_phantom_agent_default(self) -> None:
        create_tool = self._find_tool("workhub_create_meeting")
        create_result = _run_async(create_tool._run(
            agenda="x", attendees=["backend"], milestone_index=0,
        ))
        meeting_id = create_result.data["id"]
        close_tool = self._find_tool(
            "workhub_close_meeting", agent_id="")
        result = _run_async(close_tool._run(
            meeting_id=meeting_id,
            produced_artifacts=[],
        ))
        self.assertFalse(result.success)
        self.assertIn("agent", (result.error_message or "").lower())

    # ------------------------------------------------------------------
    # Bundle / tool-surface registration guards
    # ------------------------------------------------------------------

    def test_meeting_tools_registered_in_writes_surface(self) -> None:
        """Closed-by-construction guard: each new write tool MUST be
        listed in HUB_TOOL_SURFACE['workhub']['writes'] or the focus
        gate will silently strip it from the agent's pool."""
        from multi_agent.hub_tool_surface import HUB_TOOL_SURFACE
        writes = HUB_TOOL_SURFACE["workhub"]["writes"]
        self.assertIn("workhub_create_meeting", writes)
        self.assertIn("workhub_add_meeting_decision", writes)
        self.assertIn("workhub_close_meeting", writes)

    def test_meeting_tools_bundle_registered(self) -> None:
        from multi_agent.tool_bundles import (
            TOOL_BUNDLE_REGISTRY,
            TOOL_BUNDLE_REQUIREMENTS,
        )
        self.assertIn("meeting_tools", TOOL_BUNDLE_REGISTRY)
        self.assertEqual(
            TOOL_BUNDLE_REQUIREMENTS["meeting_tools"], {"workhub"},
        )


if __name__ == "__main__":
    unittest.main()
