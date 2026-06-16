"""Tests that the verifier prompt now forbids direct bug-task creation and requires
publishing bug_found events."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_DIR = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent"
    / "prompts" / "v3"
)
PROMPTS_PARENT_DIR = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts"
)


class VerifierBugPublishPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([
            str(PROMPTS_DIR), str(PROMPTS_PARENT_DIR)
        ]))
        tpl = env.get_template("verifier_agent.j2")
        mod = tpl.make_module()
        # Try the standard macro name first; fall back to a probe if the name differs.
        for candidate in ("verifier_specifics", "verifier_system_prompt"):
            if hasattr(mod, candidate):
                cls.system = getattr(mod, candidate)()
                break
        else:
            raise RuntimeError("could not find a verifier specifics/system macro")

    def test_prompt_mentions_bug_create_or_bug_found(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "BUG_CREATE" in upper or "BUG_FOUND" in upper,
            "verifier prompt must reference the new bug reporting tool/event",
        )

    def test_prompt_forbids_direct_remediation_task_creation(self) -> None:
        upper = self.system.upper()
        # Either explicit "do not assign" or "do not create task" or "find only".
        self.assertTrue(
            any(phrase in upper for phrase in (
                "DO NOT ASSIGN",
                "DO NOT CREATE",
                "MUST NOT ASSIGN",
                "MUST NOT CREATE",
                "FIND ONLY",
                "DETECTION ONLY",
                "DETECT ONLY",
            )),
            "verifier prompt must explicitly forbid bug-fix assignment",
        )

    def test_prompt_references_bug_triage_orchestrator(self) -> None:
        upper = self.system.upper()
        self.assertIn("BUG TRIAGE", upper)


if __name__ == "__main__":
    unittest.main()
