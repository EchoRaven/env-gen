# Cutover 4 — CodeHub Real Git + File Coordination Deletion

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Transform CodeHub from a metadata shell into a real `git`-backed service. Add worktree management, diff/blob/conflict-resolution APIs, real merge with conflict-task creation, and check/list/get filter queries. Migrate validation / build / verification / artifact / table state into the new model. **Delete `file_coordination.py` entirely** along with all CRDT file-coordination methods — git branches replace them.

**Why now (audit ref):** `docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md` §2.1 — CodeHub is the metadata-shell hub. Per §3.2 + §3.4, this cutover absorbs the remaining Class B method group (validation/build/verification/artifact/table) and the entire Class D group (file coordination). After this, the only CRDT residue is Class C (token/perf/retry/health metrics → Cutover 5).

**Out of scope (deferred to Cutover 5):**
- `record_token_usage / get_token_usage / get_token_budget_status`
- `record_operation_time / get_performance_stats`
- `record_retry / get_retry_stats`
- `check_agent_health / get_stuck_agents` (touch agent_status — uses EventHub now; helpers stay until Cutover 5)
- `get_progress_dashboard / get_summary`
- `increment_progress / get_progress`
- Deleting `CRDTWorkspace` class entirely

**Source spec:** `docs/superpowers/specs/2026-05-21-four-hubs-design.md` §7.
**Audit:** `docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md` §2.1, §3.2, §3.4.

---

## Phase Map

| Phase | Scope | Approx tasks |
|---|---|---|
| A | `GitOps` thin wrapper + `register_agent_worktree` + `cleanup_worktree` + agent-spawn integration | 4 tasks |
| B | `record_commit` (real `git commit`), `commit` (single-file write), `open_pr` (real branch metadata) | 3 tasks |
| C | `get_diff(pr_id)`, `get_blob(commit_hash, path)`, `get_file_content(pr_id, path)`, `list_prs(filter)`, `list_checks(pr_id/name)` | 4 tasks |
| D | Real `merge_pull_request` (git merge with conflict → WorkHub task), `resolve_conflict` | 3 tasks |
| E | Migrate validation/build/verification/artifact/table from CRDT → CodeHub.checks / APIHub.register_table | 5 tasks |
| F | Delete `file_coordination.py` + all CRDT file-coord methods + `crdt_file_coordination_tools.py` + `crdt_validation_tools.py` + `crdt_projection.py` audit + ship | 6 tasks |

Total: ~25 tasks across 6 phases. Effort estimate: 1.5-2 weeks per audit.

---

## File Map (cumulative)

**Create:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py` — `GitOps` subprocess wrapper
- `agent/tests/test_codehub_git_ops.py` — GitOps unit tests
- `agent/tests/test_codehub_worktree.py` — worktree lifecycle
- `agent/tests/test_codehub_diff_blob.py` — diff/blob reads
- `agent/tests/test_codehub_merge.py` — merge + conflict tests
- `agent/tests/test_codehub_checks.py` — list_checks/get_check_summary
- `agent/tests/test_apihub_tables.py` — register_table family (if pursued)
- `agent/tests/test_codehub_validation_migration.py` — validation/build migration parity
- `docs/superpowers/migration-logs/05-codehub-real-git.md`

**Modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py` — wire CodeHub methods to GitOps; add ~10 new methods
- `agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py` — pass repo_root to CodeHub constructor
- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — add `register_table` family (if pursued)
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py` — delete validation/build/verification/artifact/table methods + their stores
- `agent/env_generator/llm_generator/multi_agent/agent_spawn_service.py` — call `codehub.register_agent_worktree` during spawn
- `agent/env_generator/llm_generator/multi_agent/orchestrator.py` — switch validation/build callers
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/sync.py` — switch verification/check callers
- `agent/env_generator/llm_generator/tools/hub_tools.py` — add ~10 new CodeHub tool classes
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — widen codehub bundle, drop crdt_validation_tools
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — replace crdt_validation_tools refs
- Various agent prompts under `prompts/v2/` — substitute `record_build_attempt` etc. with `codehub_record_check`

**Delete:**
- `agent/env_generator/llm_generator/multi_agent/runtime/file_coordination.py` (entire file, ~787 lines)
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_validation.py` (after Phase E migrates callers)
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_projection.py` (audit-required: if `_project_api_spec` callers are gone, delete; otherwise keep until Cutover 5)
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_observer.py` (push model replaces it)
- `agent/env_generator/llm_generator/tools/crdt_file_coordination_tools.py`
- `agent/env_generator/llm_generator/tools/crdt_validation_tools.py`
- File-coordination CRDT methods in `crdt.py` (~25 methods)
- `_validation_results / _builds / _retries / _performance / _artifacts / _files / _file_history / _projection_errors / _file_regions / _file_anchors / _file_anchor_ops / _crdt_text_docs / _tables / _contracts` stores in `crdt.py` (12+ stores)

---

## Phase 0 — Pre-flight

### Task 1: Branch + baseline

- [ ] **Step 1: Branch from Cutover 3 tip**

```bash
cd /data/common/haibotong/env-gen
git fetch red-env-gen
git worktree add .worktrees/haibotong-cutover-4-codehub-real-git -b haibotong-cutover-4-codehub-real-git red-env-gen/haibotong-cutover-3-workhub-migrations
cd .worktrees/haibotong-cutover-4-codehub-real-git
```

- [ ] **Step 2: Baseline**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_architecture agent.tests.test_workhub_completeness agent.tests.test_apihub_strengthen agent.tests.test_eventhub_completeness 2>&1 | tail -3
```

Expected: regressions 7 OK; hub tests green.

- [ ] **Step 3: Confirm `git` is available**

```bash
which git && git --version
```

Required: any `git >= 2.5` (for worktree support).

---

## Phase A — GitOps + Worktree Lifecycle

### Task 2: TDD `GitOps` thin wrapper

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py`
- Create: `agent/tests/test_codehub_git_ops.py`

- [ ] **Step 1: Write failing tests**

```python
import os
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

from multi_agent.runtime.hubs.codehub.git_ops import GitOps  # noqa: E402


class GitOpsTests(unittest.TestCase):
    def _setup(self, td):
        repo = Path(td) / "repo"
        repo.mkdir()
        ops = GitOps(repo)
        ops.init()
        # Initial commit so we have a HEAD to work with
        (repo / "README.md").write_text("init")
        ops.add(["README.md"])
        ops.commit(message="Initial", author_name="cutover", author_email="cutover@example.com")
        return ops, repo

    def test_init_creates_dot_git(self):
        with tempfile.TemporaryDirectory() as td:
            ops, repo = self._setup(td)
            self.assertTrue((repo / ".git").exists())

    def test_commit_returns_hash(self):
        with tempfile.TemporaryDirectory() as td:
            ops, repo = self._setup(td)
            (repo / "a.txt").write_text("hello")
            ops.add(["a.txt"])
            sha = ops.commit(message="add a.txt", author_name="cutover", author_email="cutover@example.com")
            self.assertEqual(len(sha), 40)  # full SHA

    def test_add_worktree_creates_isolated_checkout(self):
        with tempfile.TemporaryDirectory() as td:
            ops, repo = self._setup(td)
            wt_path = Path(td) / "wt"
            ops.add_worktree(wt_path, branch="agent/backend", base="master")
            self.assertTrue((wt_path / "README.md").exists())
            # branch should be checked out
            self.assertEqual(ops.current_branch(wt_path), "agent/backend")

    def test_diff_between_commits(self):
        with tempfile.TemporaryDirectory() as td:
            ops, repo = self._setup(td)
            base = ops.current_head()
            (repo / "a.txt").write_text("hello\nworld\n")
            ops.add(["a.txt"])
            head_sha = ops.commit(message="add a.txt",
                                   author_name="cutover", author_email="cutover@example.com")
            diff = ops.diff(base, head_sha)
            self.assertIn("a.txt", diff)
            self.assertIn("+hello", diff)

    def test_show_returns_file_content_at_commit(self):
        with tempfile.TemporaryDirectory() as td:
            ops, repo = self._setup(td)
            (repo / "a.txt").write_text("line one\n")
            ops.add(["a.txt"])
            sha = ops.commit(message="add", author_name="x", author_email="x@y")
            content = ops.show(sha, "a.txt")
            self.assertEqual(content, "line one\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Confirm FAIL** (`GitOps` not implemented yet)

- [ ] **Step 3: Implement `GitOps`**

```python
"""Thin subprocess wrapper around `git` for CodeHub.

We use subprocess (not GitPython) for predictability + minimal deps.
All methods raise GitOpsError on non-zero exit.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


class GitOpsError(RuntimeError):
    def __init__(self, cmd, returncode, stderr):
        super().__init__(f"git {' '.join(cmd)} failed (exit {returncode}): {stderr.strip()}")
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr


@dataclass
class MergeResult:
    success: bool
    conflict_files: List[str]
    output: str


class GitOps:
    def __init__(self, repo_root: Path):
        self.repo = Path(repo_root).resolve()

    def _run(self, args: List[str], cwd: Optional[Path] = None, check: bool = True,
             input_text: Optional[str] = None) -> str:
        cmd = ["git", *args]
        result = subprocess.run(
            cmd,
            cwd=str(cwd or self.repo),
            capture_output=True,
            text=True,
            input=input_text,
        )
        if check and result.returncode != 0:
            raise GitOpsError(cmd, result.returncode, result.stderr)
        return result.stdout

    def init(self) -> None:
        self.repo.mkdir(parents=True, exist_ok=True)
        self._run(["init", "--quiet"])
        # Configure a default identity so commits don't fail in CI/test sandboxes.
        self._run(["config", "user.name", "cutover-bot"])
        self._run(["config", "user.email", "cutover@example.com"])

    def add(self, files: List[str], cwd: Optional[Path] = None) -> None:
        self._run(["add", *files], cwd=cwd)

    def commit(self, message: str, author_name: str = "", author_email: str = "",
               cwd: Optional[Path] = None) -> str:
        env_args = []
        if author_name and author_email:
            env_args = [
                "-c", f"user.name={author_name}",
                "-c", f"user.email={author_email}",
            ]
        self._run([*env_args, "commit", "-m", message, "--quiet"], cwd=cwd)
        return self.current_head(cwd=cwd)

    def add_worktree(self, path: Path, branch: str, base: str = "master") -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._run(["worktree", "add", "-b", branch, str(path), base])

    def remove_worktree(self, path: Path, force: bool = False) -> None:
        args = ["worktree", "remove", str(path)]
        if force:
            args.append("--force")
        self._run(args)

    def list_worktrees(self) -> List[dict]:
        out = self._run(["worktree", "list", "--porcelain"])
        worktrees: List[dict] = []
        current: dict = {}
        for line in out.splitlines():
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[len("worktree "):]
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD "):]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):]
        if current:
            worktrees.append(current)
        return worktrees

    def current_head(self, cwd: Optional[Path] = None) -> str:
        return self._run(["rev-parse", "HEAD"], cwd=cwd).strip()

    def current_branch(self, cwd: Optional[Path] = None) -> str:
        return self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).strip()

    def list_branches(self) -> List[str]:
        out = self._run(["branch", "--list", "--format=%(refname:short)"])
        return [b.strip() for b in out.splitlines() if b.strip()]

    def show(self, commit: str, path: str) -> str:
        return self._run(["show", f"{commit}:{path}"])

    def diff(self, base: str, head: str, paths: Optional[List[str]] = None) -> str:
        args = ["diff", base, head]
        if paths:
            args.append("--")
            args.extend(paths)
        return self._run(args)

    def log_for_branch(self, branch: str, max_count: int = 50) -> List[dict]:
        out = self._run(
            ["log", branch, f"--max-count={max_count}", "--pretty=format:%H%x00%an%x00%s"]
        )
        items: List[dict] = []
        for line in out.splitlines():
            parts = line.split("\x00")
            if len(parts) >= 3:
                items.append({"sha": parts[0], "author": parts[1], "subject": parts[2]})
        return items

    def merge(self, target: str, source: str, strategy: str = "squash",
              cwd: Optional[Path] = None) -> MergeResult:
        # Caller must `git checkout target` in cwd first.
        if strategy == "squash":
            args = ["merge", "--squash", source, "--no-edit"]
        elif strategy == "rebase":
            args = ["rebase", source]
        else:
            args = ["merge", source, "--no-edit"]
        try:
            output = self._run(args, cwd=cwd)
            return MergeResult(success=True, conflict_files=[], output=output)
        except GitOpsError as exc:
            # Detect merge conflict
            status = self._run(["diff", "--name-only", "--diff-filter=U"], cwd=cwd, check=False)
            conflicts = [line for line in status.splitlines() if line.strip()]
            return MergeResult(success=False, conflict_files=conflicts, output=str(exc))

    def checkout(self, ref: str, cwd: Optional[Path] = None) -> None:
        self._run(["checkout", ref, "--quiet"], cwd=cwd)

    def branch_exists(self, name: str) -> bool:
        out = self._run(["branch", "--list", name])
        return bool(out.strip())
```

- [ ] **Step 4: Run, confirm PASS**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_git_ops -v 2>&1 | tail -8
```

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/git_ops.py agent/tests/test_codehub_git_ops.py
git commit -m "Add GitOps subprocess wrapper for CodeHub"
```

### Task 3: TDD `register_agent_worktree` + `cleanup_worktree`

**Files:**
- Create: `agent/tests/test_codehub_worktree.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py` (pass repo_root to CodeHub)

- [ ] **Step 1: Write tests**

```python
# test_codehub_worktree.py
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path: sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.crdt import CRDTWorkspace  # noqa: E402


class CodeHubWorktreeTests(unittest.TestCase):
    def test_register_agent_worktree_creates_real_git_branch(self):
        with tempfile.TemporaryDirectory() as td:
            ws = CRDTWorkspace(Path(td))
            ch = ws.hubs.codehub
            ch.ensure_repo()
            result = ch.register_agent_worktree("backend")
            self.assertTrue(Path(result["worktree_path"]).exists())
            self.assertEqual(result["branch"], "agent/backend")
            # branch shows up in git
            branches = ch.git.list_branches()
            self.assertIn("agent/backend", branches)

    def test_cleanup_worktree_removes_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            ws = CRDTWorkspace(Path(td))
            ch = ws.hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("backend")
            ch.cleanup_worktree("backend")
            # Worktree directory should be gone
            wt_list = ch.git.list_worktrees()
            paths = [w.get("path", "") for w in wt_list]
            self.assertFalse(any("workspaces/backend" in p for p in paths))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Confirm FAIL**

- [ ] **Step 3: Update `HubWorkspace.__init__` to pass repo_root to CodeHub**

Currently CodeHub gets only `crdt_dir`. We need it to know the repo root so it can construct worktrees relative to it.

In `agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py`, change the CodeHub construction:

```python
self.codehub = CodeHub(self.base_dir, self.crdt_dir, eventhub=self.eventhub)
```

(was previously `CodeHub(self.crdt_dir, eventhub=...)`)

- [ ] **Step 4: Update `CodeHub.__init__`** in `runtime/hubs/codehub/service.py`:

```python
def __init__(self, repo_root: Path, crdt_dir: Path, eventhub: "EventHub | None" = None):
    self.repo_root = Path(repo_root)
    self.crdt_dir = Path(crdt_dir)
    self.eventhub = eventhub
    from .git_ops import GitOps
    self.git = GitOps(self.repo_root)
    self.stores = CodeHubStores.create(self.crdt_dir)
    self.stores.ensure_documents()
```

- [ ] **Step 5: Implement `ensure_repo`, `register_agent_worktree`, `cleanup_worktree`** in service.py:

```python
def ensure_repo(self) -> dict:
    if not (self.repo_root / ".git").exists():
        self.git.init()
        # Seed an initial commit so worktrees have a HEAD
        readme = self.repo_root / "README.md"
        if not readme.exists():
            readme.write_text("# Project\n", encoding="utf-8")
        gi = self.repo_root / ".gitignore"
        if not gi.exists():
            gi.write_text(
                ".worktrees/\nworkspaces/\nshared/crdt/\nnode_modules/\n__pycache__/\n.checkpoint.json\n",
                encoding="utf-8",
            )
        self.git.add(["README.md", ".gitignore"])
        self.git.commit(message="Initial repo bootstrap", author_name="codehub",
                         author_email="codehub@example.com")
    return {"repo_root": str(self.repo_root), "main_branch": self.git.current_branch()}

def register_agent_worktree(self, agent_id: str, branch: str = None) -> dict:
    self.ensure_repo()
    branch = branch or f"agent/{agent_id}"
    wt_path = self.repo_root / "workspaces" / agent_id
    if wt_path.exists():
        # Already registered — return existing record
        return {"agent_id": agent_id, "branch": branch, "worktree_path": str(wt_path)}
    base = self.git.current_branch() or "main"
    self.git.add_worktree(wt_path, branch=branch, base=base)
    from ...crdt_types import Timestamp
    ts = Timestamp.now(agent_id)
    record = {
        "id": f"main:{branch}",
        "repo_id": "main",
        "name": branch,
        "base": base,
        "owner": agent_id,
        "worktree_path": str(wt_path),
        "status": "active",
        "_updated_by": agent_id,
        "_updated_at": ts.wall_time,
    }
    self.stores.branches.update(lambda m: m.set(record["id"], record, ts))
    self._emit("worktree_registered", record, recipients=[agent_id])
    return {"agent_id": agent_id, "branch": branch, "worktree_path": str(wt_path)}

def cleanup_worktree(self, agent_id: str, force: bool = True) -> dict:
    wt_path = self.repo_root / "workspaces" / agent_id
    if wt_path.exists():
        self.git.remove_worktree(wt_path, force=force)
    from ...crdt_types import Timestamp
    ts = Timestamp.now(agent_id)
    branch = f"agent/{agent_id}"
    key = f"main:{branch}"
    existing = self.stores.branches.get().get(key) or {}
    updated = {**existing, "status": "cleaned", "_updated_at": ts.wall_time, "_updated_by": agent_id}
    self.stores.branches.update(lambda m: m.set(key, updated, ts))
    return {"agent_id": agent_id, "branch": branch, "status": "cleaned"}
```

- [ ] **Step 6: PASS + commit**

```bash
git add agent/tests/test_codehub_worktree.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py
git commit -m "Add CodeHub.ensure_repo / register_agent_worktree / cleanup_worktree (real git)"
```

### Task 4: Agent spawn integrates CodeHub.register_agent_worktree

Modify `agent/env_generator/llm_generator/multi_agent/agent_spawn_service.py`. After agent setup, before returning the agent instance, call `register_agent_worktree`. Skip for `dynamic_worker_inheriting_worktree` agents (some workers share parent's worktree).

- [ ] **Step 1: Read current spawn**

```bash
grep -n "async def spawn\|register_agent_repo\|register_agent_worktree" agent/env_generator/llm_generator/multi_agent/agent_spawn_service.py
```

- [ ] **Step 2: Insert worktree registration**

```python
# Around the end of spawn()
try:
    if not getattr(request, "inherit_worktree", False):
        self.orch.crdt_workspace.hubs.codehub.register_agent_worktree(request.agent_id)
except Exception as exc:
    self._logger.warning(f"[{request.agent_id}] worktree registration failed: {exc}")
```

The `try/except` is intentional: legacy tests construct agents without a real repo; failure here shouldn't crash spawn during the transitional period.

- [ ] **Step 3: Verify regressions + commit**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
git add agent/env_generator/llm_generator/multi_agent/agent_spawn_service.py
git commit -m "Register agent worktree via CodeHub during spawn"
```

---

## Phase B — Real `record_commit`, `commit`, `open_pr`

### Task 5: TDD CodeHub.commit (real git commit per agent)

Add `commit(agent_id, message, files=None)` that runs in the agent's worktree:

```python
def commit(self, agent_id: str, message: str, files: Optional[List[str]] = None) -> dict:
    wt_path = self.repo_root / "workspaces" / agent_id
    if not wt_path.exists():
        self.register_agent_worktree(agent_id)
    files = files or ["."]
    self.git.add(files, cwd=wt_path)
    full_msg = f"{message}\n\n[agent: {agent_id}]"
    sha = self.git.commit(message=full_msg, author_name=agent_id,
                          author_email=f"{agent_id}@hub", cwd=wt_path)
    # Persist commit metadata
    from ...crdt_types import Timestamp
    ts = Timestamp.now(agent_id)
    branch = f"agent/{agent_id}"
    record = {
        "id": sha, "repo_id": "main", "branch": branch, "author": agent_id,
        "files": files if files != ["."] else [], "diff_summary": message,
        "created_at": ts.wall_time,
        "_updated_by": agent_id, "_updated_at": ts.wall_time,
    }
    self.stores.commits.update(lambda m: m.set(sha, record, ts))
    self._emit("commit_recorded", record, recipients=[])
    return record
```

The existing `record_commit` (metadata-only) is kept for backward-compat but the **new path** is `commit` (real git). Update tests.

Commit: `Add CodeHub.commit with real git commit`.

### Task 6: Real `open_pr` (`open_pull_request` already exists but with weak head tracking)

Update `open_pull_request` so `pr["head"]` always reflects `git.current_head(branch_worktree)`. Add a sanity check that the branch actually exists in git.

Commit: `CodeHub.open_pull_request validates against real git branch state`.

### Task 7: Tool surface — `codehub_commit`, `codehub_open_pr` widening

Add new tool class `CodeHubCommitTool` (NAME=`codehub_commit`). Update existing `CodeHubOpenPRTool` to call updated `open_pull_request`. Widen `_bundle_codehub_tools`.

Commit: `Add codehub_commit LLM tool + widen bundle`.

---

## Phase C — Read APIs

### Task 8: TDD `get_diff(pr_id, max_lines=5000)`

```python
def get_diff(self, pr_id: str, max_lines: int = 5000) -> dict:
    pr = self.stores.pull_requests.get().get(pr_id)
    if not pr:
        return {"error": f"PR not found: {pr_id}"}
    source = pr.get("source_branch")
    target = pr.get("target_branch", "main")
    try:
        full = self.git.diff(target, source)
    except Exception as exc:
        return {"error": str(exc)}
    lines = full.splitlines()
    if len(lines) > max_lines:
        return {
            "pr_id": pr_id,
            "diff": "\n".join(lines[:max_lines]),
            "truncated": True,
            "total_lines": len(lines),
            "shown_lines": max_lines,
        }
    return {"pr_id": pr_id, "diff": full, "truncated": False, "total_lines": len(lines)}
```

Commit: `Add CodeHub.get_diff with truncation`.

### Task 9: TDD `get_blob(commit_hash, path)` + `get_file_content(pr_id, path)`

Both return raw file content. `get_blob` is git-native; `get_file_content` looks up `pr.head` and delegates.

Commit: `Add CodeHub.get_blob and get_file_content`.

### Task 10: TDD `list_prs(filter)`

```python
def list_prs(self, status: str = None, author: str = None, reviewer: str = None) -> List[dict]:
    out = []
    for pr in self.stores.pull_requests.value().values():
        if status is not None and pr.get("status") != status:
            continue
        if author is not None and pr.get("author") != author:
            continue
        if reviewer is not None and reviewer not in (pr.get("reviewers") or []):
            continue
        out.append(pr)
    return out
```

Commit: `Add CodeHub.list_prs filter API`.

### Task 11: TDD `list_checks(pr_id, name=None)` + `get_check_summary(pr_id)`

```python
def list_checks(self, pr_id: str = None, name: str = None) -> List[dict]:
    out = []
    for chk in self.stores.checks.value().values():
        if pr_id is not None and chk.get("pr_id") != pr_id:
            continue
        if name is not None and chk.get("name") != name:
            continue
        out.append(chk)
    return out

def get_check_summary(self, pr_id: str) -> dict:
    checks = self.list_checks(pr_id=pr_id)
    total = len(checks)
    passed = sum(1 for c in checks if c.get("status") == "passed")
    failed = sum(1 for c in checks if c.get("status") == "failed")
    skipped = sum(1 for c in checks if c.get("status") == "skipped")
    return {"pr_id": pr_id, "total": total, "passed": passed, "failed": failed, "skipped": skipped,
            "ready_for_delivery": failed == 0 and total > 0}
```

Commit: `Add CodeHub.list_checks and get_check_summary`.

---

## Phase D — Real Merge + Conflict Resolution

### Task 12: TDD real `merge_pull_request`

Rewrite `merge_pull_request` to actually run `git merge`. On success → status=merged. On conflict → status=conflict, create WorkHub task assigned to PR author.

```python
def merge_pull_request(self, pr_id: str, strategy: str = "squash", agent: str = "codehub") -> dict:
    pr = self.stores.pull_requests.get().get(pr_id)
    if not pr:
        return {"error": f"PR not found: {pr_id}"}
    if pr.get("merge_state") != "ready":
        return {"error": "PR not ready", "merge_state": pr.get("merge_state")}
    source = pr.get("source_branch")
    target = pr.get("target_branch", "main")
    main_wt = self.repo_root  # main worktree is repo root by convention
    # Ensure we're on target branch in main worktree
    self.git.checkout(target, cwd=main_wt)
    merge_result = self.git.merge(target=target, source=source, strategy=strategy, cwd=main_wt)
    from ...crdt_types import Timestamp
    ts = Timestamp.now(agent)
    updated = dict(pr)
    if merge_result.success:
        if strategy == "squash":
            # squash needs commit step
            self.git.commit(message=f"Merge {source} into {target} (squash)\n\nPR: {pr_id}",
                            author_name=agent, author_email=f"{agent}@hub", cwd=main_wt)
        updated["status"] = "merged"
        updated["merged_at"] = ts.wall_time
        updated["merged_by"] = agent
        updated["merge_strategy"] = strategy
        self._emit("pull_request_merged", updated, recipients=[pr.get("author")] if pr.get("author") else [])
    else:
        updated["status"] = "conflict"
        updated["conflict_files"] = merge_result.conflict_files
        updated["conflict_recorded_at"] = ts.wall_time
        # Auto-create WorkHub fix task
        workhub = self.eventhub.eventhub if self.eventhub else None  # placeholder; real wiring below
        # Actually we need HubWorkspace to inject workhub, mirror APIHub.attach_workhub pattern
        if hasattr(self, "_workhub") and self._workhub is not None:
            try:
                self._workhub.create_task(
                    title=f"Resolve merge conflict in PR {pr_id}",
                    description=f"Files: {merge_result.conflict_files}",
                    assignee=pr.get("author"),
                    agent=agent,
                    source="codehub_merge_conflict",
                    linked_pr=pr_id,
                    affected_files=merge_result.conflict_files,
                    priority="urgent",
                )
            except Exception:
                pass
        self._emit("pull_request_conflict", updated,
                   recipients=[pr.get("author")] if pr.get("author") else [],
                   priority="urgent")
    self.stores.pull_requests.update(lambda m: m.set(pr_id, updated, ts))
    return updated
```

Add `attach_workhub` setter to CodeHub (mirror APIHub pattern). Wire it in `HubWorkspace.__init__` right after WorkHub is constructed:

```python
self.codehub.attach_workhub(self.workhub)
```

Commit: `Replace CodeHub.merge_pull_request with real git merge + conflict task`.

### Task 13: TDD `resolve_conflict`

```python
def resolve_conflict(self, pr_id: str, resolution_files: Dict[str, str], agent: str = "") -> dict:
    pr = self.stores.pull_requests.get().get(pr_id)
    if not pr:
        return {"error": f"PR not found: {pr_id}"}
    if pr.get("status") != "conflict":
        return {"error": f"PR is not in conflict state: {pr.get('status')}"}
    # Write resolution files into the main worktree, then add + commit
    for path, content in resolution_files.items():
        full = self.repo_root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        self.git.add([path], cwd=self.repo_root)
    self.git.commit(message=f"Resolve merge conflict for PR {pr_id}",
                    author_name=agent, author_email=f"{agent}@hub", cwd=self.repo_root)
    from ...crdt_types import Timestamp
    ts = Timestamp.now(agent)
    updated = dict(pr)
    updated["status"] = "merged"
    updated["merged_at"] = ts.wall_time
    updated["merged_by"] = agent
    updated["conflict_resolved_by"] = agent
    self.stores.pull_requests.update(lambda m: m.set(pr_id, updated, ts))
    self._emit("conflict_resolved", updated, recipients=[pr.get("author")] if pr.get("author") else [])
    return updated
```

Commit: `Add CodeHub.resolve_conflict`.

### Task 14: Tool surface — diff/blob/list/merge tools

Add 6 new tool classes: `codehub_get_diff`, `codehub_get_blob`, `codehub_get_file_content`, `codehub_list_prs`, `codehub_list_checks`, `codehub_resolve_conflict`. Widen bundle.

Commit: `Add 6 new CodeHub LLM tools (diff/blob/list/conflict)`.

---

## Phase E — Migrate validation/build/artifact/table from CRDT

### Task 15: Parity tests for validation → CodeHub.checks migration

`workspace.record_validation_result(task_id, status, agent, summary, ...)` becomes `workspace.hubs.codehub.record_check(pr_id, name=task_id, status=status, evidence={"summary": summary}, agent=agent)`.

`get_validation_results(limit=...)` and `get_validation_summary()` map to `codehub.list_checks(name=...)` + `codehub.get_check_summary`.

Build parity tests in `agent/tests/test_codehub_validation_migration.py`.

Commit: `Add CodeHub validation migration parity tests`.

### Task 16: Switch validation callers to CodeHub.record_check

Find callers:
```bash
grep -rn "record_validation_result\|get_validation_results\|get_validation_summary\|handle_validation_failure\|create_dev_task_from_validation_failure" --include='*.py' agent/ | grep -v __pycache__ | grep -v test_
```

Targets: `orchestrator.py:_validate_delivery_gate` (validation reads), `multi_agent/agents/runtime/sync.py`, task_suite_executor, etc.

Each `record_validation_result(task_id, status, summary, ...)` → `record_check(pr_id=current_pr_or_"main", name=task_id, status=status, evidence={"summary": summary}, agent=...)`. Note: many validations happen outside a PR context (e.g., delivery gate); use `pr_id="main"` as a synthetic PR id for now, or extend CodeHub.record_check to accept `pr_id=None`.

`handle_validation_failure` / `create_dev_task_from_validation_failure` rewrite to call `workhub.create_task(...)` directly.

Commit: `Switch validation callers from CRDTWorkspace to CodeHub.record_check + WorkHub`.

### Task 17: Switch build/verification callers

`record_build_attempt(component, status, ...)` → `record_check(pr_id="main", name=f"build:{component}", status=status, evidence={...}, agent=...)`.

`get_build_status(component)` → `list_checks(name=f"build:{component}")` + summarize.

`get_verification_checklist()` → `get_check_summary(pr_id="main")`.

Commit: `Switch build / verification callers to CodeHub.record_check`.

### Task 18: Migrate artifacts

`update_artifact(path, data, agent)` → either CodeHub.create_release attachments, or as a CodeHub.checks entry with `name=f"artifact:{path}"`. The simpler mapping is the check (artifacts are evidence; their lifecycle is similar).

Commit: `Migrate artifact tracking to CodeHub.checks (kind=artifact)`.

### Task 19: Decide and apply table migration

Per audit recommendation: APIHub `register_table` family.

Add to APIHub: `register_table(name, schema, agent, **meta)`, `update_table_schema(name, schema, agent)`, `list_tables(provider=None)`, `get_table(name)`, `register_table_consumer(table_name, file_path, agent, metadata)`.

Switch `workspace.update_table / get_tables / get_table` callers in `crdt_projection.py` and elsewhere.

Delete `_tables` store from `crdt.py`.

Commit: `Migrate update_table family to APIHub.register_table`.

---

## Phase F — Delete file_coordination + crdt remnants + ship

### Task 20: Delete file_coordination.py

```bash
git rm agent/env_generator/llm_generator/multi_agent/runtime/file_coordination.py
```

Find callers (should be zero — `_file_regions / _file_anchors / _file_anchor_ops / _files / _file_history / _projection_errors / _crdt_text_docs` access in crdt.py is internal; once we delete the methods + stores, no consumer remains).

```bash
grep -rn "FileCoordinator\|publish_file_region\|claim_file_region\|reserve_file_anchor\|record_file_anchor_op\|record_file_read\|record_file_write\|sync_file_change\|sync_text_document_snapshot\|file_coordination" --include='*.py' agent/ | grep -v __pycache__ | grep -v test_
```

Any matches → fix in this task (delete the call entirely; git replaces these). Then delete the file_coordination methods from `crdt.py`.

Delete corresponding stores from `crdt.py:__init__` + `ensure_core_documents`:
- `_files`, `_file_history`, `_projection_errors`, `_file_regions`, `_file_anchors`, `_file_anchor_ops`, `_crdt_text_docs`

Commit: `Delete file_coordination.py and all CRDT file-coordination methods (replaced by git worktree)`.

### Task 21: Delete `crdt_file_coordination_tools.py` + `crdt_validation_tools.py`

```bash
git rm agent/env_generator/llm_generator/tools/crdt_file_coordination_tools.py
git rm agent/env_generator/llm_generator/tools/crdt_validation_tools.py
```

Remove their entries from `tool_bundles.py` + `agents_config.yaml`.

Commit: `Delete CRDT file-coordination and validation tool files`.

### Task 22: Delete `crdt_observer.py` + `crdt_projection.py`

`crdt_observer.py` is replaced by EventHub push delivery. Audit callers; if none, delete.

`crdt_projection.py` — if its only purpose was to project design spec into CRDT (which now goes via `hubs.apihub.register_endpoint` + `hubs.apihub.register_table`), it can be deleted. If callers remain, keep until Cutover 5.

Commit: `Delete crdt_observer.py and (if clean) crdt_projection.py`.

### Task 23: Final CRDT residue audit

```bash
grep -rn "workspace\.\(record_validation_result\|get_validation_results\|get_validation_summary\|record_build_attempt\|get_build_status\|get_verification_checklist\|update_artifact\|get_artifacts\|update_table\|get_tables\|get_table\|publish_file_region\|claim_file_region\|reserve_file_anchor\|record_file_read\|sync_text_document_snapshot\|create_observer\|wait_for_convergence\|get_state_hash\)" --include='*.py' agent/ | grep -v __pycache__ | grep -v test_
```

Expected: zero matches. Fix stragglers.

Commit: `Final cleanup of legacy CRDT references for Cutover 4`.

### Task 24: Update prompts

```bash
grep -lE "record_build_attempt|record_validation_result|get_verification_checklist|update_table|update_artifact|publish_file_region|claim_file_region|reserve_file_anchor" agent/env_generator/llm_generator/multi_agent/prompts/v2/*.j2
```

Substitute legacy tool names with CodeHub equivalents (e.g., `codehub_record_check(name="build:backend", status="passed", evidence=...)`). For file-region tools, drop the references — agents now just edit files in their worktree directly.

Commit: `Update agent prompts to reference CodeHub.record_check and drop file-coordination tools`.

### Task 25: Full regression + e2e + migration log + push

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -5
```

Expected: all green; total hub-related ~200+ tests.

E2E smoke (same as previous cutovers): confirm bridge + worktree creation.

Write migration log `docs/superpowers/migration-logs/05-codehub-real-git.md`. Capture audit ref §2.1, §3.2, §3.4; phase summary A-F; methods added (~10 new CodeHub); migrated callers; files deleted (`file_coordination.py`, `crdt_observer.py`, `crdt_validation.py`, `crdt_projection.py`, `crdt_file_coordination_tools.py`, `crdt_validation_tools.py`); commit list; smoke output; gotchas (real git error handling, `pr_id="main"` synthetic PR convention for non-PR validations); next (Cutover 5).

Push branch `haibotong-cutover-4-codehub-real-git` to red-env-gen.

PR compare URL: `https://github.com/Virtue-AI/red-env-gen/compare/haibotong-cutover-3-workhub-migrations...haibotong-cutover-4-codehub-real-git`.

Commit: `Add Cutover 4 migration log`.

---

## Constraints recap

- **No `Co-Authored-By: Claude` trailer** on any commit (user preference).
- Use `dt` conda env Python.
- Branch from `red-env-gen/haibotong-cutover-3-workhub-migrations`.
- ~25 commits.

## Recovery Notes

The biggest single risk is real `git` interactions in test environments (e.g., sandboxed CI without `git` writable, or `user.name`/`user.email` not configured). Mitigations are in `GitOps.init` (set user.name/email at repo init) and in the spawn-service `try/except` (worktree registration failure is non-fatal during the transitional period).

If real-merge tests interact poorly with the sandbox, isolate them in `agent/tests/test_codehub_git_ops.py` and skip via `unittest.skipIf` based on a sandbox env var. Document the skip in the migration log.
