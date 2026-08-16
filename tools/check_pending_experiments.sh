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
    # #756: grep the WHOLE file, not the last 5 lines. `[main-exit]` is printed the moment
    # main() returns, and asyncio tasks that were already in flight keep flushing AFTER it —
    # r149 printed it 26 lines from the end, so `tail -5` declared a FINISHED run unfinished
    # and stamped every number below with the "this is a snapshot" banner. I then read that
    # banner as "the run was killed" and spent a turn on a death that never happened. A
    # position-based test for a whole-file fact is the same mistake #717 was written to stop.
    if ! grep -q -- "\[main-exit\]" "$LOG"; then
        echo "############################################################################"
        echo "#  WARNING: this run has NOT finished — no [main-exit] anywhere in the log."
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
grep_log "#736 blank capture refunded"   "blank capture, attempt refunded" "r148 blanked 10 of 12 screens for 9 rounds; #711 fired on it twice. Any #711 hit ABOVE with no hit here is now a GENUINE divergence — that is what #736 bought"
grep_log "#737 blackout held off plateau" "blackout round does NOT count toward the plateau" "each hit = a round that used to feed the #138 escape; r148 shipped v1.0.0 on 5 of them with the SPA crashing on every route"
grep_log "#737 SPA crash filed"          "is not a function" "the r148 killer, found by the verifier while the gate called itself clear. Any hit = the delivered app may not render — check it before trusting the release"
grep_log "#715 served build is stale"    "the SERVED frontend does not know" "a hit VOIDS those screens' scores; #713's cause, caught before the capture"
grep_log "#715 probe inconclusive"       "715 probe inconclusive" "fires if route literals do NOT survive the bundle — then the check needs rethinking, not the app"
grep_log "#738 served bundle frozen"     "SERVED bundle did not change while app/frontend did" "the half #715 is blind to: routes unchanged, fix never reached the container. r148 died of this and #715 would have called it clean"
grep_log "#739 UI evidence is thin"      "ui_smoke_pass=True rests on" "the passed/failed split behind ui_smoke_pass. r148 read True off landing+login while 12/14 pages crashed; this is the number item 13's decision always lacked"
grep_log "#740 console error captured"   "distinct uncaught/console error(s) during this capture" "the browser's OWN error text, grouped by message. A blank capture with NO hit here is the interesting case: empty shell, nothing raised"
grep_log "#743 FAILED task at the cut"   "in status FAILED at the delivery cut" "an authorised 'attempted and did not work' at release. 20 of 148 corpus runs end with one and 4 of them released (#755-corrected); the narrowest gate candidate on the table"
grep_log "#743 open P0 bug at the cut"   "P0 BUG task(s) are still open at the delivery cut" "kind=bug only, so stale structural tasks cannot inflate it. Corpus: 90 of 129 runs, 90 of 90 released"
grep_log "#254 downgrade refused"       "refused to downgrade" "was UNREACHABLE for 255 runs (#746) — first sighting tells us whether the r51 guard is load-bearing or historical"
grep_log "#748 compose failure cause"    "compose up FAILED for run" "216 corpus boot failures recorded the cause in the store and none said why in the log; a hit means the reason travels with the failure now"
grep_log "#758 declaration overrules"    "declared reference OVERRULES the name guess" "item 67 open question: do the lane declaration and the token guess ever disagree? A hit = the heuristic HAS been binding the wrong page"
grep_log "#765 inverse alias refused"    "refusing to alias" "the alias repair would have wired an operation to its OPPOSITE (unlike->like). A hit = the lane imported a name api.js does not export, and the near-match was its inverse"
grep_log "#767 zero kept its reply"      "raw_judge_reply" "for any screen at 0.00, the judge's own text. Empty/shapeless = #766 was the cause; a considered verdict = the rubric scores rendered pages at zero"
grep_log "#769 capture failed"           "capture FAILED for screen" "the reason a screen was never photographed. r150 lost 9 of 12 to a bare `except: continue` and the gate reported 0.1727 about the HARNESS"
grep_log "#770 auto-repair failed"       "auto-repair" "a source-mutating repair threw and the gate then reported the symptom it was meant to clear. Any hit = read the blocker below it as a consequence"
grep_log "#774 spec owner column lost"   "SPEC names an owner column" "the contract is self-consistent and still not the requirement. 8 of 111 corpus runs, every one profile_id on the per-profile private tables"
grep_log "#780 route-filter task filed"  "Pass a route-derived filter on" "the #615 finding as a TASK, not a log line. r151 computed the fix and filed nothing among its 136 tasks"
grep_log "#758 declaration bound"        "declared reference bound screen" "how many screens the lane STATED instead of the gate guessing. r149 carried 15 declarations and logged none of this"
grep_log "#657 picker stall"            "never got past the PROFILE PICKER" "introduced 08-12, only 5 runs since, 0 hits — TOO YOUNG to call dead. A hit means profile selection does not persist; keep counting"
grep_log "#750 DELIVERY VETOED"          "DELIVERY VETOED — the app does not render" "user-approved veto: blackout past the refund cap WITH console errors. Would have stopped r148. Any hit = no release cut, deliberately"
grep_log "#751 failed task blocks"       "unresolved_failed_tasks" "13% of corpus runs end with a failed task; 4 of them released anyway (#755-corrected)"
grep_log "#752 UI evidence contradicts"  "validation_ui_evidence_failed" "passing AND failing UI records in one run: 6 of 148 corpus runs"
grep_log "#707 invented asset staged"    "staged .* placeholder asset(s) the frontend referenced" "each hit = a path the lane invented instead of search_icons/save_image or drawing it"
grep_log "#706 integration promoted"     "promoted integration -> main" "should appear once per delivered run; then rev-list --count main..integration should be 0"
grep_log "#706 promotion refused"        "promotion did not happen" "the callee declined and names why — read it, do not assume the topology"
grep_log "#701 coverage completion failed" "coverage-chain completion FAILED" "any hit explains a coverage stuck-blocker; was silent before"
grep_log "#700 identical-content routes" "routes render identical content" "#760 dedupes per GROUP, so the count is now defects not passes — r149 read x108 for TWO findings (54x each). Bounded at <=2 per group by item 78's dual import"
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

# --- D2. #776: scoped by SOMEONE is not scoped by the RIGHT someone ------------------------------
# #749 accepts any of (user_id|profile_id|owner_id|account_id) as an owner predicate, so a GET on
# a per-PROFILE table filtering `WHERE user_id = :uid` reads CLEAN. r151 is the case: its DDL
# declares BOTH columns on my_list/ratings/continue_watching, POST /api/my-list writes profile_id
# (x6), and GET /api/my-list + GET /api/continue-watching scope by user_id only -- so profile B
# sees profile A's list, which is the one privacy rule those specs state. #774 is green too (the
# contract HAS profile_id), so two checks pass over one real leak.
# Corpus: 16 runs declare both columns on a table; 2 read it by the broader owner only (r151, r60).
python3 - "$RUN" <<'D2'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
ddl = root / "app" / "database" / "init" / "01_init.sql"
routes = root / "app" / "backend" / "custom_routes.py"
lab = "#776 read scoped by the WIDER owner"
if not ddl.is_file() or not routes.is_file():
    print("%-9s %-46s %s" % ("n/a", lab, "no ddl/custom_routes")); raise SystemExit(0)
both = set()
for m in re.finditer(r'CREATE TABLE(?:\s+IF NOT EXISTS)?\s+"?([A-Za-z_]\w*)"?\s*\((.*?)\n\s*\);',
                     ddl.read_text(errors="ignore"), re.S | re.I):
    if re.search(r"\buser_id\b", m.group(2)) and re.search(r"\bprofile_id\b", m.group(2)):
        both.add(m.group(1))
if not both:
    print("%-9s %-46s %s" % ("n/a", lab, "no table declares both owners")); raise SystemExit(0)
src = routes.read_text(errors="ignore")
bad = set()
for h in re.split(r"\n@(?:router|app)\.", src)[1:]:
    if not h.split("\n", 1)[0].lower().startswith("get"): continue
    if "profile_id" in h: continue
    for t in both:
        if re.search(r"\b%s\b" % re.escape(t), h) and "user_id" in h: bad.add(t)
note = (", ".join(sorted(bad)) + " -- read by user_id on a per-profile table") if bad else \
       ("%d table(s) declare both; every GET uses the narrow one" % len(both))
print("%-9s %-46s %s" % ("LEAK" if bad else "clean", lab, note + "  (corpus: 2 of 16)"))
D2

# --- D. #749: does the DELIVERED backend leak another user's rows? -------------------------------
# Audited across the corpus and CLEAN — 0 of 135 delivered `custom_routes.py` have a GET handler
# reading a per-user table with no owner predicate and no Python-side scoping. That is a result,
# not an absence: the probe was checked against a planted leak (caught) and a scoped handler (not
# flagged) before the zero was believed. Kept here so the clean state is a REGRESSION guard rather
# than a one-off audit — memory says to audit the delivered app even after a green gate (#569 was
# a live leak in r134's shipped /api/search).
python3 - "$RUN" <<'PY'
import re, sys, pathlib
OWNER = r'(user_id|profile_id|owner_id|account_id)'
p = pathlib.Path(sys.argv[1]) / "app" / "backend" / "custom_routes.py"
if not p.is_file():
    print("%-9s %-46s %s" % ("n/a", "#749 owner-scoped delivered reads", "no custom_routes.py"))
    raise SystemExit(0)
src = p.read_text(errors="ignore")
bad = []
for h in re.split(r'\n@(?:router|app)\.', src)[1:]:
    head = h.split('\n', 1)[0]
    if not head.lower().startswith('get'):
        continue
    for m in re.finditer(r'SELECT\b[^"\';]{10,300}', h, re.I):
        st = m.group(0)
        if not re.search(r'FROM\s+\w+', st, re.I):
            continue
        if re.search(r'(WHERE|AND|ON)\b[^;]{0,200}?' + OWNER, st, re.I):
            continue
        if not re.search(OWNER, st, re.I):
            continue
        if re.search(OWNER + r'\s*(==|!=|in\b)', h) or re.search(r'current_user|_owner_val|profile_id\s*=', h):
            continue
        bad.append(" ".join(st.split())[:80])
lab = "#749 owner-scoped delivered reads"
if bad:
    print("%-9s %-46s %s" % ("P0", lab, "%d unscoped read(s): %s" % (len(bad), "; ".join(bad[:2]))))
else:
    print("%-9s %-46s %s" % ("DATA", lab, "clean (corpus: 0 of 135 delivered backends leak)"))
PY

# --- E. #759: the session's SILENT fixes, measured from artifacts --------------------------------
# A sweep of #736-#758 found six with neither a log signature nor a checker line: #741 #742 #744
# #745 #747 #754. (#747 is a false positive — #758 logs it.) The other five change data rather
# than emit text, so the honest instrument is a measurement, not a new log line: adding five
# warnings to say "I ran" would be noise, and #758's lesson is about EVALUABILITY, not volume.
python3 - "$RUN" "${LOG:-}" <<'PY'
import json, os, re, sys
run, log = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
def say(k, lab, note): print("%-9s %-46s %s" % (k, lab, note))
def load(p):
    try:
        with open(os.path.join(run, "shared", "hubs", p)) as f:
            d = json.load(f)
        return [r for r in (d if isinstance(d, list) else list(d.values())) if isinstance(r, dict)]
    except Exception:
        return None

tasks = load("workhub_tasks.json")
if tasks is None:
    say("n/a", "#744/#745 bug lifecycle", "no workhub_tasks.json")
else:
    bugs = [t for t in tasks if (t.get("metadata") or {}).get("kind") == "bug"]
    done = [b for b in bugs if str(b.get("status")) == "completed"]
    stale = [b for b in done if (b.get("metadata") or {}).get("bug_state") in
             ("open", "triaged", "assigned", "in_progress", "fix_proposed")]
    say("DATA", "#744 completed bugs hidden from open list",
        "%d of %d completed bugs still read bug_state=open — each was a phantom "
        "'open P0' before #744 (corpus: 616)" % (len(stale), len(done)))
    say("DATA", "#745 retro would count these as closed",
        "%d fixed bugs; before #745 the retro reported closed=%d (corpus: 127 of 129 "
        "runs reported 0)" % (len(done),
                              len([b for b in bugs if (b.get("metadata") or {}).get("bug_state") == "closed"])))

# #742: are affected_endpoint values parseable? corpus baseline 449/1129 = 40%
ev = load("eventhub_events.json")
if ev is None:
    say("n/a", "#742 affected_endpoint parseable", "no eventhub_events.json")
else:
    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("bug_artifacts"), dict):
                yield o["bug_artifacts"]
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    seen, tot, ok = set(), 0, 0
    for ba in walk(ev):
        k = json.dumps(ba, sort_keys=True)[:200]
        if k in seen:
            continue
        seen.add(k)
        ae = str(ba.get("affected_endpoint") or "")
        if " " not in ae:
            continue
        tot += 1
        p = ae.split(" ", 1)[1]
        if p.startswith("/") and " " not in p and "(" not in p:
            ok += 1
    if tot == 0:
        say("n/a", "#742 affected_endpoint parseable", "no bug carried one this run")
    else:
        say("DATA", "#742 affected_endpoint parseable",
            "%d of %d well-formed (corpus baseline 449/1129 = 40%%; n<10 proves nothing)"
            % (ok, tot))

# #741: bugs whose files name no lane but do name a language
LANE = ("backend", "frontend", "database", "migrations", "db")
EXT = ("jsx", "tsx", "vue", "svelte", "css", "scss", "less", "py", "sql")
if tasks is not None and ev is not None:
    n = 0
    seen = set()
    for ba in walk(ev):
        k = json.dumps(ba, sort_keys=True)[:200]
        if k in seen:
            continue
        seen.add(k)
        fs = ba.get("affected_files") or []
        if not isinstance(fs, list) or not fs:
            continue
        if any(s.strip().lower() in LANE for p in fs for s in str(p).replace("\\", "/").split("/")):
            continue
        if any(str(p).lower().rsplit(".", 1)[-1] in EXT for p in fs if "." in str(p)):
            n += 1
    say("DATA", "#741 bugs routed by extension alone",
        "%d bug(s) whose files name no lane but do name a language — unowned before #741 "
        "(corpus: +25)" % n)

# #754: the compose-path defect is the ABSENCE of this cause
if log and os.path.isfile(log):
    try:
        txt = open(log, errors="ignore").read()
    except Exception:
        txt = ""
    miss = len(re.findall(r"missing files: \[", txt))
    # NOT a verdict on the fix: a run that PREDATES #754 shows the baseline, and this script
    # cannot tell which build it is reading. The header already says GONE/STILL is not
    # self-interpreting; saying "the fix did not cover this" would be the exact error the
    # header warns about, and it is the one I made when I first wrote this line.
    say("GONE" if miss == 0 else "STILL", "#754 compose path resolves",
        ("0 'missing files' this run" if miss == 0 else
         "x%d 'missing files' — check the build date FIRST: pre-#754 this is the BASELINE, "
         "post-#754 it means the cwd fix missed a call path" % miss) + " (r149, pre-fix: 13)")
else:
    say("n/a", "#754 compose path resolves", "no run log given")
PY

# 9. #782 the projected metadata row reads via fallback accessors, not bare field names
python3 - "$RUN" <<'PY'
import glob,os,sys
pages=glob.glob(os.path.join(sys.argv[1],'app/frontend/src/pages/*.jsx'))
if not pages:
    print(f"{'n/a':<9} {'9 #782 metadata accessors':<46} no projected pages"); raise SystemExit
bare=[os.path.basename(f) for f in pages
      if any(t in open(f,encoding='utf-8',errors='ignore').read()
             for t in ('cur.year','ep.duration || ep.runtime','cur.duration || cur.runtime'))]
emitted=[f for f in pages if 'const _yearOf' in open(f,encoding='utf-8',errors='ignore').read()]
if bare:
    print(f"{'STILL':<9} {'9 #782 metadata accessors':<46} {len(bare)} page(s) still read bare "
          f"field names {bare[:3]} — 13% of runs alias year, 17% of episode tables alias duration")
elif not emitted:
    print(f"{'n/a':<9} {'9 #782 metadata accessors':<46} no reference-structured page in this run")
else:
    # Presence of the accessor is NOT presence of the chip: it still needs the column to exist.
    # Read the title_detail capture for the verdict; this only says the fix reached the build.
    print(f"{'GONE':<9} {'9 #782 metadata accessors':<46} {len(emitted)} page(s) use "
          f"_yearOf/_durOf/_genresOf — now LOOK at title_detail.png for a year chip beside the rating")
PY
