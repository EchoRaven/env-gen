"""Auto-commit primitives for per-agent worktree writes.

Two pure helpers — no agent state, no hub access. The agent invokes
``stage_file`` after each successful Write/Edit/Patch/Delete in its
worktree, and ``commit_worktree`` once per finish() (or whenever the
agent explicitly calls ``codehub_commit``).
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple, Union

_GIT_TIMEOUT = 30

_LOG = logging.getLogger(__name__)

# Phase 0.2 RE-FIX 5: auto-stage path filter.
#
# When an agent finishes, auto-stage walks the worktree and feeds files
# to ``git add``. Anything an agent has written (including dotfiles like
# ``.gates/allowed_code_checks.yaml`` that the agent itself authors)
# would otherwise ride the squash-merge into the shared ``integration``
# branch — and subsequently get picked up by user-side gates that read
# allowlist files from the merged tree (e.g. ``user_gates`` reading
# ``.gates/allowed_code_checks.yaml``). That's the agent-controllable
# escalation path Phase 0.1/0.2 close from multiple sides; this filter
# is the propagation-layer defense.
#
# Layer A — dotfile rejection (universal): any path component beginning
# with ``.`` is refused unless it's a small, vetted set of standard
# dotfiles that legitimately need to live in the repo.
ALLOWED_DOTFILES = frozenset({
    ".gitignore",
    ".gitattributes",
    ".gitkeep",
    ".env.example",
})


def _should_stage_path(rel_path: str, agent_id: Optional[str] = None) -> bool:
    """Return True if ``rel_path`` is safe to auto-stage in a worktree.

    Layer A: any path component whose basename begins with ``.`` is
    refused unless it appears in ``ALLOWED_DOTFILES``. This blocks
    agent-authored ``.gates/``, ``.secrets/``, ``.github/`` etc. from
    riding auto-stage → squash-merge into the shared branch.

    Layer B (not enforced here yet — flagged for follow-up): per-agent
    write-scope (e.g. backend agent → ``app/backend/``). Wiring requires
    the spawn-service to pass the declared scope into the auto-stage
    helpers; that's a larger refactor. For now layer A alone is the
    blocker for the documented bypass chain (agent → dotfile → user_gates).

    ``rel_path`` MUST be a worktree-relative path (forward or backward
    slashes accepted). Absolute paths return False defensively — every
    caller in this module derives ``rel_path`` via ``Path.relative_to``,
    so an absolute slipping in is itself a sign of a bug.
    """
    if not rel_path:
        return False
    norm = rel_path.replace("\\", "/")
    # Defensive — relative_to() should have produced a relative path.
    if norm.startswith("/"):
        return False
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    # Compiled-Python / build junk must NEVER be staged — committed
    # ``__pycache__/*.pyc`` files cause "Cannot merge binary files" conflicts on
    # agent→integration merges (instagram MM run #9: the backend's
    # ``main.cpython-*.pyc`` blocked ``_merge_committed_agent_work``, so its fixes
    # never reached the validated tree → api_smoke stalled on stale code). These are
    # build artifacts, never source — refuse them unconditionally.
    base = parts[-1] if parts else norm
    if "__pycache__" in parts or base.endswith((".pyc", ".pyo", ".pyd")):
        return False
    for part in parts:
        if part.startswith(".") and part not in ALLOWED_DOTFILES:
            try:
                _LOG.warning(
                    "auto-stage refused %s for agent %s: dotfile not in allowlist",
                    rel_path,
                    agent_id or "<unknown>",
                )
            except Exception:
                pass
            return False
    return True


def _filter_paths_for_staging(
    rel_paths: List[str],
    agent_id: Optional[str] = None,
) -> List[str]:
    """Filter a list of worktree-relative paths through ``_should_stage_path``.

    Used by callers that gather multiple files (e.g. ``git add .`` on a
    populated worktree). Returns the subset that passes the filter.
    Rejections are logged inside ``_should_stage_path``.
    """
    return [p for p in rel_paths if _should_stage_path(p, agent_id=agent_id)]


def _run_git(args, cwd: Path) -> Tuple[int, str, str]:
    """Run a git command, transparently retrying on transient
    ``index.lock``/``HEAD.lock`` busy errors.

    Two agents finishing in the same millisecond both try to
    ``git checkout integration && git merge``. git's index.lock
    serializes us, but the loser sees ``fatal: Unable to create
    '.git/index.lock': File exists``. That's not a real merge failure
    — wait a beat and retry up to 3 times before reporting.
    """
    import time as _time
    attempts = 0
    while True:
        attempts += 1
        p = subprocess.run(
            ["git"] + list(args),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        err = (p.stderr or "")
        if (
            p.returncode != 0
            and attempts < 3
            and ("index.lock" in err or "HEAD.lock" in err or "Another git process" in err)
        ):
            _time.sleep(0.2 * attempts)  # 200ms, 400ms backoff
            continue
        return p.returncode, p.stdout, p.stderr


def stage_file(
    worktree_dir: Union[str, Path],
    file_path: Union[str, Path],
    *,
    agent_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Stage ``file_path`` in ``worktree_dir``.

    Returns ``(ok, message)``. ``ok=False`` for: path missing, path
    outside the worktree, refused by ``_should_stage_path`` (e.g.
    dotfile not in allowlist), git error. Never raises — file tools
    call this in their result-path and a failure here must not crash a
    successful write.
    """
    wt = Path(worktree_dir).resolve()
    fp = Path(file_path).resolve()
    try:
        rel = fp.relative_to(wt)
    except ValueError:
        return False, f"path is outside worktree: {fp} not under {wt}"
    rel_str = str(rel)
    if not _should_stage_path(rel_str, agent_id=agent_id):
        return False, (
            f"auto-stage refused {rel_str}: dotfile not in allowlist"
        )
    if not fp.exists():
        return False, f"file does not exist: {fp}"
    try:
        rc, _out, err = _run_git(["add", "--", rel_str], cwd=wt)
    except Exception as exc:
        return False, f"git add raised: {exc}"
    if rc != 0:
        return False, f"git add exit {rc}: {err.strip()}"
    return True, rel_str


def stage_deletion(
    worktree_dir: Union[str, Path],
    file_path: Union[str, Path],
    *,
    agent_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Stage a removal of ``file_path`` (the path may no longer exist).

    Used by DeleteFileTool's auto-stage hook so the deletion is
    recorded in the next commit rather than silently dropped.
    """
    wt = Path(worktree_dir).resolve()
    fp = Path(file_path).resolve()
    try:
        rel = fp.relative_to(wt)
    except ValueError:
        return False, f"path is outside worktree: {fp} not under {wt}"
    rel_str = str(rel)
    if not _should_stage_path(rel_str, agent_id=agent_id):
        return False, (
            f"auto-stage refused {rel_str}: dotfile not in allowlist"
        )
    try:
        rc, _out, err = _run_git(["add", "-A", "--", rel_str], cwd=wt)
    except Exception as exc:
        return False, f"git add -A raised: {exc}"
    if rc != 0:
        return False, f"git add -A exit {rc}: {err.strip()}"
    return True, rel_str


def restage_written_files(
    worktree_dir: Union[str, Path],
    rel_paths: List[str],
    *,
    agent_id: Optional[str] = None,
) -> List[str]:
    """Backstop re-stage of every file an agent wrote this session.

    Per-write ``_auto_stage`` can silently skip (e.g. ``workspace.resolve``
    returns None), leaving deliverables UNTRACKED so ``commit_worktree``
    (which commits only PRE-STAGED changes) finds nothing and the agent's
    work never reaches its branch (smoke #2: backend app/* untracked →
    ``agent/backend`` empty). This is the backstop ``_auto_stage``'s own
    docstring promises. Re-stages each path via ``stage_file`` (so the
    dotfile filter still applies), resolving as ``worktree/<rel>`` — robust
    to the resolve→None failure mode. Idempotent; returns the rel paths
    successfully (re)staged.
    """
    wt = Path(worktree_dir).resolve()
    staged: List[str] = []
    seen: set = set()
    for rel in rel_paths or []:
        if not rel:
            continue
        key = str(rel)
        if key in seen:
            continue
        seen.add(key)
        ok, _info = stage_file(wt, wt / key, agent_id=agent_id)
        if ok:
            staged.append(key)
    return staged


# PROPOSAL #22 — ownership partition for deterministic agent/backend→integration
# conflict resolution. main.py + the other skeleton outputs are FRAMEWORK-owned
# (regenerated from the contract by backend_skeleton.write_backend_skeleton /
# write_backend_build_infra + the oauth_scaffold AS modules), so on a conflict they
# take INTEGRATION's by-construction version; ``custom_routes.py`` is THE ONE
# lane-owned backend file (backend_skeleton _MAIN_FOOTER: "the framework NEVER writes
# it"), so it takes the AGENT's version (the lane's real business logic). Keep these
# in sync with the skeleton writer's file list. Matched by basename under app/backend/.
_BACKEND_FRAMEWORK_OWNED = frozenset({
    "main.py", "models.py", "database.py", "auth_dependency.py", "schemas.py",
    "pyproject.toml", "Dockerfile", "reset.sh",
    "oauth_routes.py", "oauth_store.py", "jwt_manager.py",
    # seed_data.py is the framework-owned LOADER (reads the lane-owned seed_data.json,
    # hashes passwords, backfills owners). The DATA file seed_data.json is lane-owned
    # (authored by the backend agent) and is intentionally NOT listed here.
    "seed_data.py",
})
# custom_routes.py = non-standard business logic; seed_data.json = the demo DATA the
# backend agent authors (the framework's seed_data.py loader consumes it).
_BACKEND_LANE_OWNED = frozenset({"custom_routes.py", "seed_data.json"})
# PROPOSAL #23 — the frontend lane AUTHORS App.jsx (the framework only ADDITIVELY
# injects declared routes into it via #19 project_missing_ui_routes, which re-runs
# every heal tick + at release), so App.jsx resolves to the LANE; the framework owns
# the build/infra files it pins (main.jsx entry, vite/tailwind/postcss config,
# Dockerfile/nginx/start, package manifests).
_FRONTEND_FRAMEWORK_OWNED = frozenset({
    "main.jsx", "vite.config.js", "tailwind.config.js", "postcss.config.js",
    "index.html", "Dockerfile", "nginx.conf", "nginx.conf.template", "start.sh",
    "package.json", "package-lock.json",
})
_FRONTEND_LANE_OWNED = frozenset({"App.jsx"})
# The frontend lane AUTHORS everything under these dirs — pages, components, the api
# service layer, and the client-logic free zones. The framework only projects FALLBACK
# stubs for declared pages; when the lane authored a real file the framework also
# stubbed, an add/add conflict arises on merge — resolve it to the LANE (the agent's
# real file supersedes the stub). Prefix-matched (per-page basenames are unknowable up
# front). Without this the resolver aborted on src/pages/* (basename not in the owned
# set) → the frontend's work was stranded out of integration → the run STALLED (the
# verifier waits on frontend, which never merged).
_FRONTEND_LANE_OWNED_DIRS = (
    "src/pages/", "src/components/", "src/services/",
    "src/hooks/", "src/contexts/", "src/lib/", "src/utils/",
)
# lane → (path prefix, framework-owned basenames, lane-owned basenames)
_OWNERSHIP = {
    "backend": ("app/backend/", _BACKEND_FRAMEWORK_OWNED, _BACKEND_LANE_OWNED),
    "frontend": ("app/frontend/", _FRONTEND_FRAMEWORK_OWNED, _FRONTEND_LANE_OWNED),
}

# #623 — A STASH FAILURE IS NOT A MERGE CONFLICT.
# When `git stash` cannot save a dirty worktree the pull is simply skipped: nothing merged,
# nothing conflicted, the agent's files untouched. It used to return False, and the caller
# publishes False as a `merge_conflict` event plus a P0 task titled "Resolve step-start merge
# conflict … resolve the conflicting files in your worktree".
#
# That false label is the ignition of the #622 storm. In r124 the FIRST FOUR events, all inside
# one minute and all BEFORE any real conflict existed, were this stash failure. The orchestrator
# did the one thing that makes a dirty tree stashable — it committed it:
#
#     codehub_commit("chore(orchestrator): clear worktree — commit stray BrowseHomePage.jsx …")
#
# a sound response to the message it was given, and the direct cause of 394 real conflicts over
# the next 70 minutes. Measured 187 times across 6+ runs; a concurrency cause was tested and
# REJECTED (within ±2s of another commit: 2.1% vs a 2.1% random-time control).
#
# This mirrors the `merge_failed_no_conflict` branch below, which already returns
# success-with-skip for exactly this reason. The caller logs it; the next step retries.
_STASH_SKIP_623 = ("stash_failed_no_conflict: worktree could not be stashed so the pull was "
                   "SKIPPED (nothing merged, no conflict, your files are untouched; retries "
                   "next step — do NOT commit files your lane does not own to clear it): {err}")


def _lane_of_worktree(wt: Path) -> str:
    """The lane name from a worktree's checked-out ``agent/<lane>`` branch, or ''."""
    rc, out, _e = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt)
    br = out.strip() if rc == 0 else ""
    return br.split("/", 1)[1] if br.startswith("agent/") else ""


def _resolve_conflict_by_ownership(repo: Path, *, lane: str,
                                   framework_side: str,
                                   superseded_out: Optional[List[str]] = None) -> Tuple[bool, str]:
    """PROPOSAL #22/#23 — deterministically resolve a framework-owned-file merge/pull
    conflict by per-path OWNERSHIP, so the framework's regenerated files and the lane's
    authored files both survive and the conflict stops blocking delivery. SHARED by both
    git paths; the only difference is DIRECTION:
      * MERGE (merge_agent_branch_to_main, integration checked out): framework=``--ours``
      * PULL  (pull_main_into_worktree, lane worktree checked out):  framework=``--theirs``
    so the caller passes ``framework_side`` and the lane-owned side is the opposite.
    Resolves framework-owned basenames (per the ``lane``'s _OWNERSHIP entry) to the
    framework side, lane-owned basenames to the lane side; if ANY conflicted path is
    OUTSIDE the known owned-set, returns ``(False, ...)`` so the caller aborts (never
    guess on a path a lane legitimately owns). Best-effort; never raises. (Index carries
    the unmerged stages, so ``git checkout --ours/--theirs -- <path>`` + ``git add`` is
    the standard resolution; add/add resolves the same way.)

    #622 — A LANE HAS NO CLAIM ON ANOTHER LANE'S TERRITORY.
    The rule above only ever fired for a lane that is IN the ownership map, and only for
    paths under ITS OWN prefix. Everything else aborted. Measured over 15 runs that is the
    minority case: of 2091 conflicted-file mentions, 1907 (91%) are CROSS-TERRITORY — a
    lane conflicting on a path belonging to a different lane — and only 184 are the
    same-territory case this resolver was written for.

    The consequence was a permanent stall, not a slowdown. `agent/orchestrator` is not in
    the map, so every step-start pull aborted and re-hit the identical conflict: 394 times
    in r124, 306 in r129, 227 in r137, still failing at the final second of the run in 8 of
    15 runs. Ground truth (`git merge-tree agent/orchestrator integration` on the kept
    repo) still reproduces it today.

    The trigger is the interesting part, because it was an agent REPAIRING itself. Handed a
    P0 "resolve the conflicting files in your worktree", the orchestrator ran
    `codehub_commit("clear worktree — commit stray BrowseHomePage.jsx … so step_start_pull
    can succeed")`. That turned a stashable dirty file into a divergent commit on a branch
    that never merges. In the 50 min before it: 4 conflicts, none on that file. In the 70
    min after: 394, ALL on that file — a 70.8x rate change. Its repair CAUSED the storm,
    and nothing ever told it so.

    Ownership decides this without guessing: a path under a DIFFERENT lane's prefix is one
    this worktree cannot be authoritative about, so it takes the integration side —
    ``framework_side``, which is the shared side in both directions (merge: ``--ours``,
    pull: ``--theirs``). Paths under NO known prefix still abort, and an unidentifiable lane
    (``lane == ""``) still aborts — if we cannot say whose worktree this is, we must not
    discard its work.

    WHY DISCARDING IS SAFE, structurally: ``docker/docker-compose.yml`` builds ``../app/backend``
    and ``../app/frontend`` — the ROOT tree, which is checked out on ``integration``. No lane
    worktree is ever a build context, so resolving a conflict inside one cannot change what
    ships. (An earlier draft of this comment argued it statistically, from "0 of those commits
    had reached integration". That reasoning was WRONG and is recorded here as a trap: lane
    merges are SQUASH merges, so ``integration..agent/<lane>`` lists commits whose CONTENT is
    already in integration — it over-counted 84 branches where a content diff finds 54, and a
    content diff in turn only proves the branch is stale. Ancestry cannot answer this question.)
    """
    try:
        spec = _OWNERSHIP.get(lane)
        if not spec and not lane:
            # #622: an unnamed lane could BE the owner — never discard on a guess.
            return False, "lane could not be identified; not resolving by ownership"
        prefix, framework_owned, lane_owned = spec if spec else ("", (), ())
        # #622: territory belonging to some lane OTHER than this one.
        others = tuple(pre for _l, (pre, _f, _o) in _OWNERSHIP.items() if _l != lane)
        lane_side = "--theirs" if framework_side == "--ours" else "--ours"
        rc, out, _e = _run_git(
            ["diff", "--name-only", "--diff-filter=U"], cwd=repo)
        paths = [p.strip() for p in out.splitlines() if p.strip()] if rc == 0 else []
        if not paths:
            return False, "no conflicted paths to resolve"
        resolved: List[str] = []
        for p in paths:
            base = p.rsplit("/", 1)[-1]
            rel = p[len(prefix):] if prefix and p.startswith(prefix) else ""
            if prefix and p.startswith(prefix) and base in framework_owned:
                side, who = framework_side, "framework"
            elif prefix and p.startswith(prefix) and (
                    base in lane_owned
                    or (lane == "frontend"
                        and rel.startswith(_FRONTEND_LANE_OWNED_DIRS))):
                side, who = lane_side, "lane"
            elif p.startswith(others):
                # #622: another lane's territory → the shared side wins, always.
                side, who = framework_side, "other-lane-territory"
            else:
                return False, f"conflict path outside {lane}-owned set: {p}"
            rcc, _o, ec = _run_git(["checkout", side, "--", p], cwd=repo)
            if rcc != 0:
                return False, f"checkout {side} {p} failed: {ec.strip()}"
            _run_git(["add", "--", p], cwd=repo)
            resolved.append(f"{p}→{who}")
            # PROPOSAL #26 N2: surface the paths where the LANE's edit was SUPERSEDED
            # by the framework (framework-owned paths kept the framework's version) so
            # the hub-holding caller can notify the lane (it would otherwise re-edit
            # these → re-conflict). Lane-owned paths kept the lane's version → not a
            # supersede. auto_commit stays hub-free: we only populate the caller's list.
            # #622: cross-territory paths are superseded for the SAME reason and need the
            # notice MORE — the orchestrator that committed a stray page had no other way
            # to learn its repair was the thing generating the conflict.
            if who in ("framework", "other-lane-territory") and superseded_out is not None:
                superseded_out.append(p)
        return True, "resolved by ownership: " + ", ".join(resolved)
    except Exception as exc:  # never raise into the merge/coordination loop
        return False, f"ownership-resolve raised: {type(exc).__name__}: {exc}"


def _resolve_backend_conflict_by_ownership(
        repo: Path, superseded_out: Optional[List[str]] = None) -> Tuple[bool, str]:
    """PROPOSAL #22 — backend MERGE path (integration checked out → framework=--ours).
    Thin wrapper over the shared direction-aware resolver so the two git paths share one
    ownership source-of-truth and cannot drift."""
    return _resolve_conflict_by_ownership(
        repo, lane="backend", framework_side="--ours", superseded_out=superseded_out)


def merge_agent_branch_to_main(
    *,
    repo_root: Union[str, Path],
    agent_branch: str,
    main_branch: str = "integration",
    agent_id: str = "",
    superseded_out: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """Merge ``agent_branch`` (e.g. ``agent/backend``) into ``main_branch``
    (default ``agent``) via squash-merge. Triggered after each agent's
    auto-commit so verifier/other agents pulling ``agent`` main see the
    integrated state.

    Returns ``(ok, info_or_error)``:
        * ``(True, sha)`` — merge produced a new commit; sha is the SHORT SHA
        * ``(True, "nothing to merge")`` — agent branch has no new commits
        * ``(False, "conflict: ...")`` — merge conflict; caller should emit
          an issue event and let humans/orchestrator decide
        * ``(False, "...")`` — any other git error

    Implementation note: operates on the bare ``repo_root`` (the project
    base), NOT on a worktree. Each worktree has its branch checked out
    and locked; we instead use ``git fetch . agent/<id>:agent`` or
    ``checkout agent && merge``. We pick a robust 3-step:
      1. ``git branch --merged agent`` to see if anything's new
      2. ``git checkout agent`` in repo_root
      3. ``git merge --squash --no-commit agent/<id>``
      4. ``git commit --author=...``
    On conflict: ``git merge --abort`` to clean up.
    """
    repo = Path(repo_root).resolve()
    if not (repo / ".git").exists():
        return False, f"not a git repo: {repo}"

    # Step 1 — does agent_branch have commits not in main_branch?
    rc, out, _err = _run_git(
        ["log", f"{main_branch}..{agent_branch}", "--oneline"], cwd=repo,
    )
    if rc == 0 and not out.strip():
        return True, "nothing to merge"
    # If main_branch doesn't exist yet, create it pointing at agent_branch
    # — first-commit-on-the-shared-main bootstrap.
    rc_check, _o, _e = _run_git(["rev-parse", "--verify", main_branch], cwd=repo)
    if rc_check != 0:
        rc_create, _o, err_create = _run_git(
            ["branch", main_branch, agent_branch], cwd=repo,
        )
        if rc_create != 0:
            return False, f"create {main_branch} failed: {err_create.strip()}"
        return True, "bootstrapped main from agent branch"

    # Step 2 — checkout main_branch in repo_root. The repo_root is NOT a
    # worktree (worktrees are sub-paths), so HEAD here is independent.
    # ``git checkout`` refuses if TRACKED dirty files would be overwritten
    # by switching branches — observed in live runs when a previous
    # ``--squash --no-commit`` left staged changes that didn't fully
    # commit. Stash them, checkout, then drop the stash; on conflict
    # restore the stash so the operator can recover.
    #
    # Smoke #22 root cause + fix (2026-06-03): pre-fix this used
    # ``git stash push -u`` which ALSO captured untracked files. The
    # workspace root has critical untracked state under ``shared/hubs/``
    # (workhub_pages.json + workhub_tasks.json + workhub_attendees.json
    # + workhub_comments.json — hub state owned by HubRegistry, never
    # tracked by git on purpose). The `-u` flag stashed those, then
    # the subsequent ``git stash drop`` (line below) PERMANENTLY
    # DESTROYED them. Smoke #21 + #22 both wedged because the kickoff
    # meeting page vanished from workhub_pages.json every time
    # ``merge_agent_branch_to_main`` ran on a finishing lane.
    #
    # New behavior: filter the ``status --porcelain`` lines to
    # IGNORE untracked entries (lines starting with "??") — they
    # don't block ``git checkout`` (untracked files survive branch
    # switches; only tracked-modified files conflict). Only
    # tracked-modified state triggers the stash. The stash command
    # drops ``-u`` so untracked files stay in the working tree
    # across the merge. Hub state survives.
    rc_st, st_out, _err = _run_git(["status", "--porcelain"], cwd=repo)
    tracked_dirty_lines = [
        line for line in st_out.splitlines()
        if rc_st == 0 and line.strip() and not line.startswith("??")
    ]
    repo_dirty = bool(tracked_dirty_lines)
    repo_stashed = False
    if repo_dirty:
        rc_sp, _so, se_sp = _run_git(
            # NO `-u` — keep untracked (hub state) on disk.
            ["stash", "push", "-m", "auto-merge-pre-checkout"], cwd=repo,
        )
        if rc_sp == 0:
            repo_stashed = True
        else:
            # Stash failed (e.g. nothing to stash after all). Try a hard
            # reset as last resort — only resets TRACKED state to HEAD;
            # untracked hub state (shared/hubs/) is preserved.
            _run_git(["reset", "--hard", "HEAD"], cwd=repo)
    sc, _so, se = _run_git(["checkout", main_branch], cwd=repo)
    if sc != 0:
        if repo_stashed:
            _run_git(["stash", "pop"], cwd=repo)
        return False, f"checkout {main_branch} failed: {se.strip()}"
    if repo_stashed:
        # Drop the stash — the changes were transient leftovers from a
        # prior incomplete merge, not real work to preserve. Untracked
        # files weren't stashed so this drop is now safe.
        _run_git(["stash", "drop"], cwd=repo)

    # Step 3 — squash merge with --no-commit so we can set the author.
    mc, _mo, me = _run_git(
        ["merge", "--squash", "--no-commit", agent_branch], cwd=repo,
    )
    if mc != 0 and "untracked working tree files would be overwritten" in ((me or "") + (_mo or "")):
        # Not a true merge conflict — agent_branch TRACKS files that exist as
        # UNTRACKED residue in repo_root. At scale (full-instagram) this is the
        # framework-scaffolded app surface: the runtime writes app/database/ +
        # design/README.md + docker/ into integration's working tree AFTER the
        # lanes branched, so they sit untracked; git's fast-forward then refuses
        # to overwrite them and the lane is stranded → orchestrator spins. Git
        # prefixes each colliding path with a tab; the list can land in stdout OR
        # stderr, and names files AND directories, so parse both streams and clean
        # with -d. RESTRICT cleaning to app-level paths so the intentionally-
        # untracked hub state (shared/hubs/*) and dot-state (.agents/, .memory/,
        # .checkpoint) are NEVER touched. The lane's tracked versions arrive via
        # the merge; the orchestrator's heal tick re-applies any framework repair.
        blob = (me or "") + "\n" + (_mo or "")
        colliding: List[str] = [
            line.lstrip("\t").strip()
            for line in blob.splitlines()
            if line.startswith("\t") and line.strip()
        ]
        safe = [
            c for c in colliding
            if c and not c.startswith("shared/") and not c.startswith(".")
        ]
        if safe:
            _run_git(["clean", "-fd", "--", *safe], cwd=repo)
        else:
            # Collision list not parseable from either stream — fall back to
            # cleaning the framework app dirs wholesale (still preserving
            # shared/hubs + dot-state, which we never name here).
            for _d in ("app", "design", "docker", "docs"):
                _dp = Path(repo) / _d
                if not _dp.exists():
                    continue
                if _d == "design":
                    # #388: NEVER git-clean design/dataset — it is the framework's REAL
                    # seed source that _ensure_seed_dataset regenerates app/backend/
                    # seed_dataset.json from on every tick. Cleaning design/ wholesale
                    # removed it, so the api-smoke image shipped an EMPTY catalog → GET
                    # /api/titles [] → POST /api/titles/1/rating 404 → business_chain
                    # STUCK abort (netflix r13). Clean the colliding framework residue
                    # (design/README.md etc.) but PRESERVE dataset. Agents never author
                    # design/, so dataset can never be a genuine merge collision.
                    for _sub in _dp.iterdir():
                        if _sub.name == "dataset":
                            continue
                        _run_git(["clean", "-fd", "--",
                                  str(_sub.relative_to(repo))], cwd=repo)
                else:
                    _run_git(["clean", "-fd", "--", _d], cwd=repo)
        mc, _mo, me = _run_git(
            ["merge", "--squash", "--no-commit", agent_branch], cwd=repo,
        )
    if mc != 0:
        # PROPOSAL #22/#23: for an OWNED lane (backend + frontend), try a deterministic
        # per-path ownership resolution BEFORE aborting — framework-owned skeleton/infra
        # files keep integration's by-construction version; lane-owned files take the
        # lane's authored version (backend → custom_routes.py; frontend → App.jsx +
        # src/pages|components|services|hooks|contexts|lib|utils). This unblocks the
        # agent/<lane>→integration merge that otherwise deadlocks delivery: the framework
        # projects FALLBACK page stubs into integration, the frontend authors the real
        # pages, and the resulting add/add conflict used to abort → the frontend's work
        # was stranded out of integration → run STALL (the verifier waits on frontend,
        # which never merged). Any conflict touching a path OUTSIDE the lane's owned set
        # still aborts (the resolver returns False) so a lane that legitimately owns an
        # unmapped path is never corrupted.
        _lane = agent_branch.split("/", 1)[1] if agent_branch.startswith("agent/") else ""
        res_ok, res_info = False, ""
        if _lane in _OWNERSHIP:
            res_ok, res_info = _resolve_conflict_by_ownership(
                repo, lane=_lane, framework_side="--ours", superseded_out=superseded_out)
        if res_ok:
            # conflicts resolved + staged → fall through to Step 4 (commit).
            # superseded_out (if passed) now carries the framework-superseded
            # paths for the caller to notify the lane (PROPOSAL #26 N2).
            pass
        else:
            # non-owned lane (verifier/debugger/…) OR a conflict on an unmapped path —
            # abort cleanly and report; the orchestrator/humans decide.
            _run_git(["merge", "--abort"], cwd=repo)
            try:
                _run_git(["reset", "--hard", "HEAD"], cwd=repo)
            except Exception:
                pass
            _suffix = f" [{res_info}]" if res_info else ""
            return False, (f"conflict merging {agent_branch} → {main_branch}: "
                           f"{me.strip()}{_suffix}")

    # Step 4 — commit with agent author.
    author = agent_id or agent_branch.split("/")[-1]
    author_email = f"{author}@env-gen.local"
    env_override = {
        "GIT_AUTHOR_NAME": author,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    env = {**os.environ, **env_override}
    message = f"merge {agent_branch} → {main_branch}"
    # Empty index after squash (branch already integrated) is a benign success,
    # but ``git commit -q`` exits 1 and ``-q`` suppresses the "nothing to commit"
    # text the check below relies on. Detect the empty index explicitly.
    rc_staged, _ds, _de = _run_git(["diff", "--cached", "--quiet"], cwd=repo)
    if rc_staged == 0:
        return True, "nothing to commit after squash (branch already integrated)"
    try:
        p = subprocess.run(
            ["git", "commit", "-qm", message],
            cwd=str(repo), env=env,
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
    except Exception as exc:
        return False, f"git commit (post-merge) raised: {exc}"
    if p.returncode != 0:
        # Could be "nothing to commit" if squash produced no changes after
        # all (rare race). Treat as benign.
        if "nothing to commit" in (p.stdout + p.stderr).lower():
            return True, "nothing to commit after squash"
        return False, f"git commit (post-merge) exit {p.returncode}: {p.stderr.strip()}"
    rc, out, _err = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo)
    sha = out.strip() if rc == 0 else "?"
    return True, sha


def resolve_merge_conflict_via_strategy(
    *,
    repo_root: Union[str, Path],
    agent_branch: str,
    main_branch: str = "integration",
    strategy: str = "agent",
    agent_id: str = "",
) -> Tuple[bool, str]:
    """Re-attempt a previously-conflicted merge of ``agent_branch`` →
    ``main_branch`` using a git strategy option.

    Called by the orchestrator (or a privileged caller) after Phase 0b
    has emitted a ``merge_conflict`` urgent event. Phase 0b aborts the
    failed merge cleanly — this helper retries with one of:

    * ``strategy="agent"``   → agent_branch wins on every conflict
      (``git merge -X theirs``, from main_branch's POV the incoming
      branch is "theirs"). Default — agent's work is typically newer
      and is the reason we're merging in the first place.
    * ``strategy="integration"`` → main_branch wins on conflicts
      (``git merge -X ours``). Use when integration's version has
      already been blessed by other agents and the new agent should
      defer.
    * Anything else → returns (False, "unknown strategy: ...").

    Returns ``(ok, info)`` with same semantics as
    ``merge_agent_branch_to_main``.
    """
    repo = Path(repo_root).resolve()
    if not (repo / ".git").exists():
        return False, f"not a git repo: {repo}"

    if strategy == "agent":
        merge_opt = "theirs"
    elif strategy == "integration":
        merge_opt = "ours"
    else:
        return False, f"unknown strategy: {strategy!r} (expected 'agent' or 'integration')"

    # Need main_branch to exist before we can re-attempt the merge.
    rc_check, _o, _e = _run_git(["rev-parse", "--verify", main_branch], cwd=repo)
    if rc_check != 0:
        # No integration yet — first merge bootstraps it via the regular path.
        return merge_agent_branch_to_main(
            repo_root=repo, agent_branch=agent_branch,
            main_branch=main_branch, agent_id=agent_id,
        )

    # Dirty-tree handling BEFORE the ``checkout main_branch`` (Bug 1, youtube
    # run, observed 6×). The agent left UNCOMMITTED edits in repo_root's
    # working tree (e.g. ``app/backend/main.py``); ``git checkout main_branch``
    # then aborts — "Your local changes to the following files would be
    # overwritten by merge ... Please commit your changes or stash them" — so
    # no conflict resolution ever runs.
    #
    # The regular path (``merge_agent_branch_to_main``) treats repo_root dirt
    # as transient prior-merge residue and stashes-then-DROPS it. That is the
    # wrong move HERE: this dirt is the AGENT's actual work, so dropping it
    # would silently discard the agent's edits. Instead, COMMIT the dirt onto
    # the AGENT branch (never onto main_branch) with the agent as author, so it
    # becomes part of the very branch we are about to integrate. Mirrors the
    # commit-WIP-before-integration shape used by ``pull_main_into_worktree``
    # (which commits in-progress subtrees rather than stashing them).
    rc_st, st_out, _err = _run_git(["status", "--porcelain"], cwd=repo)
    tracked_dirty = [
        line for line in (st_out or "").splitlines()
        if rc_st == 0 and line.strip() and not line.startswith("??")
    ]
    repo_stashed = False
    if tracked_dirty:
        # Determine the currently-checked-out branch deterministically.
        rc_cur, cur_out, _ce = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo)
        current_branch = cur_out.strip() if rc_cur == 0 else ""
        if current_branch == agent_branch:
            # Genuinely ON the agent branch (a non-worktree caller): the dirt is
            # the agent's own WIP → commit it onto the agent branch so it becomes
            # part of the very branch we're about to integrate (never onto
            # main_branch). git carries the edits; we author as the agent.
            wip_author = agent_id or agent_branch.split("/")[-1]
            wip_email = f"{wip_author}@env-gen.local"
            wip_env = {
                **os.environ,
                "GIT_AUTHOR_NAME": wip_author,
                "GIT_AUTHOR_EMAIL": wip_email,
                "GIT_COMMITTER_NAME": wip_author,
                "GIT_COMMITTER_EMAIL": wip_email,
            }
            _run_git(["add", "-A"], cwd=repo)
            try:
                subprocess.run(
                    ["git", "commit", "--no-verify", "-qm",
                     f"auto-commit uncommitted work on {agent_branch} "
                     f"before strategic merge"],
                    cwd=str(repo), env=wip_env,
                    capture_output=True, text=True, timeout=_GIT_TIMEOUT,
                )
            except Exception as exc:
                return False, f"auto-commit WIP before strategic merge raised: {exc}"
        else:
            # current_branch is main_branch (integration). The repo_root tracked
            # dirt is the FRAMEWORK's scaffold/heal residue (skeleton/infra/route
            # projections written into the integration working tree, committed
            # later by commit_framework_delivery) — NOT the agent's work, which
            # lives in worktrees/<id>. agent_branch is checked out in its OWN
            # worktree, so a `git checkout agent_branch` here is IMPOSSIBLE (git
            # forbids a 2nd checkout of a worktree-held branch — this was the run
            # #34 "strategic merge blocked … already checked out at worktrees/…"
            # wedge that starved the ownership resolver). Stash the transient
            # residue (mirrors merge_agent_branch_to_main) so the checkout+merge
            # can proceed; the scaffold re-emits these files every tick, so
            # dropping the stash is safe. NO -u → keep untracked hub state on disk.
            rc_sp, _so_sp, _se_sp = _run_git(
                ["stash", "push", "-m", "strategic-merge-pre-checkout"], cwd=repo)
            if rc_sp == 0:
                repo_stashed = True
            else:
                # Nothing stashable / stash failed — hard-reset TRACKED state to
                # HEAD as last resort (untracked hub state is preserved).
                _run_git(["reset", "--hard", "HEAD"], cwd=repo)

    sc, _so, se = _run_git(["checkout", main_branch], cwd=repo)
    if sc != 0:
        if repo_stashed:
            _run_git(["stash", "pop"], cwd=repo)
        return False, f"checkout {main_branch} failed: {se.strip()}"
    if repo_stashed:
        # Transient framework residue — drop it (the scaffold re-emits + commits
        # it via commit_framework_delivery). Untracked state wasn't stashed.
        _run_git(["stash", "drop"], cwd=repo)

    # Squash-merge with strategy option. --no-commit so we can author.
    mc, _mo, me = _run_git(
        ["merge", "--squash", "--no-commit", "-X", merge_opt, agent_branch],
        cwd=repo,
    )
    if mc != 0 and "untracked working tree files would be overwritten" in (me or ""):
        # Not a true conflict — agent_branch tracks files that exist as untracked
        # residue in repo_root (e.g. memory-bank/<lane>/*.md or a generated tree
        # left over from a prior worktree op). Mirror merge_agent_branch_to_main:
        # clean the tab-prefixed colliding paths and retry. (smoke #12b: this
        # blocked the agent/backend → integration merge → 0 release.)
        colliding: List[str] = [
            line.lstrip("\t").strip()
            for line in me.splitlines()
            if line.startswith("\t") and line.strip()
        ]
        if colliding:
            _run_git(["clean", "-f", "--", *colliding], cwd=repo)
            mc, _mo, me = _run_git(
                ["merge", "--squash", "--no-commit", "-X", merge_opt, agent_branch],
                cwd=repo,
            )
    if mc != 0:
        # Even with -X strategy, true tree-level conflicts (add/add of
        # different file content with both as binary, etc.) can fail.
        _run_git(["merge", "--abort"], cwd=repo)
        return False, f"strategic merge still conflicts: {me.strip()}"

    author = agent_id or agent_branch.split("/")[-1]
    author_email = f"{author}@env-gen.local"
    env_override = {
        "GIT_AUTHOR_NAME": author,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    env = {**os.environ, **env_override}
    message = f"merge {agent_branch} → {main_branch} (resolved via strategy={strategy})"
    # ``--squash --no-commit`` left the merge result in the index. If the index
    # is EMPTY (the agent branch is already integrated, or the strategic squash
    # netted no change) then committing is a no-op that SUCCEEDED — but
    # ``git commit -q`` exits 1 and ``-q`` SUPPRESSES the "nothing to commit"
    # text, so the string check below misreads it as a real failure and the
    # orchestrator wrongly reports the merge blocked (smoke #8/#11:
    # "codehub_resolve_merge_conflict FAILED: git commit exit 1" with empty
    # stderr → delivery blocked on an already-merged frontend). Detect the empty
    # index explicitly (``diff --cached --quiet`` rc 0 == nothing staged).
    rc_staged, _ds, _de = _run_git(["diff", "--cached", "--quiet"], cwd=repo)
    if rc_staged == 0:
        return True, "nothing to commit after squash (branch already integrated)"
    try:
        p = subprocess.run(
            ["git", "commit", "-qm", message],
            cwd=str(repo), env=env,
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
    except Exception as exc:
        return False, f"git commit (post-resolution) raised: {exc}"
    if p.returncode != 0:
        if "nothing to commit" in (p.stdout + p.stderr).lower():
            return True, "nothing to commit after squash"
        return False, f"git commit exit {p.returncode}: {p.stderr.strip()}"
    rc, out, _err = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo)
    sha = out.strip() if rc == 0 else "?"
    return True, sha


def revert_commit_on_branch(
    *,
    repo_root: Union[str, Path],
    branch: str,
    commit_sha: str,
    actor: str = "orchestrator",
) -> Tuple[bool, str]:
    """Revert ``commit_sha`` on ``branch`` (e.g. on the ``integration``
    branch to undo a bad merge). Produces a NEW commit that inverts the
    target commit's diff — safe history operation (no rewriting).

    Returns ``(ok, sha_or_error)``. On clean revert: ``(True, new_sha)``.
    Conflicts during revert: aborts cleanly and returns
    ``(False, "conflict: ...")``.
    """
    repo = Path(repo_root).resolve()
    if not (repo / ".git").exists():
        return False, f"not a git repo: {repo}"

    # Check we can resolve the SHA before doing destructive ops.
    rc_v, _o, err_v = _run_git(["rev-parse", "--verify", f"{commit_sha}^{{commit}}"], cwd=repo)
    if rc_v != 0:
        return False, f"commit not found: {commit_sha} ({err_v.strip()})"

    # Check the branch exists.
    rc_b, _o, err_b = _run_git(["rev-parse", "--verify", branch], cwd=repo)
    if rc_b != 0:
        return False, f"branch not found: {branch} ({err_b.strip()})"

    # Checkout the branch in the repo root (not a worktree — worktrees
    # have their own branches locked).
    sc, _so, se = _run_git(["checkout", branch], cwd=repo)
    if sc != 0:
        return False, f"checkout {branch} failed: {se.strip()}"

    author = actor
    author_email = f"{author}@env-gen.local"
    env_override = {
        "GIT_AUTHOR_NAME": author,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    env = {**os.environ, **env_override}
    try:
        p = subprocess.run(
            ["git", "revert", "--no-edit", commit_sha],
            cwd=str(repo), env=env,
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
    except Exception as exc:
        return False, f"git revert raised: {exc}"
    if p.returncode != 0:
        # Abort the half-applied revert so the branch stays clean.
        _run_git(["revert", "--abort"], cwd=repo)
        return False, f"revert conflict: {p.stderr.strip()}"
    rc, out, _err = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo)
    new_sha = out.strip() if rc == 0 else "?"
    return True, new_sha


def pull_main_into_worktree(
    *,
    worktree_dir: Union[str, Path],
    main_branch: str = "integration",
    superseded_out: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """Pull ``main_branch`` into the agent's worktree so the agent sees
    OTHER agents' committed-and-merged work at the start of its step.

    Strategy: ``git merge --no-edit main_branch`` inside the worktree.
    The worktree's own branch (``agent/<id>``) receives commits from
    ``main_branch``. Subsequent agent commits diverge again from main
    until the next auto-merge.

    Dirty worktrees: ``git merge`` refuses when uncommitted changes
    would conflict, so we stash first, merge, then pop. If the stash
    pop conflicts we abort and report; the caller emits the issue
    event and the agent's next step gets a chance to resolve.

    Returns ``(ok, info)``. On conflict: aborts and reports — the
    agent's next step receives an issue event.
    """
    wt = Path(worktree_dir).resolve()
    if not wt.exists():
        return False, f"worktree missing: {wt}"

    # Bail-out if main_branch doesn't exist yet (no agent has merged anything).
    rc_check, _o, _e = _run_git(["rev-parse", "--verify", main_branch], cwd=wt)
    if rc_check != 0:
        return True, f"main branch {main_branch} does not exist yet; skipping pull"

    # Is there anything to pull?
    rc, out, _err = _run_git(
        ["log", f"HEAD..{main_branch}", "--oneline"], cwd=wt,
    )
    if rc == 0 and not out.strip():
        return True, "already up to date"

    # Dirty-tree handling. The May 29 facebook-clone run audit
    # diagnosed a 19h stall caused by stash-pop conflicts on
    # untracked ``memory-bank/<role>/*.md`` files: stash -u captures
    # them, the merge of integration pulls in the same files from
    # another agent's commit, and stash pop fails with "already
    # exists, no checkout". Closed-by-construction fix: memory-bank
    # is each agent's OWN scratch subtree — commit it onto the
    # agent's branch BEFORE the pull so it lands as a regular merge
    # ancestor (no stash, no conflict). For any other dirty content
    # we still use stash; the stash-pop recovery path
    # (``checkout --theirs`` + ``stash drop``) handles whatever the
    # commit-first path doesn't.
    rc_st, st_out, _err = _run_git(["status", "--porcelain"], cwd=wt)
    dirty = bool(rc_st == 0 and st_out.strip())
    stashed = False
    if dirty:
        # Parse `git status --porcelain` to split memory-bank lines
        # from the rest. Format: 2 status chars + " " + path (or
        # rename "orig -> new").
        memory_bank_paths: List[str] = []
        non_memory_dirty = False
        for line in st_out.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].split(" -> ")[-1].strip()
            if path.startswith("memory-bank/"):
                memory_bank_paths.append(path)
            else:
                non_memory_dirty = True

        # Auto-commit memory-bank files first so they survive the
        # merge as ancestor commits — no stash needed for this part.
        if memory_bank_paths and not non_memory_dirty:
            _run_git(["add", "--", *memory_bank_paths], cwd=wt)
            rc_c, _co, se_c = _run_git(
                ["commit", "--no-verify",
                 "-m", "auto-commit memory-bank before integration pull"],
                cwd=wt,
            )
            if rc_c != 0:
                # If commit fails (unusual — empty diff, hook issue),
                # fall back to the stash path so we don't lose state.
                rc_sp, _so, se_sp = _run_git(
                    ["stash", "push", "-u", "-m", "auto-pull-integration"],
                    cwd=wt,
                )
                if rc_sp != 0:
                    return True, _STASH_SKIP_623.format(err=se_sp.strip())
                stashed = True
        else:
            # Mixed dirty or no memory-bank — use stash for safety.
            rc_sp, _so, se_sp = _run_git(
                ["stash", "push", "-u", "-m", "auto-pull-integration"],
                cwd=wt,
            )
            if rc_sp != 0:
                return True, _STASH_SKIP_623.format(err=se_sp.strip())
            stashed = True

    mc, _mo, me = _run_git(
        ["merge", "--no-edit", main_branch], cwd=wt,
    )
    if mc != 0:
        # Round 8h Patch A: not every non-zero `git merge` exit is a
        # real code-level conflict — pre-commit hooks, signing
        # requirements, or transient I/O can also produce non-zero
        # exits with NO unmerged paths in the index. Pre-fix the
        # smoke #18 EventHub had 184 spurious merge_conflict events
        # (`phase=step_start_pull`) drowning out the 5 legitimate
        # kickoff/task_created events; the orchestrator log
        # diagnosed them as "engine-level metadata drift" because
        # they referenced paths/branches that didn't match actual
        # worktree state. By capturing the genuine conflict file
        # set BEFORE the abort, we can distinguish a real conflict
        # (return False — caller emits the event) from an
        # everything-else failure (return True — caller skips the
        # emit, logs warning).
        rc_diff, df_out, _ = _run_git(
            ["diff", "--name-only", "--diff-filter=U"], cwd=wt,
        )
        conflict_files = (
            [ln.strip() for ln in df_out.splitlines() if ln.strip()]
            if rc_diff == 0 else []
        )
        # PROPOSAL #23: the SAME framework-owned-file conflict class as the MERGE path
        # (#22), here on the step-start PULL (integration → lane worktree). Resolve
        # per-path by ownership BEFORE aborting, so the lane stops re-hitting the
        # identical conflict every step and finally converges. DIRECTION is reversed
        # vs the merge: the worktree has the lane's branch checked out, so framework
        # files = ``--theirs`` (integration) and lane files = ``--ours``. Scoped to
        # known lanes (backend/frontend) + their owned paths; anything else → abort+event.
        # The pull is a real ``git merge`` (not --squash), so COMMIT to finish it.
        _pull_resolved = False
        if conflict_files:
            _lane = _lane_of_worktree(wt)
            _res_ok, _res_info = _resolve_conflict_by_ownership(
                wt, lane=_lane, framework_side="--theirs",
                superseded_out=superseded_out)  # PROPOSAL #26 N2
            if _res_ok:
                rc_ci, _ci, _ec = _run_git(["commit", "--no-edit"], cwd=wt)
                _pull_resolved = (rc_ci == 0)
        if not _pull_resolved:
            _run_git(["merge", "--abort"], cwd=wt)
            if stashed:
                # Restore the agent's uncommitted work so they don't lose it.
                _run_git(["stash", "pop"], cwd=wt)
            if not conflict_files:
                # Non-conflict merge failure (signing / hook / transient).
                # The worktree was returned to HEAD by `merge --abort`.
                # Return success-with-skip so step_runner.py does NOT
                # publish a misleading merge_conflict event. The next
                # step retries the pull, which is the same recovery
                # behavior as before — just without the false alarm.
                return True, (
                    f"merge_failed_no_conflict pulling {main_branch} "
                    f"(worktree returned to HEAD; will retry next step): "
                    f"{me.strip()}"
                )
            return False, (
                f"conflict pulling {main_branch} "
                f"[files={','.join(conflict_files)}]: {me.strip()}"
            )
        # #23-resolved + committed → fall through to the stash-pop + sha return
        # below, exactly like a clean merge.

    if stashed:
        rc_pop, _po, se_pop = _run_git(["stash", "pop"], cwd=wt)
        if rc_pop != 0:
            # Pop hit conflicts (typically: untracked files that the
            # merge also brought in from another agent). Recovery:
            # the worktree state post-merge is authoritative — drop
            # the stashed copy of those paths so the stack doesn't
            # grow forever. If the agent had legitimate uncommitted
            # work being clobbered, the worktree state IS the merged
            # truth + the agent's next step picks up fresh from there.
            # This breaks the May 29 stall loop where every subsequent
            # step_start_pull re-hit the same stash.
            _run_git(["checkout", "--theirs", "."], cwd=wt)
            # Make the discard NON-silent: list any tracked files whose stashed WIP is
            # being dropped (the worktree's merged state is authoritative, so that WIP is
            # lost). Surfacing it in the logs turns a silent loss into a diagnosable one.
            try:
                _ss_rc, _ss_out, _ss_err = _run_git(
                    ["stash", "show", "--name-only", "stash@{0}"], cwd=wt)
                _lost = [ln for ln in (_ss_out or "").splitlines() if ln.strip()]
                if _lost:
                    _LOG.warning(
                        "pull_main_into_worktree: stash-pop conflicted; dropping stash — "
                        "stashed WIP discarded for %d tracked file(s): %s",
                        len(_lost), _lost[:20])
            except Exception:
                pass
            _run_git(["stash", "drop"], cwd=wt)
            # Continue — don't fail the pull. Worktree is in the
            # merged state; agent proceeds.

    rc, out, _err = _run_git(["rev-parse", "--short", "HEAD"], cwd=wt)
    sha = out.strip() if rc == 0 else "?"
    return True, sha


def promote_integration_to_main(
    *,
    repo_root: Union[str, Path],
    integration_branch: str = "integration",
    main_branch: str = "main",
    actor: str = "verifier",
    blessed_run_id: str = "",
) -> Tuple[bool, str]:
    """Fast-forward (or merge) ``integration_branch`` into ``main_branch``.

    Called by the verifier after a successful RunHub run so that
    ``main`` only ever points at code that has passed the latest
    verification. Auto-merge to integration stays unchanged — that's
    the WIP coordination branch — but ``main`` becomes the
    "verifier-blessed" reference. Other agents can still pull
    ``integration`` for cross-agent visibility; teams that want
    "only ship verified" can deploy from ``main``.

    Returns ``(ok, info)``:
      * ``(True, sha)``               — promotion succeeded; sha is the new HEAD
      * ``(True, "nothing to promote")`` — already up-to-date
      * ``(False, "...")``            — checkout, ff-merge, or commit failed
    """
    repo = Path(repo_root).resolve()
    if not (repo / ".git").exists():
        return False, f"not a git repo: {repo}"

    rc_chk_int, _o, err_int = _run_git(
        ["rev-parse", "--verify", integration_branch], cwd=repo,
    )
    if rc_chk_int != 0:
        return False, f"integration branch missing: {integration_branch} ({err_int.strip()})"

    rc_chk_main, _o, _e = _run_git(["rev-parse", "--verify", main_branch], cwd=repo)
    if rc_chk_main != 0:
        # Bootstrap: create main from integration.
        rc_b, _o, err_b = _run_git(
            ["branch", main_branch, integration_branch], cwd=repo,
        )
        if rc_b != 0:
            return False, f"create {main_branch} failed: {err_b.strip()}"
        return True, "bootstrapped main from integration"

    # Anything new to promote?
    rc_log, out_log, _err = _run_git(
        ["log", f"{main_branch}..{integration_branch}", "--oneline"], cwd=repo,
    )
    if rc_log == 0 and not out_log.strip():
        return True, "nothing to promote"

    sc, _so, se = _run_git(["checkout", main_branch], cwd=repo)
    if sc != 0:
        return False, f"checkout {main_branch} failed: {se.strip()}"

    # Try fast-forward first; fall back to a real merge commit with
    # the blessing recorded if histories diverged.
    rc_ff, _o, _e = _run_git(
        ["merge", "--ff-only", integration_branch], cwd=repo,
    )
    if rc_ff == 0:
        rc, sha, _err = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo)
        return True, sha.strip() if rc == 0 else "?"

    # Need a merge commit (main has commits integration doesn't).
    author = actor
    author_email = f"{author}@env-gen.local"
    env_override = {
        "GIT_AUTHOR_NAME": author,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    env = {**os.environ, **env_override}
    message = f"promote {integration_branch} → {main_branch}"
    if blessed_run_id:
        message += f" (blessed by run={blessed_run_id})"
    try:
        p = subprocess.run(
            ["git", "merge", "--no-ff", "-m", message, integration_branch],
            cwd=str(repo), env=env,
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
    except Exception as exc:
        return False, f"promotion merge raised: {exc}"
    if p.returncode != 0:
        _run_git(["merge", "--abort"], cwd=repo)
        return False, f"promotion merge conflict: {p.stderr.strip()}"
    rc, out, _err = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo)
    return True, out.strip() if rc == 0 else "?"


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
    rc, out, _err = _run_git(["rev-parse", "--short", "HEAD"], cwd=wt)
    sha = out.strip() if rc == 0 else "?"
    return True, sha


def flush_worktree(
    *,
    worktree_dir: Union[str, Path],
    branch: str,
    author: str,
    message: str = "flush: capture uncommitted lane work before merge",
) -> Tuple[bool, str]:
    """Stage + commit any uncommitted/untracked APP work in a lane's worktree so
    it reaches its agent branch (and thus integration on the next merge).

    Why: files an agent WROTE but no commit-gate captured (e.g. pages the
    frontend authored but never finish-committed) are invisible to the squash
    merge ('nothing to merge') → integration ships a blank shell
    (``frontend_navigable: 0``), which idle-wedges the run. This flush is the
    safety net the merge needs. Scoped to deliverable dirs (``app``/``mcp_server``
    /``docker``) and excludes build junk (node_modules / dist / __pycache__ /
    .venv). Best-effort; 'nothing to commit' is fine; never raises."""
    wt = Path(worktree_dir).resolve()
    if not (wt / ".git").exists() and not (wt.parent / ".git").exists():
        return True, "not a git worktree; skipping"
    subs = [s for s in ("app", "mcp_server", "docker") if (wt / s).exists()]
    if not subs:
        return True, "no deliverable dirs to flush"
    try:
        rc, _o, err = _run_git(
            ["add", "-A", "--", *subs,
             ":(exclude)**/node_modules/**", ":(exclude)**/__pycache__/**",
             ":(exclude)**/*.py[cod]", ":(exclude)**/dist/**", ":(exclude)**/.venv/**"],
            cwd=wt)
    except Exception as exc:
        return False, f"git add -A raised: {exc}"
    if rc != 0:
        return False, f"git add -A exit {rc}: {err.strip()}"
    return commit_worktree(worktree_dir=wt, branch=branch, author=author, message=message)
