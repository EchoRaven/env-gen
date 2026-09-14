"""
GitOps — thin subprocess wrapper around /usr/bin/git for CodeHub.

All public methods raise GitOpsError on non-zero exit codes.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
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


# #1075: generous by default — ordinary git here is sub-second; this is a
# ceiling on a HANG, not a performance budget.
try:
    _GIT_TIMEOUT_1075 = max(1, int(os.environ.get("ENVGEN_GIT_TIMEOUT") or 120))
except (TypeError, ValueError):
    _GIT_TIMEOUT_1075 = 120

# #1202kw: a lock older than the ceiling on a git call CANNOT be held by a live
# git this framework started -- #1075 bounds every call in this class to
# _GIT_TIMEOUT_1075, so anything still holding one past that was killed or
# crashed. The margin is slack for a machine under load, not a guess about git.
_LOCK_STALE_AFTER_1202KW = _GIT_TIMEOUT_1075 + 60

# git names the lock in its own message; match that rather than guessing paths.
_LOCK_ERR_RE_1202KW = re.compile(
    r"(index\.lock|HEAD\.lock|Another git process)", re.I)

_LOCK_NAMES_1202KW = ("index.lock", "HEAD.lock")


class GitOps:
    """Subprocess wrapper for git operations on a single repository."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, *args: str, check: bool = True, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        cmd = [GIT, *args]
        # #1075: BOUND IT, and never wait on stdin.
        #
        # This is the wrapper every CodeHub git operation goes through — commit,
        # merge, stash, branch, worktree — and it had no timeout, so a git that
        # blocks blocked forever with no log line and no ceiling. 52 of this
        # package's 54 subprocess call sites already pass one; this was the
        # exception. Two ways it blocks: an operation waiting on an `index.lock`
        # left by a crashed process (the git pain here is documented — "could not
        # write index" 187 times, feeding #623's conflict storm), and one that
        # wants credentials. GIT_TERMINAL_PROMPT was set nowhere in the package, so
        # git waited on stdin that never arrives.
        #
        # The timeout surfaces as GitOpsError — the type every caller already
        # handles. A hang has to become a legible failure, not a new exception
        # nobody catches.
        _env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd or self.repo_root),
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_1075,
                env=_env,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitOpsError(
                f"git {' '.join(args)} timed out after {_GIT_TIMEOUT_1075}s in "
                f"{cwd or self.repo_root} — a held index.lock or a credential "
                f"prompt will do this. Raise ENVGEN_GIT_TIMEOUT if the repo is "
                f"genuinely this slow."
            ) from exc
        # #1202kw: a STALE lock is not contention, and no lane can clear it.
        #
        # auto_commit._run_git already retries this signature 3x with 200/400ms
        # backoff, for the case it documents: "two agents finishing in the same
        # millisecond". That is real, and backoff fixes it. It cannot fix a lock
        # left behind by a git that was killed -- and this wrapper, which every
        # CodeHub operation goes through, had no retry at all. The comment in
        # _run above already names the cause ("an index.lock left by a crashed
        # process ... 187 times").
        #
        # tiktok-r118 died of one. A ZERO-BYTE .git/index.lock appeared at
        # 17:16:08 (git creates it O_EXCL and writes the new index into it, so
        # empty means it never got that far) and was still there when the run
        # aborted at 18:36 -- 80 minutes in which every merge failed. The lanes
        # could not clear it BY CONSTRUCTION: the debugger answered "my tool
        # subset has no filesystem/shell/delete capability", the orchestrator
        # raised a P0 "filesystem-capable cleanup" task anyway, and the backend
        # lane's attempt was refused by the path sandbox ("'..' escapes its
        # route's root"). A host-level fault laundered into a lane P0 that no
        # lane can do is how a run burns its remaining ticks.
        #
        # Clearing is safe here for a reason, not by hope: #1075 bounds every git
        # call in this class, so a lock older than that ceiling cannot belong to
        # one that is still running. Below the threshold nothing is touched --
        # that window is exactly auto_commit's contention case, which owns it.
        if result.returncode != 0 and _LOCK_ERR_RE_1202KW.search(
                (result.stderr or "") + (result.stdout or "")):
            _cleared = self._clear_stale_locks_1202kw(cwd)
            if _cleared:
                logging.getLogger(__name__).warning(
                    "#1202kw cleared stale git lock(s) %s under %s and retried "
                    "`git %s` -- left by a git that was killed or crashed, not by "
                    "a running one (#1075 bounds every call here to %ss). No lane "
                    "has the capability to remove these.",
                    ", ".join(_cleared), cwd or self.repo_root,
                    " ".join(args), _GIT_TIMEOUT_1075)
                try:
                    result = subprocess.run(
                        cmd, cwd=str(cwd or self.repo_root), capture_output=True,
                        text=True, timeout=_GIT_TIMEOUT_1075, env=_env)
                except subprocess.TimeoutExpired as exc:
                    raise GitOpsError(
                        f"git {' '.join(args)} timed out after "
                        f"{_GIT_TIMEOUT_1075}s in {cwd or self.repo_root} after "
                        f"#1202kw cleared a stale lock"
                    ) from exc
        if check and result.returncode != 0:
            raise GitOpsError(
                f"git {' '.join(args)} failed (exit {result.returncode}):\n"
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    def _git_dir_1202kw(self, cwd: Optional[Path]) -> Optional[Path]:
        """Resolve the real .git directory -- a linked worktree's `.git` is a FILE
        pointing elsewhere, so the lock does not live beside the checkout.
        `rev-parse` takes no index lock, so it is safe on a locked repo."""
        try:
            p = subprocess.run(
                [GIT, "rev-parse", "--absolute-git-dir"],
                cwd=str(cwd or self.repo_root), capture_output=True, text=True,
                timeout=_GIT_TIMEOUT_1075,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
            out = (p.stdout or "").strip()
            return Path(out) if p.returncode == 0 and out else None
        except Exception:
            return None

    def _clear_stale_locks_1202kw(self, cwd: Optional[Path] = None) -> List[str]:
        """Remove lock files older than any bounded git call could still hold.

        #1202mg: the age/containment/unlink logic now lives in one place, shared
        with `auto_commit._run_git` -- the OTHER git wrapper in this package,
        which had no clearing at all and so let a stale lock fail every merge in
        tiktok-r122 for 46 minutes. Two copies of a guard is how that happened;
        this call keeps there being one.

        `repo_root` is still passed as the containment boundary, and it is
        load-bearing rather than ceremonial: `rev-parse` WALKS UP, so from this
        checkout's own `generated/` it answers with the development repo's git
        dir. Deleting a lock there would be this fix corrupting the very tree it
        lives in.
        """
        from ....agents.runtime.auto_commit import clear_stale_git_locks_1202mg
        return clear_stale_git_locks_1202mg(
            cwd or self.repo_root, contain_under=self.repo_root)

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
        it just plants a ref, without disturbing whatever is currently checked
        out (agent worktrees, the integrator's HEAD, etc.). Returns the SHA the
        branch now points to.

        #724: the previous sentence said release branches "must capture a snapshot of ``main``".
        That is wrong and it points at the worst available tree. Measured across r146, r147 and
        r148: every `release-v1.0.0` is an ancestor of ``integration`` and of NEITHER ``main``
        — releases are cut with ``source="integration"``. And ``main`` is not a lagging copy of
        the same work: reproducing r148's promotion merge at the commits that existed when it
        ran gives 16 conflicting files, the whole app, because the framework's delivery commit
        writes the entire skeleton onto ``main`` while the lane's work goes to ``integration``
        (#691's stranding at full scale). A branch cut from ``main`` would be framework
        projections with no lane work in it.

        The ``start_point="main"`` default is therefore misleading, and it is retained only
        because changing a public default is not a docstring fix. Both call sites pass the point
        explicitly today (``"HEAD"`` at service.py:806, ``source`` at :1104), so nothing relies
        on it — but a third caller that did would cut from the wrong tree, and the sentence above
        used to tell them that was correct.
        """
        cmd = ["branch"]
        if force:
            cmd.append("-f")
        cmd += [branch, start_point]
        self._run(*cmd)
        return self.rev_parse_branch(branch)
