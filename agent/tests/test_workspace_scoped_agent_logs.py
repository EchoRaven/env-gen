"""Per-workspace .agent_logs/ resolution (Action History fix).

History before this fix: agents wrote to a CWD-relative ``.agent_logs/`` while
the monitor read from a hardcoded ``env-gen/agent/.agent_logs/``. Path
mismatch → the UI showed stale tool calls from an unrelated prior run that
happened to leave files in the monitor-side path.

After: each workspace gets its own ``<workspace>/.agent_logs/`` directory;
the monitor resolves the log root per project via the workspace path. The
legacy host-wide path stays as a fallback so older runs still surface.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


def _seed_tool_call_log(log_root: Path, agent_dir_name: str, ts: str, calls: list[dict]) -> Path:
    """Write a minimal jsonl that ``_load_recent_tool_calls`` will accept."""
    d = log_root / agent_dir_name
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{ts}.jsonl"
    with f.open("w") as fp:
        for call in calls:
            fp.write(json.dumps({
                "event_type": "tool_call",
                "timestamp": call["timestamp"],
                "content": f"{call['tool']}({json.dumps(call.get('args', {}))})",
                "metadata": {"result": call.get("result", "ok")},
            }) + "\n")
    return f


class TestWorkspaceScopedAgentLogs(unittest.TestCase):
    def test_workspace_scoped_log_root_preferred_over_host_root(self):
        from live_monitor_server import _agent_log_root_for, AGENT_LOG_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / ".agent_logs").mkdir()
            self.assertEqual(
                _agent_log_root_for(workspace).resolve(),
                (workspace / ".agent_logs").resolve(),
            )

    def test_falls_back_to_host_root_when_workspace_missing_agent_logs(self):
        from live_monitor_server import _agent_log_root_for, AGENT_LOG_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            # workspace exists but has no .agent_logs/ — use host root
            self.assertEqual(_agent_log_root_for(Path(tmp)), AGENT_LOG_ROOT)

    def test_falls_back_to_host_root_when_no_workspace_passed(self):
        from live_monitor_server import _agent_log_root_for, AGENT_LOG_ROOT
        self.assertEqual(_agent_log_root_for(None), AGENT_LOG_ROOT)

    def test_closest_agent_log_honors_log_root_param(self):
        from live_monitor_server import _closest_agent_log, AGENT_LOG_DIRS
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_dir = AGENT_LOG_DIRS["design"]  # "Design Agent"
            ws_file = _seed_tool_call_log(
                root, agent_dir, "20260528_020000",
                [{"timestamp": "2026-05-28T02:00:00", "tool": "read", "args": {"path": "x"}}],
            )
            picked = _closest_agent_log("design", None, log_root=root)
            self.assertEqual(picked.resolve(), ws_file.resolve())

    def test_build_state_reads_workspace_logs_not_host_logs(self):
        """End-to-end: build_state should surface tool_calls from the project's
        own ``.agent_logs/`` rather than the host-wide legacy path."""
        from live_monitor_server import build_state, AGENT_LOG_DIRS
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            # Mandatory bits build_state pokes at without crashing.
            (workspace / "logs").mkdir(parents=True, exist_ok=True)
            agent_dir = AGENT_LOG_DIRS["design"]
            _seed_tool_call_log(
                workspace / ".agent_logs", agent_dir, "20260528_020000",
                [
                    {"timestamp": "2026-05-28T02:00:01", "tool": "read",
                     "args": {"file_path": "design/spec.api.json"}},
                    {"timestamp": "2026-05-28T02:00:02", "tool": "write",
                     "args": {"file_path": "design/spec.api.json"}},
                ],
            )
            state = build_state(workspace)
            tools = state.get("toolCalls", [])
            names = [c.get("toolName") for c in tools]
            self.assertIn("read", names)
            self.assertIn("write", names)
            # Confirm they're sourced from THIS workspace's log (not the host one)
            # by checking the args we just seeded.
            args_blob = " ".join(json.dumps(c.get("args", {})) for c in tools)
            self.assertIn("design/spec.api.json", args_blob)


if __name__ == "__main__":
    unittest.main()
