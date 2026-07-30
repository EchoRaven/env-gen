#!/usr/bin/env bash
# Tail the generation log, surfacing only decisive events.
#   ./watch_netflix.sh [NAME]      (default NAME=netflix-web-r1)
NAME="${1:-netflix-web-r1}"
LOG="/home/haibotong/forgingground-gen/gm_${NAME}.log"
[ -f "$LOG" ] || { echo "no log yet: $LOG"; exit 1; }
tail -f -n +1 "$LOG" | grep -E --line-buffered \
  "kickoff|create_release|CONVERGING-GRACE|NO-CONVERGENCE|ABORT|api_smoke PASSED|delivery|Generation (complete|failed)|Cannot use|Traceback|ERROR"
