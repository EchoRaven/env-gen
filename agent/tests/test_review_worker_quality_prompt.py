"""Tests that review_worker prompt teaches the substantive-review contract."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class ReviewWorkerQualityPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("review_worker_agent.j2")
        mod = tpl.make_module()
        # Macro name may vary; try common patterns
        for name in ("review_worker_specifics", "reviewer_specifics",
                     "review_worker_system_prompt"):
            if hasattr(mod, name):
                macro = getattr(mod, name)
                try:
                    cls.system = macro()
                except TypeError:
                    # Macro requires args
                    cls.system = macro(".", "")
                break
        else:
            raise RuntimeError("could not find review_worker specifics macro")

    def test_prompt_mentions_inline_comments_requirement(self) -> None:
        self.assertIn("INLINE", self.system.upper())

    def test_prompt_mentions_considered_alternatives_requirement(self) -> None:
        # the report channel is send_message now; accept the prose form too
        self.assertIn("CONSIDERED ALTERNATIVE", self.system.upper().replace("_", " "))

    def test_prompt_forbids_lgtm_only_approvals(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "LGTM" in upper or "EMPTY APPROVE" in upper or "RUBBER STAMP" in upper
            or "RUBBER-STAMP" in upper or "LOOKS GOOD' ALONE" in upper,
            "prompt must explicitly warn against rubber-stamp approvals",
        )

    def test_prompt_specifies_at_least_one(self) -> None:
        # Reinforce the "MUST have >=1" cardinality (accept Unicode ≥ variant)
        upper = self.system.upper()
        self.assertTrue(
            "AT LEAST ONE" in upper or ">=1" in upper or "AT LEAST 1" in upper
            or "≥1" in self.system,
            "prompt must specify >=1 inline_comment/considered_alternative",
        )


if __name__ == "__main__":
    unittest.main()
