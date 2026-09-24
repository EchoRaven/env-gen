"""Tests that agents_config.yaml has the debugger profile wired correctly."""

import unittest
from pathlib import Path

import yaml

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

CONFIG_PATH = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent"
    / "agents" / "agents_config.yaml"
)


class DebuggerProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG_PATH) as f:
            cls.cfg = yaml.safe_load(f)

    def test_profile_exists(self) -> None:
        self.assertIn("debugger", self.cfg.get("profiles", {}))

    def test_profile_has_bug_tools_bundle(self) -> None:
        prof = self.cfg["profiles"]["debugger"]
        self.assertIn("bug_tools", prof.get("tool_bundles", []))

    def test_profile_has_workhub_registryhub_codehub_eventhub_tools(self) -> None:
        prof = self.cfg["profiles"]["debugger"]
        bundles = set(prof.get("tool_bundles", []))
        for required in ("workhub_tools", "registryhub_tools",
                          "codehub_tools", "eventhub_tools"):
            self.assertIn(required, bundles)

    def test_profile_pipeline_starts_with_hub_pulse_ends_with_commit_gate(self) -> None:
        prof = self.cfg["profiles"]["debugger"]
        stages = prof.get("execution_pipeline", {}).get("stages", [])
        self.assertGreater(len(stages), 0)
        self.assertEqual(stages[0], "hub_pulse")
        self.assertIn("hub_commit_gate", stages)

    def test_profile_uses_dedicated_prompt(self) -> None:
        prof = self.cfg["profiles"]["debugger"]
        template = (prof.get("prompts") or {}).get("template", "")
        self.assertTrue(template.endswith("debugger_agent.j2"))

    def test_profile_is_coordinator_but_cannot_deliver(self) -> None:
        prof = self.cfg["profiles"]["debugger"]
        flags = prof.get("flags", {}) or {}
        self.assertTrue(flags.get("coordinator"))
        self.assertFalse(flags.get("can_deliver", False))

    def test_max_tool_calls_per_stage_caps_action(self) -> None:
        prof = self.cfg["profiles"]["debugger"]
        caps = prof.get("execution_pipeline", {}).get("max_tool_calls_per_stage", {})
        # bug triage should be allowed multiple tool calls per step (read + triage + dispatch)
        self.assertGreaterEqual(caps.get("action", 0), 5)


if __name__ == "__main__":
    unittest.main()
