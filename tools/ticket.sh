#!/usr/bin/env bash
# #826: allocate a ticket number, or check one is free.
#
# WHY THIS EXISTS
#   Ticket numbers here are a namespace with no allocator. They get chosen from memory of what the
#   last one was, and after a context break that memory is a session stale. One session produced
#   three collisions:
#
#       #817  re-derived — the previous session had already shipped it
#       #820  re-derived — same, down to the number, colliding at EXPERIMENTS item 150
#       #822  TAKEN      — already used for the spec-screen drop, 4 references in code
#       #823  TAKEN      — likewise
#
#   Each was caught only after the code and the write-up existed under the wrong number. "Check
#   the log first" was written down after the first and failed twice more: a check that lives in a
#   habit is not a check.
#
# WHAT IT SCANS, AND WHY ONLY THIS
#   A number is CLAIMED in exactly two places, both with clean, unambiguous shapes:
#
#       EXPERIMENTS headings   `## 150. #820 — an unsatisfiable nav-link expectation`
#       commit subjects        `#824/#825: renumber the new audits off a collision`
#
#   The first version scanned all source text for `#NNN` and was wrong twice over: it matched a
#   CSS hex colour (`.empty { color: #999; }`) and a prose example (`"Your invoice #4021 is
#   ready"`), reporting the next free ticket as 4022. Tightening the regex chased the symptom —
#   `#999` and a ticket number are the same token, and no pattern separates them. Narrowing to the
#   places a number is DECLARED does, because those have structure. A ticket referenced in a code
#   comment but never claimed in a heading or a subject line does not exist as a ticket.
#
# USAGE
#   tools/ticket.sh            # the next free number
#   tools/ticket.sh 830        # is 830 free? (exit 0 free, 1 taken) + where it was claimed
set -euo pipefail
cd "$(dirname "$0")/.."

# #829: three MORE collisions happened after this allocator existed, and each exposed a source of
# claims it could not see. All three are now scanned.
#
#   1. TEST FILENAMES. `agent/tests/test_<slug>_<NNN>.py` is how a fix is claimed in this repo,
#      and #719's guard already treats two such files sharing a number as a collision. The
#      allocator did not — so the two components disagreed about what "claimed" MEANS, and the
#      allocator handed out a number the guard would later reject. (agent/tests is gitignored,
#      which is why a git-log scan never saw them.)
#   2. UNCOMMITTED WORK. A second writer mid-fix has `#NNN` in the working tree and nothing in
#      the log. Scanning `git diff` + untracked files closes the window between editing and
#      committing, which is exactly where every collision landed.
#   3. NO RESERVATION. Allocation was a pure read: two callers seconds apart got the same answer,
#      three times. Allocating now APPENDS to .tickets, and .tickets is itself scanned, so the
#      number is taken the moment it is handed out.
_TICKETS=".tickets"

_claimed() {   # every number claimed, one per line
  { grep -h '^## [0-9]' EXPERIMENTS_PENDING_*.md 2>/dev/null || true
    git log --format=%s 2>/dev/null || true
    cat "$_TICKETS" 2>/dev/null || true
    ls agent/tests 2>/dev/null | sed -n 's/^test_.*_\([0-9]\{3,4\}\)\.py$/#\1/p' || true
    { git diff 2>/dev/null; git diff --cached 2>/dev/null;
      git ls-files --others --exclude-standard 2>/dev/null | xargs -r grep -h '#[0-9]' 2>/dev/null
    } | grep -o '#[0-9]\{3,4\}[:)]' || true
  } | grep -o '#[0-9]\{1,4\}' | tr -d '#' | sort -n -u
}

if [ $# -ge 1 ]; then
  n="${1#\#}"
  if _claimed | grep -qx "$n"; then
    echo "#$n is TAKEN — claimed in:"
    grep -n "^## [0-9].*#$n\b" EXPERIMENTS_PENDING_*.md 2>/dev/null | head -3 || true
    git log --oneline --grep="#$n" 2>/dev/null | head -3 || true
    exit 1
  fi
  echo "#$n is FREE"
  exit 0
fi

highest="$(_claimed | tail -1)"
[ -n "$highest" ] || highest=0
next=$((highest + 1))
# #829: RESERVE it. A pure read handed the same number to two callers three times.
printf '#%s reserved %s\n' "$next" "$(date -u +%FT%TZ)" >> "$_TICKETS"
echo "$next"
