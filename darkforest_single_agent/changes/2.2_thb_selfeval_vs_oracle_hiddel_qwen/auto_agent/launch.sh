#!/usr/bin/env bash
# Start the acct2 auto-agent as a persistent systemd user service.
# The agent is a Claude Code session that builds and runs the qwen+codex Netflix experiments.
#
# Usage: launch.sh
# Stop:  systemctl --user stop shabi-forest-acct2-auto-agent-2-2.service
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
EXP=$(cd "$HERE/.." && pwd)

source /home/user/project/shabi_forest/.envs/env.sh

mkdir -p "$HERE/logs"
PIDF="$HERE/logs/agent.pid"
UNIT=shabi-forest-acct2-auto-agent-2-2.service

if systemctl --user is-active --quiet "$UNIT"; then
  systemctl --user show "$UNIT" --property=MainPID --value > "$PIDF"
  echo "auto-agent already running (pid $(cat "$PIDF"), unit $UNIT)"
  echo "log: $HERE/logs/agent.log"
  exit 0
fi

# Verify prerequisites
if [ ! -f "$HERE/JOB_SPEC.md" ]; then
  echo "ERROR: JOB_SPEC.md not found in $HERE"
  exit 1
fi

TOKEN="/home/user/project/shabi_forest/.envs/secrets/claude_oauth_token_acct2"
if [ ! -f "$TOKEN" ]; then
  echo "ERROR: acct2's oauth token not found at $TOKEN"
  exit 1
fi

# Verify benchmarks are untouched
python3 -I /home/user/project/shabi_forest/tools/benchmark_freeze.py verify > /dev/null

systemctl --user reset-failed "$UNIT" 2>/dev/null || true
systemd-run --user --collect --unit="${UNIT%.service}" \
  --property=Restart=on-failure --property=RestartSec=30s \
  --working-directory="$EXP" \
  /usr/bin/bash "$HERE/sandbox_exec.sh" \
  /usr/bin/python3 -I -B "$HERE/run_auto_agent.py"
systemctl --user show "$UNIT" --property=MainPID --value > "$PIDF"
echo "auto-agent started: pid $(cat "$PIDF"), unit $UNIT"
echo "log: $HERE/logs/agent.log"
echo "status: $HERE/status.json"
