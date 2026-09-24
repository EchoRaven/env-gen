"""L1 — primary skills are mandatory-to-consult in the catalog preamble.

Per docs/superpowers/plans/2026-06-03-skill-mandatory-trigger.md Task 2.
Strengthens build_available_skills_prompt so the PRIMARY section frames
skills as mandatory operating procedures + anti-rationalization red flags
(the env-gen analog of Claude Code's "must trigger" discipline).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _build():
    from multi_agent.skill_loader import build_available_skills_prompt, SkillDefinition
    skills = [
        SkillDefinition(name="api-contract-guard", description="d-acg",
                        file_path="p1", source="x", instructions="BODY-ACG"),
        SkillDefinition(name="ui-bootstrap", description="d-ui",
                        file_path="p2", source="x", instructions="BODY-UI"),
    ]
    return build_available_skills_prompt(skills, primary_names=["api-contract-guard"])


class PrimarySkillsMandatory(unittest.TestCase):
    def test_preamble_makes_primary_mandatory(self):
        low = _build().lower()
        self.assertIn("must", low)
        self.assertIn("mandatory", low)

    def test_has_anti_rationalization_red_flags(self):
        low = _build().lower()
        self.assertTrue(
            any(k in low for k in ["red flag", "do not", "rationaliz"]),
            f"expected anti-rationalization cue; got: {low!r}",
        )

    def test_still_lists_skills_and_hides_bodies(self):
        p = _build()
        self.assertIn("api-contract-guard", p)
        self.assertIn("ui-bootstrap", p)
        self.assertNotIn("BODY-ACG", p)
        self.assertNotIn("BODY-UI", p)

    def test_empty_returns_empty(self):
        from multi_agent.skill_loader import build_available_skills_prompt
        self.assertEqual(build_available_skills_prompt([], primary_names=[]), "")


if __name__ == "__main__":
    unittest.main()
