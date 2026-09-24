"""End-to-end: backend profile's HubConsistencyPolicy actually blocks
finish() when registryhub_endpoints is empty after writing route files."""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.workflow_policies import (              # noqa: E402
    create_workflow_policies,
    HubConsistencyPolicy,
)


def _reset_event_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class TestBackendProfileBlocksFinishWithEmptyApihub(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_backend_finish_blocked_when_registryhub_empty(self):
        import yaml
        cfg_path = (
            Path(__file__).resolve().parents[1]
            / "env_generator" / "llm_generator"
            / "multi_agent" / "agents" / "agents_config.yaml"
        )
        cfg = yaml.safe_load(cfg_path.read_text())
        backend_cfg = cfg["profiles"]["backend"]
        policies = create_workflow_policies(backend_cfg)
        gate = next(p for p in policies if isinstance(p, HubConsistencyPolicy))

        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")

            class Stub:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _logger = MagicMock()
                def __init__(self):
                    self.workspace = MagicMock()
                    self.workspace.base_dir = Path(tmp)

            agent = Stub()
            messages = []
            outcome = asyncio.run(gate.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "backend done"},
                tool_call=MagicMock(),
                tool_call_id="tc1",
                messages=messages,
                files_created=[
                    "app/backend/src/routes/auth.js",
                    "app/backend/src/routes/posts.js",
                    "app/backend/src/routes/feed.js",
                ],
                files_modified=[
                    "app/backend/src/routes/users.js",
                    "app/backend/src/routes/social.js",
                    "app/backend/src/server.js",
                ],
            ))
            self.assertEqual(outcome, {"action": "continue"})
            block_text = str(messages[1].content)
            self.assertIn("registryhub_register_endpoint", block_text)
            self.assertIn("codehub_commit", block_text)


if __name__ == "__main__":
    unittest.main()
