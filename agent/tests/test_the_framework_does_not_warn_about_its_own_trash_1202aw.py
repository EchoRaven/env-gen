r"""#1202aw: the auto-stage guard must not warn about the framework's own scratch.

r32 logged 71 copies of

    auto-stage refused .openenv_trash/ for agent frontend: dotfile not in allowlist

`.openenv_trash/` is created by the framework itself — `file_tools` moves a deleted file
there instead of unlinking it — and it is written into the generated project's .gitignore.
Refusing to stage it is correct; announcing it is not, because there is nothing anyone can
do and nothing has gone wrong. A dotfile an AGENT authored is a different thing entirely
and keeps its warning, which is the distinction these tests pin.
"""
import logging
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime import auto_commit as ac  # noqa: E402


class FrameworkTrashTests(unittest.TestCase):
    def test_the_trash_is_still_refused(self):
        """Silence must not become permission."""
        self.assertFalse(ac._should_stage_path(".openenv_trash/old.jsx", "frontend"))
        self.assertFalse(ac._should_stage_path("app/.openenv_trash/x/y.py", "backend"))

    def test_the_trash_is_refused_without_a_warning(self):
        with self.assertNoLogs(ac._LOG, level="WARNING"):
            ac._should_stage_path(".openenv_trash/old.jsx", "frontend")

    def test_an_agent_authored_dotfile_still_warns(self):
        """The finding this guard exists for is unaffected."""
        with self.assertLogs(ac._LOG, level="WARNING") as caught:
            self.assertFalse(ac._should_stage_path(".gates/secret.json", "frontend"))
        self.assertTrue(any("dotfile not in allowlist" in m for m in caught.output))

    def test_ordinary_source_is_untouched(self):
        self.assertTrue(ac._should_stage_path("src/pages/GenresPage.jsx", "frontend"))


if __name__ == "__main__":
    unittest.main()
