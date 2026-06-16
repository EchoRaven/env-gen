"""Guard: base_agent.log_tool_call persists the AUTHORITATIVE tool-success flag.

ToolResult.__str__ drops `success` (success -> str(data), which may itself contain
words like "errors" — e.g. a passing lint's {"errors": []}). Readers (Env Forge
drawer, live_monitor) must therefore consume an explicit flag rather than guess
pass/fail from the result text. This pins that the jsonl metadata carries `ok`.
"""

import sys
import types
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))

from utils.base_agent import BaseAgent  # noqa: E402
from utils.tool import ToolResult  # noqa: E402


class _CapLogger:
    def __init__(self):
        self.logged = []

    def log(self, event_type, content, metadata):
        self.logged.append((event_type, content, metadata))


def _fake_agent():
    return types.SimpleNamespace(
        _debug_logger=_CapLogger(),
        _metrics=types.SimpleNamespace(tool_calls=0),
        record_action=lambda *a, **k: None,
        record_observation=lambda *a, **k: None,
        record_error=lambda *a, **k: None,
    )


class LogToolCallOkFlagTests(unittest.TestCase):
    def test_success_persists_ok_true(self):
        a = _fake_agent()
        # A passing lint: success=True but data text contains the word "errors".
        BaseAgent.log_tool_call(a, "lint", {"path": "x.py"},
                                ToolResult(success=True, data={"errors": [], "tool": "ruff",
                                                               "message": "Python lint OK: x.py"}))
        _, _, md = a._debug_logger.logged[0]
        self.assertIs(md["ok"], True)
        self.assertIn("errors", md["result"])   # the misleading substring is still in `result`…
        self.assertIs(md["ok"], True)            # …but `ok` is the authoritative truth.

    def test_failure_persists_ok_false_and_error(self):
        a = _fake_agent()
        BaseAgent.log_tool_call(a, "read", {"path": "missing.py"},
                                ToolResult(success=False, error_message="path not found"))
        _, _, md = a._debug_logger.logged[0]
        self.assertIs(md["ok"], False)
        self.assertEqual(md["error"], "path not found")


if __name__ == "__main__":
    unittest.main()
