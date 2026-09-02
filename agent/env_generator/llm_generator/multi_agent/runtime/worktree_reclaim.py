"""#1202as: give back the per-lane worktree checkouts once the run is over.

`git worktree add` had no counterpart anywhere in the pipeline. CodeHub has carried a
working `cleanup_worktree` since forever, but its single caller is
`agent_spawn_service.py`, which fires for EPHEMERAL spawned workers only — the resident
lanes (backend, frontend, verifier, debugger, orchestrator, every browser_test_user)
never had their checkouts reclaimed, and nothing ran at the end of a run.

Each of those checkouts is a full copy of `app/`, which is 186MB once seed media is
staged. tiktok-web-r74 finished with 24 of them: 4.4GB of the run's 4.7GB, twenty-four
byte-identical copies of one directory. Across the corpus that is 93GB of the 138GB under
generated/, and it is why /data reached 99% (46GB free) — the same disk pressure that
sits behind #1202ap's five orphaned temp files, one of them a 2.4MB fragment of a 6.5MB
hub written the day r19's hub read failed.

Nothing is lost by reclaiming them, and the two ways it could lose something are both
closed deliberately:

  * `git worktree remove` runs WITHOUT --force, so git refuses on a worktree with
    uncommitted changes and that lane's work stays exactly where it is. A refusal is a
    success for our purposes and is reported, not retried harder.
  * branches are NOT deleted. `cleanup_worktree` also runs `git branch -D agent/<id>`,
    which is right for a spawned worker but would make an unmerged lane's commits
    unreachable. Here only the redundant working copy goes; every commit stays in .git and
    `git log agent/<lane>` still answers, which is what run forensics actually reads.

Set ENVGEN_KEEP_WORKTREES=1 to keep them (e.g. to inspect a failed run's files in place).
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _dir_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except Exception:
            continue
    return total


def reclaim_run_worktrees_1202as(output_dir: Any) -> Dict[str, Any]:
    """Remove the run's per-lane worktree checkouts. Never raises. (#1202as)

    Returns a summary dict: removed / kept / bytes_reclaimed / skipped.
    """
    summary: Dict[str, Any] = {
        "removed": [], "kept": [], "bytes_reclaimed": 0, "skipped": ""}
    try:
        if os.environ.get("ENVGEN_KEEP_WORKTREES") == "1":
            summary["skipped"] = "ENVGEN_KEEP_WORKTREES=1"
            return summary

        root = Path(output_dir).resolve()
        wt_root = root / "worktrees"
        if not wt_root.is_dir():
            summary["skipped"] = "no worktrees directory"
            return summary

        for entry in sorted(wt_root.iterdir()):
            if not entry.is_dir():
                continue
            size = _dir_bytes(entry)
            try:
                subprocess.run(
                    ["git", "worktree", "remove", str(entry)],
                    cwd=str(root), capture_output=True, text=True, timeout=120,
                    check=True)
            except Exception as exc:
                # Dirty, locked, or not a worktree at all. Keeping it is the correct
                # outcome, not a failure to work around.
                summary["kept"].append(entry.name)
                logger.debug("#1202as kept %s: %s", entry.name, exc)
                continue
            summary["removed"].append(entry.name)
            summary["bytes_reclaimed"] += size

        if summary["removed"]:
            try:
                subprocess.run(["git", "worktree", "prune"], cwd=str(root),
                               capture_output=True, timeout=60)
            except Exception:
                pass
            logger.info(
                "#1202as reclaimed %d lane worktrees (%.1f GB); kept %d with uncommitted "
                "work. Branches untouched — every commit is still in .git.",
                len(summary["removed"]), summary["bytes_reclaimed"] / 1073741824,
                len(summary["kept"]))
        elif summary["kept"]:
            logger.info("#1202as kept all %d worktrees (uncommitted work or locked).",
                        len(summary["kept"]))
    except Exception as exc:
        from .message_format import warn_once_1201
        warn_once_1201("reclaim_run_worktrees_1202as",
                       "the end-of-run reclamation of per-lane worktree checkouts", exc)
    return summary
