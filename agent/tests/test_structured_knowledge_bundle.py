"""Tests for structured_knowledge_tools bundle registration."""

import sys
import unittest
from pathlib import Path

import yaml

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

CONFIG = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "agents" / "agents_config.yaml"


class StructuredKnowledgeBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG) as f:
            cls.cfg = yaml.safe_load(f)

    def test_knowledge_profile_has_structured_knowledge_tools_bundle(self) -> None:
        prof = self.cfg["profiles"]["knowledge"]
        self.assertIn("structured_knowledge_tools", prof.get("tool_bundles", []))

    def test_bundle_registry_has_entry(self) -> None:
        import importlib
        mod = importlib.import_module(
            "multi_agent.tool_bundles")
        self.assertIn("structured_knowledge_tools", mod.TOOL_BUNDLE_REGISTRY)
