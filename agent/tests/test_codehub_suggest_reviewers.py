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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class SuggestReviewersTests(unittest.TestCase):
    def _setup(self, td):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        return hubs, ch

    def test_suggest_reviewers_always_includes_orchestrator(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup(td)
            result = ch.suggest_reviewers(
                branch="agent/backend",
                linked_apis=[], linked_tasks=[], author="backend",
            )
            agents = [s["agent"] for s in result]
            self.assertIn("orchestrator", agents)

    def test_suggest_reviewers_excludes_author(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup(td)
            result = ch.suggest_reviewers(
                branch="agent/backend",
                linked_apis=[], linked_tasks=[], author="orchestrator",
            )
            agents = [s["agent"] for s in result]
            self.assertNotIn("orchestrator", agents)

    def test_suggest_reviewers_weights_api_consumers(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            hubs.registryhub.register_endpoint("GET", "/api/feed", schema={},
                                          provider="backend", agent="backend")
            hubs.registryhub.register_consumer("GET /api/feed",
                                          "src/Feed.jsx", "frontend")
            result = ch.suggest_reviewers(
                branch="agent/backend",
                linked_apis=["GET /api/feed"],
                linked_tasks=[],
                author="backend",
            )
            # frontend should be high-scored as consumer
            agents = [s["agent"] for s in result]
            self.assertIn("frontend", agents)
            # orchestrator is always first (mandatory)
            self.assertEqual(agents[0], "orchestrator")
            self.assertEqual(result[0]["score"], 100.0)

    def test_suggest_reviewers_reasons_explained(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            hubs.registryhub.register_endpoint("GET", "/api/feed", schema={},
                                          provider="backend", agent="backend")
            hubs.registryhub.register_consumer("GET /api/feed",
                                          "src/Feed.jsx", "frontend")
            result = ch.suggest_reviewers(
                branch="agent/backend",
                linked_apis=["GET /api/feed"],
                linked_tasks=[],
                author="backend",
            )
            frontend_entry = next(s for s in result if s["agent"] == "frontend")
            self.assertTrue(any("consumer of GET /api/feed" in r
                                for r in frontend_entry["reasons"]))


if __name__ == "__main__":
    unittest.main()
