"""build_available_skills_prompt now lists ALL workspace skills (Claude-Code-style catalog).

Previously the catalog only showed the agent's ``profile.skills`` allowlist.
Per request, the catalog must show every skill available in the workspace
so agents can discover skills outside their allowlist (and call ``get_skill``
to load the full body on demand). The profile.skills set is annotated as
the agent's **primary** skills; other workspace skills are listed as
**also available**.

Full text of any skill is NOT pre-injected — that's the ``get_skill`` tool's job.
"""
from __future__ import annotations

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


def _make_workspace_with_skills(workspace: Path, names: list[str]) -> None:
    """Materialize fake skills directly into the workspace's project-agent
    skill dir so ``discover_workspace_skills`` finds them without going
    through the bundled-skills sync (which would pull our real skills
    too and pollute the test)."""
    skill_dir = workspace / ".agents" / "skills"
    skill_dir.mkdir(parents=True, exist_ok=True)
    for n in names:
        d = skill_dir / n
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {n}\n"
            f"description: Test skill {n} description.\n"
            f"---\n\n# {n}\n\nBody of {n} for test purposes.\n"
        )


class TestCatalogAllWorkspaceSkills(unittest.TestCase):
    def test_catalog_lists_every_workspace_skill(self):
        from multi_agent.skill_loader import (
            discover_workspace_skills,
            build_available_skills_prompt,
        )
        # Use an env var to disable the bundled-skills sync side effect so we
        # only see the test skills we explicitly materialize.
        import os
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            _make_workspace_with_skills(ws, ["alpha-skill", "beta-skill", "gamma-skill"])
            # Pin global skills dir to an empty path to keep this test isolated.
            os.environ["ENV_GEN_GLOBAL_SKILLS_DIR"] = str(ws / "_empty_global")
            try:
                skills = list(discover_workspace_skills(ws).values())
                # build_available_skills_prompt must surface every skill the
                # workspace knows about, not just an allowlist.
                # (We exercise the NEW signature: (all_skills, primary_names))
                prompt = build_available_skills_prompt(
                    skills,
                    primary_names=["alpha-skill"],
                )
                # All three names appear
                self.assertIn("alpha-skill", prompt)
                self.assertIn("beta-skill", prompt)
                self.assertIn("gamma-skill", prompt)
                # Descriptions appear too
                self.assertIn("Test skill alpha-skill description.", prompt)
                self.assertIn("Test skill beta-skill description.", prompt)
                # Primary annotation present for alpha-skill
                lower = prompt.lower()
                self.assertTrue(
                    "primary" in lower or "your" in lower,
                    f"expected primary-skill annotation in prompt; got: {prompt!r}",
                )
                # Bodies are NOT injected (full text stays behind get_skill)
                self.assertNotIn("Body of alpha-skill for test purposes.", prompt)
                self.assertNotIn("Body of beta-skill for test purposes.", prompt)
            finally:
                os.environ.pop("ENV_GEN_GLOBAL_SKILLS_DIR", None)

    def test_empty_skills_yields_empty_string(self):
        from multi_agent.skill_loader import build_available_skills_prompt
        self.assertEqual(build_available_skills_prompt([], primary_names=[]), "")

    def test_no_primary_still_lists_all(self):
        from multi_agent.skill_loader import (
            discover_workspace_skills,
            build_available_skills_prompt,
        )
        import os
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            _make_workspace_with_skills(ws, ["foo", "bar"])
            os.environ["ENV_GEN_GLOBAL_SKILLS_DIR"] = str(ws / "_empty_global")
            try:
                skills = list(discover_workspace_skills(ws).values())
                prompt = build_available_skills_prompt(skills, primary_names=None)
                self.assertIn("foo", prompt)
                self.assertIn("bar", prompt)
            finally:
                os.environ.pop("ENV_GEN_GLOBAL_SKILLS_DIR", None)


if __name__ == "__main__":
    unittest.main()
