#!/usr/bin/env bash
# Outer auto-agent filesystem boundary: only this experiment and private /tmp are writable.
set -euo pipefail
EXP=$(cd "$(dirname "$0")/.." && pwd)
SAFETY="$EXP/auto_agent/SAFETY_RULES.md"
TASK_ENVS=/home/user/project/shabi_forest/.envs/experiments/2_2_acct2
mkdir -p "$EXP/tmp"
mkdir -p "$TASK_ENVS/cache"
exec /usr/bin/bwrap \
  --ro-bind / / \
  --bind "$EXP" "$EXP" \
  --bind "$TASK_ENVS" "$TASK_ENVS" \
  --ro-bind "$SAFETY" "$SAFETY" \
  --tmpfs /tmp \
  --dev-bind /dev /dev \
  --proc /proc \
  --unshare-pid --unshare-ipc --unshare-uts \
  --hostname acct2-2-2 \
  --chdir "$EXP" \
  -- "$@"
