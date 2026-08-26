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
# #834: overridable so the SUITE does not allocate against the real ledger. The tests for this
# script call the no-arg form, which RESERVES — so running pytest was appending live ticket
# numbers to the repo's `.tickets` and the next real allocation skipped past them. A test with a
# side effect on a repo artifact is worse than no test: it makes the artifact untrustworthy.
_TICKETS="${TICKET_LEDGER:-.tickets}"

# #847: the allocator is a monotonic high-water mark, and `tail -1` is maximally sensitive to a
# single bad claim. #826's header records this happening — a prose example `"Your invoice #4021 is
# ready"` made it report 4022 — and the fix was to NARROW THE SOURCES. That defends against the
# shapes already seen. It does not defend against prose inside the two sources that remain: an
# EXPERIMENTS heading or a commit subject may quote a number, and both are scanned whole.
#
# Reproduced, not assumed. One heading appended to the real document:
#     ## 172. #848 — a task body rendering "Your invoice #4021 is ready"
#     $ tools/ticket.sh  ->  4022
#
# And it is PERMANENT, because allocating writes to `.tickets` and `.tickets` is itself scanned.
# One bad read poisons every later allocation, silently: the tool prints a bare number with no
# context, so 4022 looks exactly like 848.
#
# The bound is measured, not guessed. The real namespace is 767 claims over 1..847 with a largest
# legitimate gap of 38 (427 -> 465) and NOTHING above 50; the poison jump is 3174. 100 sits an
# order of magnitude away from both.
#
# It warns and skips rather than refusing. A refusal here wedges allocation over a false positive,
# which is the worse end (#789: the fail-open was correct, only its silence was the defect). So it
# names the outlier AND where it was claimed — that line is what lets an operator tell a quoted
# figure from a real ticket that legitimately jumped, and override.
_GAP_847=100

_where() {   # where a number was claimed — shared by the check branch and #847's warning
  grep -n "^## [0-9].*#$1\b" EXPERIMENTS_PENDING_*.md 2>/dev/null | head -3 || true
  git log --oneline --grep="#$1" 2>/dev/null | head -3 || true
}

_claimed() {   # every number claimed, one per line
  { # #847c: a heading inside a FENCED CODE BLOCK is a quotation, not a declaration — which is
    # #826's own stated criterion, applied one level deeper. Item 172 documents the poison by
    # SHOWING it, and the shown line begins with `## `, so the write-up about the bug reintroduced
    # the bug. Any document that explains this tool will contain the same shape.
    awk 'FNR==1{f=0} /^```/{f=!f; next} !f && /^## [0-9]/' EXPERIMENTS_PENDING_*.md 2>/dev/null || true
    git log --format=%s 2>/dev/null || true
    cat "$_TICKETS" 2>/dev/null || true
    # #1118: this matched ONLY test_<name>_<NNNN>.py. The repo uses both orders —
    # 463 files put the number last, 156 put it first (test_1117_the_reason...py) —
    # so 156 of its own regression tests were invisible here. That matters exactly
    # when the other sources cannot help: a ticket whose test exists but whose commit
    # has not landed yet is claimed by nothing else, and the tool re-issues it. It
    # did: with test_1117_*.py on disk and uncommitted, this printed 1117.
    ls agent/tests 2>/dev/null | sed -n \
        -e 's/^test_.*_\([0-9]\{3,4\}\)\.py$/#\1/p' \
        -e 's/^test_\([0-9]\{3,4\}\)_.*\.py$/#\1/p' || true
    { git diff 2>/dev/null; git diff --cached 2>/dev/null;
      git ls-files --others --exclude-standard 2>/dev/null | xargs -r grep -h '#[0-9]' 2>/dev/null
    } | grep -o '#[0-9]\{3,4\}[:)]' || true
  } | grep -o '#[0-9]\{1,4\}' | tr -d '#' | sort -n -u
}

if [ $# -ge 1 ]; then
  n="${1#\#}"
  if _claimed | grep -qx "$n"; then
    echo "#$n is TAKEN — claimed in:"
    _where "$n"
    exit 1
  fi
  echo "#$n is FREE"
  exit 0
fi

# #847b: walk UP from the bottom, not down from the top.
#
# The first cut descended from `max` while each step was more than _GAP_847 above the claim below
# it. **Two adjacent outliers defeat that completely**, and this write-up produced the case within
# the hour: EXPERIMENTS item 172 names both #4021 (the poison) and #4022 (what the tool answered),
# gap 1 — the descent stopped at 4022 and allocated 4023. That is not a contrived input. It is the
# GENERAL shape of the failure, because a poisoned ledger reserves N and the next allocation
# reserves N+1: after the second bad allocation the outliers are always adjacent, forever.
#
# Ascending has no such hole. The real namespace is dense — 767 claims over 1..847, largest gap 38
# — so the top of the first dense run IS the ceiling, and anything beyond it is unreachable however
# many outliers there are or however tightly they cluster.
#
# The warning goes to STDERR so `n=$(tools/ticket.sh)` still captures a bare number — an allocator
# that prints prose into its own output would be a worse bug than the one being fixed.
mapfile -t _all < <(_claimed)
[ "${#_all[@]}" -gt 0 ] || _all=(0)
_i=0
while [ "$_i" -lt $(( ${#_all[@]} - 1 )) ]; do
  _gap=$(( 10#${_all[$((_i + 1))]} - 10#${_all[$_i]} ))
  [ "$_gap" -gt "$_GAP_847" ] && break
  _i=$(( _i + 1 ))
done
highest="${_all[$_i]}"
[ -n "$highest" ] || highest=0
# #1118b: force base 10. Bash reads a leading-zero literal as OCTAL, so a claim like
# 0902 aborts the arithmetic below with "value too great for base", `next` is then
# unbound, and the script prints NOTHING on stdout while exiting 0 — a caller doing
# `n=$(tools/ticket.sh)` gets an empty ticket number and no error. No claim in this
# repo currently has a leading zero (0 of them, across filenames, commit subjects and
# the ledger), so this is unreachable today; it is one token, and the failure it
# prevents is silent.
highest=$(( 10#$highest ))

if [ "$_i" -lt $(( ${#_all[@]} - 1 )) ]; then
  {
    echo "ticket.sh: IGNORING $(( ${#_all[@]} - _i - 1 )) claim(s) above #$highest — the next is"
    echo "  #${_all[$((_i + 1))]}, $(( ${_all[$((_i + 1))]} - highest )) higher, and the largest real gap"
    echo "  in this namespace is 38. Those are quoted numbers, not tickets. Claimed at:"
    for _j in $(seq $(( _i + 1 )) $(( ${#_all[@]} - 1 )) ); do
      echo "    #${_all[$_j]}:"; _where "${_all[$_j]}" | sed 's/^/      /'
    done
    echo "  If one IS a ticket, raise _GAP_847 or add it to $_TICKETS by hand."
  } >&2
fi
next=$((highest + 1))
# #829: RESERVE it. A pure read handed the same number to two callers three times.
printf '#%s reserved %s\n' "$next" "$(date -u +%FT%TZ)" >> "$_TICKETS"
echo "$next"
