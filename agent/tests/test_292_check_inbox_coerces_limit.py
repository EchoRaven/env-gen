"""#292 — check_inbox must coerce a non-integer limit, not crash.

r76 live (10×): the orchestrator called check_inbox with a stringified limit
(the schema declares limit as integer, but the model reasonably passes numeric
args as strings). ``filtered = filtered[:limit]`` (communication_tools.py:828)
then raised

    ❌ check_inbox FAILED: slice indices must be integers or None or have an
    __index__ method

so the inbox read failed and the agent had to retry — recurring friction on a
core coordination tool. The tool declares ``limit: int`` and must accept a
coercible value (``"10"`` → 10) and fall back to the default for an
uncoercible one, never crash on a plausible model-supplied value.
"""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from tools.communication_tools import CheckInboxTool  # noqa: E402


class _StubAgent:
    agent_id = "orchestrator"

    def __init__(self, messages):
        self._subscription_inbox = list(messages)
        self._hubs = None

    def get_inbox_messages(self, limit=999, clear=False):
        return list(self._subscription_inbox)


class CheckInboxLimitCoercionTests(unittest.TestCase):
    def _msgs(self, n):
        return [{
            "id": f"m_{i}", "from": "orchestrator", "type": "task_ready",
            "content": f"body {i}", "tags": [], "priority": "normal",
            "persist": False, "timestamp": "2026-07-25T02:00:00",
        } for i in range(n)]

    def test_string_limit_is_coerced_not_crashed(self) -> None:
        tool = CheckInboxTool(agent=_StubAgent(self._msgs(5)))
        result = tool.execute(limit="3", clear=False)  # r76 failure mode
        self.assertTrue(result.success, "a stringified limit must not crash check_inbox")
        self.assertEqual(result.data["count"], 3)

    def test_uncoercible_limit_falls_back_to_default(self) -> None:
        tool = CheckInboxTool(agent=_StubAgent(self._msgs(20)))
        result = tool.execute(limit="all", clear=False)
        self.assertTrue(result.success)
        self.assertEqual(result.data["count"], 10)  # default limit

    def test_int_limit_still_works(self) -> None:
        tool = CheckInboxTool(agent=_StubAgent(self._msgs(5)))
        result = tool.execute(limit=2, clear=False)
        self.assertTrue(result.success)
        self.assertEqual(result.data["count"], 2)


if __name__ == "__main__":
    unittest.main()
