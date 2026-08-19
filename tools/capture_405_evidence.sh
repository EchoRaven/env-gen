#!/usr/bin/env bash
# Capture runtime evidence for a route that returns 405 while its code says otherwise.
#
# r162 died on one failed task: "POST /api/continue-watching is registered implemented but
# returns 405". Static diagnosis is exhausted and came back clean on every line — the route is
# declared in both custom_routes.py and main.py, the router IS included, a broken import WOULD
# be logged, and the image is rebuilt (11 builds in r162). So the answer is only visible while
# a container is alive.
#
# That window is short and I have missed it every time by checking by hand. This polls for the
# stack and captures, the moment it exists:
#
#   * what the running app ACTUALLY serves     (OPTIONS + POST against the live port)
#   * what the running app THINKS it serves    (its own /openapi.json route table)
#   * what is on disk inside the container     (grep of the module the container loaded)
#
# The third line is the one that matters: if the container's main.py lacks the POST that the
# worktree has, the repair never reached the image and the 405 is a delivery problem, not a
# routing one. If it HAS the POST and still 405s, it is a routing problem and the openapi
# table will say which methods it believes are bound.
#
# Usage:  tools/capture_405_evidence.sh <run-name> [minutes]
set -uo pipefail
RUN="${1:-}"
MINS="${2:-90}"
[ -z "$RUN" ] && { echo "usage: $0 <run-name> [minutes]"; exit 2; }
OUT="evidence_405_${RUN}.txt"
DEADLINE=$(( $(date +%s) + MINS * 60 ))

echo "[capture] waiting for a live backend for $RUN (up to ${MINS}m) -> $OUT"
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  CID="$(podman ps --format '{{.Names}}' 2>/dev/null | grep -m1 backend || true)"
  if [ -n "$CID" ]; then
    PORT="$(podman port "$CID" 2>/dev/null | head -1 | sed 's/.*://')"
    {
      echo "=== captured $(date '+%F %T')  container=$CID port=${PORT:-unknown}"
      echo
      echo "--- what it ACTUALLY serves"
      for M in OPTIONS POST GET; do
        printf '  %-7s /api/continue-watching -> %s\n' "$M" \
          "$(curl -s -o /dev/null -w '%{http_code}' -m 5 -X "$M" \
             "http://localhost:${PORT}/api/continue-watching" 2>/dev/null || echo ERR)"
      done
      echo
      echo "--- what it THINKS it serves (its own openapi table)"
      curl -s -m 5 "http://localhost:${PORT}/openapi.json" 2>/dev/null \
        | python3 -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print("  (no openapi:", e, ")"); raise SystemExit
p=d.get("paths",{})
k=[x for x in p if "continue" in x]
print("  matching paths:", k or "NONE")
for x in k: print(f"    {x}: {sorted(p[x].keys())}")' 2>/dev/null
      echo
      echo "--- what is ON DISK inside the container (the decisive line)"
      podman exec "$CID" sh -lc \
        'grep -n "continue-watching" /app/main.py /app/custom_routes.py 2>/dev/null | head -8' \
        2>/dev/null || echo "  (exec unavailable)"
    } > "$OUT" 2>&1
    echo "[capture] wrote $OUT"
    exit 0
  fi
  sleep 10
done
echo "[capture] no backend container appeared within ${MINS}m" > "$OUT"
exit 1
