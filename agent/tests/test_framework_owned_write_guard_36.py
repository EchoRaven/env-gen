"""PROPOSAL #36 CLASS B — framework-owned-file write guard.

Run #34: the backend lane wrote a broken `apt-get install libpq-dev gcc` into the
framework-owned `app/backend/Dockerfile` (in its own worktree, where it otherwise owns
everything) → broke the build + created the merge conflict that wedged validation. The
framework deterministically generates + overwrites these files from the registered
contract, so a lane edit can never stick — deny it.

This pins: framework-owned files (Dockerfile/main.py/models.py/… backend; vite.config.js/
main.jsx/Dockerfile/… frontend) are DENIED to a lane even inside its own worktree, while the
lane-owned files (custom_routes.py / App.jsx) and lane-authored pages stay writable. The
deny-set is the SAME canonical ownership map the conflict resolver uses.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402


class FrameworkOwnedWriteGuard(unittest.TestCase):
    def _ws(self, tmp: Path, lane: str) -> PathRoutedWorkspace:
        base = tmp
        code = base / "worktrees" / lane
        code.mkdir(parents=True)
        return PathRoutedWorkspace(base_root=base, code_root=code)

    def test_backend_cannot_write_framework_owned_files_in_its_worktree(self):
        with tempfile.TemporaryDirectory() as t:
            ws = self._ws(Path(t), "backend")
            for owned in ("app/backend/Dockerfile", "app/backend/main.py",
                          "app/backend/models.py", "app/backend/schemas.py",
                          "app/backend/pyproject.toml", "app/backend/database.py"):
                self.assertTrue(ws.is_framework_owned(owned), owned)
                self.assertFalse(ws.is_write_allowed(owned, "backend"),
                                 f"backend must NOT write framework-owned {owned}")

    def test_backend_CAN_write_its_lane_owned_surface(self):
        with tempfile.TemporaryDirectory() as t:
            ws = self._ws(Path(t), "backend")
            self.assertFalse(ws.is_framework_owned("app/backend/custom_routes.py"))
            self.assertTrue(ws.is_write_allowed("app/backend/custom_routes.py", "backend"),
                            "backend MUST be able to author custom_routes.py")

    def test_frontend_guard_keeps_pages_and_appjsx_writable(self):
        with tempfile.TemporaryDirectory() as t:
            ws = self._ws(Path(t), "frontend")
            # framework-owned frontend build/infra → denied
            for owned in ("app/frontend/vite.config.js", "app/frontend/src/main.jsx",
                          "app/frontend/Dockerfile", "app/frontend/package.json"):
                self.assertTrue(ws.is_framework_owned(owned), owned)
                self.assertFalse(ws.is_write_allowed(owned, "frontend"), owned)
            # lane-authored UI → allowed
            for ok in ("app/frontend/src/App.jsx", "app/frontend/src/pages/Notes.jsx",
                       "app/frontend/src/api.js"):
                self.assertFalse(ws.is_framework_owned(ok), ok)
                self.assertTrue(ws.is_write_allowed(ok, "frontend"), ok)

    def test_guard_uses_the_conflict_resolvers_ownership_map(self):
        # single source of truth: the guard's deny-set IS the resolver's _OWNERSHIP
        from multi_agent.agents.runtime.auto_commit import (
            _BACKEND_FRAMEWORK_OWNED, _FRONTEND_FRAMEWORK_OWNED)
        with tempfile.TemporaryDirectory() as t:
            ws = self._ws(Path(t), "backend")
            for b in _BACKEND_FRAMEWORK_OWNED:
                self.assertTrue(ws.is_framework_owned(f"app/backend/{b}"), b)
            for b in _FRONTEND_FRAMEWORK_OWNED:
                self.assertTrue(ws.is_framework_owned(f"app/frontend/{b}"), b)


if __name__ == "__main__":
    unittest.main()
