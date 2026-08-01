"""
GitOps — thin subprocess wrapper around /usr/bin/git for CodeHub.

All public methods raise GitOpsError on non-zero exit codes.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


GIT = "/usr/bin/git"


class GitOpsError(Exception):
    """Raised when a git subprocess exits with a non-zero status."""


@dataclass
class MergeResult:
    success: bool
    sha: str = ""
    conflicts: List[str] = field(default_factory=list)
    message: str = ""


class GitOps:
    """Subprocess wrapper for git operations on a single repository."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, *args: str, check: bool = True, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        cmd = [GIT, *args]
        result = subprocess.run(
            cmd,
            cwd=str(cwd or self.repo_root),
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise GitOpsError(
                f"git {' '.join(args)} failed (exit {result.returncode}):\n"
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    # ------------------------------------------------------------------
    # Repository lifecycle
    # ------------------------------------------------------------------

    def init(self) -> Path:
        """Initialise a repository at repo_root; set local user config.

        The unborn HEAD is deterministically pinned to ``main`` via
        ``git symbolic-ref HEAD refs/heads/main`` so the FIRST commit lands
        on ``main`` regardless of the host's ``init.defaultBranch`` setting.
        Older git (< 2.28) and any system whose default branch is ``master``
        would otherwise never create the integration branch ``main`` that
        ``merge_pull_request`` / ``force_merge_pull_request`` check out —
        observed in the youtube run as ``codehub_force_merge`` failing with
        ``pathspec 'main' did not match any file(s) known to git``. ``init()``
        only runs on a fresh repo (``ensure_repo`` calls it only when ``.git``
        is absent), so HEAD is unborn here and re-pointing it is safe.
        """
        self.repo_root.mkdir(parents=True, exist_ok=True)
        self._run("init", cwd=self.repo_root)
        # Pin the unborn default branch to ``main`` (portable across git
        # versions — no -b/--initial-branch flag, which 2.25 lacks).
        self._run("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.repo_root)
        # Ensure commits succeed even without global user config
        self._run("config", "user.name", "GitOps Bot")
        self._run("config", "user.email", "gitops@codehub.local")
        return self.repo_root

    # ------------------------------------------------------------------
    # Staging / committing
    # ------------------------------------------------------------------

    def add(self, *paths: str) -> None:
        """Stage paths (defaults to '.')."""
        targets = list(paths) if paths else ["."]
        self._run("add", *targets)

    def commit(self, message: str, allow_empty: bool = False) -> str:
        """Create a commit; returns the full 40-char SHA."""
        cmd = ["commit", "-m", message]
        if allow_empty:
            cmd.append("--allow-empty")
        self._run(*cmd)
        return self.current_head()

    # ------------------------------------------------------------------
    # Worktree management
    # ------------------------------------------------------------------

    def add_worktree(self, path: Path, branch: str) -> Path:
        """Create a linked worktree checked out to *branch* (creates branch if absent).

        The path is RESOLVED to absolute first. Callers build it as
        ``repo_root / "worktrees" / <agent>`` and ``repo_root`` is routinely RELATIVE
        (e.g. ``generated/<name>``). ``_run`` sets ``cwd=self.repo_root``, so a relative
        worktree path is re-resolved by git AGAINST the repo dir → the worktree is created
        at ``generated/<name>/generated/<name>/worktrees/<agent>`` (doubly nested). That
        does NOT match where ``path_routed_workspace`` + ``heal_pipeline`` read/write the
        lane's files (``<cwd>/generated/<name>/worktrees/<agent>``, resolved against the
        PROCESS cwd) — so a lane writes into a plain directory inside the MAIN checkout
        instead of its real per-lane worktree. Its committed work then lands on whatever
        branch the main checkout holds and NEVER reaches ``agent/<lane>`` → never merges to
        ``integration`` → the build/audit ship a stale tree (netflix r2: real LandingPage +
        components stranded on ``main`` while the audited ``app/`` stayed the bootstrap stub
        → ``deliverability_ui_flow_failed`` deadlock). Resolving to an absolute path (against
        the process cwd, exactly like the workspace/heal readers) makes ``git worktree add``
        create the worktree at the single, canonical location every reader/writer agrees on,
        regardless of git's cwd."""
        path = Path(path).resolve()
        if not self.branch_exists(branch):
            # git worktree add -b <branch> <path>
            self._run("worktree", "add", "-b", branch, str(path))
        else:
            # git worktree add <path> <branch>
            self._run("worktree", "add", str(path), branch)
        return path

    def remove_worktree(self, path: Path, force: bool = False) -> None:
        """Remove a linked worktree (path resolved absolute to match add_worktree)."""
        cmd = ["worktree", "remove", str(Path(path).resolve())]
        if force:
            cmd.append("--force")
        self._run(*cmd)

    def list_worktrees(self) -> List[dict]:
        """Return list of dicts with 'path', 'head', 'branch' keys."""
        result = self._run("worktree", "list", "--porcelain")
        worktrees: List[dict] = []
        current: dict = {}
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line[len("worktree "):].strip()}
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD "):].strip()
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):].strip()
        if current:
            worktrees.append(current)
        return worktrees

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def current_head(self, cwd: Optional[Path] = None) -> str:
        """Return full SHA of HEAD (optionally from a different working directory)."""
        return self._run("rev-parse", "HEAD", cwd=cwd).stdout.strip()

    def rev_parse_branch(self, branch: str) -> str:
        """Return the full SHA that *branch* points to."""
        return self._run("rev-parse", branch).stdout.strip()

    def current_branch(self) -> str:
        """Return current branch name."""
        return self._run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def list_branches(self) -> List[str]:
        """Return list of local branch names."""
        result = self._run("branch", "--format=%(refname:short)")
        return [b.strip() for b in result.stdout.splitlines() if b.strip()]

    def branch_exists(self, branch: str) -> bool:
        result = self._run("branch", "--list", branch)
        return bool(result.stdout.strip())

    def show(self, ref: str, path: str) -> str:
        """Return file content at *ref*."""
        return self._run("show", f"{ref}:{path}").stdout

    def diff(self, ref_a: str, ref_b: str, path: Optional[str] = None) -> str:
        """Return unified diff between two refs."""
        cmd = ["diff", ref_a, ref_b]
        if path:
            cmd += ["--", path]
        return self._run(*cmd).stdout

    def log_for_branch(self, branch: str, max_count: int = 20) -> List[dict]:
        """Return list of dicts with 'sha' and 'message' for commits on branch."""
        result = self._run(
            "log", branch,
            f"--max-count={max_count}",
            "--pretty=format:%H%x00%s",
        )
        entries: List[dict] = []
        for line in result.stdout.splitlines():
            if "\x00" in line:
                sha, msg = line.split("\x00", 1)
                entries.append({"sha": sha.strip(), "message": msg.strip()})
        return entries

    # ------------------------------------------------------------------
    # Merging / checkout
    # ------------------------------------------------------------------

    def merge(self, branch: str, message: str = "", no_ff: bool = True) -> MergeResult:
        """Merge *branch* into HEAD; returns MergeResult."""
        cmd = ["merge"]
        if no_ff:
            cmd.append("--no-ff")
        if message:
            cmd += ["-m", message]
        cmd.append(branch)
        result = self._run(*cmd, check=False)
        if result.returncode == 0:
            return MergeResult(success=True, sha=self.current_head(), message=result.stdout.strip())
        # Attempt to detect conflict files
        conflicts: List[str] = []
        for line in result.stdout.splitlines():
            if "CONFLICT" in line:
                parts = line.split(":")
                if len(parts) > 1:
                    conflicts.append(parts[-1].strip())
        return MergeResult(
            success=False,
            conflicts=conflicts,
            message=result.stderr.strip() or result.stdout.strip(),
        )

    def checkout(self, branch: str, create: bool = False) -> None:
        """Switch to *branch*, optionally creating it."""
        cmd = ["checkout"]
        if create:
            cmd.append("-b")
        cmd.append(branch)
        self._run(*cmd)

    def create_branch_at(self, branch: str, start_point: str = "main", force: bool = False) -> str:
        """Create (or move, if *force*) *branch* pointing at *start_point*.

        Unlike :meth:`checkout`, this does NOT switch the working tree's HEAD --
        it just plants a ref. Used for release branches, which must capture a
        snapshot of ``main`` without disturbing whatever is currently checked
        out (agent worktrees, the integrator's HEAD, etc.). Returns the SHA the
        branch now points to.
        """
        cmd = ["branch"]
        if force:
            cmd.append("-f")
        cmd += [branch, start_point]
        self._run(*cmd)
        return self.rev_parse_branch(branch)
