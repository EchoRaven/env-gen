#!/usr/bin/env bash
# r112_monitor.sh — token-free monitor for the multi-milestone Netflix run.
# Logs the handoff §6d signals every ~30 min to r112_monitor.status and writes a
# terminal verdict (r112_monitor.TERMINAL) when the gen process exits. Does NOT act
# (no teardown, no relaunch) — the human/agent makes the STOP/report decision.
set -u
NAME="${1:-netflix-web-r112}"
REPO=/home/haibotong/forgingground-gen
LOG="$REPO/gm_${NAME}.log"
STATUS="$REPO/${NAME}_monitor.status"
TERMINAL="$REPO/${NAME}_monitor.TERMINAL"
HUB="$REPO/agent/generated/${NAME}/shared/hubs/codehub_releases.json"

gen_line() { ps -eo pid,etime,cmd | grep "[.]venv/bin/python -m env_generator" | grep -- "$NAME" | grep -v grep | head -1; }
gen_alive() { [ -n "$(gen_line)" ]; }

tags() {
  python3 - "$HUB" <<'PY' 2>/dev/null || echo "(no hub yet)"
import json,sys
try:
    d=json.load(open(sys.argv[1]))
    ks=[k for k in d if k!='_meta']
    print(",".join(ks) if ks else "(none)")
except Exception:
    print("(no hub yet)")
PY
}

full_check() {
  local ts pl etime tg blk undef adv
  ts=$(date '+%Y-%m-%d %H:%M:%S')
  pl=$(gen_line)
  etime=$(echo "$pl" | awk '{print $2}')
  [ -n "$etime" ] || etime="DOWN"
  tg=$(tags)
  blk=$(grep "Framework deliver declined: delivery gate has" "$LOG" 2>/dev/null | tail -1 | sed 's/.*delivery gate has/gate has/' | cut -c1-160)
  [ -n "$blk" ] || blk="(no decline logged)"
  undef=$(grep -c "UndefinedColumn" "$LOG" 2>/dev/null)
  adv=$(grep -icE "advancing to milestone|_await_prior_milestone|advance.*milestone" "$LOG" 2>/dev/null)
  {
    echo "[$ts] etime=$etime | tags=[$tg] | undefcol=$undef | advance_signals=$adv"
    echo "         blocker: $blk"
  } >> "$STATUS"
}

terminal_verdict() {
  local ts rc mainrc watchdog tg ntags gencomplete status
  ts=$(date '+%Y-%m-%d %H:%M:%S')
  mainrc=$(grep -oE "main\(\) returned [0-9]+" "$LOG" 2>/dev/null | tail -1)
  watchdog=$(grep -oE "forcing exit \(rc=[0-9]+\)" "$LOG" 2>/dev/null | tail -1)
  gencomplete=$(grep -c "GENERATION COMPLETE" "$LOG" 2>/dev/null)
  status=$(grep -E "Status: (SUCCESS|FAIL)" "$LOG" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//')
  tg=$(tags)
  ntags=$(python3 - "$HUB" <<'PY' 2>/dev/null || echo 0
import json,sys
try:
    d=json.load(open(sys.argv[1])); print(len([k for k in d if k!='_meta']))
except Exception: print(0)
PY
)
  rc="UNKNOWN"
  echo "$mainrc" | grep -q "returned 0" && rc=0
  echo "$watchdog" | grep -q "rc=0" && rc=0
  echo "$mainrc" | grep -qE "returned [1-9]" && rc="NONZERO ($mainrc)"
  {
    echo "==================== TERMINAL @ $ts ===================="
    echo "gen process:      DOWN"
    echo "main-exit:        ${mainrc:-<none>} | ${watchdog:-<none>}"
    echo "GENERATION COMPLETE lines: $gencomplete | $status"
    echo "release tags ($ntags): [$tg]"
    echo "rc verdict:       $rc"
    if [ "$ntags" -ge 2 ] && [ "$rc" = "0" ]; then
      echo "VERDICT:          *** MULTI-MILESTONE VALIDATED *** (>=2 tags + rc=0)"
    elif [ "$rc" = "0" ]; then
      echo "VERDICT:          rc=0 but only $ntags tag(s) — NOT the multi-milestone target; inspect."
    else
      echo "VERDICT:          NON-SUCCESS / WEDGE — diagnose ground-truth-first, STOP+report before relaunch."
    fi
    echo "========================================================"
  } | tee -a "$STATUS" > "$TERMINAL"
}

echo "[$(date '+%Y-%m-%d %H:%M:%S')] monitor start for $NAME (pid $$)" >> "$STATUS"
while gen_alive; do
  full_check
  # sleep up to 30 min, waking within 60s if the gen exits
  for _ in $(seq 1 30); do gen_alive || break; sleep 60; done
done
full_check
terminal_verdict
