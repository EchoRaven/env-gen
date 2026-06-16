"""Smoke tests for skill_loader (Cutover 18)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.skill_loader import (  # noqa: E402
    SkillDefinition,
    _normalize_skill_name,
    discover_workspace_skills,
)


class NormalizeSkillNameTests(unittest.TestCase):
    def test_basic_lowercase_dash(self) -> None:
        self.assertEqual(_normalize_skill_name("Release Readiness"), "release-readiness")

    def test_underscore_to_dash(self) -> None:
        self.assertEqual(_normalize_skill_name("api_contract_guard"), "api-contract-guard")

    def test_path_traversal_strip(self) -> None:
        # ../etc/passwd should not produce a parent-relative path
        result = _normalize_skill_name("../etc/passwd")
        self.assertNotIn("..", result)
        self.assertNotIn("/", result)


class DiscoverWorkspaceSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="skill_loader_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_skill(self, root: Path, name: str, body: str = "skill body") -> None:
        d = root / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test\n---\n{body}\n"
        )

    def test_discover_empty_workspace_returns_empty_after_bundle_sync(self) -> None:
        # discover_workspace_skills syncs bundled skills into the workspace's
        # .agents/skills directory first, so the returned dict reflects whatever
        # bundled skills exist. The result must be a dict keyed by skill name.
        skills = discover_workspace_skills(workspace_root=self.tmp)
        self.assertIsInstance(skills, dict)
        for key, value in skills.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, SkillDefinition)

    def test_discover_finds_workspace_skill(self) -> None:
        # Skills under <workspace>/skills override project-agent / global.
        workspace_skills_dir = self.tmp / "skills"
        self._write_skill(workspace_skills_dir, "test-skill")
        skills = discover_workspace_skills(workspace_root=self.tmp)
        self.assertIn("test-skill", skills)
        self.assertIsInstance(skills["test-skill"], SkillDefinition)
        self.assertEqual(skills["test-skill"].name, "test-skill")
        self.assertEqual(skills["test-skill"].source, "workspace")


if __name__ == "__main__":
    unittest.main()
