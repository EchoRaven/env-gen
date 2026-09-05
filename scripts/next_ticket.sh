#!/usr/bin/env bash
# Print every ticket id already in use, and the next free one.
#
# WHY (2026-09-05): picking a ticket id collided TWICE in one session, both times because
# the check matched ONE representation instead of the fact:
#   1st — checked `git log -S`, but the whole live range exists only in the WORK TREE
#         (uncommitted), so history showed nothing and #1202de / #1202df were re-used.
#   2nd — checked file CONTENTS for `#1202d[a-z]`, missing ids encoded in FILE NAMES
#         (test_1202dn_a_js_fragment_is_not_an_endpoint.py), so dn / do were re-used.
# This looks at file names AND contents, with and without the leading '#', and never
# consults git history.
#
# Usage:  scripts/next_ticket.sh            # highest used + next free
#         scripts/next_ticket.sh --all      # every id in use
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PREFIX=${TICKET_PREFIX:-1202}

used=$( { grep -rhoE "${PREFIX}[a-z]{1,3}" --include='*.py' agent/ 2>/dev/null
          ls agent/tests/ 2>/dev/null | grep -ohE "${PREFIX}[a-z]{1,3}"
          grep -rhoE "${PREFIX}[a-z]{1,3}" ./*.md 2>/dev/null
        } | sed "s/^${PREFIX}//" | sort -u )

if [ "${1:-}" = "--all" ]; then echo "$used" | tr '\n' ' '; echo; exit 0; fi

echo "prefix : #${PREFIX}"
echo "in use : $(echo "$used" | wc -w) ids, highest = #${PREFIX}$(echo "$used" | awk '{print length, $0}' | sort -n -k1,1 -k2,2 | tail -1 | cut -d" " -f2)"
next=$(python3 - "$PREFIX" <<'PY'
import sys, subprocess, re, string, itertools
pref = sys.argv[1]
out = subprocess.run(
    f"{{ grep -rhoE '{pref}[a-z]{{1,3}}' --include='*.py' agent/ 2>/dev/null; "
    f"ls agent/tests/ 2>/dev/null | grep -ohE '{pref}[a-z]{{1,3}}'; "
    f"grep -rhoE '{pref}[a-z]{{1,3}}' ./*.md 2>/dev/null; }}",
    shell=True, capture_output=True, text=True).stdout
used = set(re.findall(rf"{pref}([a-z]{{1,3}})", out))
def seq():
    for n in (1, 2, 3):
        for t in itertools.product(string.ascii_lowercase, repeat=n):
            yield "".join(t)
order = list(seq())
# Allocate AFTER the highest id in use, never the first gap: an early gap (#1202a) is a
# retired id, and re-issuing it makes two unrelated changes share a name -- the exact
# failure this script exists to prevent. Sort by (length, alpha): "z" precedes "aa".
rank = {s: i for i, s in enumerate(order)}
hi = max((s for s in used if s in rank), key=lambda s: rank[s], default=None)
start = rank[hi] + 1 if hi is not None else 0
print(next(s for s in order[start:] if s not in used))
PY
)
echo "next   : #${PREFIX}${next}"
echo
echo "Claim a RANGE, not one id, when two sessions share this tree:"
echo "  e.g. this session takes #${PREFIX}${next}..#${PREFIX}${next%?}z  and records it in the handoff doc."
