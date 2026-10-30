#!/usr/bin/env bash
# Start (or resume) run <run> (default 0) in the background with nohup. Safe to re-run: a finished job exits at once.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
RUN=${1:-0}
source /home/user/project/shabi_forest/.envs/env.sh
mkdir -p "$HERE/logs"
PIDF="$HERE/logs/job_r$RUN.pid"
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  echo "run $RUN already running (pid $(cat "$PIDF"))"; exit 0
fi
python3 -I /home/user/project/shabi_forest/tools/benchmark_freeze.py verify   # benchmarks must be untouched
# Strip the parent Claude Code session's variables so the agent starts as an independent CLI.
setsid nohup env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_CHILD_SESSION \
  "$SF_ENVS/bin/python3.12" -I -B "$HERE/scripts/run_selfval_job.py" "$RUN" >> "$HERE/logs/job_r$RUN.log" 2>&1 &
echo $! > "$PIDF"
echo "run $RUN started: pid $(cat "$PIDF"); log: $HERE/logs/job_r$RUN.log"
