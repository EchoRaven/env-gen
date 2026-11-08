#!/usr/bin/env bash
# Start (or resume) the 2.3 pipeline in the background (scripts/pipeline.py). Safe to re-run, e.g. after a reboot: jobs
# resume from their status.json and the gateway unit is recreated by the jobs' launch.sh. Stop: `touch STOP` (the
# pipeline exits at its next check; running jobs continue until stopped by PID: job_*/logs/job_r0.pid).
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$HERE/logs"
PIDF="$HERE/logs/pipeline.pid"
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then echo "pipeline already running: pid $(cat "$PIDF")"; exit 0; fi
rm -f "$HERE/STOP" "$HERE/logs/PIPELINE_FAILED"
bash "$HERE/scripts/gateway.sh"
setsid nohup env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_CHILD_SESSION \
  /home/user/project/shabi_forest/.envs/bin/python3.12 -I -B "$HERE/scripts/pipeline.py" >> "$HERE/logs/pipeline.out" 2>&1 < /dev/null &
echo $! > "$PIDF"
echo "pipeline started: pid $(cat "$PIDF"); log $HERE/logs/pipeline.log"
