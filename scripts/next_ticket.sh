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
# 3rd (2026-10-14, #1203jb): a THIRD representation was unseen. The scan matched
# `[a-z]{1,3}`, so every id containing a DIGIT was invisible. Measured in the 1203 range
# the moment the scan was widened: 96 id-shaped tokens appeared that `--all` and the "in
# use" count had been reporting as nonexistent — about a third of that range. Most are
# real claims (#1203a0 … #1203j2); a few are derived locals (`_e1203io2` for a second
# #1203io handler, `1203b5s`, `1203c8b`, `_e1203i7r`), which are equally confusing to
# re-issue. #1203j0/j1/j2 are the ones that exposed it: 16 code references and 3 test
# files, all invisible. The generator cannot RE-ISSUE one (its
# sequence is letters-only, below), so nothing collided on its own — the harm is that
# this script is what a session consults before claiming an id by hand, and it answered
# "j0 is free" about an id in use. Same shape as #1118 on the other allocator
# (`tools/ticket.sh`), which could not see 156 of the repo's own test files.
#
# DETECTION is widened; ALLOCATION is not. `[a-z][a-z0-9]{0,2}` must still START with a
# letter: `${PREFIX}` followed by digits is just a longer number (a line reading
# `#1203456` claims nothing), and matching it would re-introduce #826's original bug of
# reading `#999` as a ticket. Digit-bearing ids are reported separately rather than
# ranked with the rest, because "highest" drives allocation and the two orderings
# disagree — ASCII puts j0 before ja while the generator issues ja after j.
#
# Usage:  scripts/next_ticket.sh            # highest used + next free
#         scripts/next_ticket.sh --all      # every id in use
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PREFIX=${TICKET_PREFIX:-1202}

SUFFIX_RE="[a-z][a-z0-9]{0,2}"      # #1203jb: must start with a letter (see header)
used=$( { grep -rhoE "${PREFIX}${SUFFIX_RE}" --include='*.py' agent/ 2>/dev/null
          ls agent/tests/ 2>/dev/null | grep -ohE "${PREFIX}${SUFFIX_RE}"
          grep -rhoE "${PREFIX}${SUFFIX_RE}" ./*.md 2>/dev/null
        } | sed "s/^${PREFIX}//" | sort -u )
# Ids this script's generator can actually issue; they alone define "highest".
used_alpha=$( echo "$used" | grep -xE "[a-z]{1,3}" )
used_mixed=$( echo "$used" | grep -vxE "[a-z]{1,3}" )

if [ "${1:-}" = "--all" ]; then echo "$used" | tr '\n' ' '; echo; exit 0; fi

echo "prefix : #${PREFIX}"
echo "in use : $(echo "$used" | wc -w) ids, highest = #${PREFIX}$(echo "$used_alpha" | awk '{print length, $0}' | sort -n -k1,1 -k2,2 | tail -1 | cut -d" " -f2)"
if [ -n "$used_mixed" ]; then
  echo "also   : $(echo "$used_mixed" | wc -w) id-shaped token(s) carrying a digit — in use,"
  echo "         not issuable here (letters-only sequence): $(echo "$used_mixed" | tr '\n' ' ')"
fi
next=$(python3 - "$PREFIX" <<'PY'
import sys, subprocess, re, string, itertools
pref = sys.argv[1]
out = subprocess.run(
    f"{{ grep -rhoE '{pref}[a-z][a-z0-9]{{0,2}}' --include='*.py' agent/ 2>/dev/null; "
    f"ls agent/tests/ 2>/dev/null | grep -ohE '{pref}[a-z][a-z0-9]{{0,2}}'; "
    f"grep -rhoE '{pref}[a-z][a-z0-9]{{0,2}}' ./*.md 2>/dev/null; }}",
    shell=True, capture_output=True, text=True).stdout
used = set(re.findall(rf"{pref}([a-z][a-z0-9]{{0,2}})", out))
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
