#!/usr/bin/env bash
# Reclaim per-lane git worktrees from FINISHED runs.
#
# Same rules as the framework's own #1202as, which now does this at the end of every run:
#   * `git worktree remove` WITHOUT --force, so git refuses on a worktree holding
#     uncommitted work and that lane keeps its files. A refusal is a success here.
#   * branches are NEVER deleted, so every commit stays reachable and
#     `git log agent/<lane>` still answers. Only the redundant checkout goes.
#   * compiled-Python leftovers are removed first (#1202ay), because `__pycache__`
#     alone would otherwise keep a 186MB checkout alive to preserve build junk.
#
# DRY RUN by default. Set APPLY=1 to actually reclaim.
#   bash reclaim_worktrees.sh            # show what would happen
#   APPLY=1 bash reclaim_worktrees.sh    # do it
#
# SKIP protects runs you want left alone (space-separated, matched as substrings).
set -uo pipefail
REPO="${REPO:-/data/common/haibotong/forgingground-gen}"
SKIP="${SKIP:-netflix-local-r30 netflix-local-r31 netflix-local-r32}"
APPLY="${APPLY:-0}"

cd "$REPO/generated" || exit 1
tot_rm=0; tot_kept=0; bytes=0

for run in */; do
  run="${run%/}"
  [ -d "$run/worktrees" ] || continue
  skip=0
  for s in $SKIP; do case "$run" in *"$s"*) skip=1;; esac; done
  [ "$skip" = 1 ] && { echo "SKIP $run (protected)"; continue; }

  for wt in "$run"/worktrees/*/; do
    [ -d "$wt" ] || continue
    wt="${wt%/}"
    sz=$(du -sb "$wt" 2>/dev/null | cut -f1)

    if [ "$APPLY" = 1 ]; then
      find "$wt" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
      find "$wt" \( -name '*.pyc' -o -name '*.pyo' -o -name '*.pyd' \) -delete 2>/dev/null
    fi

    # Ignore what the framework itself refuses to commit, so it cannot masquerade as
    # lane work: compiled Python (auto_commit refuses *.pyc unconditionally — committed
    # ones break agent->integration merges) and dotfiles outside auto_commit's allowlist
    # (.gitignore/.gitattributes/.gitkeep/.env.example), which is what `.agents/` is.
    # Anything else dirty — a modified .py/.jsx, an untracked source dir — still keeps
    # the worktree.
    dirty=$(git -C "$wt" status --porcelain 2>/dev/null \
            | grep -vE '(^|/|\s)__pycache__/|\.py[cod]$' \
            | grep -vE '^\?\? \.(agents|openenv_trash|pytest_cache|mypy_cache|ruff_cache)/' \
            | head -1)
    if [ -n "$dirty" ]; then
      echo "KEEP $wt  (uncommitted: $(echo "$dirty" | cut -c1-40))"
      tot_kept=$((tot_kept+1)); continue
    fi

    if [ "$APPLY" = 1 ]; then
      if git -C "$run" worktree remove "$PWD/$wt" 2>/dev/null; then
        tot_rm=$((tot_rm+1)); bytes=$((bytes+sz))
      else
        echo "KEEP $wt  (git refused)"; tot_kept=$((tot_kept+1))
      fi
    else
      tot_rm=$((tot_rm+1)); bytes=$((bytes+sz))
    fi
  done
  [ "$APPLY" = 1 ] && git -C "$run" worktree prune 2>/dev/null
done

echo
echo "$([ "$APPLY" = 1 ] && echo RECLAIMED || echo WOULD-RECLAIM): $tot_rm worktree(s), $(awk "BEGIN{printf \"%.1f\", $bytes/1073741824}") GB"
echo "KEPT (uncommitted work): $tot_kept"
df -h "$REPO" | tail -1
