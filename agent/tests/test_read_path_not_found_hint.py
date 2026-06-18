"""Guard: a failed read/resolve points at what ACTUALLY exists.

Agents guess conventional file layouts (e.g. app/backend/models.py) that a given
generated project may not use. A bare "path not found" makes them re-guess and
burn rounds. The resolver now appends the nearest existing directory's contents
and a closest-name suggestion. Domain-agnostic (no project-specific names baked
into the framework).
"""

import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from workspace import Workspace  # noqa: E402
from tools.file_tools import _resolve_workspace_path  # noqa: E402


class PathNotFoundHintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pnfh_"))
        self.ws = Workspace(self.tmp)
        # A backend layout WITHOUT a models.py (mirrors the real generated tree).
        be = self.tmp / "app" / "backend"
        be.mkdir(parents=True)
        for f in ("main.py", "oauth_routes.py", "jwt_manager.py"):
            (be / f).write_text("# x\n")
        (be / "src").mkdir()

    def test_hint_lists_actual_dir_contents(self):
        _, err = _resolve_workspace_path(self.ws, "app/backend/models.py", op_name="read", must_exist=True)
        self.assertIsNotNone(err)
        self.assertIn("path not found", err)
        # It names the nearest existing dir and what's really there.
        self.assertIn("app/backend", err)
        self.assertIn("main.py", err)
        self.assertIn("src/", err)            # directories flagged with a trailing slash
        self.assertNotIn("models.py", err.split("contains:")[1])  # the missing file isn't invented

    def test_close_name_suggestion(self):
        # A near-miss filename gets a "did you mean" pointer.
        _, err = _resolve_workspace_path(self.ws, "app/backend/main.pyy", op_name="read", must_exist=True)
        self.assertIn("did you mean 'main.py'", err)

    def test_climbs_to_nearest_existing_ancestor(self):
        # Several missing segments → climbs to the nearest dir that exists (root).
        _, err = _resolve_workspace_path(self.ws, "backend/src/index.js", op_name="read", must_exist=True)
        self.assertIn("path not found", err)
        self.assertIn("app/", err)            # root listing shows the real top-level (app/), not 'backend/'

    def test_no_hint_when_path_exists(self):
        resolved, err = _resolve_workspace_path(self.ws, "app/backend/main.py", op_name="read", must_exist=True)
        self.assertIsNone(err)
        self.assertTrue(str(resolved).endswith("app/backend/main.py"))

    def test_hint_never_raises_and_stays_in_workspace(self):
        # Even a deep nonexistent path produces a string error, no traceback.
        _, err = _resolve_workspace_path(self.ws, "a/b/c/d/e.py", op_name="read", must_exist=True)
        self.assertIsInstance(err, str)
        self.assertNotIn(str(self.tmp.parent), err)  # no absolute paths outside the workspace leak


if __name__ == "__main__":
    unittest.main()
