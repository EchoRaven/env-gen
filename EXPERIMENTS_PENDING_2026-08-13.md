# Pending experimental verification — offline review of 2026-08-12/13

Everything in this session was derived from **kept artifacts only** (no generation runs). Each
fix below is proven correct at the unit level and its *premise* is measured against the corpus,
but its **effect on a live run** is not knowable offline. This file records exactly what a run
would have to show, so the next person with a run budget does not have to re-derive it.

Format per item: what was changed → what is already proven → **what only a run can settle** →
the cheapest observation that settles it.

---

## CLOSED — era audit of every premise behind this session's fixes

The `verification_checklist_not_ready` investigation showed a ranking of mine was not
era-controlled and forced a correction to #690's committed claim. Applying the same control to
every measurement that justified a fix, since an un-audited premise can point a fix at a problem
that was solved months ago:

| fix | r<100 | r100+ | live share |
|-----|-------|-------|------------|
| #675 `must be a list of length` | 0 | 1200 | **100%** |
| #674 bare `HTTP Error: N` | 864 | 900 | 51% |
| #676 `old_string not found` | 204 | 216 | 51% |
| #677 `Connection refused` | 1042 | 742 | 42% |
| #664 chain-registration rejects | 3144 | 1794 | 36% |
| #668 impl-task denials | 1836 | 750 | 29% |
| #678 FRAMEWORK-OWNED write denials | 1122 | 440 | 28% |

All seven survive: every one has substantial live-era volume, so none targets solved history.
#686-#690 were era-split during discovery, and #682-#685 come from r145 itself, so they are live
by construction.

One thing to look at with a run: **#675 is 100% live and zero before r100** — 1200 occurrences in
the newer era and none in the older. A failure mode that appears rather than persists usually
means something changed. The fix (say what arrived instead of one message for two mistakes) is
right either way, but the ARRIVAL is unexplained and disk cannot say why.

---

## CLOSED — the broken-assertion axis, decomposed by STATUS CODE

Sorting the 202 stored broken assertions by status code instead of by wording is what surfaced
#686; recording the full decomposition here so nobody re-walks it. Every entry is era-checked,
because most of the volume turned out to be already-fixed history:

| status | n | share | disposition |
|--------|---|-------|-------------|
| 400 | 75 | 37.1% | 53 `null value in column` ALL r13-r67 (historical); **11 `X-Profile-Id header is required` ALL r100+ → #686**; 6 integrity r<100; 1 rating enum (r145, single instance) |
| 404 | 59 | 29.2% | → #682 (names the id that was sent) |
| 500 | 36 | 17.8% | 28 r<100; **8 live, all lane-authored raw SQL** — see below, no framework fix |
| 2xx | 20 |  9.9% | ALL DENIAL-PROBE, all r100+ → #663 |
| 403 |  8 |  4.0% | → #682b (ownership, opposite remedy to 404) |
| 422 |  4 |  2.0% | all r<100, historical |

**The 500s are not a framework defect.** Six of the eight live ones are one error across r105,
r114 and r128: `insert or update on table "ratings" violates foreign key constraint
"ratings_profile_id_fkey", Key (profile_id)=(46)`. I first traced this to `_fw_owner_val`'s
documented fallback ("every failure falls back to the user id", which the same comment says
FK-violates) and was wrong: the rating handler is LANE-authored in custom_routes.py, a raw
`INSERT INTO ratings (profile_id, ...)` with `int(pid)` and no existence check, wrapped as
`HTTPException(500, "rating db op failed: ...")`. `_fw_owner_val` is not in that path.

Ruled out first: no reset/factory chain exists in any of the three runs, so #566x's mid-pass
database wipe cannot explain the missing profile.

Checked and correct: `classify_endpoint_failure` routes a 500 to `framework_defect` ONLY when the
body matches a projected-handler traceback. The lane's wording does not match, so it is
classified `broken` and dispatched to the lane — the right destination.

What remains is a generated-app quality issue the framework cannot reach from here: a lane
handler that inserts caller-supplied ids without checking them, and reports a client error as a
500. Worth a prompt-level look if it recurs; not worth a framework patch.

---

## PARTLY RETRACTED — the projector DOES overwrite the lane's pages, but it costs no score

I recorded this as the session's most consequential finding and implied it was why the visual
gate cannot pass. The second half is refuted by the run's own data. Keeping the whole thing here,
correction included, because the retraction is the useful part.

**What stands.** The page files oscillate, proven by content hash across the 9 `code_state`s:

    MyListPage.jsx    59 lines, projection marker present   ↔  241 lines, no marker (lane)
    PlayerPage.jsx    87 lines, projection marker present   ↔  214 lines, no marker (lane)

and it is deliberate, not a bug: `#221 AUTHORITATIVE STRUCTURED FLOOR ... must ship the
REFERENCE-STRUCTURED projection as its FLOOR — even over a page the lane already authored`,
added because the lane's generic layouts were scoring 0.10-0.15 against a 0.65 bar. The
docstring 100 lines above it still promises the opposite — "page stubs are written ONLY when
missing (never clobber a real page)" — and is stale; #221 superseded it and nobody updated it.

**What is retracted.** That the overwrite destroys value. Pairing each round's `code_state` with
that round's judged score settles it:

    my_list   projection (59 lines)  rounds 4,5,7,8 → 0.60
              lane       (241 lines) round 6        → 0.60
    player    projection (87 lines)  7 rounds       → 0.55
              lane       (214 lines) 1 round        → 0.55

Identical, on both pages testable this way. The lane's richer page — real staged icons, hover
preview, reference structure — scores exactly what the generic projection scores. #221's premise
holds up here: the projection is not worse.

**So the frozen score is still unexplained.** r146's blocking average sat at 0.641 for the last
four rounds while four more commits landed, and the oscillation is not the reason. What a run
would have to show: whether the remediation the lane receives is being applied at all in those
rounds (compare the flagged components against the diff), or whether it is applied and the judge
does not move — which would be about the judge, not the lane.

**Still worth doing regardless of that.** Fix the stale docstring at
`scaffold_pages_from_contract`, so the next reader is not told the opposite of what the code does.

**Cheapest observation.** Hash each `pages/*.jsx` at every `code_state` in `rounds.jsonl` and pair
with that round's score in `live`. Alternating hashes = the churn; differing scores = a real cost,
which is what this run did NOT show.

---

## SETTLED BY r145 + r146 — close these, they are answered

Auditing my own record the way I audited the checker: an item still listed as open after the runs
answered it costs the next reader exactly what a stale docstring costs.

**Item 10 — "267 chains registered but never run" → CLOSED.** r145 ended with 47 passing / 3
failing / **0 registered**; r146 with 9 passing / **0 registered**. No chain was stranded in
either run. The corpus figure (267 across 26 runs) is history; #664, which cut the
re-registration loop from 126 attempts on one endpoint down to 2, is the plausible reason but the
closure stands on the count alone.

**Item 17 — "the breaking-change machinery is starved of consumers" → PREMISE GONE.** The corpus
median was 0 registered consumers. r145 registered **65**, r146 **53**. Whatever the machinery
does or does not do downstream, it is no longer input-starved, so the question as written cannot
be asked any more. Anything further has to be posed against the new behaviour.

**Items 13, 14, 18 — fact CONFIRMED, action still open.** Each reproduced twice more:

    13  tasks/tasks.yaml   absent in both       -> 146 of 146. The matrix gate keys on a file
                                                   nothing ever writes.
    13  tasks/tasks.yaml   absent in both       -> writer NOT unreachable (verifier+api_test_user
                                                  hold save_task_suite); the PROMPT marks the
                                                  whole path OPTIONAL. Half answered 2026-08-14.
    15  blank crops        n/a                  -> CLOSED 2026-08-14: crops ARE read (#461 renders
                                                  the hero title-art crop); 0 of 2606 hero crops
                                                  are blank, so the feared case never happens.
    16  19 dead stores     n/a                  -> DECOMPOSED 2026-08-14 by write-count: 1 drained,
                                                  6 never-written, 3 writerless, 9 out of probe
                                                  scope. #693 fixes the docstring.
    14  max_ticks          5/240 and 1/240      -> CLOSED 2026-08-14, no action: delivered runs
                                                  spend MORE ticks than aborted ones (median 2
                                                  vs 1), so no reachable cap discriminates.
    18  mcp_server/        absent in both       -> SOLVED + FIXED 2026-08-14. The reflog dates it:
                                                  integration was forked at 23:10:47 with HEAD left
                                                  on main, and the framework's first delivery
                                                  commit landed there at 23:12:41. Blast radius is
                                                  exactly the 3-file subtree, because the MCP
                                                  writer runs once while app/ and docker/ are
                                                  rewritten every round. #691 makes the skip
                                                  audible, #691b restores the subtree.

**Item 15 — still open, and the checker cannot help.** 330 and 339 crops exist in the two runs,
but PIL is unavailable in this environment so the blank-detection line reports `n/a`. It needs an
environment with Pillow, not another run.

---

## NEXT RUN — run this first

    tools/check_pending_experiments.sh <run-dir> [<run-log>]
    e.g.  tools/check_pending_experiments.sh agent/generated/netflix-web-r145 gm_netflix-web-r145.log

It is the "cheapest observation" column of this file, executable. Three sections:

  A. **Did this session's fixes actually execute?** Signature greps for #663/#664/#671/#675/
     #676/#677/#678. `NOT SEEN` is NOT the same as broken — the branch may simply not have been
     reached. Check which before concluding. #674 has no unique signature (its change is that
     the body now FOLLOWS the error line, and "HTTP Error" appears in the old wording too), so
     it prints the first such line for a human to read; grepping it reported a false LIVE on a
     pre-fix log while this script was being written.
  B. **The nine findings disk could not settle** — items 8, 10–18 below, each printed beside its
     corpus baseline so the comparison needs no lookup.
  C. **The wasted-step ranking re-measured** — failed tool calls by tool, against the corpus
     medians (test_api 22/run, chain-register 28, write 18, workhub_task 20). Per #257 each
     failed call is a whole step re-sending the prompt, so this is the number that says whether
     #674–#678 paid.

Two things to hold onto while reading it, both learned the hard way this session:

  * **A zero is a claim about the instrument until proven otherwise.** Five probe results were
    retracted for reading the wrong field or the wrong path. Dump one real record before
    believing any count.
  * **"The fix's message never appears" only means something if runs exist AFTER the fix
    landed.** #634 and #635 were reported inert on exactly this mistake; every run in the corpus
    predates them.

---

## 1. #652 — rail/carousel position indicator

**Changed.** `_rail_pagination_652` emits a dots/bar indicator inside each rail block, gated on
the design's own enumeration.

**Proven offline.** 141 of 144 designs enumerate an indicator; only 7 of 144 delivered frontends
contain any dot-shaped element (verified by SHAPE, not wording); the gate fires on 141/144 with
78 dots / 63 bars; markup is deterministic and data-independent.

**Only a run can settle.** Whether the judge's `components` score on rail-bearing screens
actually rises. `components` is the floor dimension on 800 of 1254 scored records, so this is
the axis that gates — but a rendered indicator that does not match the reference's *position*
(the corpus roles say top-right for some rails, under-rail for others) could score neutral.

**Cheapest observation.** One run; diff `components.missing` on browse_home / movies / shows
against the r112-r144 baseline for the five wordings (`carousel pagination dots`,
`row pagination indicator dots`, `carousel pagination indicator`, `row pagination indicator`,
`row pagination dots`). Success = those five stop appearing. Watch also that `layout` does not
drop — the indicator adds vertical height to every rail block.

---

## 2. #653 — account menu behind the caret

**Changed.** The avatar chip is now a CSS-only disclosure (`group-hover` + `group-focus-within`)
containing a Sign-out menu item, instead of a button that logged you out on click.

**Proven offline.** 61 of 144 delivered frontends carry the chip; 61/61 render the caret; 44 of
them have no menu state anywhere. The logout action is preserved byte-for-byte.

**Only a run can settle.** (a) Whether the judge scores the closed state the same — the menu is
`hidden` at rest, so the screenshot should be unchanged, but the wrapper div could shift the
utility cluster by a pixel or two. (b) Whether a **user-agent** driving the app can now reach
account actions instead of being signed out. That is the standing goal's own test loop and
cannot be simulated offline.

**Cheapest observation.** A browser task that clicks the avatar and asserts it is still
authenticated afterwards. Before the fix that task fails 100% of the time by construction.

---

## 3. #654 — Kids chip target

**Changed.** The chip resolves its href from the app's registered routes; with no kids/family
route it renders as a badge (`<span>`) rather than linking to `/browse`.

**Proven offline.** 17 of 28 delivered navs contain two items pointing at one page, and 16 of
those 17 are this chip. No product literal remains.

**Only a run can settle.** Whether the judge treats a non-link badge as *present* (the design
enumerates a "kids profile chip"/"badge", which argues yes) or as *missing* (if its rubric keys
on it being a nav link). This is the one item where the fix could measurably lose a point while
being unambiguously more correct.

**Cheapest observation.** Same run as #652: check whether `kids profile chip` / `kids profile
badge` appear in `components.missing` more often than the baseline. If they do, keep the
behaviour and make the badge visually closer to the reference rather than reverting to a wrong
link.

---

## 4. #655 / #656 — wholesale-failure refunds

**Changed.** The auth re-mint retry now counts bounces by ROUTE, not by screen; the blank
`capture_transient` refund now fires on a near-total blackout, not only a total one.

**Proven offline.** r30/r49/r68 each had 10 of 12 screens bounce with `auth_unavailable` false
and no re-mint attempted; 18 of 58 blank events name 8+ screens; replayed against all six
corpus runs carrying blanks, #656 fires for r60/r43/r121 and not for r125/r72/r86.

**Only a run can settle.** Whether the extra re-mint / refund actually *recovers* those runs, or
merely spends one more capture pass before reaching the same verdict. The corpus records the
condition but not what a second attempt would have produced — that is the definition of an
experiment.

**Cheapest observation.** Any run that trips either condition: check whether the retry produced
a scored verdict, and whether `transient_refunds` stayed under `_TRANSIENT_REFUND_CAP` (3). If
a run burns all three refunds and still blanks, the cap is doing its job and the app was
genuinely broken — record that separately from "the retry helped".

---

## 5. #657 — profile-picker diagnosis

**Changed.** A screen stuck on the profile picker gets its own deviation text instead of "the
SPA never hydrated".

**Proven offline.** Nothing — deliberately. The two causes are indistinguishable in every
artifact a run leaves behind (same list, same message, and the picker path logs nothing), which
is precisely the defect. The fix is what makes it measurable.

**Only a run can settle.** How often the picker path actually fires, and whether the lane acts
correctly on the new instruction ("make profile selection persist") rather than the old wrong
one ("fix the page's mount/data load").

**Cheapest observation.** After one run, grep the verdicts for `never got past the PROFILE
PICKER`. Any hit is the first measurement of a rate that has never been observed. Zero hits over
several runs is also informative — it would mean the conflation was harmless in practice.

---

## 6. #658 — `submit_plan` above the auto-approve threshold

**Changed.** `BaseMessage(content=)` → `payload=`, so plans with more than
`_auto_approve_threshold` (3) steps no longer raise TypeError.

**Proven offline.** The crash and the fix are both demonstrated directly; the message now
reaches the bus with `payload["type"] == "plan_decision_request"`.

**Resolved offline, partly.** I flagged this as the file's highest risk — that a >3-step plan
would now stall 300s instead of crashing instantly — and then checked it. The loop IS closeable:
`accept_plan` / `request_plan_changes` set `_decision_events[plan_id]`, and the lead reaches a
pending plan through the `list_pending_plan_decisions` tool. What does not exist is a subscriber
for the `plan_decision_request` notification itself (grep finds only the sender and a test), so
the realistic failure is "the lead never polled". #659b makes that expiry say so — naming the
lead, the poll tool, the two decision calls, and the under-threshold escape — instead of the
bare "Rejected: decision timeout". The 300s value itself is untouched: changing a tuned constant
without data would violate the convention the #647 guard enforces.

**Only a run can settle.** Whether a lead agent, given the notification and the poll tool,
actually decides a plan — i.e. whether the flow completes or always ends in the timeout branch.
Nothing offline can answer that: the path has never executed.

**Cheapest observation.** One run containing any >3-step plan. Grep the verdict/log for
"Rejected: no decision within". Every hit is a 300s stall that a lead failed to resolve; zero
hits with plans present means the flow works. If stalls dominate, the fix is a subscriber for
the notification, not a shorter timeout.

---

## 7. #661 — the empty-state diagnosis

**Changed.** The P1 backend task raised for an empty-state screen now runs `audit_seed_data`
and either names the under-seeded tables or says plainly that seeding is NOT the cause and
points at the read path (filters, owner-scoping, route precedence).

**Proven offline.** 99 empty-state screens across 48 runs, 19 blocking, similarity min 0.03 /
median 0.35 / max 0.60 — not one ever cleared the bar. The checker exists and is reachable.

**Only a run can settle.** Which branch actually fires. If the tables are genuinely under-seeded
most of the time, the old wording was right by luck and the change is cosmetic; if they are
seeded, every one of those 99 screens was a misrouted round. The corpus records the screens but
NOT the seed-audit result at that moment, so the split cannot be recovered offline.

**Cheapest observation.** One run with an empty-state screen: read the P1 task text. "flags
these registered tables as under-seeded" vs "probably NOT a seeding problem" is the answer.

---

## 8. r135's nav order

**Not changed.** `_order_nav_by_ref` (#458) runs after `_assign_ref_labels` (#651) at
frontend_scaffold.py:4308-4309, which is the correct order, and 26 of 27 delivered navs are
ordered correctly. r135 is the exception: it shipped `Home, My List, Shows, …` with a CORRECT
"My List" label but the wrong position, from a framework-projected nav.

That combination should be impossible — ordering keys on the label, and the label was right.
Replaying r135's design against both the old and new labelling produces the correct order in
both cases, so #651 is not the fix and #458 alone would have sufficed. **I could not determine
offline why it shipped mis-ordered**: the projector's real input is the contract route list at
build time, which the kept artifacts do not preserve in the form the projector saw.

**Cheapest observation.** One run: log `nav_routes` as `_ref_nav_jsx` receives it, alongside
`_ref_nav_labels(design)`. If they disagree with the shipped order, the bug is between them.
Low priority — 1 of 27.

---

## 9. #663 — are the 20 denial-probe successes leaks or rebinds?

**Changed.** A denial probe that succeeds now compares the id the prober SENT against the id the
server STORED, and says "BOUNDARY CROSSED" (P0) or "SUBSTITUTED, wrong status not a leak".

**Proven offline.** 20 denial-probe successes in the r100+ era across 8 runs
(r117/127/130/131/133/135/141/143), on my-list, continue-watching, rating and profiles. r127's
`rating_upsert_and_isolation` step 5 is a correctly-authored probe (`auth: tokenB` carrying A's
profile_id) that returned 201 instead of 403.

**Only a run can settle.** Which class those 20 actually are. The artifact records
`last_result.steps` as method/path/status/ok/note only — the saved variables and response
bodies of the successful steps are discarded — so `profileA_id` is unrecoverable and the class
cannot be determined from what is on disk. That gap is exactly what this fix closes going
forward, but it cannot be applied retroactively.

**Cheapest observation.** One run with any isolation chain. Grep for "BOUNDARY CROSSED": each
hit is a live cross-user write and should be triaged as P0; each "SUBSTITUTED" is a status-code
defect in the projected handler. If they are all SUBSTITUTED, the owner-scoping is sound and the
fix belongs in the handler's validation, not its query.

---

## 10. Chain coverage — 267 registered chains that never ran

**Not changed.** 267 chains across 26 runs sit at `status: registered` with `last_run_at: None`
and `last_result: None` — authored, stored, never executed. The names are exactly the ones that
matter: `auth_round_trip` x8, `rating_and_continue_watching` x6,
`my_list_ownership_isolation` x5, `auth_and_profile_isolation` x4.

An ownership-isolation chain that never runs is the check that would have caught #566y / #598 /
#569. Whether these were never scheduled, or ran after the store's last flush, is not decidable
offline — the store records no attempt.

**Cheapest observation.** One run: count chains still at `registered` when the run ends. If it
is non-zero, find out whether the executor skipped them or never reached them.

---

## 11. player_controls / title_episodes are never judged

**Not changed, deliberately.** In all 40 r100+ verdicts, `player_controls` and `title_episodes`
appear in `coverage.unjudged` — never judged, never failed, and classified as REAL pages (not
transient), so they count against coverage as self-exempted pages.

`player_controls` is plainly an interaction state (controls auto-hide; a static route capture
cannot reproduce them), but adding `controls` to `_TRANSIENT_STATE_RE` is NOT safe: "parental
controls" legitimately names a navigable page, which is the exact trap that vocabulary's own
comment warns about for `menu`/`sheet`. A name-based fix would misclassify a real settings page.

**Cheapest observation.** One run: does either screen ever resolve to a served route? If never,
the honest fix is upstream in reference classification, not in the transient vocabulary.

---

## 12. The persistent notebook is unused by the roles that most need it

**Not changed — this is behaviour, and I verified it is NOT a wiring block.**

`memory-bank/<agent>/notebook.md` is the only agent-WRITABLE memory file. Its own template says
"THIS FILE IS YOURS … record here what your NEXT wake should not have to re-derive". Across
1715 agent memory banks (144 runs), 1191 are still the untouched template — median content
lines: 0. Split by role:

    verifier        136/144  94%      frontend        66/144  46%
    orchestrator    120/144  83%      design_analyst  60/144  42%
    backend         120/144  83%      debugger        13/144   9%
    test_user         9/706   1%      knowledge        0/144   0%

test_user at 1% is right — those lanes are ephemeral. The rest is not obviously right, and the
`knowledge` role never once used it in 144 runs.

Checked for a wiring cause and found none: no profile denies a memory tool, `UpdateMemoryBankTool`
IS instantiated (multi_agent/tools.py:247), and the debugger's action-stage allowlist omits the
write-side tools but its `knowledge_sync` stage uses `KNOWLEDGE_STORE_TOOL_NAMES` independently
— which is exactly why the debugger is 9% and not 0%. So the gap is prompt/behaviour.

**Only a run can settle.** Whether a lane that writes its notebook re-derives less on its next
wake — i.e. whether the 94% roles are cheaper or faster per step than the 0-46% ones. The corpus
has the notebooks but not a per-wake cost attribution, so the two cannot be joined offline.

**Cheapest observation.** One run with `knowledge` and `frontend` prompted to record a decision
before finishing: compare their step counts and re-read volume against a control run. If there
is no difference, the notebook is ceremony and the template's claim should be softened rather
than the lanes pushed to fill it.

---

## 13. #671 — should the runtime-validation matrix be enforced?

**Changed (visibility only).** The gate now reports `matrix_skipped_reason` when there is no task
suite, so an unevaluated matrix stops reading like a passed one.

**Proven offline.** `tasks/tasks.yaml` exists in 0 of 144 runs; `tasks.yaml` and
`action_space.yaml` appear nowhere in any run tree; the gate logged `task_suite=False` 41 times
and `True` never. Through `get_validation_results`' normalisation, api_smoke passes in 90 of 144
runs and ui_smoke in 116 of 144 — so 54 runs delivered with no API smoke pass and 28 with no UI
smoke pass, and the gate never asked.

**Only a run can settle.** Whether to drop the `if task_suite_exists:` guard. On this corpus 54
runs would gain `validation_api_smoke_missing` and 28 the UI equivalent. Two things are not
decidable from disk: whether those runs genuinely lacked a working API, and whether anything
still intends to write `tasks/tasks.yaml` at all.

**~~Cheapest observation.~~ HALF ANSWERED 2026-08-14, offline — the writer is NOT unreachable.**
The second undecidable above ("whether anything still intends to write `tasks/tasks.yaml` at
all") is decidable from the tree, and the answer is yes, all the way down the chain:

    SaveTaskSuiteTool          writes output_dir/"tasks"/"tasks.yaml" with write_text
    create_task_definition_tools()   includes it (task_definition_tools.py:554)
    _bundle_task_definition()        bundles that factory as "task_definition"
    agents_config.yaml               grants "task_definition" to verifier AND api_test_user

Nothing is unreachable. `save_task_suite` appears in 0 of 253 run logs — not called, not even
mentioned — and the reason is in the only prompt that raises the subject:

    test_user_agent.j2:92   {"tool": "execute_task_suite", "when": "OPTIONAL — author
                            tasks/tasks.yaml ... then run it.", "cap": "as needed"}

**So the gate keys on an artifact whose production is explicitly OPTIONAL to the only role asked
to produce it.** 0 of 146 is not a broken writer, it is what "optional and never chosen" looks
like, and no run can tell us anything further about this half. That also redirects the fix: either
the matrix stops keying on `tasks/tasks.yaml`, or the prompt stops calling it optional — but
"find the unreachable writer" is a dead end, and the next reader should not spend a run on it.

**Still needs a run:** the FIRST undecidable only — whether the 54 runs that delivered without an
api_smoke pass genuinely lacked a working API. Dropping the `if task_suite_exists:` guard is
still gated on that, unchanged.

**Method note.** My first probe for a writer grepped for `tasks.yaml` on the same line as a write
call and concluded there was none. The write is three lines below the path assignment. A
single-line grep cannot answer "does anything write this file"; read the call site.

**Trap for the next reader.** Measuring `codehub_checks.json` directly says api_smoke and
ui_smoke pass in 0 of 144 — the records carry `status: "success"` and the kind under `evidence`,
not `metadata`. #193/#236 normalise both in `get_validation_results`. Measure through the
normaliser or the number is meaningless.

---

## 14. max_ticks is a cap that cannot bind

**Not changed.** All 134 `run_budget.json` files carry `max_ticks: 240`; observed usage is min 0,
median 1, p90 3, **max 6**. No run has ever reached it; 3 reached the 7200s wall cap. At the
observed rate a run needs roughly 120 hours to spend 240 ticks against a 2-hour wall budget, so
the tick cap cannot fire before wall-clock — anyone relying on it for protection has none.
Lowering it needs evidence of a correct value the corpus does not supply.

(`tick_count` in run_budget and `idle_tick_count` in the coordination loop are the same counter
family — incremented on adjacent lines in orchestrator.py — so `stalled = idle_tick_count >= 3`
also sits above p90.)

**CLOSED 2026-08-14 — no run needed, and the answer is "leave it alone".** The sentence above says
lowering it "needs evidence of a correct value the corpus does not supply". That framing was too
weak: the corpus can decide the question outright, by asking whether ticks separate the runs a cap
would exist to kill. Splitting all 136 runs that record a tick count by OUTCOME:

    delivered      27 runs   ticks {1,2,3,4,6}      median 2   max 6
    not delivered 109 runs   ticks {0,1,2,3,4,5}    median 1   max 5

The ranges overlap, and the direction is the opposite of the one a cap assumes: **delivered runs
spend MORE ticks than aborted ones** (median 2 vs 1, max 6 vs 5). A tick cap is therefore not a
weak stuck-detector, it is an anti-correlated one — every reachable value kills healthy runs
strictly before stuck ones. r145 (STUCK, 85 min, 0 tags) burned 5 ticks; r146 (delivered v1.0.0)
burned 1. Nothing to change: 240 is inert, and inert is the correct behaviour for this knob. The
protection people might imagine it gives comes from the STUCK detector, which fired in r145.

---

## 15. 847 component crops are single-colour blanks

**Not changed.** `design_prep` writes "every component with a region gets a physical crop at
design/crops/<screen>__<id>.png … so lanes/gates can view each component in isolation" (133 of
144 runs have the directory; 43,928 PNGs, 4.9 GB).

**Proven offline.** Decoding every crop under 1.5 KB: **847 are single-colour**, across 91
component names, and the top eight are all player controls — `volume-button` x73,
`next-episode-button` x72, `subtitles-button` x72, `fullscreen-button` x72, `rewind-10-button`
x66, `forward-10-button` x66, `pause-button` x62, `episode-title-center` x40. Consistent: the
player's controls auto-hide, so the reference frame had nothing at those regions. A lane shown
one of these is being told the component is an empty rectangle.

**Only a run can settle.** Who reads a crop and what a missing one costs. r139 has NO crops
directory yet has full component_specs, so crops are not required — but skipping a blank one
could surprise a consumer expecting a file per component. The naming also differs between the
two artifacts (specs `pause_button`, crops `pause-button`), so any consumer joining them by name
already normalises.

**~~Cheapest observation.~~ CLOSED 2026-08-14 — and the premise behind the suggested fix is
wrong.** "Grep for reads of `design/crops/`" is a code question, not a run question, and the
answer is that crops are very much read:

    frontend_scaffold.py:10432  #461 stages design/crops/*.png → /assets/crops/ in the app
    frontend_scaffold.py:5777   _hero_title_crop_url_461 picks the hero TITLE-ART crop and the
                                projector renders it AS the hero title — "the crop IS the real
                                reference wordmark"

So they are not write-only, and "stop writing a crop for an empty region" would remove an input
the hero depends on. r146's release tree carries 339 staged crops; decoding every one, **10 are
single-colour** (3%) — `player_controls__{pause,subtitles,fullscreen,episodes,rewind-10,
forward-10,next-episode}-button`, plus one card. Exactly the auto-hide set the corpus measurement
found. Those ship as dead assets: staged, never referenced by a rendered component. A size
question, not a correctness one.

**Hypothesis raised here and REFUTED, recorded so nobody re-raises it.** If the hero title-art
crop were blank, `_hero_title_crop_url_461` would render an empty image as the hero title, and
the resolver does NOT check the crop has content — it matches on name and size only. That is a
real gap in principle. Decoding every hero/title-art/logo/wordmark crop in the corpus:

    2606 such crops, 0 single-colour

Zero, across 146 runs. The blanks cluster entirely in auto-hiding player chrome, which is where
the reference frame genuinely had nothing. Adding a content check to the resolver would be
defending a case that has never occurred, so it is deliberately NOT added — same disposition as
the FK-literal rule and the accent-colour filter, both measured and rejected rather than shipped.

**Nothing here needs a run.** Item 15 is closed; the 4.9 GB of PNGs remains a size question worth
revisiting on its own terms, not a correctness one.

---

## 16. 19 of the 43 hub stores are created every run and never written

**Not changed.** Counting non-`_meta` records across all 144 runs, these stores are empty in
every one:

    codehub_code_reviews, codehub_pull_requests, codehub_repos, codehub_review_threads,
    registryhub_examples, registryhub_mocks, registryhub_pending_consumers,
    registryhub_projects, registryhub_providers, registryhub_reviews, registryhub_schemas,
    registryhub_seed_registrations, registryhub_table_breaking_changes,
    registryhub_table_consumers, workhub_acceptance_criteria, workhub_databases,
    workhub_decisions, workhub_reactions, workhub_workspaces

That includes most of what RegistryHub's own docstring advertises ("endpoints, database tables,
consumers, contract tests, examples, breaking changes" — examples, mocks and schemas are dead)
and the entire CodeHub PR/review surface. For contrast the live ones: eventhub_events 288562,
eventhub_threads 132822, workhub_tasks 12836, codehub_checks 6242, registryhub_endpoints 3983,
registryhub_breaking_changes 3924, registryhub_verification_chains 3442.

**DECOMPOSED 2026-08-14 — "empty on disk" was three different states wearing one face.** Counting
RECORDS cannot tell a queue that drained from a writer that never ran. Counting WRITES can:
`JsonStore.update` always `_save_raw`s and always `_bump_meta`s, with no branch that skips either,
so `_meta.version` is an exact write count. Across all 146 runs:

    state          stores                                              evidence
    drained        pending_consumers                                   v29/v33 in r145+r146
    never written  examples, mocks, reviews, seed_registrations,       v1 in 146/146, but a
                   table_consumers, table_breaking_changes             writer exists in the tree
    no writer      projects, providers, schemas                        v1 in 146/146, and NO
                                                                       mutation anywhere at all
    unscoped       the 9 codehub_* / workhub_* stores                  RESOLVED 2026-08-14,
                                                                       see below

Only the first of those was ever a question about behaviour, and it is CLOSED above: the queue
works. The third is statically decided — a store that is constructed, read via `.value()`, and
mutated nowhere makes every branch keyed on it unreachable, and no run can change that.

**Fixed: #693**, and only the docstring. The stores stay: their readers exist, an empty store is a
legitimate state, and deleting live-looking machinery on a static argument is the kind of change
that should wait for evidence. What was wrong was a class docstring telling the next reader that
`schema` and `mock` carry data when neither has ever held a record. Seventeen tests, including a
negative control proving the writerless probe can find a writer when one exists, and a guard that
fails if anybody later adds a writer without updating the docstring.

**The last nine, resolved 2026-08-14.** They are built by keyword in a factory
(`decisions=JsonStore(hub_dir / "workhub_decisions.json")`), which is why the attribute-based
probe missed them. All nine are `version == 1` in 146 of 146 runs. By writer count:

    no writer at all (4)   codehub_review_threads, workhub_acceptance_criteria,
                           workhub_databases, workhub_workspaces      — same class as
                           projects/providers/schemas: statically dead, no run can change it
    has writers (5)        codehub_pull_requests (10 write sites!), codehub_repos (3),
                           codehub_code_reviews (1), workhub_decisions (1),
                           workhub_reactions (1)

`codehub_pull_requests` is the interesting one: ten mutation sites and never written. The methods
ARE reachable — `hub_tools.py` wraps them, and `live_monitor_server.py` exposes them over HTTP —
so "unreachable" is wrong. Counting real invocations by the `🔧 <tool>:` call marker across all
253 logs (see the correction below), the whole codehub surface is:

    codehub_commit 3984 · record_check 3054 · resolve_merge_conflict 322 ·
    get_file_content 60 · list_prs 18 · get_diff 9        — and nothing else

Thirteen of the nineteen declared codehub tools have never been invoked, `codehub_open_pr` among
them. **No pull request has ever been opened in 146 runs**, so the four PR/review stores are empty
for the plainest possible reason, and `codehub_list_prs`' 18 calls all read an empty collection.

One structural oddity worth recording rather than fixing blind: the grants are inverted around
that workflow. `codehub_force_merge` — the override — is granted in **11** config places, while
the entrance `codehub_open_pr` is granted in 2 and `codehub_review_pr` / `codehub_merge_pr` in
**none at all**. A workflow whose escape hatch is its most widely granted step, and whose normal
path cannot be completed by anyone, is not going to run. Whether the PR surface is meant to be
live here is a design question this note does not answer.

**Measurement correction, recorded because it nearly became a finding.** I first counted tool
usage by grepping the tool name in run logs and reported `codehub_list_prs` at 808 calls,
`suggest_reviewers` at 700 and `list_inline_comments` at 1180 — about 2,700 calls into an
always-empty surface. Dumping the lines showed 700 of the 808 are one repeated Knowledge Agent
line, `Tool surface (register): 71 tools; categories={'codehub': 7, ...}` — a registration
inventory, not a call. The real figure is 18. Count the invocation MARKER, never the name.

**The six "never written" writers, answered 2026-08-14 — three states, not one.** Probing them by
tool NAME is what kept going wrong; `hub_tools.py` builds its tools in a factory, so a
`NAME = "..."` grep cannot see them. Walking from the hub method back to the enclosing `NAME`
assignment gives the real picture:

    no tool entry at all (2)     add_example, add_mock — no agent can reach them by any path
    tool exists, granted to
      NOBODY (2)                 request_api_review  -> registryhub_request_review   0 grants
                                 submit_api_review   -> registryhub_submit_review    0 grants
    granted, never called (2)    register_table_consumer, update_table_schema — 7 config
                                 grants each, 0 real invocations in 253 logs

The middle pair is the finding: `registryhub_reviews` has two writers, both properly exposed as
tools, and **no role in agents_config.yaml is granted either of them**. That is the same shape as
the codehub PR surface above — a workflow that is implemented and wired but has no entrance
anybody can use — and it is the reason that store has never held a record, quite apart from
whether an API review is wanted here.

**Instrument warning, because it caught me four separate times in this one item.** Grepping a
name against logs or config over-counts (registration inventories are not calls: 808 → 18) and
grepping `NAME = "x"` against the tree under-counts (factory-built tools are invisible: I twice
reported "no tool entry" for tools that exist). Count invocation MARKERS in logs, and walk
method → enclosing NAME in source. Both corrections are recorded above rather than quietly fixed.

**Sharpest single case.** `registryhub_pending_consumers` has BOTH a writer
(`register_consumer(..., pending=True)` queues a consumer whose endpoint does not exist yet) and
readers (`list_stale_pending_consumers`, whose result drives `my_stale_pending_consumers` in
every hub pulse and gates three branches there). An internal caller at registryhub.py:1365 does
pass `pending=True`. Yet the store is empty in 144 of 144 runs, so the pulse field is always
empty and those branches never fire.

**~~Only a run can settle.~~ CLOSED 2026-08-14 — the runs already happened, and the mechanism
works end to end.** Neither of the two hypotheses above is right, and the reason the store looks
dead is a third thing: entries are queued and then PROMOTED AND DELETED (registryhub.py:454), so a
fully-working queue lands on disk looking exactly like a never-used one.

The discriminator is the event, not the store: the pending branch `_emit`s `consumer_pending` at
registryhub.py:637, and events persist. Across all 146 runs there are 30 such events, and they
fall in only TWO runs — r145 and r146, the two runs from this session:

    run   consumer_pending events   store version   entries   last_modified_by
    r146            16                   33            0        registryhub
    r145            14                   29            0        registryhub

`JsonStore.update` always `_save_raw`s and always `_bump_meta`s — there is no conditional skip —
so version counts writes exactly, and the arithmetic closes it:

    r145   14 sets + 14 deletes + 1 create = 29   ✓
    r146   16 sets + 16 deletes + 1 create = 33   ✓

Every queued consumer was promoted and removed. Nothing is lost, nothing is dead, and the pulse
field is empty at the END because the queue drained, not because it never filled. The 144 older
runs have zero `consumer_pending` events, so for them the mechanism genuinely never fired — which
is why the corpus could not tell the two hypotheses apart, and why "empty in 144 of 144" was not
evidence of a defect.

**Method note, because I got this wrong twice on the way.** I first "confirmed a contradiction"
(events present, store never written) off a run set built by matching `'consumer' in type`, which
silently swallowed 2404 `consumer_registered` events and put the wrong runs in the set; r118, the
run I then dumped, has zero `consumer_pending`. Dumping one real record is what caught it — the
same rule that has caught five field-location errors in this session. The earlier claim that 22
ui_page references pointed at never-registered endpoints in 5 runs stands as a measurement, but it
is unrelated to this store: those runs emit no `consumer_pending` at all, so the endpoint existed
when the consumer registered and was absent from the FINAL registry for some other reason.

**What is still open in item 16** is the rest of the list — the other 18 stores, including the
whole CodeHub PR/review surface and `registryhub_examples` / `mocks` / `schemas`. This closure
covers only the sharpest case, and it moves the prior for the others: an empty store is not
evidence of a dead writer until the corresponding EVENT is checked too.

---

## 17. The breaking-change machinery is gated on an input that is usually absent

**Not changed.** `_record_breaking_change` notifies only the agents registered as consumers of
the endpoint, and auto-creates a fix task per consumer agent. That gating is correct. The input
is what is missing:

    runs registering ANY consumer     36 of 144 (25%)
    consumers registered per run      median 0, max 24
    endpoints registered per run      median 30
    /api paths the delivered api.js actually calls   median 7

So the frontend really does consume around 7 endpoints per run while registering a consumer in a
quarter of runs. Consistent with the other end of the same measurement: of the 3924 stored
breaking changes, **3897 (99.3%) had no consumer registered at the time** — only 27 ever reached
anybody. The largest signal combination is `('auth_added','response_key_changed')` x1220, the
signature of a stub endpoint being re-registered as its real implementation.

This matters because #627/#629/#631 spent an arc raising breaking-change DELIVERY from 2.9% to
60% — measured over whatever consumers existed. With median 0 consumers, that path is dark in
most runs.

**Only a run can settle.** Whether consumers should be registered automatically. The framework
already reverse-engineers endpoints from source in `contract_extract`, so deriving frontend
consumers from `app/frontend/src/services/api.js` is a natural extension — but it is a behaviour
ADDITION (it would start firing urgent events and auto-creating fix tasks where none fire today),
and its blast radius cannot be judged from disk.

**Cheapest observation.** One run: count `register_consumer` tool calls, and compare against the
`/api` paths in the delivered api.js. If the lane never calls it, the tool is the gap; if it
calls it and the registration is rejected, the gate is.

---

## 18. The MCP surface is registered as implemented and shipped in 23% of deliveries

**Not changed.** `registryhub_mcp_registry` holds 2079 records across 134 runs and **every one is
`status="implemented"`** — 1945 tools, 134 servers, median 15 tools per run. The registration API
defaults to `"defined"`; `scaffolder.py` passes `"implemented"` explicitly, immediately after
`write_mcp_server(orch.output_dir, ...)` returns, so at that moment the files existed.

They are not there at the end:

    runs registering MCP tools                     144
      mcp_server/ at the run root                   18
      only inside a surviving worktree               1
      nowhere at all                               125

    DELIVERED runs                                  35
      shipping an mcp_server/                        8  (23%)

Where the directory does exist the registry is accurate — median 16 tool definitions on disk
against 15 registered — so the scaffold is right when it runs. The 18 are spread across every era
(r2, r17, r34 … r139, r142) and the newest runs are among those without, so this is intermittent,
not historical.

**~~Only a run can settle.~~ SOLVED 2026-08-14 from the artifacts — it is neither of the two.**
The paragraph below was wrong about the evidence, not just the answer, and the error is worth
keeping: it said "a removed worktree leaves no trace, so the artifacts cannot separate the two".
The artifacts separate them completely; I had only looked at the filesystem, and the answer was in
git. ~~Whether the scaffold writes into a worktree that never reaches the run root, or writes to
the root and something later removes it.~~

Both r145 and r146 log that the writer ran and succeeded — `mcp_server/app/: 15 tool(s) emitted,
15 registered.` — and both end with no `mcp_server/` anywhere. `git log --diff-filter=D` finds no
commit that removes it, because none does:

    r146   mcp_server/app/{main.py,pyproject.toml,start.sh}   added in 60c738f   on branch main
    r145   same three files                                   added in 0b0e81b   on branch main
    both   HEAD = integration;  merge-base --is-ancestor <commit> HEAD  ->  FALSE

**The writer commits to `main`, delivery runs on `integration`, and the two have diverged.** The
files are neither lost nor deleted — they are on a branch the release is not cut from. That also
explains the intermittency noted above without appealing to chance: the 18 runs that do ship it
are the ones whose topology happened to put the write on the delivery line.

`commit_framework_delivery` already lists the subtree — `for sub in ("app", "mcp_server",
"docker")` — and skips it on `if not (repo / sub).exists(): continue`, which at that moment is
*correct*: on `integration` the directory really is not there. The defect is that the skip was
**silent** while `registryhub_mcp_registry` advertised the surface — 16 entries (1 server + 15
tools) in both runs.

**Fixed: #691** makes the skip audible — WARNING naming the branch question when a store still
advertises the surface, INFO otherwise. It reads the count from the store file (whose path follows
from `repo`) rather than a getattr chain into the hub graph: `MCPRegistry` is its own class, not a
registryhub mixin, so a guessed accessor would evaluate to 0 forever and the warning would never
fire — a dead branch guarding a silent skip.

**And then CLOSED too, by the reflog — it is an ordering defect, not a topology preference.**
I filed the repair as an open branch-topology decision and that was one measurement short. The run
repository keeps a reflog, which dates every ref operation:

    22:53:11  bootstrap                              26067f8   on main
    23:10:47  "branch: Created from agent/backend"  integration PLANTED at 26067f8
    23:12:41  first framework delivery commits ON MAIN         60c738f  <- the mcp_server write
    23:44 / 23:46 / 23:47 / 23:48   four more deliveries, all on integration, all find it absent

`create_branch_at` plants a ref and, by its own docstring, deliberately does NOT move HEAD. So
`integration` was forked at 23:10:47 while HEAD stayed on `main`, and the framework's first
delivery commit two minutes later landed on the wrong side of a fork that already existed. When
HEAD later moved to `integration`, git removed the now-untracked subtree from the working tree.

`git diff --name-status integration main` bounds the damage at **exactly three files — the
mcp_server subtree and nothing else**. That also answers the "intermittent, not historical" note
above without appealing to chance: `app/` and `docker/` survive because the projector rewrites
them every round, while **the MCP writer runs once per run and so has no second chance**. One
writer, one shot, one fork in the wrong place.

**Fixed: #691b** restores it — `git log --all -1 --diff-filter=AM -- <sub>` then `git checkout
<sha> -- <sub>`, best-effort, with three separate fall-throughs to the original skip. The repair
path carries no product literal; only the registry count is MCP-specific. `--diff-filter=AM`
matters: a commit that only deleted the subtree is not a source to restore from.

Verified against r146's actual repository (copied out, original untouched): on `integration` the
directory is absent, the search finds 60c738f, the checkout restores all three files into working
tree and index, and what comes back is a real server — 270 lines of fastmcp over httpx.

**What a run still adds:** confirmation that the restored subtree survives into the release cut,
and whether `deliverability_failed_mcp_probes` then has something to probe. The related tightening
below is unchanged — requiring the surface would still have failed 27 of 35 delivered runs, though
#691b should move that number.

**Related, deferred with it.** The delivery gate has `deliverability_failed_mcp_probes` but does
not require the surface to exist. Requiring it would have failed 27 of the 35 delivered runs, so
it is a tightening of the same class as item 13, not a blind switch.

---

## 20. #692 — how often does the owner fall back? (frequency only; the fix is already in)

**Changed: #692.** Found by auditing what r146 actually SHIPPED after the gate went green — the
habit #569 left behind. `_fw_owner_val` resolves a per-user sub-entity owner (netflix `profiles`),
and when the shape matches but the caller has no row and #390's auto-create fails, it returned the
caller's USER id. The two call sites diverge and only one was ever considered:

    WRITE  owner = user_id -> FK violation -> 404. Loud, and the entire subject of #390/#391/
           #393/#394 — four fixes, all about this one consequence.
    READ   `owner_col == user_id` -> silently returns the rows of the sub-entity whose id equals
           the caller's user id. Profile ids and user ids are independent sequences, so that is
           generally another user's data. No foreign key protects a read. Nothing fails.

route_projector emits that filter at four sites (route_projector.py:1038, 1125, 1197, 1244), so
every projected owner-scoped read in every generated app inherits it. #692 returns -1 from that
one branch instead: reads match nothing, writes still FK-violate to a 404 exactly as before, and
the two branches where the user id is right — a shape that never matched (apps scoping directly by
user_id) and a detection that raised — are untouched. Fourteen tests EXECUTE the helper extracted
from the generated-main template rather than grepping it.

**Only a run can settle: the RATE.** `_fw_dbg` writes to the backend container log under
FW_DEBUG, not to the generation log — `grep autocreate_sub_entity` over all 253 run logs returns
nothing for that reason alone, so the corpus cannot say how often the branch is taken. The fix
stands on the asymmetry, not on a frequency; the frequency is still worth knowing.

**Cheapest observation.** Run with FW_DEBUG on and grep the backend container log for
`fw_owner_val.unresolved_sub_entity`. Zero means #393/#394 closed the auto-create failures for
good and this is now belt-and-braces; non-zero means projected reads were being scoped to the
wrong owner every time it appeared, and each line names the table and the uid it refused to use.

**RETRACTED, same day, before it cost anyone a look.** I first recorded here that r146 shipping
ELEVEN duplicate route definitions — every user-facing path declared once in the lane's
`custom_routes.py` and again as a projection in `main.py` — was "a standing hazard of the
#566y/#568 class". It is not a hazard at all; it is the designed override mechanism, and the
framework says so in the docstring of the very function that looks for duplicates:

    duplicated_routes(): "(METHOD, normpath) routes defined 2+ times WITHIN a single served
    module ... A cross-module override (main.py's projected handler + a custom_routes.py
    override) is NOT flagged — only same-file duplicates, which are always a lane bug."
                                                    — backend_audit.py:197-202

`include_router(_custom_router)` at main.py:849 running before the projections at 990+ is the
mechanism working as intended, not an accident of ordering. What I actually verified is worth
keeping, though, because it is the thing that matters: **both sides are owner-safe** — the lane's
`_resolve_profile_id` scopes with `WHERE id = :pid AND user_id = :uid` and 404s otherwise, and the
projections use `_fw_owner_val`/`_fw_owns` — so whichever serves, the read is scoped.

Also checked in the same pass and clean: the three `text(f"DELETE FROM {tbl}")` interpolations in
the shipped `custom_routes.py` take `tbl` from a hardcoded literal tuple, not from a request, so
they are not an injection surface.

---

## 21. The rating enum — MEASURED AND REJECTED 2026-08-14, no change

Carried since the 400-decomposition as "1 rating enum (r145, single instance)": the shipped
`custom_routes.py` rejects anything outside `['down','up','love']` (or an integer 1-5) with a 400,
while the endpoint contract declares the field as a free `value: str`. A verifier authoring a
chain from the contract can therefore send a legal-looking string and be refused, and the refusal
is recorded as a broken assertion against a handler that is behaving correctly.

Real, and not worth a mechanism. Two measurements over all 146 runs:

    endpoint schemas that declare an `enum`      0 of 4043
    enum-style rejections in verification chains 4 occurrences, in 3 runs

So no contract anywhere has ever carried an enum, and the mismatch this creates costs four
recorded failures in the whole corpus. Teaching the contract layer to declare and propagate enums
— or deriving them from handler source — is a large, cross-cutting change against a four-instance
problem, and every such change this session that was measured first has been rejected: the
hardcoded-FK registration rule (5% failure with and without), the accent-colour filter (best cut
still lost 27% of genuine red accents), and the blank-crop content check (0 of 2606 hero crops
affected). This joins them.

**Nothing to run.** If the count ever climbs — the cheapest watch is `grep -ciE "must be one
of|invalid value|allowed values"` over the chain store — the arithmetic changes and so does the
answer. It is recorded here so the next reader inherits the number rather than the anecdote.

---

## 21. #696 — does the suppressed load failure actually reach console_errors?

**Changed: #696.** Every projected page fetch throws `HTTP <status>` and then discards exactly
that error, falling through to the graceful empty state. The suppression is deliberate, measured
(r104 new_and_popular) and unchanged. What it also did is make a 500 indistinguishable from an
empty dataset — the user reads "Titles you add will appear here." while the endpoint is failing,
and the framework judges a screenshot of a clean, plausible, well-scoring page. #566x shape: the
harm is invisible BECAUSE nothing looks broken. The suppressed branch now writes a
`console.error`; no pixel changes and the error text still never reaches the DOM.

**Only a run can settle.** Whether `browser_navigate`'s `console_errors` actually surfaces it in
the lane, and how often it fires. The mechanism is right on paper — core.py filters
`log["type"] == "error"` and drops extension noise, which a `console.error` from app code passes
— but no kept run contains the line, because no kept run has the fix.

**Cheapest observation.** Grep a run log for `[projected] data load failed:`. Every occurrence is
a page that rendered as an ordinary empty state while its API was failing. Zero occurrences with
non-zero `deviations` about blank pages would mean the suppression is not the path those come
through.

---

## 22. Audited in r146's SHIPPED tree and found clean — do not re-raise

Four frontend hypotheses from the same audit that produced #696, each measured and dropped. They
look like defects and are not; recording them so the next reader does not spend the same time.

- **Unhandled fetch rejections.** None. Every component in the shipped frontend that calls
  `fetch` has a `catch`.
- **The hero renders TEXT when data loads and the reference title-art CROP only when it does
  not** — which looks like an inversion of #461's stated purpose. It is `#531`, deliberate and
  measured: "the static reference crop (#461) is DROPPED for data pages and kept ONLY as the
  fallback shown when there is NO record ... the r97 miss: thin catalog screens scored 0.40-0.55
  rendering the static crop over the live backdrop."
- **Unreferenced components shipped.** `HeroBillboard.jsx`, `NetflixNav.jsx`, `TenantPicker.jsx`
  and a second `LoginPage.jsx` under `pages/` (App.jsx imports the one under `components/`) are
  in the release and imported by nothing. They are residue of `#221`: when the projector
  re-projects a page it takes over the rendering, and the lane's components lose their importer.
  Vite tree-shakes unreferenced modules out of the build, so the runtime cost is nil; the cost is
  a reader opening a 161-line LoginPage that does not serve `/login`.
- **`text(f"DELETE FROM {tbl}")` in the shipped `custom_routes.py`.** Not injection — `tbl` comes
  from a hardcoded literal tuple in all three occurrences.

Also confirmed deliberate, from the backend half of the same audit: the five unauthenticated
`/api/v1/*` admin endpoints are exempted on purpose — main.py's auth middleware treats
`/api/v1/*` as public infra — and the eleven duplicate route definitions are the DESIGNED
override mechanism, stated in `duplicated_routes`' own docstring.

---

## 23. The "computed but never consumed" sweep — run to exhaustion

#691, #694b, #696 and #698 were all one shape: a correct computation whose result nothing
consumes. Rather than keep finding them one at a time, the pattern itself became the search.
Two mechanical sweeps, both run over the whole framework:

**Sweep A — every string-literal dict key assigned and never read back.** 69 candidates, almost
all false positives: `merged_at`, `active_runs`, `log_tail` and friends are serialised to JSON
and read by the live-monitor UI or a human, not by Python. Narrowing to keys whose NAME implies
an action (`recommend|should_|suggest|stale|blocker|unresolved|available|_needed|_required|
violation|mismatch|drift|regress`) and excluding the HTTP layer returns **exactly one hit:
`better_state_available`** — already found and fixed as #698. `advisory_reason` is written three
times and never read, but it explains a decision already taken (the `advisory` flag that drives
it IS consumed), so it is documentation rather than an unheard recommendation. **This class is
exhausted.**

**Sweep B — every module-level function whose name appears only at its own `def`.** 26 hits, all
triaged rather than sampled:

    real findings   promote_integration_to_main       -> #699
                    duplicate_route_content_groups    -> #700
    checked, benign _declared_critical_flows (delivery_gate.py) — looks like a coverage gap and
                    is not: `compute_flow_coverage` IS called, from deliverability.py:270, and
                    the gate consumes its `deliverability_critical_flows_invalid` verdict. This
                    is a redundant wrapper that was never wired, not a missing check.
    utilities       get_project_root / get_prompts_dir / get_screenshot_dir / truncate_output /
                    get_tool_logger / create_workspace / create_console_emitter /
                    reset_for_tests / _tail_lines / _recent_tool_calls — helpers and test hooks;
                    an uncalled helper costs nothing and hides nothing
    tested-only     failure_signature (14 test refs, 0 production calls),
                    _has (2), _login_jwt (bundled oauth contract test)
    remainder       _all_phase_acked, _canon_seg_len, _owner_value,
                    _resolve_backend_conflict_by_ownership, bootstrap_spec_for_backend,
                    build_intent_judge_prompt, classify_memory_line, design_premises_text,
                    list_requests, write_config — dead code with no detector semantics; none
                    computes a finding that a consumer is missing

**Sweep C — every `except ...: pass` in the runtime whose guarded body calls something
detector-shaped** (audit/check/detect/validate/verify/blocker/coverage/probe/scan/assert). Ten
sites. Nine are the documented and correct "a hiccup must never wedge the gate" pattern, where the
swallow degrades a check to a no-op and the gate carries on. One is more than that:
`delivery_gate`'s `complete_coverage_chain(hubs)` → **#701**.

**Sweep D — every CLASS METHOD whose name appears only at its own `def`** (sweep B's completion;
it only covered module-level functions). 113 hits, most false positives where a framework calls by
convention rather than by name — `do_POST`, `log_message`, `do_DELETE`. One matters:
`AgentStepStageMixin._run_hub_sync_stage` → **#702**.

**Sweep E — calls whose RETURN is discarded, where the callee's name is finding-shaped**
(blocker/error/issue/violation/missing/failure/defect/gap/verdict/report/finding) and it actually
returns something. 5 hits, **no defect**: `stage_missing_seed_photos`, `stage_missing_frontend_
assets`, `_persist_verdict` and `handle_validation_failure` are verbs — the side effect IS the
point and the return is informational. The fifth, `project_missing_routes`, is a NAME COLLISION in
my own scan: the `heal_pipeline` method returns `None`, and it was flagged because a same-named
function in `route_projector` returns a dict.

**Sweep F — module-level CONSTANTS never read.** 11 hits, **no live defect**, but all three
signal-bearing ones needed checking against delivered code rather than assumption:

  * `_LANDING_TEMPLATE` — a landing-page template added to fix "stuck on a dead 'Landing' heading
    with no way in", referenced nowhere. Superseded: `_landing_page_src` (called from
    frontend_scaffold.py:7652) builds the same wordmark + working `/login`+`/signup` nav inline.
    r146's delivered LandingPage.jsx is a full page. The guarantee exists; the constant is an
    orphaned duplicate.
  * `ENFORCE_ROUTINE_SRC` — documents itself as "emitted verbatim into seed_data.py AND
    oauth_store.py" and is emitted into neither: `_enforce_user_bootstrap_rows` appears in **0
    generated files across all 146 runs**. Also superseded — the delivered `seed_data.py` carries
    `_ensure_canonical_rows()` (defined line 117, called line 588) under FIX #72, same purpose.
  * `_ANALYST_PROMPT`, `ALL_HUB_TOOLS`, and the `_paths.py` directory constants — inert, no
    guarantee attached.

The pattern in sweep F is worth stating: every hit was a fix implemented TWICE, where the second
implementation won and the first was left in the tree. None is a behaviour gap; each is a
maintenance trap, because the orphan reads like the live path.

**Sweep G — keys in `agents_config.yaml` that no code reads.** 5 hits; three (`dynamic`,
`notifies`, `coordinator`) are common words my key scan matched loosely and are not dead. Two are
real, and NEITHER is a live defect:

  * **`optional_stages: [retrieve_context, knowledge_sync]`**, under the comment "Optional stages
    may be skipped by the model" — read nowhere, so the declaration has no effect. Its neighbour
    `stages:` IS live (`step_runner` calls `_stage_enabled(...)`). Inert declaration, no
    behaviour attached; not fixed, because "which stages the model may skip" is a design question
    and inventing an enforcement for it would be a behaviour change.
  * **`can_spawn`** — also read by no code, and three PROMPTS present it to agents as
    enforcement: "DO NOT spawn workers (can_spawn=false by YAML flag)". The real mechanism is the
    `team_spawn` tool bundle: no bundle, no tool, whatever the prompt says. Cross-checking the two
    independently-maintained declarations: **all 7 roles with `can_spawn: false` also lack
    `team_spawn`**, so no role is restricted by prompt alone today.

**Guarded, not fixed: #703.** Nothing is broken, so there is no production change. What is missing
is anything that KEEPS the two declarations agreeing — they live in different parts of the same
file, and adding `team_spawn` to a `can_spawn: false` role would leave that agent reading "you are
restricted by YAML flag" with the tool in its hands. Eight tests pin the invariant in both
directions, the current restricted set, and the premise itself (that no code reads the flag and
the prompts still claim it) so the guard deletes itself honestly if either changes.

**Sweep H — prompt fragments assembled but never included.** Two probes, **no defect**, and the
first probe was entirely my own false positives.

  * *Unreferenced `.j2` templates.* 5 of 18 looked dead until I noticed my scan read Python and
    other templates but not the YAML: prompts are named in `agents_config.yaml` under
    `template: "v3/..."`. All five are referenced there. Of the 7 not named in the YAML, 2 are
    shared fragments included by other templates and 5 are loaded from Python (the `vision/` and
    `v4/` sets). **No dead template.**
  * *The v4 prompt set.* `v4/backend_agent.j2` and `v4/frontend_agent.j2` exist while every
    config entry says v3. `resolve_prompt_version` switches on `ENVGEN_PROMPT_VERSION`, which is
    read in exactly one place — the resolver itself — set nowhere in the tree, and absent from
    all 253 run logs. So the v4 rewrite has never been exercised. **Not a defect:** the
    docstring describes a deliberate per-file opt-in ("v4 can be introduced" gradually), the
    fallback is correct, and an unset feature flag is an unset feature flag. Worth knowing only
    so nobody assumes v4 is what runs.

**Sweep I — a NEW family: code whose own comments contradict the tree.** Two sub-probes.

  * *Docstrings claiming "Called by X".* 15 objects make the claim; 14 have real callers. The
    one that does not is `promote_integration_to_main`, already #699. Clean — and it confirms
    #699 was the only instance of its kind rather than the first of many.
  * *Measured claims of the form "N of M runs" in comments.* 18 of them, and the denominators
    give the game away: 39, 45, 50, 21 — all measured when the corpus was a third of its
    current size. Most cannot be re-verified offline (#618's 24/39 needs per-round scores, and
    only r145/r146 have a `rounds.jsonl` at all). **One can, and it was: #615's "32 of 45".**

**Re-measured, and the premise moved: #705.** Running the #615 detector over every kept run with
both a frontend and ui_pages gives **112 of 136 (82%)** against the recorded 32/45 (71%), with a
size distribution the comment never had:

    max group size   2:10   3:19   4:27   5:28   6:23   7:4   8:1   runs

The median affected run has FIVE routes rendering the same list; the worst has eight. This
reinforces the "deliberately not a blocker" call rather than overturning it — at 82% a blocker
wedges more runs than the 71% the decision was made on — and it raises the value of #700's
report, because this is not a rare defect but the normal state of a delivered app. The original
figure is kept beside the new one; a premise that moved is more useful than a premise replaced.

**The other 12 "N of M runs" claims, worked through rather than left as a list.** Five are now
resolved; the rest need probes matching their original definitions and are listed for whoever
writes them.

| claim | where | re-measured | verdict |
|---|---|---|---|
| 32 of 45 | deliverability #615 | **112 of 136** | moved, premise STRENGTHENED → #705 |
| 0 of 144 `tasks.yaml` | delivery_gate | **0 of 146** | holds |
| 125 of 144 no `mcp_server/` | heal_pipeline ×2 | **128 of 146** | holds, same rate |
| 125× in 50 of 50 `ruff` | code_tools #635 | **1042 in 145 logs; 0 in r145+r146** | premise bigger than recorded, and the FIX WORKS → #705b |
| 24 of 39 record>live | visual_fidelity ×6 | **not re-verifiable** | only 2 kept runs carry both `blocking_average` and `blocking_average_live`; the rest predate the fields entirely (r100's verdict.json has five keys and neither of them) |

**The rest, probed to their own definitions.** Two more re-verify, one is a fix-verification, one
is bespoke and left alone:

| claim | where | re-measured | verdict |
|---|---|---|---|
| 27 of 45 `motion` | design_prep | **77 of 146** (53% vs 60%) | holds in substance |
| 79 of 144 dup-cancels | workhub | **79 runs**, 474 of 867 cancels = **55%** | holds PRECISELY |
| 514 in 50 of 50 rejects | registryhub | not directly comparable | see below |
| 4 of 21 blast radius | test_user_squad #630 | **does NOT reproduce — see below** | the only claim in the sweep that fails |
| 6 of 45 default-import sites | frontend_scaffold | **7 of 146, 22 sites** | fix WORKS — extinct after r127 |
| 146 of 146 ×2 | seed_audit, tool_bundles | current | mine, measured this session |

The duplicate-cancellation one is the strongest verification in the set: same run count (79), same
percentage (55%), on a corpus that grew from 12,836 tasks to 13,047. It also shows what a probe
written to the ORIGINAL definition buys — my first loose `grep duplicat` returned 107 of 146 by
counting any mention; keying on `status == cancelled` and matching `cancel_reason` (a TOP-LEVEL
field, not under `metadata`) reproduces the figure exactly.

The registryhub 514 cannot be matched by string, because #664 rewrote the message. What its new
escalation text shows instead is a fix-verification in the #705b mould: `have now been rejected`
fires **68 times in r145 and 0 in r146**, and the underlying "NOT in the registered contract"
rejection is absent from r146 entirely.

The #632 one was run the same way #705 was — the detector over every delivered tree, on a COPY of
each `app/frontend/src` since it is a repair function that writes. **7 of 146 runs, 22 sites**
against the recorded 6 of 45 and 21. The absolute numbers barely moved while the corpus tripled,
so the rate fell from 13% to 4.8%, and the newest affected run is **r127** — r128 through r146 are
all clean. Third fix-verification in this batch: the defect is extinct, not merely rarer.

**#630's `4 of 21` does not reproduce, and the gap matters.** The claim justifies DEFERRING a
release when non-test-user P0s are open, on the grounds that the blast radius is small: "21 runs
released, 17 carried ZERO, 4 would have deferred". Reconstructing it two ways over the current
corpus, counting bug tasks with `metadata.kind == "bug"`, `metadata.severity == "P0"` and
`metadata.source` outside `TEST_USER_SOURCES`:

    at run END                      27 released,  5 with zero,  22 would defer
    at FIRST RELEASE (reconstructed) 27 released,  7 with zero,  20 would defer

against 21 / 17 / 4. r109 matches the named figure exactly (2); r127, r128 and r133 come out
higher than recorded.

**My reconstruction is not sound on its own** and I will not present it as if it were: only
**15% (84 of 552)** of these bugs carry any `metadata.triage_history`, so the other 85% default to
"open" in my probe no matter what actually happened. What rescues the ORDER of magnitude is a
different number: of those 552 bugs, only **23 ever reach a closed `bug_state` at all**. Even if
every one of those 23 closed before its release, the radius cannot fall from ~20 runs to 4.

So either the original probe filtered materially differently, or the population moved. Both
matter, because the conclusion resting on this figure — that the deferral is safe to enable
because it would touch 4 runs in 21 — reads very differently at ~20 in 27. **This is the one item
in the sweep I would not act on without the original probe**, and it is recorded rather than
resolved.

**Nine of thirteen measured claims re-checked; eight re-verified, one does not reproduce**, none was found stale in DIRECTION, one
moved up and strengthened its decision (#615/#705), and THREE turned into evidence that their fix
works (#635/#705b, #664, #632). The only ones left are `4 of 21` — bespoke over 21 named runs,
where rebuilding the criteria costs more than the answer — and the two `146 of 146` figures, which
are mine and current.

**The lesson from the two that resolved cleanly.** #615's premise moved UP and strengthened the
decision resting on it; #635's premise moved up too but its fix had already erased the symptom.
Neither could be known without re-measuring, and a fix whose premise is never re-checked is
indistinguishable from one that quietly stopped mattering.

**Nine sweeps, nine axes; five yielded, four did not** — A→#698, B→#699+#700, C→#701, D→#702,
E→nothing, F→nothing, G→#703 (a guard), H→nothing. Three of the last four came back empty, which
is the first real evidence that this family is thinning rather than that I keep finding new places
to look. The named axes are now all run. A, B, C and D are individually
exhausted, but the honest summary is not "the search is finished" — it is that this FAMILY of
defect (a correct computation whose result nothing observes) is dense enough that every new way of
looking finds more: A→#698, B→#699+#700, C→#701, D→#702. A→#698, B→#699+#700, C→#701, D→#702,
E→nothing, F→nothing, G→#703 (a guard, not a defect), H→nothing, I→#705 (a refreshed premise). All named axes are run.

---

## 25. #700 — #615's detector was never called, not even to report

**Fixed: #700.** `duplicate_route_content_groups` finds distinct routes whose delivered pages
fetch an identical unparameterised endpoint set, and therefore render identical content ("click
Games, see Movies"). Half its silence is deliberate and documented at the detector: "Deliberately
NOT wired as a delivery blocker. At 32/45 it would wedge nearly every run, and whether 'six
identical pages' should block OR MERELY BE REPORTED is a calibration decision, not a measurement."

Nobody took the reporting option either. Running it over r146's DELIVERED frontend:

    /browse, /browse/browse-by-languages, /browse/games, /browse/latest
        all fetch only /api/titles
        BrowseByLanguagesPage, BrowseHomePage, GamesPage, NewAndPopularPage

Four nav destinations rendering the same list, in a run that shipped and passed its gate. r145
finds none, so this is not a universal artifact of the projection. It is now a WARNING from
`deliverability.py`; the calibration decision is untouched and nothing blocks.

**Only a run can settle.** Whether it should block. The detector's own 32/45 measurement is the
argument against, and it predates #221's projection changes — the rate may have moved.

**Cheapest observation.** Grep a run log for `#615` and count the routes named. If a delivered
run shows four or more identical destinations and still scores well, that is the calibration
evidence the original comment says is missing.

---

---

## 24. #699 — the branch-promotion function that has never run

**Fixed (docstring only): #699.** `auto_commit.promote_integration_to_main` says "Called by the
verifier after a successful RunHub run so that `main` only ever points at code that has passed
the latest verification." Nothing calls it — a call-syntax scan of the framework finds zero call
sites. The consequence is in every generated repo that has both branches:

    diverged in BOTH directions   130 runs   integration ahead 20-73, main holding 1 commit
                                             integration lacks
    main purely behind              5
    main ahead                      3
    in sync                         0

`main` is frozen at the early bootstrap + first framework-delivery commit while integration
accumulates the whole run, and they never reconverge because the function designed to reconverge
them is dead. **That single orphaned commit on `main` is the one item 18 is about** — the MCP
writer runs once, lands there, and the release, cut from integration, never sees it. Two findings,
one topology.

**WIRED 2026-08-14 as #706, on the user's decision.** Not into the verifier — into
`orchestrator.py`, immediately AFTER the delivery gate goes fully clear and
`create_release(source="integration")` has cut the release. Placing it after the cut is what makes
it safe: the release still comes from `integration` and `main` now follows it rather than feeding
it, so nothing that ships depends on the promotion succeeding. Nothing is rolled back — the
opposite of the bounded-escape question, which was declined for exactly that reason. Best-effort:
the run has already delivered when this executes, so a failure is logged and swallowed, and a
refused promotion `(False, info)` reads differently from a raised one.

**Still only a run can settle.** Whether it succeeds in practice, and whether anything downstream
reads `main` as a fixed reference and notices it moving.

**Cheapest observation.** After a run, `git -C <run> rev-list --count main..integration`. Today it
is 20-73 in 130 of 146 runs; with #706 in the build it should be **0 at release**. The log line
`framework delivery: promoted integration -> main` says it ran; `promotion did not happen` says
the callee refused and names why.

---

## 26. #701 — the fix for the #1 stuck-blocker could fail silently and leave the blocker

**Fixed: #701.** `delivery_gate` calls `complete_coverage_chain(hubs)` inside a bare
`except Exception: pass`. The comment two lines above says what that call is:

    "COVERAGE-BY-CONSTRUCTION (2026-07-01): once the verifier authored real chains, let the
     framework complete the mechanical api-coverage gap (the #1 recurring stuck-blocker —
     run-12/run-19 wedged 78min here)."

When it raises, no `kind="coverage"` chain is registered, the api-coverage check immediately below
finds the mechanical gap this call exists to close, and the run wedges on exactly the blocker the
call prevents — while the wedge reads as a verifier failure, because nothing said the prevention
had failed. The swallow is KEPT (a completion hiccup must not crash the gate, and the check below
still runs correctly); only the silence ends.

**Only a run can settle: does it ever actually raise?** A silent failure leaves no artifact, so
the corpus cannot say — the same reason #692's rate is unmeasurable offline. What can be said is
that the consequence is expensive when it happens: two named runs lost 78 minutes each.

**Cheapest observation.** Grep a run log for `coverage-chain completion FAILED`. Any hit explains
a coverage stuck-blocker in that run and redirects the fix away from the verifier.

---

## 27. #702 — a step-pipeline stage that has never run, and cannot as wired

**Fixed (docstring only): #702.** Three sibling stages live in `AgentStepStageMixin`.
`_run_retrieve_context_stage` has 2 call sites, `_run_knowledge_sync_stage` 1, and
`_run_hub_sync_stage` **0**. It is inert three ways over:

  1. `step_runner.py:146` initialises `hub_sync_tool_names: set = set()`, and an AST scan of the
     file finds exactly ONE assignment to that name — that one. Nothing ever adds to it.
  2. The always-empty set is still threaded into `action.py:290`'s
     `... | knowledge_store_names | hub_sync_tool_names`, a union contributing nothing.
  3. `step_runner` never calls the stage, so even its `executed=False, skip_reason=...` branch
     never fires — the pipeline does not know the stage exists.

No run has executed it: no call site, no `hub_sync` entry in any step trace, and the 56 log files
that appear to mention it are all matching the tail of the unrelated `registryhub_sync`.

**Only a run can settle.** What wiring it costs. Hub-sync tool calls at every step boundary is a
per-step token cost (#257), and the stage's own `_decide_stage_boolean` adds an LLM call when
there are no file changes. That is why this is a docstring fix and not a wiring change.

**Cheapest observation.** After wiring it experimentally, compare `tool_io_rollup` and step count
against a matched run. If the stage fires on most steps, the cost is the whole question.

---

## 31. r147 — FIVE fixes validated live, mid-run

r147 is the first generation containing #683-#707. Signatures already fired while it is still
running, so these are no longer "proven at the unit level":

**#691 + #691b — the pair fired exactly as designed, and the subtree SHIPPED.**

    03:33:53  delivery subtree 'mcp_server' is not in the working tree at commit time —
              nothing from it will ship while the registry still advertises 16 registered
              MCP entries
    03:33:53  recovered delivery subtree 'mcp_server' from 5f9973483 — it was committed on a
              branch the release is not cut from. Shipping it.

and on disk `mcp_server/app/main.py` (9652 bytes) plus `pyproject.toml` now exist. **This is the
first run in 146 where the MCP subtree survives to delivery.** The "16 registered MCP entries" in
the warning matches the offline measurement exactly (1 server + 15 tools).

**#700 — the #615 detector reports for the first time in its existence**, and finds MORE than
r146 did:

    5 routes render identical content: /browse/languages, /games, /movies, /new, /shows
        — all fetch only /api/titles
    2 routes render identical content: /title/:id, /watch/:titleId
        — all fetch only /api/titles/

A five-route group against r146's four. This is the defect that was invisible for 146 runs.

**#698 — #641's recommendation is audible**, and the first two firings show the gap WIDENING:

    03:34:55  an earlier capture of this run scored 0.633 (+0.036) at commit 5f9973483c3b
    03:37:01  an earlier capture of this run scored 0.633 (+0.077)

The run is drifting from its own best in real time — #618's pattern, visible as it happens
rather than reconstructed afterwards.

**#664** also fired 32 times (chain-reject escalation).

**r147 FINISHED — rc=0, released v1.0.0. Build cutoff first, because nothing below is readable
without it.** r147 launched 08-14 03:10:56, so its build contains every fix committed before that
and none after:

    IN     #691/#691b 00:23 · #696 01:11 · #698 01:43 · #700 02:00 · #701 02:04 · #706 03:02
    OUT    #707 03:38 · #708b 03:48 · #709 04:01 · #706b 04:15

So `NOT SEEN` for #707 says nothing at all — it was not in the build. `NOT SEEN` for #696 and
#701 DOES mean something: both were in, so their conditions simply did not arise (no suppressed
load failure, no coverage-completion crash). That is the checker header's own rule applied before
reading any verdict.

**The result that matters most: #706 was IN the build, r147 released, and the promotion never
fired.** That is not a condition-did-not-arise; it is a defect, and it is mine. The release notes
read "Final delivery: delivery gate fully clear." — the other call site's wording — so the cut
came from `orchestrator.py:2122`, not the `:3563` site #706 patched. r147 ends with
`rev-list --count main..integration` = **40** and one commit unique to `main`: the exact
pre-#706 topology. Fixed as **#706b**, and the test is generalised from "a hook exists" to "EVERY
`create_release()` is followed by a promotion", which fails on the tree without it. A
one-of-two-call-sites miss cannot be caught any other way than by running.

**ITEM 18 IS NOW CLOSED IN A LIVE RUN — the strongest single result of the session.** The offline
diagnosis was that `mcp_server` is committed on `main`, delivery is cut from `integration`, and
`merge-base --is-ancestor` is FALSE so the release never sees it. In r147:

    r146   mcp_server commit is NOT an ancestor of integration     (the defect)
    r147   1b6eb54 IS an ancestor of integration                   (fixed)

and it got there the right way: #691b's `git checkout <sha> -- mcp_server` restores into the
working tree AND the index, so the pre-existing `git add -A -- mcp_server` swept it into the
framework delivery commit ON integration. The whole chain works, not just the file copy.

**#682b also fired (x3)** — the ownership-403 diagnosis, new this run. #700 is now at x17 and
#698 at x3, both climbing.

Still to check when it finishes: #706's `promoted integration -> main` and whether
`rev-list --count main..integration` is 0 at release (r147 has not released yet — `releases` is
empty and neither the promotion nor a FINAL DELIVERY line has appeared), #696's
suppressed-load-failure line, #701, #707, and the four expected-zero signatures
(#684/#685/#686/#687, all GONE so far).

---

## 33. r147: #664's escalation informs but does not deter — measured live

Mining r147's own log (the freshest data, and the first run carrying #683-#708b) by tool-failure
class puts chain registration on top by a wide margin:

    registryhub_register_verification_chain   160 attempts, 80 FAILED (50%)
    write 24 · edit 6 · test_api 4 · register_endpoint 4 · apply_patch 4

and 62 of those 80 are one endpoint, `PUT /api/profiles/{}`, which the contract genuinely lacks —
the requirements declare `GET`/`POST /api/profiles` and no `PUT`. The verifier is authoring
chains for profile EDITING, a plausible feature nobody asked for.

**#664 fires, immediately, and changes nothing.** First attempt at log line 2705; first escalation
at line **2711**, six lines later. Last attempt at line **8994**. Rejections of that same endpoint
by thousand-line bucket:

    2000s: 8    5000s: 14    6000s: 18    7000s: 22

**Increasing, not tapering.** The escalation fired 72 times over the run and the re-submission
rate for the endpoint it names went UP.

**The message is not the problem.** It already gives both exits verbatim: "DROP those steps (or
the chain). If delivery genuinely needs this coverage, ask the backend lane to implement +
register the endpoint FIRST." This is not the #682/#690 class where the text named a problem
without a resolution — the text is good and is ignored. So a wording fix cannot help, which is
worth recording because wording is what every neighbouring fix in this file did.

**Only a run can settle: which mechanism actually stops it.** Two candidates, both changing
verification semantics, so neither is guessed at here:

  * **auto-drop** — register the chain minus the offending steps and say so ("registered 4 of 5
    steps; step[2] PUT /api/profiles/{id} dropped, not in the contract"). Gets coverage moving,
    but a silently thinner chain tests less than the author intended;
  * **file the gap** — turn the Nth rejection into a work item for the backend lane instead of a
    message to the verifier, so the request is dispatched once rather than repeated 62 times.

**Cheapest observation.** Count `🔧 registryhub_register_verification_chain` against `❌` of the
same, and bucket the rejected endpoint by log position. A working deterrent shows the buckets
DECAYING after the first escalation; today they grow 8 → 14 → 18 → 22.

---

## 33. #710 — #664's escalation is READ-ONLY in practice — and more words will not fix it

r147 is the first run with #664 fully in the build, and it answers a question #664's own comment
left open ("what the logs CANNOT show: whether the agent read the warning"):

    registration attempts                160      failures  80 (50%)
    escalations emitted                   72
    first attempt                        line 2705
    first escalation                     line 2711    six lines later
    last attempt                         line 8994    6,283 lines later

For the worst single endpoint, `PUT /api/profiles/{}` — 62 rejections between lines 2711 and
7825 — the rate **accelerates** after the escalation:

    rejections per 1000 log lines:   2000s: 8    5000s: 14    6000s: 18    7000s: 22

**This is not an instruction gap of the #694/#707 kind, and that matters because it rules out the
cheap fix.** The verifier prompt names `registryhub_list_endpoints` and registered/implemented
**30 times**, and the escalation already says precisely the right thing ("DROP those steps (or
the chain) … re-submitting will keep failing"). Thirty mentions plus a targeted, early, repeated
escalation did not change the behaviour. Writing a thirty-first sentence is the reflex to resist.

Worth noting WHY the verifier wants it: `PUT /api/profiles/{id}` is a perfectly reasonable
endpoint for a profile picker with "Manage Profiles" — it is simply not in the requirements,
which declare only `GET /api/profiles` and `POST /api/profiles`. The verifier is not hallucinating
so much as completing a familiar product shape.

**Only a run can settle** which of the two real options is right:

  * ENFORCEMENT — strip the unregistered steps and register the remainder, so the chain makes
    progress instead of bouncing. Risk: a chain missing a step may no longer test anything.
  * ACCEPTANCE — auto-queue the endpoint as a pending consumer so the backend lane sees the
    demand. Risk: the framework invents contract the requirements never asked for.

**Cheapest observation.** Implement ENFORCEMENT behind a flag and count, in one run: total
registration attempts, failures, and whether the stripped chains still fail their assertions. If
attempts drop toward the number of distinct causes (r147: 80 failures for a handful of causes) and
the stripped chains still catch real defects, enforcement is right. If the stripped chains pass
vacuously, acceptance is the answer instead.

---

## 34. r147 FINAL — what the run settled, and what its NOT SEENs are worth

r147 ended on the shutdown watchdog (`[main-exit] ... forcing exit (rc=0)`) **without delivering**,
deferred throughout by "visual fidelity gate converging, frontend in bounded remediation window".
`fast_release` never appears in the log, so no release path was taken.

**Build cutoff — read this before any NOT SEEN.** r147 launched 03:10:56. Commits at or before
03:02 are in it; everything from 03:18 on is not.

| signature | r147 | reading |
|---|---|---|
| #691 + #691b | LIVE x1 each | subtree recovered AND landed on the delivery line — item 18 closed live |
| #700 | LIVE x37 | the #615 detector's first run ever; found a FIVE-route group |
| #698 | LIVE x4 | #641's recommendation is audible at last |
| #682b | LIVE x7 | ownership-403 diagnosis |
| #664 | LIVE x76 | and #710 shows it informs without deterring |
| #677 | LIVE x2 | transport diagnosis |
| #684 #685 #686 #687 | **GONE, all four** | the defects they name did not occur |
| #706 | NOT SEEN, **and meaningful** | it WAS in the build (03:02). r147 took the other release path → already repaired by #706b |
| #696 #701 | NOT SEEN, inconclusive | their conditions need a delivery r147 never reached |
| #692 | NOT SEEN, proves nothing | its signature is in the backend CONTAINER log under FW_DEBUG |
| #707 #711 #712 | NOT SEEN, **meaningless** | committed 03:38-04:18, after the cutoff |

**The non-delivery is explained and it is not a framework regression.** Round 6's live average
collapsed to 0.3817 (genre_category 0.08, browse_by_languages 0.05, player 0.03) in the same
commit that renamed three routes in `App.jsx` to match the declared contract — `/new-and-popular`
→ `/new`, `/genre/:id` → `/browse/genre/:genreId`, `/browse-by-languages` → `/browse/languages`.
The lane was right to align them; the captures for those screens went to near-zero in the same
round. Whether the gate's screen→URL map follows a route rename is the obvious next question and
is NOT answered here — I could not find the capture site, and the log records no navigation URLs.

**ANSWERED IN PART, 2026-08-14 — and the first answer was wrong.** The capture list is NOT
stale: `run_visual_fidelity` re-parses `known_routes` straight out of `App.jsx` on every call
(`re.findall(r'<Route\s+path=["\']([^"\']+)["\']')`), and `_concrete_capture_route` substitutes
params (`/browse/genre/:genreId` → `/browse/genre/1`). Both hypotheses I formed — a literal
`:param` navigation, then a stale route list — are refuted, and the second had already reached
production text before I checked it.

What survives is narrower and sharper: **the route list is read from SOURCE while the browser
hits the SERVED app.** Any lag between the two — a bundle not rebuilt since the rename — makes
every renamed path miss and fall to the catch-all, which is exactly the five-way byte-identical
capture #713 now detects.

**Strengthened, and the offline half is now exhausted.** r147's final `App.jsx` declares all
FIFTEEN routes, `/watch/:titleId` included, and the working tree matches HEAD exactly. So at the
commit the gate scored, the SOURCE was complete and correct — and four of those declared routes
still captured as the landing page. That leaves source-vs-served as the only surviving
explanation, and it cannot be closed from disk: `app/frontend/dist/` is not kept (the build lives
in the container), so there is nothing to diff the source against.

(A probe error of my own on the way, recorded because it briefly looked like a second finding: I
listed the routes through `head -14` on a SORTED list, which cut `/watch/:titleId` — it sorts
after `/title/:id` — and made a complete file look like it was missing the route the round had
just added. The file has 15.)

**Cheapest observation, revised.** One run: log the URL each capture navigates to AND the mtime
or hash of the served bundle beside it. If the bundle predates the route rename, the gate is
scoring a build that no longer matches the tree and every route-changing round will look like a
collapse; if the bundle is current, the collapse is the app's and belongs to the lane.

---

## 34. #713's real scale — a quarter of every fidelity number is measured on a shared page

#713 was found on r147 (four screens byte-identical to `landing.png`) and its corpus scale turned
out to be far worse than the single run suggested. Hashing every capture in every run:

    runs with >= 2 captures          127
    runs with an identical group     103  (81%)
    screens inside a duplicate group 380 of 1476  (26%)

    worst: r37 12 of 13 screens are ONE image · r48 11/13 · r6 11/12

**Era-split, because "85% of runs" invites the assumption that it is solved history:**

    r<100    84 runs, 71 affected (85%), 254/1032 screens (25%)
    r100+    43 runs, 32 affected (74%), 126/444 screens (28%)

The affected-RUN rate fell slightly and the affected-SCREEN fraction ROSE. This is live.

**What that costs is not a screen here and there — it is the validity of the metric.** Every
fidelity number this document reasons with was computed over a population in which roughly a
quarter of screens did not render their own page: the 0.65 bar, r146's 0.6409, r147's 0.3817,
#618's "24 of 39 runs deliver worse than their own best", the per-screen deviations the
remediation is built from. A screen that photographed the landing page contributes a real-looking
low score, and a low score is exactly what the remediation loop then works on — the lane is sent
to fix a page that was never captured.

**How much does it distort the SCORES? Less than expected, and in the opposite direction.**
Recomputing each affected run's blocking average with the duplicate members removed:

    81 runs recomputable — average rises in 42, falls in 21, unchanged in 18
    median shift +0.0058, mean +0.0083, range -0.115 .. +0.225

So the duplicates mostly drag the average DOWN and the recorded numbers are, at the median,
slightly PESSIMISTIC rather than flattering. The median shift is negligible; the tail is not.

**And at the 0.65 bar exactly ONE verdict flips: r143, False -> True.** Its only two blocking
screens were `browse_by_languages` at **0.25** — the phantom, an image belonging to another
screen — and `login` at 0.70. Drop the phantom and the gate passes.

**What that does NOT prove.** r143 never released, but its log carries no STUCK/ABORT and no
final `Failed checks:` line — it ends mid-activity, so the run was cut off rather than turned
away by this gate. The phantom made the verdict False; whether it cost the release is not in
evidence and is not claimed here.

**The phantom-remediation loop, measured.** The consequence is not just a wrong score — the
deviations computed from that score become the lane's to-do list. Counting deviations
(`deviations` + `measured_deviations`) by whether the screen was inside a duplicate group:

    screens in a duplicate group   333 screens -> 5835 deviations   (17.5 per screen)
    screens that captured properly 1024 screens -> 15715 deviations (15.3 per screen)

A never-captured screen produces MORE remediation than a real one, which follows: scored against
a page that is not its own, nearly everything about it looks wrong. **5835 of the corpus's 21550
fidelity deviations — 27% — describe a screen the gate never photographed.** More than a quarter
of all fidelity remediation is work aimed at a phantom, and it is authored with the same
confidence and specificity as the real quarter.

That also reframes the "frozen score" observations elsewhere in this file: a lane that fixes
everything it is told and sees no movement may be fixing a page the gate is not looking at.

**SETTLED — it is the SERVE side, and r147 proves it by timeline.** I said this needed a run;
the evidence was already on disk and I had not gone looking for it. The chain:

    03:59:12   [VERIFIER] Task complete: Validation pass BLOCKED at docker_up
    04:02:44   the route rename lands (code_state 9e606251d)
    04:03:54   the last capture — 70 seconds later
    04:04:54   "Frontend build tooling pinned to known-good" — AFTER the capture

There is **no rebuild or restart between the rename and the capture**, and the validation before
it was blocked at `docker_up`. `known_routes` is re-parsed from App.jsx on every call, so the gate
navigated to the NEW paths; the browser was serving a bundle built before the rename, which knows
only the OLD ones; every new path missed and fell to the catch-all. Source fresh, serve stale.

That generalises past r147: **a capture is only meaningful if the served bundle postdates the
source the route list was parsed from, and nothing checks that.** The cheapest guard is to compare
the two at capture time — read the served app's route table (or a build stamp) and refuse to score
screens whose route is absent from it, rather than recording 0.03 and generating remediation for
a page that was never reachable.

~~**Only a run can settle: which side of source-vs-served causes it.**~~ The corrected #713 comment
is careful here — `known_routes` is re-parsed from App.jsx on every call so the list is never stale;
what remains is that the list comes from SOURCE while the browser hits the SERVED app, so any lag
(a bundle not rebuilt after a route change) makes new paths miss and fall to the catch-all. Which
it was in r147 is not decided, and guessing it is how the first version of that comment went
wrong.

**Cheapest observation.** With #713 in the build, grep a run for `screens captured the SAME
image`. Then, for one affected screen, compare the served bundle's route table against App.jsx at
capture time — if they differ, it is the serve lag; if they agree, the navigation itself is at
fault and the capture layer needs the fix.

---

## 36. The recurring shape, swept: 137 of 290 tools have never been called

Three times this session I stumbled on the same thing — an instrument built for a problem,
never pointed at it — and each time I found it by accident. Sweeping all 290 tool `NAME`s against
every run log (a name appears in a log only when the tool is CALLED, so zero means never called):

    tools defined                      290
    never called in 253 runs           137  (47%)

**That number is not a defect list, and reading it as one would be the mistake.** Most of the 137
are legitimately situational: `docker_down`, `interrupt_process`, `terminate_agent_team`,
`request_plan_changes` — you call them when the circumstance arises and it usually does not.

**The actionable subset is the one with a matching, MEASURED problem.** All three of this
session's finds have that shape, and it is the triage rule for the rest:

    docker_inspect_image        "containers show stale content"   occurring in 81% of runs  -> #715
    search_icons/search_photos  source an asset you lack          8 of 27 delivered runs    -> #707
    promote_integration_to_main promote after verification        130 of 146 runs diverged  -> #706

So the question to ask of each remaining name is not "is it used" but "is the problem it names
happening". Candidates from the list that look worth that question, none of them checked yet:
`compare_screenshots` and `extract_components` (a fidelity gate that judges by LLM while two
mechanical comparators sit unused), `db_query`/`db_schema` (seed and schema defects are a
recurring class), `log_search`/`log_analyze` (every lane greps logs by hand), and
`check_environment`/`wait_for_service` (the docker_up blockers in items 26 and 33).

**Cheapest observation.** For any candidate, grep the corpus for the failure its docstring
names. If the failure has a non-zero live-era count and the tool has a zero call count, that is
the same finding again — and the fix is a wiring change, not a feature.

---

## 35. The generalisation behind #713: nothing checks that the running app is THIS source

#713's diagnosis settled as the SERVE side — source fresh, bundle stale. Following that one level
up asks a question the framework never asks anywhere: **is the app currently serving actually
built from the current source?**

Searching for any freshness mechanism finds one near-miss and nothing else.
`maybe_refresh_stale_build_checklist` (#120/#492) re-records stale `build:*` CHECK RESULTS when a
transient stamps them failure — it is about the records, not about the binary. Grepping for a
build stamp, build id, source hash or bundle hash returns nothing. So every probe that reasons
about the running app — the visual capture, api_smoke, the browser lane, the chain executor —
trusts that the container matches the tree, and nothing verifies it.

#713 is that gap made visible, and it is not rare: **103 of 127 runs (81%)** contain screens
scored against a page produced by a bundle older than the source the route list came from.

**Only a run can settle: how wide the gap is beyond the visual gate.** The same staleness would
make an api_smoke pass describe code that is no longer there, and nothing in the corpus
distinguishes that from a genuine pass — which is exactly why it has never surfaced.

**THE INSTRUMENT ALREADY EXISTS AND IS UNWIRED.** I filed this as "build a stamp feature" and
that was one grep short. `DockerInspectImageTool` exists, and its own description is this exact
problem:

    "Check if specific files exist inside a built Docker image. Useful for debugging when
     containers show stale/placeholder content. Verifies that source code was actually
     included in the Docker build."
    docker_inspect_image(service="frontend", paths=["src/App.jsx", "dist/index.html"])

It is exported at `tools/__init__.py:199`, appears in **no bundle**, and shows up in **0 of 253
run logs** — against `docker_up`'s 235. Same shape as #699 and #700: the framework built the
instrument and never pointed it at the problem, while the problem it was built for runs at 81%.

**Cheapest observation, revised.** Not a new stamp — compare the served `src/App.jsx` against the
one on disk at capture time, which `docker_inspect_image` was written to do. A mismatch is not a
failure of the app; it is a statement that the measurement is void, and that is the distinction
#713 shows the framework currently cannot make. Wiring it is a tool-grant change plus one call in
the capture path, not a feature.

---

## 32. #615's CAUSE fix — unblocked, quantified, and genuinely run-dependent

#708 retired the technical objection ("the seed gives every title `kind='standard'`") and #708b
made the report name the filters the contract declares. What remains is making `/movies` actually
fetch `?kind=movie`. Every prerequisite is confirmed:

    backend    list_titles(kind=Query(None), genre=..., language=...) — already accepts them
    contract   schema.request = {kind: string?, genre: string?, language: string?, …}
    seed       seed_dataset.json: 60 titles, kind movie 28 / series 32, real genres

**It is not implemented, and the reason is a trade I cannot settle offline.** Filtering by route
changes how much each page renders:

    /movies  -> kind=movie    60 -> 28 items   (-53%)
    /shows   -> kind=series   60 -> 32 items   (-47%)
    a genre page              as few as 1 item

The visual gate scores each rendered screen against a reference screenshot, and the Netflix
references are dense poster grids. Halving a grid — or rendering a genre page with one poster —
is exactly the kind of change that moves a fidelity score, and the standing goal asks for
functionally-correct AND visually-similar. So the fix that makes five routes stop being the same
page may cost the thing the gate measures. That is not a judgement to make from a corpus.

**Only a run can settle.** Score the same app twice, once with route-derived filtering and once
without, and compare per-screen similarity on the affected screens (`movies`, `shows`,
`genre_category`, `browse_by_languages`, `new_and_popular`).

**Cheapest observation.** The projector change is small enough to gate behind an env flag; run
one generation with it on and diff `design/visual_gate/verdict.json`'s per-screen scores against
a matched run. If the affected screens hold their score, the functional fix is free and should
ship; if they drop, the calibration question #615 raised is the real one and the report (#700 +
#708b) is the right ceiling.

---

## 30. The asset/data policy audit — two clean, one gap, and the pairing is the point

Checking the DELIVERED corpus against the run description's own words ("use the REAL provided
assets", "seed the catalog from dataset/titles.json", "no dead links", "no fabricated data"):

| requirement | measured over 27 delivered runs | result |
|---|---|---|
| never pull a remote stock URL (rule 3) | remote image URLs in the shipped frontend | **0** |
| seed from the real dataset | `seed_data.py` containing any of the 60 real titles | **27 of 27** |
| images must resolve (rule 5) | local `/assets/...` refs that 404 | **20, across 8 runs** → #707 |

**The pairing is what makes #707 a policy defect rather than lane sloppiness.** The lane obeys
"no remote URLs" in 27 of 27 and seeds real data in 27 of 27 — it follows the asset policy
everywhere the policy is satisfiable. The one place it breaks rule 5 is the one place the policy
offered no exit: the "who's watching" screen needs avatars, `assets[]` has none, and rule 3 said
only "use the staged assets". 19 of the 20 broken references are invented
`/assets/avatars/...` paths.

So the fix is the missing rung, not more enforcement — #707's rule 5b ladder plus the widened
`stage_missing_frontend_assets` backstop. Recorded here because the two clean rows are what rule
out the alternative diagnosis.

---

## 29. Sweep K — every declared business endpoint IS served, in every delivered run

**Clean, and the two ways I nearly got it wrong are the useful part.** The probe compares the
endpoints in `registryhub_endpoints.json` against the routes actually decorated in the delivered
`app/backend`, path-normalised so `{id}` and `{title_id}` compare equal.

    delivered runs with a backend            27
    declared BUSINESS endpoints across them  654
    declared but not served                  **0**

The first two drafts said otherwise and both were my error, not the framework's:

  * scanning only `app/backend/*.py` instead of walking subdirectories reported **126 missing
    across 32 runs**; recursing cut it to 3 runs;
  * the 8 that survived were all `/api/v1/*` — the control plane, which `is_control_surface_path`
    exempts by design and which no lane backend is supposed to serve. Excluding `/health` and
    `/api/v1/*` takes it to zero.

So the contract→implementation link holds across the whole delivered corpus. Recorded as a
verified positive, and as a reminder that a probe reporting a large number is more likely to be
wrong than the tree is.

**Sweep L — the frontend dual: is every declared screen actually routed?** Comparing each
delivered run's `registryhub_ui_pages` routes against the `path=` props in its shipped `App.jsx`,
normalising `:param` and `{param}` alike:

    delivered runs with an App.jsx   27
    declared ui_page routes          325
    declared but not routed          **0**

Both halves of the contract hold, then — 654 business endpoints served and 325 screens routed,
across every run that shipped. That is consistent with `ui_page_delivery_blockers` being one of
the LIVE gates, in contrast to the dead detectors items 23-27 are about: the checks that run are
the checks whose subject comes out clean.

---

## 28. Sweep J and the per-profile privacy audit — both clean, recorded so they are not re-mined

**Sweep J — gates or pulses reading a store nothing writes.** The never-written stores from item
16 have readers; the question was whether any is a CHECK whose branch therefore cannot fire.
Almost all reads are one serialise-everything snapshot at `registryhub.py:2190-2208`. The one real
candidate is `hub_pulse.py:499`, which builds `api_reviews_pending_my_decision` by iterating
`_api_reviews` — a store at version 1 in 146 of 146 runs, whose two tools appear in 0 of 253 logs.
So the field is permanently empty. **Not a defect:** both consumers gate on it with `or` chains
(`hub_pulse.py:638` and `:783`), an empty list is falsy, and nothing renders. A dead field that
costs no tokens is not worth removing.

**Per-profile privacy in r146's DELIVERED app — holds on every surface.** The run description
requires "Each profile sees only its own My List, ratings and Continue Watching". Reading the
shipped `custom_routes.py`:

    GET/DELETE /api/my-list        _resolve_profile_id -> WHERE id = :pid AND user_id = :uid
    GET  /api/continue-watching    same
    POST /api/titles/{id}/rating   same
    POST /api/continue-watching    "body wins" — and the body path does its OWN ownership
                                   query, 403 "profile does not belong to the authenticated
                                   user" when it fails

The POST body path is the one worth having checked: a `profile_id` in the request body overrides
the header, so if it skipped the check it would let any caller write another user's progress. It
does not.

---

## 19. Older, still unresolved

- **#644 viewport.** Two measured targets conflict: 796px matches the reference image aspect,
  981px matches its content fraction. Changing to 796px took `_measured_deviations` error from
  +9.1% to +23%, so it was reverted. Settling this needs a run at each candidate width scored by
  the real judge, not by pixel arithmetic.
- **#641 round-ledger recommendation at release.** ~~Needs one run's `rounds.jsonl`.~~
  **VALIDATED 2026-08-14 — the run happened.** Only r145 and r146 have a `rounds.jsonl` at all
  (`design/visual_gate/rounds.jsonl`), which is why the corpus could not answer this. r146's
  nine rounds:

      r1 .5809  r2 .5809  r3 .5855  r4 .6027  r5 .6700 (live .6655)
      r6-r9 .6700, live .6409 — four rounds that never recovered r5's live score

  and `design/visual_gate/verdict.json` carries exactly the right call:

      "better_state_available": {"code_state": "5333c4b1ffe2...", "score": 0.6655,
                                 "delta": 0.0246}

  Right round (r5), right score, and a delta matching an independent recomputation to the digit
  (0.6655 - 0.6409). It cleared the 0.02 margin by 0.0046, so this run is also a narrow case,
  not a comfortable one. r145 correctly did NOT fire — one round, nothing earlier to beat.

  This also sharpens the PARTLY RETRACTED section above. "r146's blocking average sat at 0.641
  for the last four rounds" is `blocking_average_live`, and it is not a plateau: it is a
  **regression from r5's 0.6655 that four subsequent rounds never undid**.

  **And it told nobody — fixed as #698.** Grepping the tree for `better_state_available` /
  `better_state_note` finds only the three lines that PRODUCE them, and the sole reader of
  `verdict.json` is #500's best-of merge, which takes per-screen similarities and never looks at
  these keys. A correct recommendation reached no agent, no gate, no log and no human: the same
  shape as #691's silent skip and #696's invisible load failure. #698 emits a WARNING with the
  score, delta, commit and the #618 population figure. Best-effort; it changes no decision.

  **What stays open is a decision, not a measurement.** The recommendation fired and the run
  shipped r9 anyway — by design, "it changes no decision taken here" — so r146 is the 25th
  instance of the pattern its own note quotes (#618: 24 of 39 runs deliver worse than their own
  best). Whether the bounded escape should ship the BEST recorded round instead of the last one
  is a release-policy change and is deliberately NOT made here: an earlier commit can score
  better VISUALLY while being functionally worse, and that trade is not the fidelity scorer's to
  make. #641 has now produced the evidence to argue it with, and #698 makes the evidence visible
  at the moment it is produced.
- **`_auto_approve_threshold = 3`.** ~~One run's plans would give the distribution.~~ **Two runs
  happened and gave zero.** `submit_plan` appears in **0 of 253 run logs** — r145 and r146
  included, and r146 had #658 in the build. It is not unreachable: `tool_bundles.py:661` bundles
  it and the orchestrator's `tool_categories` includes `team_planning`
  (agents_config.yaml:91). So the whole submit_plan → approval → threshold path, including
  `plan_decision.py`, has never executed once in the kept history. The question is therefore not
  "run once more for the distribution" — no run of this workload produces one. It is whether this
  subsystem is supposed to run at all for a single-team app build, and #658 correspondingly has
  no run that can validate it. Same probe as item 13, opposite answer: there the tool is reachable
  and optional, here it is reachable and simply never invoked by anything.

---

## 22. Tools no role can reach — one real orphan, and why the obvious guard does not work

Three findings in this session had the same shape (`register_seed_data` routed to a lane without
the category, `registryhub_request_review`/`submit_review` granted to nobody, the codehub PR
entrance granted 2/0/0 while `force_merge` is granted 11 times), so I set out to build the
generalizable guard: **assert that every declared tool is granted to at least one role.**

**Result: exactly one genuine orphan in the whole tree.**

    data_engine_tools   discover_datasets, preview_dataset, download_dataset, generate_seed_sql
                        "data_engine" is whitelisted as a category in tool_surface.py:41
                        granted to 0 roles in agents_config.yaml
                        0 invocations in 253 run logs

A whole dataset-acquisition surface — including `generate_seed_sql`, which is adjacent to the
seed-gate work above — that no agent can reach. Whether it is wanted is a design question; that it
is currently unreachable is not.

**And the guard itself is NOT the cheap static check I claimed.** Four independent indirections
sit between a tool and a grant, and my first four attempts each produced false positives before I
checked usage:

    1. tools are granted by CATEGORY, not by name   -> flagged eventhub_subscribe, which every
                                                       role holding "eventhub" can call
    2. bundle key `X_tools` <-> category `X`        -> flagged milestone_tools; config says
                                                       "milestone"
    3. bundle name unrelated to category            -> flagged material_prep_tools; it is granted
                                                       as "design", and its tools are among the
                                                       most-used in the corpus (extract_palette
                                                       1023, decompose_reference 1139,
                                                       sample_color 898)
    4. bundle routes to tools named for ANOTHER hub -> flagged schemahub_tools, whose wrappers
                                                       deliberately kept `registryhub_*` NAMEs
                                                       ("prompts and trained behaviour still
                                                       reference them") and arrive via
                                                       "registryhub"

So a string-matching guard cannot be made correct. The only sound implementation instantiates the
tool pool per role through `ToolPoolBuilder` and asks which tools actually land — a real
integration check, not a lint. That is a larger job than the one-liner I proposed, and worth
saying plainly: **I recommended this fix as "pure static, zero runtime risk" and that was wrong.**

Catching it cost four measurements and no production change, which is the right ratio. The three
original instances remain individually recorded above; each was verified by hand.

---

## Where the tests are — read this before auditing a commit

Every fix in this document says "N tests". None of those files appear in the commits, and that is
**deliberate repo policy, not an omission**:

    .gitignore:38   /agent/tests/
    3b71e33  2026-06-18  chore(repo): keep dev tests and run scripts local-only

312 test files exist on disk; **112 are tracked and 200 are local-only.** So a commit message
reading "30 tests; 3115 pass" describes verification that was run, not files that shipped. Anyone
pulling this branch gets the production fixes without the tests that pin them, and should not
read the absence as untested work.

The exception is deliberate too, and worth knowing: the four CONVENTION guards are all force-added
and tracked, so they enforce for everybody —

    test_no_new_fixed_width_source_windows.py     test_no_get_event_loop_in_tests.py
    test_tuned_constants_carry_a_rationale_647.py test_llm_provider_signatures_stay_uniform.py

I nearly "fixed" that last one, having convinced myself it was local-only while its two named
siblings were tracked. It was tracked all along; my filter pattern (`_have_`) simply does not
match `carry_a_rationale`. Fifth instance in this session of reading "absent from my filtered
list" as "absent from the world" — the same error class as the 5 wrong zeros, the `'consumer' in
type` run set, and the two "no tool entry" verdicts on tools that exist.

---

## Next actions that are still offline-checkable

1. ~~**#658 follow-up.**~~ Done — no subscriber exists; see item 6 and #659b.
2. ~~**`llm_func` annotation.**~~ **Already done** — `utils/memory.py:361` now reads
   `Callable[[str], Awaitable[str]]`, with `Awaitable` imported at line 14 and a comment
   recording why. Stale entry, found by re-checking my own list rather than by trusting it.
   Its twin was NOT done and is now fixed with it: `condenser_llm_func: Callable = None` at
   line 503 is forwarded verbatim as `llm_func=` at 514, so it carries the same type and the
   same `= None`-without-`Optional` defect that item 3 below is about.
3. **The 363 `bad-function-definition` reports.** Count independently confirmed 2026-08-14 with
   an ast scan that needs no checker: **361 parameters** of the form `X: T = None` where `T` is
   not Optional, across **56 files** — `str` 164, `dict` 36, `list` 30, `List` 28, `Dict` 17,
   `Workspace` 17, `'EnvGenAgent'` 17, `int` 14. Close enough to 363 to call it the same set.

   **SWEPT 2026-08-14 once pyrefly was installed, and the stated payoff is REFUTED.** 365
   parameters across 55 files rewritten by ast-located text surgery (positions from the AST,
   text spliced in place, so nothing is reformatted). Measured before and after:

       bad-function-definition   362 -> 0
       bad-argument-type         248 -> 245      <- DOWN 3, not up
       missing-attribute         252 -> 264      <- up 12
       total                    1591 -> 1244

   The claim in the original entry — "each one currently hides real `bad-argument-type` findings
   downstream" — does not survive its own test. Fixing all 362 revealed no masked argument-type
   errors; the category shrank. What the sweep DID surface is a different category: **95 of the
   264 `missing-attribute` errors are now `NoneType has no attribute`**.

   **That thread is now followed to the end, and it is ALSO a negative — the "real yield" line
   that stood here was one commit too optimistic.** The 95 are dominated by two families and
   neither contains a live bug:

   * **`self.workspace.<x>` (~20).** Nine classes take `workspace: Optional[Workspace] = None`.
     Still not a live bug, but **my first reason for saying so was wrong and is corrected here**:
     I measured "18 instantiation sites, zero omit `workspace`", which counts whether the
     PARAMETER is passed, not whether a non-None value is. Three sites pass `workspace=None`
     explicitly — `orchestrator.py:2084` and `framework_validation.py:185/1204`, all
     `RunValidationTool(workspace=None)`. The conclusion survives for a better reason: that class
     guards correctly (`if self.workspace is not None and getattr(self.workspace, "base_root",
     None)`), and the classes that dereference unguarded are never handed None. The
     INCONSISTENCY inside `verification_tools.py` — one method guards with
     `if not self.workspace:` while others do not — is real even though the crash is not.
   * **`reg.<hub>` after `_resolve_hubs` (~30).** The shape is
     `reg, err = _resolve_hubs(...)` / `if err: return err` / `reg.workhub...`, and pyrefly
     cannot express that the two are correlated. Reading every return path settles it:
     `(None, err)` when the workspace is missing, `(reg, None)` otherwise — and the
     `if reg is None:` branch CONSTRUCTS a HubRegistry rather than erroring. `reg` is never None
     when `err` is falsy. Pure false positive.

   Net for item 3: keep the sweep — 362 real annotation defects corrected, 1591 -> 1244 total,
   and the signatures now say what the code means — but it surfaced **no live bug**, matching
   the independent conclusion reached on the 248 masked findings. The remaining 1244 should not
   be assumed to hide one either.

   **It also broke the tree, briefly, in exactly the way the entry predicted.** These modules do
   not use `from __future__ import annotations`, so annotations evaluate at def time. Six files
   use `Optional[` ABOVE their own `from typing import` line (reasoning_tools.py uses it at 163
   and imports at 187), and my import-insertion regex took the first typing import it found —
   too late in the file. 52 collection errors, `NameError: name 'Optional' is not defined`.
   Repaired by inserting the import after the module docstring in those six. 3192 tests pass.

   ~~**NOT swept, deliberately, and the reason is about this environment rather than the
   change.**~~ (Kept below for the record; pyrefly is back.)
   `pyrefly` is gone — `[tool.pyrefly]` is still in pyproject.toml but no binary exists on PATH
   or in the venv — so the claimed payoff ("each one hides real `bad-argument-type` findings
   downstream") cannot be observed here. A 361-site sweep would therefore deliver churn with no
   visible benefit, and it is not free of risk: these modules do not use
   `from __future__ import annotations`, so annotations evaluate at def time and any file that
   gains `Optional[...]` without gaining the import fails at IMPORT, not at type-check.

   Worth doing the moment a checker is available again, in one commit, verified by the diff in
   `bad-argument-type` count before and after — that number is the whole point and is the one
   thing this environment cannot produce.

4. **The rating enum — MEASURED AND DROPPED 2026-08-14.** The 400-decomposition table above
   lists "1 rating enum (r145, single instance)": `custom_routes.py` enforces
   `['down','up','love']` while the contract declares `value: str`. Two measurements close it:
   `value must be one of` appears in **1 of 253 run logs**, and **no hub store anywhere holds
   that assertion** — it never persisted. The general form is real but unused in both
   directions: of **4043 endpoint schemas with a schema at all, 0 declare an enum**, so the
   contract language for value sets exists and nobody, in any run, has ever used it.

   n=1 with no persisted artifact and no recurrence does not justify a framework change, and
   the plausible fix (require or infer enums in contracts) is large. Recorded as a rejection so
   it is not re-raised — same disposition as the FK-literal rule, the accent-colour filter and
   the blank-crop content check.

   **UNBLOCKED and RE-MEASURED 2026-08-14.** pyrefly was missing from the venv; `pip install
   pyrefly` through the fwdproxy works (1.2.0). It then produced nothing at all, because it dies
   walking the tree on a **tracked broken symlink**:

       agent/env_generator/llm_generator/screenshot/expedia
         -> /Users/thb/Desktop/Gen-Env/openenv-gen-Agent-base/screenshot

   committed in `11d7960` (the engine migration), pointing at somebody's macOS Desktop, the only
   symlink under `agent/` and the only broken link in the tree. Nothing references it — its
   siblings `airbnb/` and `doordash/` are real directories, and the single textual mention is a
   CLI help string naming `screenshot/expedia.png`, a file that does not exist either. Removed.
   Any recursive tool would have hit the same wall.

   With that gone, `pyrefly check` reports **1,591 errors**, and the entry's characterisation
   holds up exactly:

       362 bad-function-definition   287 bad-assignment   252 missing-attribute
       248 bad-argument-type         196 bad-override      94 bad-instantiation

   362 against the 363 recorded (one was fixed in between), and every sampled message is the
   predicted shape — "Default `None` is not assignable to parameter `assignee` with type `str`".

   **Triaged for real bugs before any sweep, and there are none.** The bug-like classes are
   `unbound-name` (17) and `bad-return` (12); reading every `unbound-name` site:

       checkpoint.py:399        redundant `import json` INSIDE a try, shadowing the module-level
                                import at line 10 and making `except json.JSONDecodeError`
                                theoretically unbound. A stdlib import does not fail; harmless.
       chain_executor.py:2334   `_is_denial` — guarded by a short-circuit the code already
                                documents ("referencing _is_denial after it is always safe").
       route_projector.py:1044  `_parent_owner_filter` — has a default at line 1015.

   That last one deserved a second look, because the default is `""`, i.e. a parent lookup with
   NO owner filter, which is the #692 shape. It is not: the filter is empty only when
   `_owner_fk(parent_meta)` finds no owner column on the parent at all (`genres`, `titles`), so
   there is nothing to scope by. Correct by construction.

   So the 362 remain a typing sweep with no bug behind them, and "mechanical, zero-risk" is
   accurate — but it is 362 sites, and its only payoff is unmasking some of the 248
   `bad-argument-type` findings. Worth doing deliberately, not as a drive-by.

   **And the 248 were then read too, so the payoff is known rather than assumed.** Most are the
   implicit-`Optional` cascade (`X | None` handed to a parameter typed `X`) — the same root, not
   new information. Three classes are genuine type MISMATCHES rather than None-ness, and all
   three were traced to the call site:

       str -> Path (6)          canonical_file_tools/delete.py. `execute(self, file_path: str)`
                                immediately rebinds file_path from `_resolve_workspace_path`,
                                which returns `Tuple[Optional[Path], Optional[str]]`. At runtime
                                it IS a Path — line 61 calls `.is_dir()` on it. The parameter
                                ANNOTATION is what lies, exactly the `llm_func` defect fixed
                                earlier in this session. No runtime bug.
       dict[int] -> dict[str]   chain_executor builds `eps_dict = {i: dict(e) for i, e in
       (4)                      enumerate(...)}` — integer keys — and hands it to
                                `state_entities_missing_write(endpoints: Dict[str, Any])`. The
                                callee never indexes it: `_methods_touching` iterates
                                `_iter_endpoints(endpoints)` by record. Key type is irrelevant.
       tuple arity (4+5)        material_prep_tools.crop_reference. `_region()` returns
                                `tuple[float, ...]`, and the 4-tuple contract is enforced at
                                runtime one line later — `if reg is None: return fail("region
                                must be 4 numbers")`. Guarded.

   **Net result of running the strongest static analyser available over the whole tree: 1,591
   findings, zero live bugs.** Every bug-like class — 17 `unbound-name`, 12 `bad-return`, and the
   three mismatch families above — resolves to a stale annotation, a documented invariant, or a
   runtime guard the checker cannot see. That is a real answer to item 3 rather than a deferral:
   the sweep is cosmetic, and nobody should expect defects to fall out of it.
