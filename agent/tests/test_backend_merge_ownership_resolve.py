"""PROPOSAL #22 — ownership-partitioned deterministic resolution of the
agent/backend → integration merge conflict (A′).

Both envs (youtube run #5, smoke-notes) reached api_smoke-PASSED then DEADLOCKED:
`main.py` is BOTH framework-owned (the skeleton regenerates it from the contract)
AND lane-edited, so `agent/backend → integration` conflicts on main.py (+ add/add on
`custom_routes.py`); the auto-merge aborted, integration lagged, the orchestrator LLM
spun on the conflict, and `create_release` never fired.

Fix A′ (reviewer-prescribed): in `merge_agent_branch_to_main`, for `agent/backend`
only, resolve a conflict per-path by OWNERSHIP — framework-owned skeleton files take
integration's by-construction version (`--ours`); the lane-owned `custom_routes.py`
takes the agent's (`--theirs`). Any conflict outside the backend-owned set, or on any
other lane, keeps today's abort+event (scope guard). Reuses git's --ours/--theirs.

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
    merge_agent_branch_to_main, _resolve_backend_conflict_by_ownership,
    _BACKEND_FRAMEWORK_OWNED, _BACKEND_LANE_OWNED)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _write(repo, rel, content):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _commit_all(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _init_repo():
    td = tempfile.mkdtemp(prefix="p22_merge_")
    _git(td, "init", "-q")
    _git(td, "config", "user.email", "t@t.local")
    _git(td, "config", "user.name", "t")
    _git(td, "checkout", "-q", "-b", "integration")
    # base: a runnable main.py the lane will later edit (the seeded BASE)
    _write(td, "app/backend/main.py", "# BASE\nfrom fastapi import FastAPI\napp=FastAPI()\n@app.get('/health')\ndef h(): return {}\n")
    _commit_all(td, "base")
    return td


def _make_conflict_repo():
    """integration: framework main.py + a stale custom_routes.py.
    agent/backend (from base): lane main.py (divergent) + richer custom_routes.py.
    → content conflict on main.py + add/add conflict on custom_routes.py."""
    td = _init_repo()
    base = _git(td, "rev-parse", "HEAD").stdout.strip()
    # agent/backend branch from base
    _git(td, "checkout", "-q", "-b", "agent/backend", base)
    _write(td, "app/backend/main.py", "# LANE main\nfrom fastapi import FastAPI\napp=FastAPI()\n@app.get('/notes')\ndef lane_notes(): return ['lane']\n")
    _write(td, "app/backend/custom_routes.py", "# LANE custom_routes — REAL business logic\nLANE_CRUD=True\ndef create_note(): ...\ndef list_notes(): ...\n")
    _commit_all(td, "lane backend")
    # integration: framework skeleton main.py + stale custom_routes.py
    _git(td, "checkout", "-q", "integration")
    _write(td, "app/backend/main.py", "# FRAMEWORK skeleton main (by-construction)\nfrom fastapi import FastAPI\napp=FastAPI()\n@app.get('/api/notes')\ndef fw_notes(): return []\n")
    _write(td, "app/backend/custom_routes.py", "# stale\nSTALE=True\n")
    _commit_all(td, "framework integration")
    return td


class OwnershipResolve(unittest.TestCase):
    def test_backend_conflict_resolves_by_ownership(self):
        repo = _make_conflict_repo()
        ok, info = merge_agent_branch_to_main(
            repo_root=repo, agent_branch="agent/backend", main_branch="integration")
        self.assertTrue(ok, f"merge should succeed via ownership-resolve, got: {info}")
        # integration now checked out; inspect the resolved tree
        main = (Path(repo) / "app/backend/main.py").read_text()
        custom = (Path(repo) / "app/backend/custom_routes.py").read_text()
        # main.py → FRAMEWORK (integration) won
        self.assertIn("FRAMEWORK skeleton", main)
        self.assertNotIn("LANE main", main)
        # custom_routes.py → LANE (agent) won — its real logic preserved
        self.assertIn("REAL business logic", custom)
        self.assertNotIn("stale", custom)
        # no conflict markers left anywhere
        self.assertNotIn("<<<<<<<", main + custom)

    def test_helper_resolves_only_known_paths(self):
        # ownership tables are sane
        self.assertIn("main.py", _BACKEND_FRAMEWORK_OWNED)
        self.assertIn("custom_routes.py", _BACKEND_LANE_OWNED)
        self.assertNotIn("custom_routes.py", _BACKEND_FRAMEWORK_OWNED)


class ScopeGuards(unittest.TestCase):
    def test_unknown_backend_path_conflict_aborts(self):
        # a conflict on app/backend/weird.py (NOT in either set) must NOT auto-resolve
        td = _init_repo()
        base = _git(td, "rev-parse", "HEAD").stdout.strip()
        _git(td, "checkout", "-q", "-b", "agent/backend", base)
        _write(td, "app/backend/weird.py", "lane=1\n"); _commit_all(td, "lane weird")
        _git(td, "checkout", "-q", "integration")
        _write(td, "app/backend/weird.py", "fw=1\n"); _commit_all(td, "fw weird")
        ok, info = merge_agent_branch_to_main(
            repo_root=td, agent_branch="agent/backend", main_branch="integration")
        self.assertFalse(ok, "unknown-path backend conflict must abort, not guess")
        self.assertIn("conflict", info.lower())

    def test_frontend_lane_conflict_still_aborts(self):
        # NOTE (updated for PROPOSAL #23): the auto-resolve is NO LONGER backend-only.
        # #23 extended ownership-resolve to the frontend lane — App.jsx and
        # src/{pages,components,services,hooks,contexts,lib,utils}/* are lane-owned and
        # now resolve to the lane's version (see _FRONTEND_LANE_OWNED / _DIRS in
        # auto_commit.py + the companion test below). The scope guard that REMAINS: a
        # frontend conflict on a path OUTSIDE the frontend-owned set must still abort —
        # the resolver never guesses on an unmapped path a lane may legitimately own.
        # Use app/frontend/src/random_widget.js (basename not App.jsx; not under any
        # owned dir) to exercise that surviving guard.
        td = _init_repo()
        base = _git(td, "rev-parse", "HEAD").stdout.strip()
        _git(td, "checkout", "-q", "-b", "agent/frontend", base)
        _write(td, "app/frontend/src/random_widget.js", "// lane\n"); _commit_all(td, "lane fe")
        _git(td, "checkout", "-q", "integration")
        _write(td, "app/frontend/src/random_widget.js", "// fw\n"); _commit_all(td, "fw fe")
        ok, info = merge_agent_branch_to_main(
            repo_root=td, agent_branch="agent/frontend", main_branch="integration")
        self.assertFalse(ok, "frontend conflict on an unmapped path must still abort")
        self.assertIn("conflict", info.lower())

    def test_frontend_owned_file_conflict_resolves_by_ownership(self):
        # PROPOSAL #23 (companion to the scope guard above): a conflict on a
        # frontend LANE-OWNED file (App.jsx) is deterministically resolved to the
        # lane's authored version instead of aborting — this is the intentional
        # semantics change that made test_frontend_lane_conflict_still_aborts stale
        # for App.jsx. Without it the frontend's real pages/App were stranded out of
        # integration → run STALL.
        td = _init_repo()
        base = _git(td, "rev-parse", "HEAD").stdout.strip()
        _git(td, "checkout", "-q", "-b", "agent/frontend", base)
        _write(td, "app/frontend/src/App.jsx", "// LANE App — real routes\n"); _commit_all(td, "lane fe")
        _git(td, "checkout", "-q", "integration")
        _write(td, "app/frontend/src/App.jsx", "// framework stub\n"); _commit_all(td, "fw fe")
        ok, info = merge_agent_branch_to_main(
            repo_root=td, agent_branch="agent/frontend", main_branch="integration")
        self.assertTrue(ok, f"frontend App.jsx conflict should resolve by ownership, got: {info}")
        app = (Path(td) / "app/frontend/src/App.jsx").read_text()
        self.assertIn("LANE App", app)
        self.assertNotIn("<<<<<<<", app)

    def test_backend_no_conflict_happy_path_unchanged(self):
        # agent/backend with a non-conflicting change merges normally
        td = _init_repo()
        base = _git(td, "rev-parse", "HEAD").stdout.strip()
        _git(td, "checkout", "-q", "-b", "agent/backend", base)
        _write(td, "app/backend/custom_routes.py", "lane=1\n"); _commit_all(td, "lane add")
        _git(td, "checkout", "-q", "integration")
        ok, info = merge_agent_branch_to_main(
            repo_root=td, agent_branch="agent/backend", main_branch="integration")
        self.assertTrue(ok, f"clean backend merge should succeed, got: {info}")
        self.assertTrue((Path(td) / "app/backend/custom_routes.py").exists())


if __name__ == "__main__":
    unittest.main()
