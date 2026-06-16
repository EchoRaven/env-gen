# Per-Agent Worktree Isolation + Auto-Commit (Phase 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agent writes land in the agent's own git worktree (branch `agent/<id>`) and auto-commit on `finish()` — replacing today's fiction where every agent writes to a shared `base_dir` and branches sit unused at the bootstrap SHA.

**Architecture:** `EnvGenAgent.__init__` asks `codehub.register_agent_worktree(agent_id)` for its worktree path and stores it. File tools (`Read/Write/Edit/ApplyPatch/Delete`) get a per-agent `Workspace` that resolves `app/*` paths under the worktree but keeps `design/*`, `shared/*`, `.memory/*` rooted at the project base (those are cross-agent shared artifacts). Every successful write auto-stages in the worktree via `git add`. `FinishTool` (and explicit `codehub_commit`) commits staged changes to the agent's branch with author = `agent_id`. Verifier prompt is updated to use `codehub_get_file_content`/`codehub_get_diff` for cross-agent code review instead of bare `read()`.

**Tech Stack:** Python `Workspace` (workspace.py), GitOps (multi_agent/runtime/hubs/codehub/git_ops.py), canonical file tools (tools/canonical_file_tools/), workflow_policies, FinishTool, agent prompts (multi_agent/prompts/v2/).

**Non-goals (Phase 0b/0c — DEFERRED):**
- Auto-merging agent branches to a shared `agent` main branch
- Auto-pulling other agents' commits into one's worktree
- Replacing design spec files with pure hub-data (specs stay as cross-agent shared files for now)
- Pre-write declaration tools (`apihub_declare_change`) and peer review on declarations
- Code-scanning for consumer-of references that aren't registered
- New rollback tool (`codehub_revert_commit`)

---

## Decisions locked in

| Decision | Value | Why |
|---|---|---|
| Worktree location | `<base_dir>/worktrees/<agent_id>/` (already registered by codehub) | Existing convention; we just start actually using it |
| Branch | `agent/<agent_id>` (already created) | Same |
| Per-agent Workspace | `PathRoutedWorkspace(base=<base_dir>, worktree=<worktree_dir>, code_prefix="app/")` | One class, two roots, prefix-routed |
| Shared paths (read from base_dir) | `design/`, `shared/`, `.memory/`, `.user_gates.json`, `logs/`, anything outside `app/` | These are cross-agent (specs, hub stores, knowledge, gates, logs) |
| Code paths (write to worktree) | Anything starting with `app/` (e.g. `app/backend/...`, `app/frontend/...`, `app/database/...`) | Per-agent code |
| Auto-stage trigger | Success result of write/edit/apply_patch/delete | Mirrors `git add` after every successful change |
| Auto-commit trigger | `finish()` (success path) + explicit `codehub_commit` calls | Lowest-friction: agent finishes a task → its work auto-commits |
| Commit author | `<agent_id> <agent_id>@env-gen.local` | Lets `git log --author=design` answer "what did design do" |
| Commit message format | `"[<agent_id>] finish: <finish.message[:120]>"` for auto, `<message>` for explicit | Author-attributed, finishable from finish() summary |
| Failure mode of auto-commit | Log WARNING, do NOT block finish | Auto-commit is bookkeeping, not load-bearing yet |

## File Structure

**Create:**
- `multi_agent/runtime/path_routed_workspace.py` — `PathRoutedWorkspace` class. Has `code_root` (worktree) + `base_root` (project base) + `code_prefixes` (default `["app/"]`). `resolve(path)` returns code-root path if path starts with any prefix, else base-root path. Otherwise quacks like `Workspace` so existing tools accept it without change.
- `multi_agent/agents/runtime/auto_commit.py` — small helper module with `stage_file(worktree_dir, file_path)` and `commit_worktree(worktree_dir, branch, author, message)` pure functions. Wraps `subprocess.run(["git", ...])` with shutil/timeout safety. No agent state.

**Modify:**
- `agent/env_generator/llm_generator/multi_agent/agents/base.py` — `EnvGenAgent.__init__` calls `hubs.codehub.register_agent_worktree(agent_id)` (already exists, idempotent) and stores `self._worktree_dir`. Build per-agent `PathRoutedWorkspace`. Hook auto-stage into write/edit/apply_patch/delete tool dispatch in `_run_chat_mini_loop` and mirror in step_pipeline (Task 5).
- `agent/env_generator/llm_generator/multi_agent/tools.py` — `_assemble_full_tool_pool` builds the path-routed workspace per agent.
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/step_pipeline/tooling.py` — `_process_tool_calls` auto-stages on successful file writes (already tracks `files_created`/`files_modified`; just add `stage_file()` call).
- `agent/env_generator/llm_generator/tools/agent_interaction_tools.py` `FinishTool._run` (or via a workflow policy) — auto-commit hook on success.
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2` — instruct verifier to use `codehub_get_file_content(branch="agent/<author>", path=...)` and `codehub_get_diff(pr_id=...)` for review; `read(path)` of cross-agent code becomes a soft anti-pattern.
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2` — add `apihub_list_endpoints` discoverability instruction (today only frontend has it). Also: instruct `apihub_register_consumer` when the new endpoint depends on another agent's API.

**Tests (new):**
- `agent/tests/test_path_routed_workspace.py`
- `agent/tests/test_auto_commit_helpers.py`
- `agent/tests/test_agent_writes_to_worktree.py`
- `agent/tests/test_finish_auto_commits.py`

---

### Task 1: `PathRoutedWorkspace` class — code paths → worktree, others → base

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/path_routed_workspace.py`
- Test: `agent/tests/test_path_routed_workspace.py` (new)

- [ ] **Step 1: Write the failing test**

Save as `agent/tests/test_path_routed_workspace.py`:

```python
"""PathRoutedWorkspace — routes code paths to a per-agent worktree
while keeping shared paths (design/, shared/, .memory/) under the
project base. Replaces the global shared-Workspace pattern that
made every agent write to the same directory."""
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


class TestPathRoutedWorkspace(unittest.TestCase):
    def test_app_paths_resolve_under_worktree(self):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wt = base / "worktrees" / "backend"
            wt.mkdir(parents=True)
            ws = PathRoutedWorkspace(base_root=base, code_root=wt)
            self.assertEqual(
                ws.resolve("app/backend/src/routes/auth.js"),
                wt / "app/backend/src/routes/auth.js",
            )

    def test_design_paths_resolve_under_base(self):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wt = base / "worktrees" / "backend"
            wt.mkdir(parents=True)
            ws = PathRoutedWorkspace(base_root=base, code_root=wt)
            # design/* is a shared cross-agent artifact: stays under base.
            self.assertEqual(
                ws.resolve("design/spec.api.json"),
                base / "design/spec.api.json",
            )

    def test_shared_and_memory_stay_under_base(self):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wt = base / "worktrees" / "backend"
            wt.mkdir(parents=True)
            ws = PathRoutedWorkspace(base_root=base, code_root=wt)
            self.assertEqual(ws.resolve("shared/hubs/eventhub_events.json"),
                             base / "shared/hubs/eventhub_events.json")
            self.assertEqual(ws.resolve(".memory/design.knowledge.jsonl"),
                             base / ".memory/design.knowledge.jsonl")

    def test_root_property_returns_code_root(self):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wt = base / "worktrees" / "backend"
            wt.mkdir(parents=True)
            ws = PathRoutedWorkspace(base_root=base, code_root=wt)
            # The ``root`` property (used by callers that scan the
            # tree) returns the code root, since that's where this
            # agent's tree-changing operations live.
            self.assertEqual(ws.root, wt)

    def test_custom_code_prefixes(self):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wt = base / "worktrees" / "backend"
            wt.mkdir(parents=True)
            ws = PathRoutedWorkspace(
                base_root=base, code_root=wt,
                code_prefixes=("app/", "src/"),
            )
            self.assertEqual(ws.resolve("src/routes/auth.js"), wt / "src/routes/auth.js")
            self.assertEqual(ws.resolve("app/x.js"),           wt / "app/x.js")
            self.assertEqual(ws.resolve("docs/readme.md"),     base / "docs/readme.md")

    def test_contains_checks_either_root(self):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wt = base / "worktrees" / "backend"
            wt.mkdir(parents=True)
            ws = PathRoutedWorkspace(base_root=base, code_root=wt)
            # A path under EITHER root counts as "contained" — tools use
            # this for the no-escape check.
            self.assertTrue(ws.contains(base / "design/spec.api.json"))
            self.assertTrue(ws.contains(wt / "app/backend/src/server.js"))
            self.assertFalse(ws.contains(Path("/etc/passwd")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test — should fail (ImportError)**

Run:
```bash
cd /data/common/haibotong/env-gen && \
  /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_path_routed_workspace.py -v
```

Expected: FAIL — `ImportError: cannot import name 'PathRoutedWorkspace'`.

- [ ] **Step 3: Implement the class**

Create `agent/env_generator/llm_generator/multi_agent/runtime/path_routed_workspace.py`:

```python
"""Per-agent workspace that routes ``app/*`` paths to the agent's git
worktree while keeping cross-agent shared paths (``design/*``,
``shared/*``, ``.memory/*``, run logs, gates) anchored at the project
base directory.

Quacks like ``workspace.Workspace`` for the file-tool surface — same
``root``, ``resolve(path)``, ``relative(path)``, ``contains(path)``
interface — so existing tools accept it without changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple, Union


_DEFAULT_CODE_PREFIXES: Tuple[str, ...] = ("app/",)


class PathRoutedWorkspace:
    """``resolve(path)`` routes by prefix:

    * If ``path`` starts with one of ``code_prefixes`` → resolved
      under the agent's worktree (``code_root``).
    * Anything else → resolved under the project base (``base_root``).

    This is the minimum-viable per-agent isolation: each agent writes
    its OWN copy of ``app/*`` under its worktree, but all agents still
    see the same ``design/*`` and ``shared/*`` artifacts.
    """

    def __init__(
        self,
        *,
        base_root: Union[str, Path],
        code_root: Union[str, Path],
        code_prefixes: Iterable[str] = _DEFAULT_CODE_PREFIXES,
    ):
        self._base = Path(base_root).resolve()
        self._code = Path(code_root).resolve()
        # Normalize prefixes — strip leading slash, ensure trailing slash so
        # "app" doesn't match "appendix/".
        norm: list[str] = []
        for p in code_prefixes:
            s = str(p).strip().lstrip("/")
            if not s:
                continue
            if not s.endswith("/"):
                s = s + "/"
            norm.append(s)
        self._code_prefixes: Tuple[str, ...] = tuple(norm)
        self._base.mkdir(parents=True, exist_ok=True)
        self._code.mkdir(parents=True, exist_ok=True)

    # ------ Workspace-compat surface -------------------------------

    @property
    def root(self) -> Path:
        """Tree-traversal root. Returns the agent's CODE root because
        most tree-walking tools (Glob, project_structure) care about
        the agent's own changeable files, not the shared base."""
        return self._code

    @property
    def name(self) -> str:
        return self._code.name

    @property
    def base_root(self) -> Path:
        return self._base

    @property
    def code_root(self) -> Path:
        return self._code

    def resolve(self, path: Union[str, Path, None]) -> Path:
        """Resolve a user-provided path to an absolute file location."""
        if path is None or path == "":
            return self._code
        p = Path(str(path))
        if p.is_absolute():
            return p.resolve()
        as_str = str(p).replace("\\", "/")
        if as_str.startswith("/"):
            as_str = as_str.lstrip("/")
        for prefix in self._code_prefixes:
            if as_str == prefix.rstrip("/") or as_str.startswith(prefix):
                return (self._code / as_str).resolve()
        return (self._base / as_str).resolve()

    def relative(self, path: Union[str, Path]) -> str:
        """Path relative to whichever root contains it (for display)."""
        ap = Path(str(path)).resolve()
        try:
            return str(ap.relative_to(self._code))
        except ValueError:
            pass
        try:
            return str(ap.relative_to(self._base))
        except ValueError:
            return str(ap)

    def contains(self, path: Union[str, Path]) -> bool:
        ap = Path(str(path)).resolve()
        try:
            ap.relative_to(self._code)
            return True
        except ValueError:
            pass
        try:
            ap.relative_to(self._base)
            return True
        except ValueError:
            return False
```

- [ ] **Step 4: Run test — should pass**

Run: same pytest command as Step 2. Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/path_routed_workspace.py \
        agent/tests/test_path_routed_workspace.py
git commit -m "workspace: PathRoutedWorkspace routes app/* to worktree, shared paths to base"
```

---

### Task 2: Auto-stage helper (`stage_file`) + auto-commit helper (`commit_worktree`)

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/agents/runtime/auto_commit.py`
- Test: `agent/tests/test_auto_commit_helpers.py` (new)

- [ ] **Step 1: Write the failing test**

Save as `agent/tests/test_auto_commit_helpers.py`:

```python
"""auto_commit helpers: stage_file + commit_worktree."""
from __future__ import annotations

import subprocess
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


def _init_repo_with_worktree(tmpdir: Path) -> tuple[Path, Path]:
    """Init a bare-ish repo with one initial commit + a worktree for tests."""
    repo = tmpdir / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    wt = tmpdir / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "agent/backend", str(wt)],
        cwd=repo, check=True,
    )
    return repo, wt


class TestStageFile(unittest.TestCase):
    def test_stage_file_runs_git_add_in_worktree(self):
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            (wt / "app").mkdir()
            target = wt / "app/server.js"
            target.write_text("console.log('hi');\n")
            ok, err = stage_file(wt, target)
            self.assertTrue(ok, f"stage_file failed: {err}")
            # git status --porcelain should show 'A  app/server.js' (added/staged).
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=wt, capture_output=True, text=True,
            )
            self.assertIn("A  app/server.js", r.stdout)

    def test_stage_file_silent_on_missing_path(self):
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            ok, err = stage_file(wt, wt / "does/not/exist.txt")
            # Doesn't blow up; returns (False, msg).
            self.assertFalse(ok)
            self.assertIn("does/not/exist", err)

    def test_stage_file_outside_worktree_refused(self):
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            outside = Path(tmp) / "outside.txt"
            outside.write_text("x")
            ok, err = stage_file(wt, outside)
            self.assertFalse(ok)
            self.assertIn("outside", err.lower())


class TestCommitWorktree(unittest.TestCase):
    def test_commit_records_change_with_agent_author(self):
        from multi_agent.agents.runtime.auto_commit import stage_file, commit_worktree
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            (wt / "app").mkdir()
            f = wt / "app/server.js"
            f.write_text("x\n")
            stage_file(wt, f)
            ok, info = commit_worktree(
                worktree_dir=wt,
                branch="agent/backend",
                author="backend",
                message="[backend] finish: scaffolding",
            )
            self.assertTrue(ok, f"commit failed: {info}")
            # Verify the commit exists with the right author + message.
            log = subprocess.run(
                ["git", "log", "-1", "--format=%an|%s"],
                cwd=wt, capture_output=True, text=True,
            )
            line = log.stdout.strip()
            self.assertTrue(line.startswith("backend|"), f"author wrong: {line}")
            self.assertIn("[backend] finish: scaffolding", line)

    def test_commit_no_op_when_nothing_staged(self):
        from multi_agent.agents.runtime.auto_commit import commit_worktree
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            ok, info = commit_worktree(
                worktree_dir=wt, branch="agent/backend",
                author="backend", message="empty",
            )
            # An empty commit attempt should NOT be an error; should be a
            # quiet no-op (the helper is called from finish() — we don't
            # want every finish to produce a noisy "nothing to commit").
            self.assertTrue(ok)
            self.assertIn("nothing to commit", info.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test — should fail**

Run:
```bash
cd /data/common/haibotong/env-gen && \
  /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_auto_commit_helpers.py -v
```

Expected: FAIL with `ImportError: cannot import name 'stage_file' from 'multi_agent.agents.runtime.auto_commit'`.

- [ ] **Step 3: Implement the helpers**

Create `agent/env_generator/llm_generator/multi_agent/agents/runtime/auto_commit.py`:

```python
"""Auto-commit primitives for per-agent worktree writes.

Two pure helpers — no agent state, no hub access. The agent invokes
``stage_file`` after each successful Write/Edit/Patch/Delete in its
worktree, and ``commit_worktree`` once per finish() (or whenever the
agent explicitly calls ``codehub_commit``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Tuple, Union

_GIT_TIMEOUT = 30


def _run_git(args, cwd: Path) -> Tuple[int, str, str]:
    p = subprocess.run(
        ["git"] + list(args),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )
    return p.returncode, p.stdout, p.stderr


def stage_file(worktree_dir: Union[str, Path], file_path: Union[str, Path]) -> Tuple[bool, str]:
    """Stage ``file_path`` in ``worktree_dir``.

    Returns ``(ok, message)``. ``ok=False`` for: path missing, path
    outside the worktree, git error. Never raises — file tools call
    this in their result-path and a failure here must not crash a
    successful write.
    """
    wt = Path(worktree_dir).resolve()
    fp = Path(file_path).resolve()
    try:
        rel = fp.relative_to(wt)
    except ValueError:
        return False, f"path is outside worktree: {fp} not under {wt}"
    if not fp.exists():
        # `git add` would fail; we surface a clearer message. We DO
        # allow staging of intentionally-deleted files via ``git add -A``,
        # but the caller is responsible for using ``stage_deletion``.
        return False, f"file does not exist: {fp}"
    try:
        rc, _out, err = _run_git(["add", "--", str(rel)], cwd=wt)
    except Exception as exc:
        return False, f"git add raised: {exc}"
    if rc != 0:
        return False, f"git add exit {rc}: {err.strip()}"
    return True, str(rel)


def stage_deletion(worktree_dir: Union[str, Path], file_path: Union[str, Path]) -> Tuple[bool, str]:
    """Stage a removal of ``file_path`` (the path may no longer exist).

    Used by DeleteFileTool's auto-stage hook so the deletion is recorded
    in the next commit rather than silently dropped.
    """
    wt = Path(worktree_dir).resolve()
    fp = Path(file_path).resolve()
    try:
        rel = fp.relative_to(wt)
    except ValueError:
        return False, f"path is outside worktree: {fp} not under {wt}"
    try:
        rc, _out, err = _run_git(["add", "-A", "--", str(rel)], cwd=wt)
    except Exception as exc:
        return False, f"git add -A raised: {exc}"
    if rc != 0:
        return False, f"git add -A exit {rc}: {err.strip()}"
    return True, str(rel)


def commit_worktree(
    *,
    worktree_dir: Union[str, Path],
    branch: str,
    author: str,
    message: str,
) -> Tuple[bool, str]:
    """Commit currently-staged changes in ``worktree_dir`` to ``branch``.

    Returns ``(ok, info_or_error)``. ``ok=True, info='nothing to commit'``
    when the index is empty — finish() shouldn't be noisy.
    """
    wt = Path(worktree_dir).resolve()
    if not (wt / ".git").exists() and not (wt.parent / ".git").exists():
        # Not a git worktree at all (e.g. unit-test stub) — silent skip.
        return True, "not a git worktree; skipping"

    # Are we already on the expected branch?
    try:
        rc, out, _err = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=wt)
    except Exception as exc:
        return False, f"symbolic-ref raised: {exc}"
    if rc == 0:
        current = out.strip()
        if current != branch:
            # Try to switch — worktrees usually pin a branch so this
            # is rarely needed, but be tolerant.
            sc, _so, se = _run_git(["checkout", branch], cwd=wt)
            if sc != 0:
                return False, f"checkout {branch} failed: {se.strip()}"

    # Anything staged?
    rc, out, _err = _run_git(["diff", "--cached", "--name-only"], cwd=wt)
    if rc == 0 and not out.strip():
        return True, "nothing to commit"

    author_email = f"{author}@env-gen.local"
    env_override = {
        "GIT_AUTHOR_NAME": author,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    import os
    env = {**os.environ, **env_override}
    try:
        p = subprocess.run(
            ["git", "commit", "-qm", message],
            cwd=str(wt),
            env=env,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except Exception as exc:
        return False, f"git commit raised: {exc}"
    if p.returncode != 0:
        return False, f"git commit exit {p.returncode}: {p.stderr.strip()}"
    # Return the new HEAD short SHA.
    rc, out, _err = _run_git(["rev-parse", "--short", "HEAD"], cwd=wt)
    sha = out.strip() if rc == 0 else "?"
    return True, sha
```

- [ ] **Step 4: Run tests — should pass**

Run: same pytest command as Step 2. Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/runtime/auto_commit.py \
        agent/tests/test_auto_commit_helpers.py
git commit -m "auto_commit: stage_file / stage_deletion / commit_worktree helpers"
```

---

### Task 3: `EnvGenAgent` picks up its worktree path on init + builds path-routed Workspace

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/base.py` — `EnvGenAgent.__init__`
- Modify: `agent/env_generator/llm_generator/multi_agent/tools.py` — `_build_tool_assembly_context` to use the agent's per-agent workspace when present.
- Test: `agent/tests/test_agent_writes_to_worktree.py` (new)

- [ ] **Step 1: Write the failing test**

Save as `agent/tests/test_agent_writes_to_worktree.py`:

```python
"""End-to-end: a real ConfigurableAgent given a workspace_manager
must write app/* files into its own worktree, not the shared base."""
from __future__ import annotations

import os
import subprocess
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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class TestAgentResolvesWorktreeOnInit(unittest.TestCase):
    def test_envgen_agent_exposes_worktree_dir(self):
        """After construction, agent._worktree_dir must point to
        ``<base>/worktrees/<agent_id>``."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            # Manually call register_agent_worktree the way EnvGenAgent
            # will (we test the integration in step 3).
            wt_path = reg.codehub.register_agent_worktree("backend")
            self.assertEqual(wt_path, Path(tmp) / "worktrees" / "backend")
            self.assertTrue(wt_path.exists())

    def test_path_routed_workspace_is_attached(self):
        """A ConfigurableAgent created with workspace_manager pointed at
        ``base`` exposes a workspace that resolves app/* under the
        agent's worktree."""
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")
            ws = PathRoutedWorkspace(base_root=base, code_root=wt)
            # Sanity (covered by Task 1, repeated here as the integration anchor):
            self.assertEqual(
                ws.resolve("app/backend/src/server.js"),
                wt / "app/backend/src/server.js",
            )
            self.assertEqual(
                ws.resolve("design/spec.api.json"),
                base / "design/spec.api.json",
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test — should pass for the bare-helper part, fail nothing yet**

Run:
```bash
cd /data/common/haibotong/env-gen && \
  /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_agent_writes_to_worktree.py -v
```

Expected: PASS — both tests just exercise `register_agent_worktree` and `PathRoutedWorkspace` (Task 1 already shipped). They form the contract anchor for Steps 3/4.

- [ ] **Step 3: Wire the worktree path into `EnvGenAgent.__init__`**

In `multi_agent/agents/base.py`, locate the `EnvGenAgent.__init__` block where `workspace_manager` is bound (around line 185):

```python
        # Workspace
        self.workspace = workspace_manager
```

Immediately after that line, append:

```python
        # Per-agent git worktree resolution (Phase 0). When the codehub
        # is available, ensure this agent has a registered worktree and
        # store its path. Tools later (multi_agent/tools.py) build a
        # ``PathRoutedWorkspace`` anchored on this worktree for ``app/*``
        # writes while keeping cross-agent shared paths (``design/*``,
        # ``shared/*``, ``.memory/*``) under the project base.
        self._worktree_dir: Optional[Path] = None
        try:
            hubs = getattr(workspace_manager, "hubs", None) or getattr(self, "_hubs", None)
            if hubs is not None and hasattr(hubs, "codehub"):
                wt = hubs.codehub.register_agent_worktree(self.agent_id)
                self._worktree_dir = Path(wt)
        except Exception as _wt_err:
            try:
                self._logger.warning(
                    f"[{self.agent_id}] worktree registration skipped: {_wt_err}"
                )
            except Exception:
                pass
```

- [ ] **Step 4: Wire `PathRoutedWorkspace` into the tool pool**

In `multi_agent/tools.py`, locate the function that builds the `ToolAssemblyContext` (the one called from `configurable_agent.py:_setup_tools` or equivalent — search `grep -n "ToolAssemblyContext\b" multi_agent/tools.py`). Modify it so that when the agent has a `_worktree_dir`, we substitute a `PathRoutedWorkspace`:

```python
def _build_tool_assembly_context(agent, workspace, agent_type, ...):
    # ... existing code ...
    
    # Phase 0: if the agent has a worktree, route code paths to it.
    wt = getattr(agent, "_worktree_dir", None)
    if wt is not None:
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        # base_root: whatever the original WorkspaceManager pointed at.
        base_root = getattr(workspace, "base_dir", None) or getattr(workspace, "root", None) or Path(".")
        workspace = PathRoutedWorkspace(base_root=Path(base_root), code_root=Path(wt))
    
    return ToolAssemblyContext(
        agent=agent,
        workspace=workspace,
        agent_type=agent_type,
        # ... rest ...
    )
```

(Exact signature/locals match `multi_agent/tools.py` as it stands. Read the file once before editing to bind variable names correctly.)

- [ ] **Step 5: Run test — should pass**

Run: same pytest command as Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/base.py \
        agent/env_generator/llm_generator/multi_agent/tools.py \
        agent/tests/test_agent_writes_to_worktree.py
git commit -m "agent: per-agent worktree via PathRoutedWorkspace; app/* writes isolated"
```

---

### Task 4: Auto-stage on Write / Edit / Apply_Patch / Delete

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/step_pipeline/tooling.py` — `_process_tool_calls`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/base.py` — `_run_chat_mini_loop` (mirror the same hook)

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_agent_writes_to_worktree.py`:

```python
class TestAutoStageOnWrite(unittest.TestCase):
    def test_successful_write_auto_stages_in_worktree(self):
        """After a successful WriteTool execution under a per-agent
        worktree, the file is staged in that worktree's git index."""
        # Build a minimal Stub agent + drive _process_tool_calls.
        # Run `git status --porcelain` in the worktree and expect
        # 'A  app/backend/src/test_route.js' for the new file.
        # Detail: this is the explicit hook the implementation must add.
        # The full integration is exercised in Task 7's e2e test.
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        from multi_agent.agents.runtime.auto_commit import stage_file
        from multi_agent.runtime.hub_registry import HubRegistry

        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")
            ws = PathRoutedWorkspace(base_root=Path(tmp), code_root=wt)
            target_rel = "app/backend/src/test_route.js"
            target_abs = ws.resolve(target_rel)
            target_abs.parent.mkdir(parents=True, exist_ok=True)
            target_abs.write_text("module.exports = {};\n")
            ok, info = stage_file(wt, target_abs)
            self.assertTrue(ok, f"stage_file should succeed: {info}")
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=wt, capture_output=True, text=True,
            )
            self.assertIn("A  app/backend/src/test_route.js", r.stdout)
```

- [ ] **Step 2: Run test — should pass**

Run:
```bash
cd /data/common/haibotong/env-gen && \
  /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_agent_writes_to_worktree.py::TestAutoStageOnWrite -v
```

Expected: PASS. (This test verifies the pieces; the production wiring is added in Step 3 + Step 4 of THIS task.)

- [ ] **Step 3: Wire `stage_file`/`stage_deletion` into `_process_tool_calls`**

In `multi_agent/agents/runtime/step_pipeline/tooling.py`, locate the file-tracking block (~line 196-230) where `files_created` / `files_modified` are appended. Right where `files_created.append(path)` lives, also call the stager:

```python
            if tool_name == "write":
                path = tool_args.get("path") or tool_args.get("file_path")
                if path:
                    files_created.append(path)
                    if hasattr(self, "memory"):
                        self.memory.record_file_created(path)
                    # Phase 0: auto-stage in the agent's worktree so
                    # the next commit sees the new file. Best-effort —
                    # we don't propagate stage_file errors to the
                    # caller; a stage failure is logged at WARNING.
                    _auto_stage(self, path, action="add")
            elif tool_name == "edit":
                path = tool_args.get("file_path") or tool_args.get("path")
                if path:
                    files_modified.append(path)
                    if hasattr(self, "memory"):
                        self.memory.record_file_modified(path)
                    _auto_stage(self, path, action="add")
            elif tool_name == "apply_patch":
                # ... existing patch_path tracking ...
                for patch_path in patch_created:
                    files_created.append(patch_path)
                    if hasattr(self, "memory"):
                        self.memory.record_file_created(patch_path)
                    _auto_stage(self, patch_path, action="add")
                for patch_path in patch_paths:
                    files_modified.append(patch_path)
                    if hasattr(self, "memory"):
                        self.memory.record_file_modified(patch_path)
                    _auto_stage(self, patch_path, action="add")
            elif tool_name == "delete_file":
                path = tool_args.get("file_path") or tool_args.get("path")
                if path:
                    _auto_stage(self, path, action="delete")
```

Add the `_auto_stage` helper at module top (after the existing imports):

```python
def _auto_stage(agent, file_path: str, *, action: str) -> None:
    """Best-effort auto-stage of an agent write in its worktree.

    Failures are logged at WARNING — staging is bookkeeping, not
    load-bearing. The next commit will still pick the file up via
    ``git add -A`` if explicit staging fails."""
    wt = getattr(agent, "_worktree_dir", None)
    if wt is None:
        return
    workspace = getattr(agent, "workspace", None)
    try:
        resolved = workspace.resolve(file_path) if workspace else None
    except Exception:
        resolved = None
    if resolved is None:
        return
    from multi_agent.agents.runtime.auto_commit import stage_file, stage_deletion
    fn = stage_deletion if action == "delete" else stage_file
    ok, info = fn(wt, resolved)
    if not ok:
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] auto-stage ({action}) skipped for "
                f"{file_path}: {info}"
            )
        except Exception:
            pass
```

- [ ] **Step 4: Mirror in mini-loop**

In `multi_agent/agents/base.py:_run_chat_mini_loop`, find the file-tracking block we already added in the post-review fix (`chat_files_created.append(...)` and `chat_files_modified.append(...)`). Right after each `append`, call `_auto_stage`:

```python
                if success and _writer_path:
                    if tool_name == "write":
                        chat_files_created.append(_writer_path)
                        if hasattr(self, "memory"):
                            try:
                                self.memory.record_file_created(_writer_path)
                            except Exception:
                                pass
                        _auto_stage_in_mini_loop(self, _writer_path, action="add")
                    elif tool_name in ("edit", "apply_patch"):
                        chat_files_modified.append(_writer_path)
                        if hasattr(self, "memory"):
                            try:
                                self.memory.record_file_modified(_writer_path)
                            except Exception:
                                pass
                        _auto_stage_in_mini_loop(self, _writer_path, action="add")
                    elif tool_name == "delete_file":
                        _auto_stage_in_mini_loop(self, _writer_path, action="delete")
```

Add a module-private `_auto_stage_in_mini_loop` helper in `base.py` (private prefix because this duplicates the step_pipeline helper — both wrap the same pure functions and accept different signatures):

```python
def _auto_stage_in_mini_loop(agent, file_path: str, *, action: str) -> None:
    wt = getattr(agent, "_worktree_dir", None)
    if wt is None:
        return
    workspace = getattr(agent, "workspace", None)
    try:
        resolved = workspace.resolve(file_path) if workspace else None
    except Exception:
        resolved = None
    if resolved is None:
        return
    from multi_agent.agents.runtime.auto_commit import stage_file, stage_deletion
    fn = stage_deletion if action == "delete" else stage_file
    ok, info = fn(wt, resolved)
    if not ok:
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] mini-loop auto-stage ({action}) skipped: {info}"
            )
        except Exception:
            pass
```

- [ ] **Step 5: Run regression**

Run:
```bash
cd /data/common/haibotong/env-gen && \
  /home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
    agent/tests/test_path_routed_workspace.py \
    agent/tests/test_auto_commit_helpers.py \
    agent/tests/test_agent_writes_to_worktree.py \
    agent/tests/test_human_chat_mini_loop.py \
    agent/tests/test_hub_consistency_policy.py \
    -q
```

Expected: every test passes.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/runtime/step_pipeline/tooling.py \
        agent/env_generator/llm_generator/multi_agent/agents/base.py \
        agent/tests/test_agent_writes_to_worktree.py
git commit -m "tooling: auto-stage writes/edits/patches/deletes into per-agent worktree"
```

---

### Task 5: Auto-commit on `finish()`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/workflow_policies.py` — add a new `AutoCommitOnFinishPolicy`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — attach the new policy to every code-writing profile
- Test: `agent/tests/test_finish_auto_commits.py` (new)

- [ ] **Step 1: Write the failing test**

Save as `agent/tests/test_finish_auto_commits.py`:

```python
"""Auto-commit on finish: when a code-writing agent's finish() succeeds,
any staged changes in the worktree are committed to ``agent/<id>`` with
author = agent_id."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _reset_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class TestAutoCommitOnFinishPolicy(unittest.TestCase):
    def tearDown(self):
        _reset_loop()

    def test_policy_commits_staged_changes_with_agent_author(self):
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        from multi_agent.agents.runtime.auto_commit import stage_file

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")
            # Stage a real change in the worktree.
            (wt / "app").mkdir(parents=True, exist_ok=True)
            f = wt / "app/server.js"
            f.write_text("console.log('hi');\n")
            stage_file(wt, f)

            class StubAgent:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _worktree_dir = wt
                _logger = MagicMock()
                workspace = MagicMock(base_dir=base)
                async def _execute_tool(self, name, args):
                    class R: success = True; data = {"summary": "ok"}; error_message = None
                    return R()

            policy = AutoCommitOnFinishPolicy()
            asyncio.run(policy.handle_finish(
                StubAgent(),
                tool_name="finish",
                tool_args={"message": "Backend scaffolded"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=["app/server.js"],
                files_modified=[],
            ))
            # Verify the commit landed on the agent/backend branch.
            log = subprocess.run(
                ["git", "log", "-1", "--format=%an|%s", "agent/backend"],
                cwd=base, capture_output=True, text=True,
            )
            line = log.stdout.strip()
            self.assertTrue(line.startswith("backend|"),
                            f"author wrong: {line!r}")
            self.assertIn("[backend]", line)
            self.assertIn("Backend scaffolded", line)

    def test_policy_returns_none_when_not_finish(self):
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        policy = AutoCommitOnFinishPolicy()
        outcome = asyncio.run(policy.handle_finish(
            MagicMock(),
            tool_name="write",
            tool_args={},
            tool_call=None, tool_call_id="",
            messages=[], files_created=[], files_modified=[],
        ))
        self.assertIsNone(outcome)

    def test_policy_quiet_when_nothing_staged(self):
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")

            class StubAgent:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _worktree_dir = wt
                _logger = MagicMock()
                workspace = MagicMock(base_dir=base)

            policy = AutoCommitOnFinishPolicy()
            # Nothing staged; policy should be a no-op and NOT block finish.
            outcome = asyncio.run(policy.handle_finish(
                StubAgent(),
                tool_name="finish",
                tool_args={"message": "nothing did"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=[],
                files_modified=[],
            ))
            self.assertIsNone(outcome)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test — should fail**

Run:
```bash
cd /data/common/haibotong/env-gen && \
  /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_finish_auto_commits.py -v
```

Expected: FAIL — `ImportError: cannot import name 'AutoCommitOnFinishPolicy'`.

- [ ] **Step 3: Implement the policy**

Append to `multi_agent/workflow_policies.py`, just before `def create_workflow_policies(...)`:

```python
class AutoCommitOnFinishPolicy(BaseWorkflowPolicy):
    """On a successful finish(), commit any staged changes in the
    agent's worktree to ``agent/<id>`` with author=agent_id.

    Side-effecting bookkeeping, never blocks: returns ``None`` so the
    finish proceeds normally. A commit failure is logged at WARNING.
    """

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        if tool_name != "finish":
            return None
        wt = getattr(agent, "_worktree_dir", None)
        if wt is None:
            return None  # no worktree (e.g. orchestrator) → skip
        from multi_agent.agents.runtime.auto_commit import commit_worktree
        msg = (tool_args.get("message") or "").strip()[:120] or "auto-commit"
        commit_msg = f"[{agent.agent_id}] finish: {msg}"
        ok, info = commit_worktree(
            worktree_dir=wt,
            branch=f"agent/{agent.agent_id}",
            author=str(agent.agent_id),
            message=commit_msg,
        )
        if not ok:
            try:
                agent._logger.warning(
                    f"[{agent.agent_id}] auto-commit on finish failed: {info}"
                )
            except Exception:
                pass
        return None
```

Then in `create_workflow_policies(agent_cfg)` add the branch:

```python
        elif kind == "auto_commit_on_finish":
            policies.append(AutoCommitOnFinishPolicy())
```

- [ ] **Step 4: Attach the policy to every code-writing profile**

In `multi_agent/agents/agents_config.yaml`, for each of `design`, `database`, `backend`, `frontend` profiles, add to their `workflow_policies:` list (after the existing `hub_consistency_gate`):

```yaml
      - kind: auto_commit_on_finish
```

- [ ] **Step 5: Run tests — should pass**

Run: same pytest command as Step 2. Expected: all 3 tests PASS.

Also run a regression on the broader chat/policy suite:
```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
  agent/tests/test_finish_auto_commits.py \
  agent/tests/test_hub_consistency_policy.py \
  agent/tests/test_hub_consistency_finish_e2e.py \
  agent/tests/test_human_chat_mini_loop.py \
  agent/tests/test_agents_config_stages.py \
  -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/workflow_policies.py \
        agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml \
        agent/tests/test_finish_auto_commits.py
git commit -m "policy: AutoCommitOnFinishPolicy commits worktree changes to agent branch"
```

---

### Task 6: Verifier reads via codehub, not bare `read()`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2`
- Test: `agent/tests/test_prompt_contains_review_instructions.py` (new)

- [ ] **Step 1: Write the failing test**

Save as `agent/tests/test_prompt_contains_review_instructions.py`:

```python
"""Verifier prompt must instruct using codehub_get_file_content for
cross-agent code review (not bare `read()`). Backend prompt must
instruct apihub_list_endpoints + apihub_register_consumer when
building / consuming APIs."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


def _load(prompt_name: str) -> str:
    p = LLM_DIR / "multi_agent" / "prompts" / "v2" / prompt_name
    return p.read_text()


class TestVerifierUsesCodeHubForReview(unittest.TestCase):
    def test_verifier_prompt_mentions_codehub_get_file_content(self):
        text = _load("verifier_agent.j2")
        self.assertIn("codehub_get_file_content", text,
                      "verifier_agent.j2 must instruct using codehub_get_file_content "
                      "for branch-scoped file reads during review")

    def test_verifier_prompt_mentions_codehub_get_diff(self):
        text = _load("verifier_agent.j2")
        self.assertIn("codehub_get_diff", text,
                      "verifier_agent.j2 must instruct using codehub_get_diff for PR review")


class TestBackendDiscoverabilityAndConsumerDeclaration(unittest.TestCase):
    def test_backend_prompt_tells_agent_to_list_endpoints_first(self):
        text = _load("backend_agent.j2")
        self.assertIn("apihub_list_endpoints", text,
                      "backend_agent.j2 must instruct calling apihub_list_endpoints "
                      "before building a new endpoint (reuse over reimplement)")

    def test_backend_prompt_tells_agent_to_register_as_consumer(self):
        text = _load("backend_agent.j2")
        self.assertIn("apihub_register_consumer", text,
                      "backend_agent.j2 must instruct calling apihub_register_consumer "
                      "when the new endpoint uses another agent's API")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test — should fail on the new assertions**

Run:
```bash
cd /data/common/haibotong/env-gen && \
  /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_prompt_contains_review_instructions.py -v
```

Expected: FAIL on `test_verifier_prompt_mentions_codehub_get_file_content` (the verifier prompt doesn't reference it), FAIL on backend ones.

- [ ] **Step 3: Update `verifier_agent.j2`**

Open `multi_agent/prompts/v2/verifier_agent.j2`. Find the section that describes how the verifier reads code (search for `read(` or `## How to verify` etc.). Add this block near the top of the verification instructions, before the `read(` examples:

```jinja
## Reading code under review

You are reviewing OTHER agents' work. Their writes land on branch
``agent/<author>`` and are visible **only** via the CodeHub review
tools. The generic ``read(file_path=...)`` reads your OWN worktree
which does NOT contain the writes you are supposed to review.

For review, use:

- ``codehub_get_file_content(pr_id=<PR>, file_path=...)`` —
  reads the file at the PR's head commit (the branch under review).
- ``codehub_get_diff(pr_id=<PR>)`` — shows what changed.
- ``codehub_list_inline_comments(pr_id=<PR>)`` — prior reviewer comments.

Bare ``read(file_path=...)`` is for files you wrote yourself.
```

- [ ] **Step 4: Update `backend_agent.j2`**

Open `multi_agent/prompts/v2/backend_agent.j2`. Find the "## Workflow" or "## Steps" section. Add this block:

```jinja
## Before you build an endpoint

1. Call ``apihub_list_endpoints(status="defined")`` — design has already
   declared the API contract; do NOT reinvent it.
2. Call ``apihub_list_endpoints(status="implemented")`` — another
   backend agent may have already built it. Reuse over reimplement.
3. If your new endpoint calls another agent's endpoint (e.g. your
   ``POST /api/posts`` reads ``GET /api/users``), you MUST call:

   ```
   apihub_register_consumer(
       endpoint_id="GET /api/users",
       file_path="app/backend/src/routes/posts.js",
       reason="post-author resolution",
   )
   ```

   Without this, the producer cannot tell you when ``/api/users`` is
   about to change, and a breaking-change rollout will surprise you.
```

- [ ] **Step 5: Run test — should pass**

Run: same pytest command as Step 2. Expected: 4/4 PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2 \
        agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2 \
        agent/tests/test_prompt_contains_review_instructions.py
git commit -m "prompts: verifier reads via codehub_get_file_content; backend lists+declares-consumer"
```

---

### Task 7: End-to-end smoke test — backend writes a route, finish auto-commits, git log shows it

**Files:**
- Test: `agent/tests/test_phase0_e2e.py` (new)

- [ ] **Step 1: Write the e2e test**

Save as `agent/tests/test_phase0_e2e.py`:

```python
"""Phase 0 end-to-end smoke: drive an agent through write → finish and
assert (a) the file landed in the agent's worktree (not the shared base),
(b) ``git log agent/backend`` shows a new commit with author=backend.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _reset_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class TestPhase0EndToEnd(unittest.TestCase):
    def tearDown(self):
        _reset_loop()

    def test_write_then_finish_commits_to_agent_branch(self):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        from multi_agent.agents.runtime.auto_commit import stage_file

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")
            ws = PathRoutedWorkspace(base_root=base, code_root=wt)

            # Simulate the write the agent would do.
            target_rel = "app/backend/src/routes/auth.js"
            target_abs = ws.resolve(target_rel)
            self.assertTrue(str(target_abs).startswith(str(wt)),
                            "code path must resolve under the agent's worktree")
            target_abs.parent.mkdir(parents=True, exist_ok=True)
            target_abs.write_text("module.exports = function auth(){};\n")
            stage_file(wt, target_abs)

            # File MUST NOT exist under shared base.
            self.assertFalse(
                (base / target_rel).exists(),
                "code write leaked into shared base — worktree isolation broken",
            )

            # Drive finish through the policy.
            class StubAgent:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _worktree_dir = wt
                _logger = MagicMock()
                workspace = ws
            policy = AutoCommitOnFinishPolicy()
            asyncio.run(policy.handle_finish(
                StubAgent(),
                tool_name="finish",
                tool_args={"message": "Backend ready"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=[target_rel],
                files_modified=[],
            ))

            # Verify: agent/backend branch has a new commit by 'backend'.
            log = subprocess.run(
                ["git", "log", "agent/backend", "--format=%an|%s"],
                cwd=base, capture_output=True, text=True,
            )
            commits = [line for line in log.stdout.strip().split("\n") if line]
            # There should be at LEAST one commit by 'backend' (the auto-commit).
            self.assertTrue(
                any(c.startswith("backend|") for c in commits),
                f"no backend-authored commit on agent/backend; log: {commits}",
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — should pass**

Run:
```bash
cd /data/common/haibotong/env-gen && \
  /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_phase0_e2e.py -v
```

Expected: PASS.

- [ ] **Step 3: Full regression**

Run:
```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
  agent/tests/test_path_routed_workspace.py \
  agent/tests/test_auto_commit_helpers.py \
  agent/tests/test_agent_writes_to_worktree.py \
  agent/tests/test_finish_auto_commits.py \
  agent/tests/test_prompt_contains_review_instructions.py \
  agent/tests/test_phase0_e2e.py \
  agent/tests/test_hub_consistency_policy.py \
  agent/tests/test_hub_consistency_finish_e2e.py \
  agent/tests/test_human_chat_mini_loop.py \
  agent/tests/test_human_chat_compression.py \
  agent/tests/test_human_chat_directive_injection.py \
  agent/tests/test_human_chat_step_event.py \
  agent/tests/test_agents_config_stages.py \
  agent/tests/test_eventhub_completeness.py \
  agent/tests/test_eventhub_new_tools.py \
  agent/tests/test_agent_human_message_handler.py \
  agent/tests/test_human_console.py \
  -q
```

Expected: all pass. If any test failures surface real regressions (vs flakey tests), fix them before continuing.

- [ ] **Step 4: Commit**

```bash
git add agent/tests/test_phase0_e2e.py
git commit -m "tests: phase 0 e2e — backend write → finish → agent/backend commit lands"
```

---

## Self-Review

**Spec coverage** (against the user's six behavioral scenarios):

- ✅ **Scenario 1 (consumer declaration)** — Task 6 adds the backend prompt block. Note: this is prompt-level reinforcement, NOT a hard gate. A follow-up Phase 1 should add `apihub_consumers` to `HubConsistencyPolicy.expect_hub_kinds` and code-scan for unregistered references.
- ✅ **Scenario 2 (discoverability)** — Task 6 backend prompt update tells backend to call `apihub_list_endpoints` first.
- ⚠️ **Scenario 3 (defined → implemented notification)** — Phase 0 does NOT fix this. APIHub still emits `endpoint_registered` with `recipients=[]` for both define and implement. Marked for Phase 1.
- ⚠️ **Scenario 4 (file-modification trace)** — Phase 0 unblocks this: real commits now exist. Adding `codehub_log` / `codehub_blame` / `codehub_file_history` tools is Phase 1 (lightweight; data is now there).
- ⚠️ **Scenario 5 (rollback)** — Phase 0 enables `git revert` as a one-tool addition. `codehub_revert_commit` tool is Phase 1.
- ✅ **Scenario 6 (reviewer reads branch)** — Task 6 verifier prompt update; Tasks 1-5 ensure the branch ACTUALLY has the code to review.

**Placeholder scan:**

- No "TBD" / "implement later" / "add appropriate error handling" — every step has runnable code.
- One assumption: Task 3 Step 4 says "match variable names in `multi_agent/tools.py` as they stand" — this is a Read-then-Edit instruction with a clear unambiguous target.
- Task 4 Step 3 spans a long code block; verified type consistency with `step_pipeline/tooling.py:196-228` which is the established pattern.

**Type consistency:**

- `_worktree_dir: Optional[Path]` — used the same way in Tasks 3 / 4 / 5 / 7.
- `stage_file(worktree_dir, file_path) -> Tuple[bool, str]` — same signature in tests and implementation.
- `commit_worktree(*, worktree_dir, branch, author, message) -> Tuple[bool, str]` — keyword-only across tests + impl.
- `AutoCommitOnFinishPolicy.handle_finish` matches the `BaseWorkflowPolicy` superclass signature (same as the other 4 policies in the same file).

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-worktree-isolation-and-autocommit.md`. Two execution options:

**1. Inline Execution (recommended given prior cadence)** — execute tasks 1–7 in this session with checkpoints between each task. Smoke test at end requires you to restart a run.

**2. Subagent-Driven** — fresh subagent per task with two-stage review. Slower but more isolated.

Which approach?
