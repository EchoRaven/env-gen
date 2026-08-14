#!/usr/bin/env bash
# Check every open question from EXPERIMENTS_PENDING_2026-08-13.md against ONE finished run.
#
# The 2026-08-12/13 review was entirely offline: no generation runs. Each fix is proven at the
# unit level and each premise is measured against the kept corpus, but a corpus cannot show a
# fix's EFFECT, and nine findings could not be resolved from disk at all. This script is the
# "cheapest observation" column of that document, made executable, so the next run settles them
# without anyone re-deriving the queries.
#
#   usage:  tools/check_pending_experiments.sh <run-dir> [<run-log>]
#   e.g.    tools/check_pending_experiments.sh agent/generated/netflix-web-r145 \
#                                              gm_netflix-web-r145.log
#
# Every check prints one of:
#   LIVE     — a fix's signature appeared, so the new code ran
#   NOT SEEN — the signature did not appear. NOT the same as "broken": the branch may simply
#              not have been reached this run. Say which before concluding anything.
#   DATA     — a measurement, for comparison against the corpus baseline quoted beside it
#   n/a      — the artifact this check needs does not exist in this run
#
# Exit status is always 0: this reports, it does not gate.

set -uo pipefail
RUN="${1:-}"
LOG="${2:-}"
if [[ -z "$RUN" || ! -d "$RUN" ]]; then
    echo "usage: $0 <run-dir> [<run-log>]" >&2
    exit 2
fi
HUBS="$RUN/shared/hubs"

say() { printf '%-9s %-46s %s\n' "$1" "$2" "${3:-}"; }

grep_log() {   # grep_log <label> <pattern> <note>
    if [[ -z "$LOG" || ! -f "$LOG" ]]; then say "n/a" "$1" "no run log given"; return; fi
    local n; n=$(grep -c -- "$2" "$LOG" 2>/dev/null || true)
    if [[ "${n:-0}" -gt 0 ]]; then say "LIVE" "$1" "x$n  ${3:-}"
    else say "NOT SEEN" "$1" "${3:-}"; fi
}

# #717: REFUSE TO BE READ AS A RESULT WHILE THE RUN IS STILL GOING.
# Every count below is a grep over a log that may still be growing, and a store read mid-run is a
# snapshot, not an outcome. This is not hypothetical: r147 was read at ~9,000 lines of an eventual
# 12,237, which produced "r147 did not deliver" (it delivered v1.0.0 in the 3,000 lines after the
# look), "#700 x17" (final: 37), "160 attempts / 80 failures" (final: 178 / 84), and a claim that
# a rejection rate "accelerates rather than tapering" drawn from a distribution whose tail had not
# happened yet. Four wrong conclusions from one habit.
#
# `[main-exit]` is written by main() on every exit path — present in r145 (rc=1), r146 (rc=0) and
# r147 (watchdog), absent while running. Cheap and unambiguous.
if [[ -n "$LOG" && -f "$LOG" ]]; then
    if ! tail -5 "$LOG" | grep -q -- "\[main-exit\]"; then
        echo "############################################################################"
        echo "#  WARNING: this run has NOT finished — no [main-exit] in the last 5 lines."
        echo "#  Every number below is a SNAPSHOT of a growing log. A zero here means"
        echo "#  'not yet', not 'never'. Re-run this after the run exits before recording"
        echo "#  anything from it."
        echo "############################################################################"
        echo
    fi
fi

echo "=== run: $RUN"
echo
echo "--- A. did this session's fixes actually execute? (signature greps) ---"
grep_log "#677 transport diagnosis"      "NOTHING IS LISTENING"            "was: 1778 bare 'Connection refused'"
grep_log "#678 framework-owned escalate" "The answer will not change"      "was: 61 run/file pairs hit 5+ times"
grep_log "#676 edit anchor diagnosis"    "the anchor is"                   "was: 418 bare 'old_string not found'"
grep_log "#675 list validator"           "entries; got"                    "was: 1128 'must be a list of length'"
# #674 has NO unique signature — its change is that `data` now FOLLOWS the error line, and
# "HTTP Error" appears in the old wording too. Grepping for it would report LIVE on a pre-fix
# log (it did, on r139, x66). Print the line instead and let the reader see whether a body
# follows it.
if [[ -n "$LOG" && -f "$LOG" ]]; then
    _l=$(grep -m1 -- "HTTP Error:" "$LOG" 2>/dev/null || true)
    if [[ -n "$_l" ]]; then
        say "MANUAL" "#674 failed ToolResult data" "does a body follow the status? ->"
        printf '          %s\n' "${_l:0:200}"
    else
        say "n/a" "#674 failed ToolResult data" "no HTTP Error line this run"
    fi
else say "n/a" "#674 failed ToolResult data" "no run log given"; fi
grep_log "#664 chain-reject escalation"  "have now been rejected"          "was: 4 escalations in 4928 rejects"
grep_log "#663 denial-probe class"       "BOUNDARY CROSSED"                "P0 if present; SUBSTITUTED = status bug"
grep_log "#671 matrix skipped"           "matrix_skipped_reason"           "reported when no tasks/tasks.yaml"
grep_log "#683 chain named in failure"   "] business_chain:"               "was: the CHECK name, never the chain"
grep_log "#688 empty-page hint"          "NO interactable elements"        "was: bare 'Timeout 5000ms exceeded'"
grep_log "#689 navigation-race retry"    "Retried once after the navigation" "was: no retry; 132 races, 50 live"
grep_log "#690 empty route parameter"    "EMPTY parameter"                 "was: 3 branches all mis-diagnosed it"
grep_log "#682 unknown id named"         "no such row exists"              "was: bare 'title not found'"
grep_log "#682b ownership 403"           "The refusal is CORRECT"          "was: bare 'does not belong to the caller'"
# #691 is the one line here whose PRESENCE is the expected outcome, not a regression. The ordering
# it reports is unrepaired BY DESIGN: integration is forked while HEAD is still on main, and the
# framework's first delivery commit lands on main. #691 detects that; #691b (next line) recovers
# the subtree rather than shipping without it. Its ABSENCE means either the fork order changed or
# the subtree was already present — check which before reading it as good news.
grep_log "#691 absent delivery subtree"  "is not in the working tree at commit time" "EXPECTED to fire; r145+r146 both silently shipped without mcp_server/"
# #691b is the repair. Seeing BOTH lines is the healthy outcome: #691 detects, #691b recovers.
# #691 alone means the restore did not find a commit to take the subtree from — a different
# defect from the one diagnosed, and worth reading the reflog for.
grep_log "#691b subtree recovered"       "recovered delivery subtree" "pairs with #691; alone-#691 means no source commit was found"

# --- fixes whose signature is the DEFECT DISAPPEARING, not a new message -------------------------
# These cannot be confirmed by presence. A zero here is the goal, but a zero also happens when the
# branch was never reached, so each prints the pre-fix count for scale rather than a verdict.
gone_log() {   # gone_log <label> <pattern> <was>
    if [[ -z "$LOG" || ! -f "$LOG" ]]; then say "n/a" "$1" "no run log given"; return; fi
    local n; n=$(grep -c -- "$2" "$LOG" 2>/dev/null || true)
    if [[ "${n:-0}" -eq 0 ]]; then say "GONE" "$1" "0 this run  ${3:-}"
    else say "STILL" "$1" "x$n  ${3:-}"; fi
}
# NEITHER verdict is self-interpreting, and this script cannot tell which fixes were compiled
# into the run. Check that FIRST — `ps -o lstart=` the gen against `git log --date=local` — then:
#   GONE  = the defect did not occur. Only evidence the fix works if the fix WAS in the build AND
#           the condition arose; otherwise it just did not come up.
#   STILL = the defect occurred. If the fix was not in the build this is the pre-fix BASELINE and
#           exactly what the next run should improve on; only if it WAS in does it mean the fix
#           missed this path.
# r146 is the worked example: it launched 22:53 and #683-#690 were committed 23:34, so every
# line in this block is baseline for it, not a verdict.
gone_log "#684 notebook readable"        "Unknown file 'notebook'"         "was: 8 refusals in r145"
gone_log "#685 endpoint lookup"          "Endpoint not found: POST /api/titles" "was: 10 in r145, 10 in r146"
gone_log "#686 step headers sent"        "X-Profile-Id header is required" "was: 11 live-era, all r132"
gone_log "#687 browser transport"        "Navigation failed: Page.goto: net::ERR_CONNECTION_REFUSED$" "was: 161 live-era with no diagnosis"
# The brackets are ESCAPED: grep reads [projected] as a character class, so the unescaped form
# matches any one of those letters followed by " data load failed:" — over-matching, quietly.
# NO BACKTICKS in these note strings: bash runs them as command substitution. The first draft
# of this line embedded `rev-list ...` and the script printed "rev-list: command not found" on
# every invocation — a checker that misreports itself is worse than one that is absent.
# The pattern is `reach=`, NOT `"reach"`. #725 renders a list argument as its SHAPE, so the log
# line reads `reach=[1]` with no quotes — the quoted form matched the dict key in hub_tools.py
# and nothing a run ever writes. #716 passed it because it checks a pattern exists in SOURCE,
# which is a different question from whether it matches the LOGGED form.
# #729 is measured from the STORE, not the log: count GET endpoints whose schema.request is
# non-empty. Above zero = the completed instruction landed; zero = enforcement, not wording.
if [[ -f "$HUBS/registryhub_endpoints.json" ]]; then
    # Scoped to BUSINESS GETs. The whole-GET count mixed in the framework's fixed surface —
    # /health, /api/v1/tenants — which has no query parameters and is correctly empty, so a
    # denominator including it measures the wrong thing. The gap is one cell: lane GETs went
    # 3/11 -> 0/11 -> 0/11 while lane POSTs held 4/4 throughout.
    _n729=$(python3 -c "
import json
d=json.load(open('$HUBS/registryhub_endpoints.json'))
def biz(p):
    p=str(p)
    return p.startswith('/api/') and '/api/v1/' not in p
g=[v for k,v in d.items() if not k.startswith('_') and isinstance(v,dict)
   and str(v.get('method')).upper()=='GET' and biz(v.get('path'))]
w=[v for v in g if ((v.get('schema') or {}).get('request'))]
print(f'{len(w)}/{len(g)}')" 2>/dev/null || echo "?")
    say "DATA" "#729 business GETs w/ query params" "$_n729  (r146 3/11 -> r147 0/11 -> r148 0/11; lane POSTs held 4/4 throughout)"
fi
grep_log "#728 crossed endpoints"        "shares no path word with its own route" "the CAUSE behind #700's groups: a page calling another page's endpoint. r146 3, r147 0, r148 2"
grep_log "#727 reach declared"           "reach=" "ADOPTION probe: how many of the 8 interaction screens the lane declares a path for. 8 = build the consumer; 0-2 = enforcement is the prerequisite"
grep_log "#723 captures all distinct"    "screen captures are distinct" "the CLEAN path; without it, absence of #713 also meant 'the hash raised'"
grep_log "#722 served build verified"    "served build matches the source" "the CLEAN path; its absence no longer means 'probe did not run' is indistinguishable"
grep_log "#713b shared-route sharing"    "share ONE route" "EXPECTED, not a defect: interaction states of one page. browse_home_rows shares in 53 of 53 runs"
grep_log "#713 identical captures"       "screens captured the SAME image" "103 of 127 runs, 32 of 43 live; every score from a shared capture is of the wrong page"
grep_log "#712 count advanced on a latch" "on a LATCHED average" "the stable-rounds precondition cannot reset; r146 fast-released this way at live 0.6409"
grep_log "#711 gate left the app behind" "the gating average has left the app behind" "gating avg is #500 best-ever-per-screen; live is THIS capture. r147 r6: 0.700 vs 0.3817"
grep_log "#715 served build is stale"    "the SERVED frontend does not know" "a hit VOIDS those screens' scores; #713's cause, caught before the capture"
grep_log "#715 probe inconclusive"       "715 probe inconclusive" "fires if route literals do NOT survive the bundle — then the check needs rethinking, not the app"
grep_log "#707 invented asset staged"    "staged .* placeholder asset(s) the frontend referenced" "each hit = a path the lane invented instead of search_icons/save_image or drawing it"
grep_log "#706 integration promoted"     "promoted integration -> main" "should appear once per delivered run; then rev-list --count main..integration should be 0"
grep_log "#706 promotion refused"        "promotion did not happen" "the callee declined and names why — read it, do not assume the topology"
grep_log "#701 coverage completion failed" "coverage-chain completion FAILED" "any hit explains a coverage stuck-blocker; was silent before"
grep_log "#700 identical-content routes" "routes render identical content" "#615 detector, reporting for the first time; r146 had a 4-route group"
grep_log "#698 better state available" "better state available: an earlier capture" "fires when an earlier round beat what ships; r146 would have"
grep_log "#696 suppressed load failure" "\[projected\] data load failed:" "each hit = a page that rendered as an ordinary empty state while its API failed"
# #692's signature is in the BACKEND CONTAINER log under FW_DEBUG, not here — see item 20. This
# line only catches it if the container log was folded into the run log.
grep_log "#692 owner unresolved"         "fw_owner_val.unresolved_sub_entity" "needs FW_DEBUG + the CONTAINER log; absence here proves nothing"
echo
echo "--- B. the nine findings that disk could not settle ---"

# 18. MCP surface: registered implemented, shipped in 23% of deliveries
if [[ -d "$RUN/mcp_server" ]]; then
    say "DATA" "18 mcp_server/ at run root" "PRESENT — the scaffold reached the root"
else
    wt=$(ls -d "$RUN"/worktrees/*/mcp_server 2>/dev/null | head -1 || true)
    if [[ -n "$wt" ]]; then say "DATA" "18 mcp_server/" "ONLY in a worktree -> merge gap: $wt"
    else say "DATA" "18 mcp_server/" "ABSENT everywhere (corpus: 125/144) — with #691b in the \
build this now means the RESTORE failed too; read the A-section #691/#691b pair"; fi
fi
# The mechanism is settled, so ask the settled question directly: is the subtree on a branch the
# release was not cut from? Costs one git call and answers item 18 without reading any log.
if git -C "$RUN" rev-parse --git-dir >/dev/null 2>&1; then
    _mcp_sha=$(git -C "$RUN" log --all -1 --format=%h --diff-filter=AM -- mcp_server 2>/dev/null || true)
    _head=$(git -C "$RUN" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
    if [[ -z "$_mcp_sha" ]]; then
        say "DATA" "18 mcp_server/ in git" "no commit ever added it — the WRITER did not run"
    elif git -C "$RUN" merge-base --is-ancestor "$_mcp_sha" HEAD 2>/dev/null; then
        say "DATA" "18 mcp_server/ in git" "$_mcp_sha is an ancestor of $_head — on the delivery line"
    else
        say "DATA" "18 mcp_server/ in git" "$_mcp_sha is NOT an ancestor of $_head — stranded off \
the delivery branch, exactly the r145/r146 shape"
    fi
fi

# 13. runtime-validation matrix: does tasks/tasks.yaml ever appear?
if [[ -f "$RUN/tasks/tasks.yaml" ]]; then
    say "DATA" "13 tasks/tasks.yaml" "PRESENT — the matrix can finally be enforced"
else
    say "DATA" "13 tasks/tasks.yaml" "absent (corpus: 0/144). If never written, the writer \
(task_definition_tools.py) is unreachable and the matrix should key on something else"
fi

# 10. chains registered but never run
if [[ -f "$HUBS/registryhub_verification_chains.json" ]]; then
    python3 - "$HUBS/registryhub_verification_chains.json" <<'PY'
import json,sys,collections
d=json.load(open(sys.argv[1]))
ch=d if isinstance(d,list) else list(d.values())
c=collections.Counter(str(x.get('status')) for x in ch if isinstance(x,dict))
reg=c.get('registered',0); tot=sum(c.values())
print(f"{'DATA':<9} {'10 chains never run':<46} {reg} registered / {tot} total "
      f"(corpus: 267 across 26 runs). If >0 at run end, find out whether the executor "
      f"skipped them or never reached them")
PY
else say "n/a" "10 chains never run" "no chain store"; fi

# 17. consumer registration — the input the breaking-change machinery needs
if [[ -f "$HUBS/registryhub_consumers.json" ]]; then
    python3 - "$HUBS/registryhub_consumers.json" "$RUN" <<'PY'
import json,sys,os,re
d=json.load(open(sys.argv[1]))
n=len([k for k in d if not k.startswith('_')])
api=os.path.join(sys.argv[2],'app/frontend/src/services/api.js')
calls=len(set(re.findall(r'["\'`](/api/[^"\'`?]+)', open(api,encoding='utf-8',errors='ignore').read()))) if os.path.isfile(api) else -1
print(f"{'DATA':<9} {'17 consumers registered':<46} {n} registered vs {calls} /api paths in "
      f"api.js (corpus: median 0 vs 7; only 36/144 runs registered any)")
PY
else say "n/a" "17 consumers registered" "no consumer store"; fi

# 16. hub stores created and never written
python3 - "$HUBS" <<'PY'
import json,glob,os,sys
empty=[]
for f in sorted(glob.glob(os.path.join(sys.argv[1],'*.json'))):
    try: d=json.load(open(f))
    except Exception: continue
    if isinstance(d,dict) and not [k for k in d if not k.startswith('_')]:
        empty.append(os.path.basename(f)[:-5])
print(f"{'DATA':<9} {'16 hub stores never written':<46} {len(empty)} empty "
      f"(corpus: 19 of 43). {', '.join(empty[:6])}{' …' if len(empty)>6 else ''}")
PY

# 15. blank component crops
if [[ -d "$RUN/design/crops" ]]; then
    python3 - "$RUN/design/crops" <<'PY'
import glob,os,sys
try:
    from PIL import Image
except Exception:
    print(f"{'n/a':<9} {'15 blank crops':<46} PIL unavailable"); raise SystemExit
blank=0; tot=0
for p in glob.glob(os.path.join(sys.argv[1],'**','*.png'), recursive=True):
    tot+=1
    if os.path.getsize(p) >= 1500: continue
    try:
        c=Image.open(p).convert('RGB').getcolors(maxcolors=200000)
        if c and len(c)<=1: blank+=1
    except Exception: pass
print(f"{'DATA':<9} {'15 blank crops':<46} {blank} single-colour of {tot} "
      f"(corpus: 847, mostly player_controls). Also grep the log for reads of design/crops/")
PY
else say "n/a" "15 blank crops" "no crops dir"; fi

# 14. max_ticks cannot bind
if [[ -f "$RUN/run_budget.json" ]]; then
    python3 - "$RUN/run_budget.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); c=d.get('caps') or {}; u=d.get('usage') or {}
print(f"{'DATA':<9} {'14 max_ticks':<46} ticks {u.get('ticks')} / cap {c.get('max_ticks')}, "
      f"elapsed {u.get('elapsed_sec')} / {c.get('max_wall_sec')} (corpus: max 6 ticks ever)")
PY
else say "n/a" "14 max_ticks" "no run_budget.json"; fi

# 11. player_controls / title_episodes never judged
python3 - "$RUN" <<'PY'
import json,glob,sys,os
un=set()
for f in glob.glob(os.path.join(sys.argv[1],'design/visual_gate/**/*.json'), recursive=True):
    try: d=json.load(open(f))
    except Exception: continue
    for x in ((d.get('coverage') or {}).get('unjudged') or []): un.add(str(x))
hit=[x for x in ('player_controls','title_episodes') if x in un]
print(f"{'DATA':<9} {'11 never-judged screens':<46} "
      f"{'still unjudged: '+', '.join(hit) if hit else 'both judged this run'} "
      f"(corpus: both unjudged in 40/40)")
PY

# 12. the persistent notebook
python3 - "$RUN" <<'PY'
import glob,os,sys
rows=[]
for d in sorted(glob.glob(os.path.join(sys.argv[1],'memory-bank','*'))):
    p=os.path.join(d,'notebook.md')
    if os.path.isfile(p): rows.append((os.path.basename(d), os.path.getsize(p)))
big=[r for r in rows if r[1]>800]
print(f"{'DATA':<9} {'12 notebook use':<46} {len(big)}/{len(rows)} agents wrote a "
      f"non-trivial notebook (corpus median 730 B = template only)")
PY

# 8. r135's nav order
python3 - "$RUN" <<'PY'
import re,glob,sys,os
f=glob.glob(os.path.join(sys.argv[1],'app/frontend/src/components/TopNav.jsx'))
if not f:
    print(f"{'n/a':<9} {'8 nav order':<46} no TopNav.jsx"); raise SystemExit
s=open(f[0],encoding='utf-8',errors='ignore').read()
pairs=re.findall(r'(?:href|to)=["\']([^"\']+)["\'][^>]*>\s*([^<{][^<]*?)\s*<', s)
labels=[l.strip() for _,l in pairs if l.strip()]
hrefs=[h for h,l in pairs if l.strip()]
dup_h=len(hrefs)!=len(set(hrefs))
note=""
if len(labels)<3:
    note=" (few plain-text labels matched — the nav may render labels from an array; read it)"
print(f"{'DATA':<9} {'8 nav order + duplicate destinations':<46} {labels[:7]}"
      f"{'  DUPLICATE HREFS' if dup_h else ''}{note}")
PY

echo
echo "--- C. the wasted-step ranking, re-measured ---"
if [[ -n "$LOG" && -f "$LOG" ]]; then
    python3 - "$LOG" <<'PY'
import re,sys,collections
c=collections.Counter()
for l in open(sys.argv[1],encoding='utf-8',errors='ignore'):
    m=re.search(r'\] ❌ (\w+) FAILED \(', l)
    if m: c[m.group(1)]+=1
tot=sum(c.values())
print(f"{'DATA':<9} {'failed tool calls (each ~1 wasted step)':<46} {tot}")
for k,v in c.most_common(6):
    print(f"{'':<9} {'  '+k:<46} {v}")
print(f"{'':<9} {'  corpus baseline, per run':<46} "
      f"test_api 22, chain-register 28, write 18, workhub_task 20 (medians)")
PY
else say "n/a" "wasted-step ranking" "no run log given"; fi
echo
echo "Read EXPERIMENTS_PENDING_2026-08-13.md for what each number means and what to conclude."
