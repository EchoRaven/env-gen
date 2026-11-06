#!/usr/bin/env bash
# Block until something needs the proctor: job <dir> done/failed/died, vLLM down, disk < 50 GB, or <max_s> elapsed.
# usage: scripts/watch.sh job_selfval|job_oracle_hidden [max_s]
HERE=$(cd "$(dirname "$0")/.." && pwd); J="$HERE/$1"; MAX=${2:-7000}; t0=$(date +%s)
ST="$J/runs/netflix__r0/status.json"
while :; do
  state=$(python3 -c "import json;print(json.load(open('$ST')).get('state'))" 2>/dev/null)
  [ "$state" = done ] && { echo EVENT=done; break; }
  [ "$state" = failed ] && { echo EVENT=failed; break; }
  kill -0 "$(cat "$J/logs/job_r0.pid")" 2>/dev/null || { echo EVENT=died; break; }
  curl -sf -m10 http://127.0.0.1:8000/health >/dev/null || { sleep 120; curl -sf -m10 http://127.0.0.1:8000/health >/dev/null || { echo EVENT=vllm_down; break; }; }
  free=$(df --output=avail -BG / | tail -1 | tr -dc 0-9); [ "$free" -lt 50 ] && { echo EVENT=disk_low; break; }
  [ $(( $(date +%s) - t0 )) -gt "$MAX" ] && { echo EVENT=heartbeat; break; }
  sleep 60
done
date; tail -4 "$J/runs/netflix__r0/job.log"
