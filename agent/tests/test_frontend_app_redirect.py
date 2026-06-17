"""Guard: the frontend lane's bare Vite-app paths route under app/frontend/.

Root of the recurring frontend saga: the frontend authors a Vite app at the repo
root (src/App.jsx, package.json, …); those bare paths fell to the worktree-root
default, so the canonical app/frontend/ stayed a blank shell AND the wrong-root
src/App.jsx collided with integration's as an add/add merge conflict that wedged
the whole run (run #7). The router now redirects them. Only the frontend lane;
only bare paths; never app/-prefixed or shared/design/dotfiles; other lanes
unaffected.
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402


def _ws(lane: str):
    base = Path(tempfile.mkdtemp(prefix="prw_"))
    code = base / "worktrees" / lane
    code.mkdir(parents=True)
    return PathRoutedWorkspace(base_root=base, code_root=code, agent_id=lane)


class FrontendRedirectTests(unittest.TestCase):
    def test_bare_src_routes_into_app_frontend(self):
        ws = _ws("frontend")
        r = ws.resolve("src/App.jsx")
        self.assertTrue(str(r).endswith("worktrees/frontend/app/frontend/src/App.jsx"), str(r))

    def test_bare_vite_config_files_route(self):
        ws = _ws("frontend")
        for f in ("package.json", "index.html", "vite.config.js", "tailwind.config.js", "Dockerfile"):
            r = ws.resolve(f)
            self.assertTrue(str(r).endswith(f"app/frontend/{f}"), str(r))

    def test_already_canonical_path_untouched(self):
        ws = _ws("frontend")
        r = ws.resolve("app/frontend/src/App.jsx")
        self.assertTrue(str(r).endswith("app/frontend/src/App.jsx"), str(r))
        self.assertNotIn("app/frontend/app/frontend", str(r))  # no double-prefix

    def test_non_app_paths_not_redirected(self):
        ws = _ws("frontend")
        # design/shared/dotfiles + non-vite names must NOT be pulled under app/frontend
        for p in ("design/spec.json", "shared/x", ".memory/note", "notes.txt"):
            self.assertNotIn("app/frontend/" + p, str(ws.resolve(p)))

    def test_backend_lane_unaffected(self):
        ws = _ws("backend")
        r = ws.resolve("src/App.jsx")  # backend never gets the frontend redirect
        self.assertNotIn("app/frontend", str(r))


if __name__ == "__main__":
    unittest.main()
