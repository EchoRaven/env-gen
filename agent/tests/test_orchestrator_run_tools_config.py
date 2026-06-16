"""Tests that orchestrator profile includes run_tools bundle (Cutover 11)."""

import unittest
from pathlib import Path

import yaml

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

CONFIG = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "agents" / "agents_config.yaml"


class OrchestratorRunToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG) as f:
            cls.cfg = yaml.safe_load(f)

    def test_orchestrator_has_run_tools_bundle(self) -> None:
        bundles = self.cfg["profiles"]["orchestrator"]["tool_bundles"]
        self.assertIn("run_tools", bundles)

    def test_orchestrator_tool_categories_include_run(self) -> None:
        cats = self.cfg["profiles"]["orchestrator"]["tool_categories"]
        self.assertIn("run", cats)
