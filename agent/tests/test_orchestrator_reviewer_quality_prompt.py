"""Tests that the orchestrator prompt teaches the NO-PR-review-ceremony posture.

The PR review/merge workflow was removed (2026-06-10, user-approved): delivery
goes through the integration merge + runtime validation gates. These tests pin
that the prompt states the new posture and no longer references the removed tools."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class OrchestratorReviewerQualityPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        for name in ("lead_specifics", "orchestrator_specifics"):
            if hasattr(mod, name):
                cls.system = getattr(mod, name)()
                break
        else:
            raise RuntimeError("could not find orchestrator specifics macro")

    def test_prompt_states_no_pr_review_ceremony(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "NO PR REVIEW" in upper or "NO PR-REVIEW" in upper,
            "prompt must state there is no PR review/merge workflow",
        )

    def test_prompt_does_not_reference_removed_review_tools(self) -> None:
        for name in ("codehub_review_pr", "codehub_merge_pr",
                     "registryhub_request_review", "registryhub_submit_review"):
            self.assertNotIn(name, self.system)

    def test_prompt_says_quality_enforced_by_gates(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "VALIDATION GATE" in upper or "GATES" in upper,
            "prompt must point quality enforcement at the runtime gates",
        )


if __name__ == "__main__":
    unittest.main()
