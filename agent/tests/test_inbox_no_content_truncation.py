"""Inbox tools must NOT truncate message content.

The PRIOR behaviour at communication_tools.py:871/960/1061 sliced
every returned message body to 500 chars via `content[:500]`. This
broke Facebook-scale tasks at the v3 re-pilot 2026-06-01:

  - Orchestrator sends task_ready with the ~3500-char Facebook spec
  - Design Agent's check_inbox returns content[:500] — Design sees
    only ~14% of the contract
  - Design has no way to ask for the rest (the re-ask reply ALSO
    truncates at 500 chars)
  - Design escalates back to orchestrator with "the inbox view
    truncates them. Please reply with the full exact contract"
  - Pipeline stuck

Per user 2026-06-01 directive ("不要截断，这个肯定要完整信息的"),
the fix removes the [:500] cap entirely from all three inbox tools.
This test locks in the no-truncation invariant so a future PR
doesn't re-introduce a "preview cap" that breaks large payloads.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
COMM_TOOLS_PY = (
    AGENT_DIR / "env_generator" / "llm_generator"
    / "tools" / "communication_tools.py"
)


class InboxToolsDoNotTruncateContent(unittest.TestCase):
    """Static scan: no `msg.get("content", "")[:N]` or similar in
    the formatted-message dicts the inbox tools return."""

    def setUp(self) -> None:
        self.src = COMM_TOOLS_PY.read_text(encoding="utf-8")

    def test_no_content_slice_in_inbox_tool_formatted_dicts(self) -> None:
        """The exact pattern that bit v3 re-pilot —
        `"content": msg.get("content", "")[:N]` — must not appear."""
        broken = re.findall(
            r'"content":\s*msg\.get\(\s*"content"\s*,\s*""\s*\)\s*\[\s*:\s*\d+\s*\]',
            self.src,
        )
        self.assertEqual(
            broken, [],
            msg=(
                f"Inbox tools STILL truncate content at runtime — "
                f"found {len(broken)} sites with the broken "
                f"`msg.get('content', '')[:N]` pattern. The v3 "
                f"re-pilot 2026-06-01 failure mode: Design Agent saw "
                f"only the first N chars of orchestrator task_ready "
                f"payloads, couldn't see full requirements, asked "
                f"orchestrator to re-send (which also got truncated)."
            ),
        )

    def test_all_three_inbox_tools_pass_full_content(self) -> None:
        """Affirmative: each tool's formatted-message dict reads
        `"content": msg.get("content", "")` with NO trailing slice."""
        # CheckInboxTool, GetImportantMessagesTool, SearchMessagesTool
        # all build a `formatted = []` list and append dicts. Count
        # those three full-content sites.
        full_content_sites = re.findall(
            r'"content":\s*msg\.get\(\s*"content"\s*,\s*""\s*\)\s*,',
            self.src,
        )
        self.assertGreaterEqual(
            len(full_content_sites), 3,
            msg=(
                f"Expected at least 3 full-content sites (CheckInbox + "
                f"GetImportantMessages + SearchMessages); found "
                f"{len(full_content_sites)}. If you refactored away "
                f"the redundancy, update this test to match."
            ),
        )

    def test_end_to_end_content_round_trips_unsliced(self) -> None:
        """E2E: send a long message via the in-memory pathway, then
        check_inbox, and assert the FULL content is returned."""
        sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

        # Build a minimal stub agent that the inbox tool can use.
        # The tool reads agent._subscription_inbox + agent._hubs;
        # we only need the in-memory path (no hubs) for this test.
        class _StubAgent:
            agent_id = "test_agent"
            def __init__(self):
                self._subscription_inbox = []
                self._hubs = None
            def get_inbox_messages(self, limit=999, clear=False):
                return list(self._subscription_inbox)

        agent = _StubAgent()
        long_content = "X" * 5000  # 5000 chars — 10x the old 500-char cap
        agent._subscription_inbox.append({
            "id": "msg_1",
            "from": "orchestrator",
            "type": "task_ready",
            "content": long_content,
            "tags": ["task_ready"],
            "priority": "high",
            "persist": False,
            "timestamp": "2026-06-01T21:00:00",
        })

        from tools.communication_tools import CheckInboxTool
        tool = CheckInboxTool(agent=agent)
        result = tool.execute(limit=10, clear=False)
        self.assertTrue(result.success)
        msgs = result.data["messages"]
        self.assertEqual(len(msgs), 1)
        returned_content = msgs[0]["content"]
        self.assertEqual(
            len(returned_content), 5000,
            msg=(
                f"check_inbox truncated 5000-char content to "
                f"{len(returned_content)} chars. The full content "
                f"MUST round-trip unchanged."
            ),
        )
        self.assertEqual(returned_content, long_content)


class ToolResultCompressorDoesNotTruncateInboxTools(unittest.TestCase):
    """3rd truncation site discovered 2026-06-02 v3 re-pilot debugging:
    ToolResultCompressor.COMPRESSION_RULES had no entry for check_inbox
    et al., so they fell through to the default rule (max_chars=1000).
    Result: even after the communication_tools.py CheckInboxTool fix
    returned full content, the LLM saw only the first ~1000 chars of
    the compressed result.

    Locks the high-cap rules so a future PR can't accidentally drop
    them back to the default. Cap is intentionally large (50000) —
    if context-budget concerns surface later, the right fix is a
    streaming or pagination protocol, NOT a hard truncation that
    silently fails the agent."""

    def test_check_inbox_has_high_compression_cap(self) -> None:
        sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))
        from multi_agent.context_management import ToolResultCompressor
        c = ToolResultCompressor()
        # 3500-char fake result (~ Facebook spec task_ready payload size)
        big = "A" * 3500
        for tool in [
            "check_inbox", "eventhub_inbox", "search_messages",
            "get_important_messages", "eventhub_get_thread",
        ]:
            out = c.compress(tool, big, True)
            self.assertGreaterEqual(
                len(out), 3500,
                msg=f"ToolResultCompressor truncated {tool!r} to "
                    f"{len(out)} chars — must keep at least 3500 to "
                    f"carry a full Facebook-scale task_ready payload. "
                    f"Add the tool to COMPRESSION_RULES with "
                    f"max_chars >= 50000.",
            )

    def test_default_compression_rule_unchanged(self) -> None:
        """The DEFAULT rule (for non-message tools) stays at 1000 —
        we only widened the inbox-message tools. This guards against
        a future PR that accidentally globally bumps the default and
        balloons context for every tool."""
        sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))
        from multi_agent.context_management import ToolResultCompressor
        self.assertEqual(
            ToolResultCompressor.COMPRESSION_RULES["default"]["max_chars"],
            1000,
            msg="Default ToolResultCompressor cap should stay at 1000. "
                "Only inbox-message tools get the high cap. If you need "
                "more for a specific tool, add it explicitly.",
        )


if __name__ == "__main__":
    unittest.main()
