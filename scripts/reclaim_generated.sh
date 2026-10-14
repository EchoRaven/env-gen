#!/usr/bin/env bash
# Reclaim disk by deleting OLD generated/ run directories. DRY-RUN BY DEFAULT.
#
# WHY (2026-10-13): /data is 100% full (3.4G free) and one run needs ~6G, so the next run
# hits ENOSPC — and #1203ib records that a full disk is misread as "the app failed", which
# burns a run's budget chasing a defect that is not in the app.
#
# SAFETY, by construction:
#   * It only ever touches directories directly under THIS repo's generated/. /data is a
#     SHARED multi-user disk (datasets/, relm/, sota/, yiran/, and a dozen users under
#     /data/common) and none of that is ours to clean — the path is hard-coded, not an arg.
#   * It KEEPS the newest N tiktok runs plus an explicit evidence set, and prints exactly
#     what it would remove before removing anything.
#   * It refuses to run while a pipeline run is live (a live run writes into generated/).
#   * Deleting is opt-in: `APPLY=1`.
#
# Complements `scripts/disk_headroom.py`, which answers "is there room, and is any of it
# reclaimable from DOCKER" (and is right that dangling volumes are other work lines' data, so
# never blanket-prune them). On 2026-10-13 that tool's answer was "not from here": docker lives
# on / with 76G free, while the pressure is on /data. This one answers the other half — where
# the space is in generated/, and which runs are safe to let go.
#
# Usage:
#   scripts/reclaim_generated.sh            # preview only (default KEEP_N=20)
#   KEEP_N=30 scripts/reclaim_generated.sh  # preview a gentler cut
#   APPLY=1 scripts/reclaim_generated.sh    # actually delete
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
GEN="$(pwd -P)/generated"
[ -d "$GEN" ] || { echo "no generated/ here" >&2; exit 1; }

KEEP_N=${KEEP_N:-20}
# This session's evidence: every ticket landed 2026-10-13 is measured over these.
KEEP_ALWAYS="tiktok-web-r184 tiktok-web-r185 tiktok-web-r186 tiktok-web-r187 tiktok-web-r188"

# Liveness is read from the run's OWN ledger (usage.pid + status), not from a command-line
# pattern: `pgrep -f` matches the checker's own command line, and this script's first version
# refused to run because of exactly that. The ledger cannot self-match.
live=$(PYBIN=${SUITE_PYTHON:-python3}; "$PYBIN" - "$GEN" <<'PY' 2>/dev/null
import json, os, sys, glob
alive = []
for f in glob.glob(os.path.join(sys.argv[1], "*", "run_budget.json")):
    try:
        u = (json.load(open(f, errors="ignore")).get("usage") or {})
    except Exception:
        continue
    if str(u.get("status") or "") not in ("running", "in_progress"):
        continue
    pid = u.get("pid")
    try:
        os.kill(int(pid), 0)                      # signal 0: does that pid exist?
    except Exception:
        continue                                  # recorded "running" but the process is gone
    alive.append(os.path.basename(os.path.dirname(f)))
print(" ".join(alive))
PY
)
if [ -n "${live// /}" ]; then
  echo "A pipeline run is LIVE ($live) — refusing to touch generated/." >&2
  exit 3
fi

keep_file=$(mktemp); trap 'rm -f "$keep_file"' EXIT
for k in $KEEP_ALWAYS; do echo "$k" >> "$keep_file"; done
# Keep every run the SOURCE CITES as evidence. Several tickets name a specific run in the
# comment that justifies them (#1203ir cites gmrun4, #1148 cites netflix-local-r8, #1203it
# cites instagram-core-r176, ...), and deleting one makes its comment unverifiable — the
# reader is told to go look at something that is no longer there.
grep -rhoE "[a-z][a-z0-9]*(-[a-zA-Z0-9.]+)*-r[0-9]+|[a-z]+-core-di\.SUCCESS-[A-Za-z0-9-]+|gmrun[0-9]+" \
     agent/env_generator agent/tests 2>/dev/null \
  | sort -u \
  | while read -r cited; do [ -d "$GEN/$cited" ] && echo "$cited"; done >> "$keep_file"

ls -d "$GEN"/tiktok-web-r* 2>/dev/null \
  | sed 's#.*/##' \
  | sed -E 's/^tiktok-web-r([0-9]+)$/\1 &/' \
  | sort -rn | head -n "$KEEP_N" | awk '{print $2}' >> "$keep_file"
sort -u "$keep_file" -o "$keep_file"

to_del=$(mktemp); trap 'rm -f "$keep_file" "$to_del"' EXIT
for d in "$GEN"/*/; do
  n=$(basename "$d")
  grep -qxF "$n" "$keep_file" || echo "$n" >> "$to_del"
done
[ -s "$to_del" ] || { echo "nothing to remove (KEEP_N=$KEEP_N)"; exit 0; }

freed=$(cd "$GEN" && du -sk $(cat "$to_del") 2>/dev/null | awk '{s+=$1} END {printf "%.0f", s/1048576}')
echo "KEEP_N=$KEEP_N  keeping $(wc -l < "$keep_file") run(s), removing $(wc -l < "$to_del")"
echo "would free ~${freed} GB"
echo "kept always: $KEEP_ALWAYS"
echo
if [ "${APPLY:-0}" != "1" ]; then
  echo "--- PREVIEW (first 15 of $(wc -l < "$to_del")) ---"
  head -15 "$to_del" | sed 's/^/  rm -rf generated\//'
  echo
  echo "re-run with APPLY=1 to delete."
  exit 0
fi
while read -r n; do
  case "$n" in */*|""|.|..) echo "refusing $n" >&2; continue;; esac
  rm -rf -- "${GEN:?}/${n:?}"
done < "$to_del"
echo "done. df:"; df -h /data | tail -1
