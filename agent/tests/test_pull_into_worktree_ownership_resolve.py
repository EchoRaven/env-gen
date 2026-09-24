"""PROPOSAL #23 — ownership-partitioned resolution on the step-start PULL path.

#22 fixed the framework-owned-file conflict on the lane→integration MERGE
(merge_agent_branch_to_main). The SAME class recurs on the step-start PULL
(pull_main_into_worktree: `git merge integration` INTO the lane worktree, every step),
which aborted on conflict and wedged the lanes (smoke-notes run #2: 10+ pull-conflict
aborts, no delivery).

Fix #23 (reviewer-prescribed): a shared, DIRECTION-AWARE ownership resolver. On the
PULL the worktree has the lane's branch checked out, so framework files = `--theirs`
(integration) and lane files = `--ours` — the REVERSE of the merge path. Per-lane map:
backend main.py→framework / custom_routes.py→lane; frontend App.jsx→LANE (#19 re-projects
routes) / main.jsx+vite.config.js+infra→framework. Unknown path → still abort.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.agents.runtime.auto_commit import (  # noqa: E402
    pull_main_into_worktree, _resolve_conflict_by_ownership)


def _git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)


def _w(repo, rel, content):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _commit(repo, msg):
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", msg)


def _setup(lane, files_base, files_lane, files_integration):
    """repo with integration + a worktree checked out to agent/<lane>, both diverged.
    Returns (repo, worktree_path)."""
    repo = tempfile.mkdtemp(prefix=f"p23_{lane}_repo_")
    _git(repo, "init", "-q"); _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "integration")
    for rel, c in files_base.items():
        _w(repo, rel, c)
    _commit(repo, "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # agent/<lane> from base, with the lane's edits
    _git(repo, "checkout", "-q", "-b", f"agent/{lane}", base)
    for rel, c in files_lane.items():
        _w(repo, rel, c)
    _commit(repo, "lane")
    # integration advances with framework edits
    _git(repo, "checkout", "-q", "integration")
    for rel, c in files_integration.items():
        _w(repo, rel, c)
    _commit(repo, "framework")
    # worktree checked out to agent/<lane>
    wt = tempfile.mkdtemp(prefix=f"p23_{lane}_wt_")
    Path(wt).rmdir()  # git worktree add wants a non-existent path
    _git(repo, "worktree", "add", "-q", wt, f"agent/{lane}")
    return repo, wt


class BackendPull(unittest.TestCase):
    def test_main_py_to_integration_custom_routes_to_lane(self):
        repo, wt = _setup(
            "backend",
            {"app/backend/main.py": "# BASE\n@app.get('/health')\ndef h(): ...\n"},
            {"app/backend/main.py": "# LANE main\n@app.get('/notes')\ndef lane(): ...\n",
             "app/backend/custom_routes.py": "# LANE custom — REAL logic\ndef create(): ...\n"},
            {"app/backend/main.py": "# FRAMEWORK skeleton main\n@app.get('/api/notes')\ndef fw(): ...\n",
             "app/backend/custom_routes.py": "# stale\nSTALE=1\n"},
        )
        ok, info = pull_main_into_worktree(worktree_dir=wt, main_branch="integration")
        self.assertTrue(ok, f"pull should resolve, not abort: {info}")
        main = (Path(wt) / "app/backend/main.py").read_text()
        custom = (Path(wt) / "app/backend/custom_routes.py").read_text()
        # PULL direction: framework files → --theirs (INTEGRATION) ...
        self.assertIn("FRAMEWORK skeleton", main)
        self.assertNotIn("LANE main", main)
        # ... lane files → --ours (LANE)
        self.assertIn("REAL logic", custom)
        self.assertNotIn("stale", custom)
        self.assertNotIn("<<<<<<<", main + custom)


class FrontendPull(unittest.TestCase):
    def test_app_jsx_to_lane_main_jsx_to_integration(self):
        repo, wt = _setup(
            "frontend",
            {"app/frontend/src/App.jsx": "// BASE app\n", "app/frontend/src/main.jsx": "// BASE main\n"},
            {"app/frontend/src/App.jsx": "// LANE App — authored pages\n",
             "app/frontend/src/main.jsx": "// LANE main edit\n"},
            {"app/frontend/src/App.jsx": "// FRAMEWORK App\n",
             "app/frontend/src/main.jsx": "// FRAMEWORK main (pinned)\n"},
        )
        ok, info = pull_main_into_worktree(worktree_dir=wt, main_branch="integration")
        self.assertTrue(ok, f"pull should resolve, not abort: {info}")
        appjsx = (Path(wt) / "app/frontend/src/App.jsx").read_text()
        mainjsx = (Path(wt) / "app/frontend/src/main.jsx").read_text()
        # App.jsx → LANE (--ours): the lane authors it; #19 re-projects routes downstream
        self.assertIn("LANE App", appjsx)
        self.assertNotIn("FRAMEWORK App", appjsx)
        # main.jsx (framework-pinned) → INTEGRATION (--theirs)
        self.assertIn("FRAMEWORK main", mainjsx)
        self.assertNotIn("LANE main edit", mainjsx)


class ScopeGuards(unittest.TestCase):
    def test_unknown_lane_authored_path_aborts(self):
        # A conflict on a path OUTSIDE the known owned-set (neither a framework-owned
        # basename nor under a lane-owned dir like src/pages|components|services/...)
        # must NOT auto-resolve. src/pages/* is now legitimately lane-owned
        # (_FRONTEND_LANE_OWNED_DIRS), so use a genuinely-unowned subdir here.
        repo, wt = _setup(
            "frontend",
            {"app/frontend/src/experimental/Widget.jsx": "// base\n"},
            {"app/frontend/src/experimental/Widget.jsx": "// LANE widget\n"},
            {"app/frontend/src/experimental/Widget.jsx": "// other widget\n"},
        )
        ok, info = pull_main_into_worktree(worktree_dir=wt, main_branch="integration")
        self.assertFalse(ok, "conflict on an unknown lane-authored path must abort")
        self.assertIn("conflict pulling", info)

    def test_reversed_direction_vs_merge(self):
        # explicit: the PULL resolver uses framework_side=--theirs; the MERGE uses --ours.
        # Same map, opposite sides — assert the helper honors the passed side.
        import inspect
        src = inspect.getsource(_resolve_conflict_by_ownership)
        self.assertIn("framework_side", src)
        self.assertIn('lane_side = "--theirs" if framework_side == "--ours" else "--ours"', src)


if __name__ == "__main__":
    unittest.main()
