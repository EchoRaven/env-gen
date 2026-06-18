"""PROPOSAL #6 Part B: `glob` must honor its own docstring.

GlobTool.DESCRIPTION's first example is `glob "*.py"  # Python files in current
dir` — i.e. NO `path` argument. But the resolver rejected an empty path with
`glob: path is required`, so an agent that followed the tool's own docs got an
error and fell back to GUESSING a path. The fix: an empty/absent `path` searches
the workspace ROOT. An EXPLICIT non-existent path must still error (with the
existing not-found hint) — that signal is correct and helps locate the real path.
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from workspace import Workspace  # noqa: E402
from tools.file_tools import GlobTool  # noqa: E402


class GlobNoPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="glob_nopath_")
        root = Path(self.tmp)
        (root / "a.py").write_text("x = 1\n")
        (root / "sub").mkdir()
        (root / "sub" / "b.py").write_text("y = 2\n")
        self.ws = Workspace(root=str(root))
        self.tool = GlobTool(workspace=self.ws)

    def test_no_path_searches_workspace_root(self):
        # `glob "*.py"` with no path → searches the workspace root (per docstring).
        r = self.tool.execute(pattern="*.py")
        self.assertTrue(r.success, r.error_message)
        self.assertIn("a.py", str(r.data))

    def test_empty_string_path_also_searches_root(self):
        r = self.tool.execute(pattern="*.py", path="")
        self.assertTrue(r.success, r.error_message)
        self.assertIn("a.py", str(r.data))

    def test_recursive_no_path(self):
        r = self.tool.execute(pattern="**/*.py")
        self.assertTrue(r.success, r.error_message)
        self.assertIn("b.py", str(r.data))

    def test_explicit_bad_path_still_errors_with_hint(self):
        # An EXPLICIT non-existent directory must still error — that signal is
        # correct (and carries the "nearest existing dir" locate hint).
        r = self.tool.execute(pattern="*.py", path="does/not/exist")
        self.assertFalse(r.success)
        self.assertIn("not found", (r.error_message or ""))

    def test_explicit_good_path_unchanged(self):
        r = self.tool.execute(pattern="*.py", path="sub")
        self.assertTrue(r.success, r.error_message)
        self.assertIn("b.py", str(r.data))


if __name__ == "__main__":
    unittest.main()
