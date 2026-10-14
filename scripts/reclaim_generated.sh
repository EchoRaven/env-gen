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
#
# #1203jp: CITE_ROOTS is the keep set's reach, and it takes absolute paths. Evidence pointers
# also live OUTSIDE this repo -- the session memory under
# ~/.claude/projects/*/memory cites a specific run in 13 non-archive entries -- so when those
# matter, add that directory and the keep set grows with it:
#
#   CITE_ROOTS="agent/env_generator agent/tests scripts $HOME/.claude/projects/*/memory" \
#     scripts/reclaim_generated.sh
#
# Measured 2026-10-14: the default keeps 100 / frees ~64 GB; adding the memory directory keeps
# 116 / frees ~47 GB. The 17 GB is what honouring every out-of-repo citation costs, stated here
# because a keep set that silently drops them is the version that looks cheaper.
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
#
# #1203jp: `scripts` is on this list because the citation that matters MOST lives there.
# `scripts/verify_shipped_fixes.py --self-test` runs against generated/tiktok-web-r140 and
# exits 2 without it, so deleting r140 silently disarms the one check that catches a fix
# verifier CONFIRMING on a pre-fix run. The first version of this script scanned agent/ only,
# and r140 survived a 129-run preview purely because agent/ happens to name it too — luck,
# not design. The keep set IS this script's whole safety argument, so it has to cover every
# place the repo says "go look at that run", and a root is cheap to add while a deleted
# evidence tree is not recoverable.
CITE_ROOTS=${CITE_ROOTS:-"agent/env_generator agent/tests scripts"}
# Counted in THIS shell, not in a `| while` subshell, so the total can be printed below:
# a protection nobody can see the size of is one nobody will notice losing.
cited_n=0
while read -r cited; do
  [ -n "$cited" ] && [ -d "$GEN/$cited" ] || continue
  echo "$cited" >> "$keep_file"
  cited_n=$((cited_n + 1))
done <<CITED
$(grep -rhoE "[a-z][a-z0-9]*(-[a-zA-Z0-9.]+)*-r[0-9]+|[a-z]+-core-di\.SUCCESS-[A-Za-z0-9-]+|gmrun[0-9]+" \
       $CITE_ROOTS 2>/dev/null | sort -u)
CITED

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
echo "kept by citation: $cited_n run(s) named in $CITE_ROOTS"
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
