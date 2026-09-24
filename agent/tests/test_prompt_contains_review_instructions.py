"""Verifier prompt must instruct using codehub_get_file_content for
cross-agent code review (not bare `read()`). Backend prompt must
instruct registryhub_list_endpoints + registryhub_register_consumer when
building / consuming APIs."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


def _load(prompt_name: str) -> str:
    p = LLM_DIR / "multi_agent" / "prompts" / "v3" / prompt_name
    return p.read_text()


class TestVerifierUsesCodeHubForReview(unittest.TestCase):
    def test_verifier_prompt_mentions_codehub_get_file_content(self):
        text = _load("verifier_agent.j2")
        self.assertIn("codehub_get_file_content", text,
                      "verifier_agent.j2 must instruct using codehub_get_file_content "
                      "for branch-scoped file reads during review")

    def test_verifier_prompt_mentions_codehub_get_diff(self):
        text = _load("verifier_agent.j2")
        self.assertIn("codehub_get_diff", text,
                      "verifier_agent.j2 must instruct using codehub_get_diff for PR review")


class TestBackendDiscoverabilityAndConsumerDeclaration(unittest.TestCase):
    def test_backend_prompt_tells_agent_to_list_endpoints_first(self):
        text = _load("backend_agent.j2")
        self.assertIn("registryhub_list_endpoints", text,
                      "backend_agent.j2 must instruct calling registryhub_list_endpoints "
                      "before building a new endpoint (reuse over reimplement)")

    def test_backend_prompt_tells_agent_to_register_as_consumer(self):
        text = _load("backend_agent.j2")
        self.assertIn("registryhub_register_consumer", text,
                      "backend_agent.j2 must instruct calling registryhub_register_consumer "
                      "when the new endpoint uses another agent's API")


class TestBackendReadsReviewInlineComments(unittest.TestCase):
    def test_backend_prompt_tells_agent_to_read_inline_comments_on_issue(self):
        text = _load("backend_agent.j2")
        self.assertIn("codehub_list_inline_comments", text,
                      "backend_agent.j2 must instruct calling "
                      "codehub_list_inline_comments after receiving an "
                      "issue / review-request — otherwise the agent fixes "
                      "the wrong line.")


class TestOrchestratorHandlesMergeConflict(unittest.TestCase):
    def test_orchestrator_prompt_mentions_resolve_merge_conflict_tool(self):
        text = _load("orchestrator_agent.j2")
        self.assertIn("merge_conflict", text,
                      "orchestrator_agent.j2 must instruct handling merge_conflict events")
        self.assertIn("codehub_resolve_merge_conflict", text,
                      "orchestrator_agent.j2 must instruct calling "
                      "codehub_resolve_merge_conflict to handle conflicts")
        self.assertIn("strategy=", text,
                      "orchestrator_agent.j2 must explain the strategy options "
                      "for codehub_resolve_merge_conflict")


if __name__ == "__main__":
    unittest.main()
