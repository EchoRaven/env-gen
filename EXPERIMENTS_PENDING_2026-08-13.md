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

(The WorkHub half of this is **#697**, the same docstring correction #693 made for RegistryHub:
five nouns advertised, one of which — `reactions` — has never held a record in 146 runs.)

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
for the plainest possible reason, and `codehub_list_prs`' 18 calls all read an empty collection. **Fixed: #695** (`tool_bundles.py`).

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

## 37. #696 — does the suppressed load failure actually reach console_errors?

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

## 33. #664/#710 — the escalation is READ-ONLY in practice, and more words cannot fix it

Two passes wrote this up independently and it sat here as two 42-line items saying one thing;
merged with the union of their evidence, because the duplicate itself cost a reader two reads.

Mining r147's own log by tool-failure class puts chain registration on top by a wide margin:

    registryhub_register_verification_chain   178 attempts, 84 FAILED (47%)
    write 24 · edit 6 · test_api 4 · register_endpoint 4 · apply_patch 4

(The first write-up said 160/80 — read while r147 was still running. Corrected against the
finished log; every count below is the final one.)

64 of those 84 are ONE endpoint, `PUT /api/profiles/{}`, which the contract genuinely lacks — the
requirements declare `GET`/`POST /api/profiles` and no `PUT`. Worth noting WHY the verifier wants
it: `PUT /api/profiles/{id}` is a perfectly reasonable endpoint for a profile picker with "Manage
Profiles". The verifier is not hallucinating so much as completing a familiar product shape.

**#664 fires immediately and changes nothing.** This answers a question #664's own comment left
open ("what the logs CANNOT show: whether the agent read the warning"):

    first attempt        line 2705
    first escalation     line 2711      six lines later
    last attempt         line 10083     7,372 lines later
    escalations emitted  76

and for that endpoint the rate CLIMBS for most of the run before finally stopping:

    rejections per 1000 log lines:
      2000s: 8    3000s-4000s: 0    5000s: 14    6000s: 18    7000s: 22
      8000s: 0    9000s: 2    (last rejection line 9122)

**A correction to the first write-up, which said the rate "accelerates rather than tapering".**
It climbs 8 → 14 → 18 → 22 across 5000-7000, which is the substance of the finding, but it does
stop: the 8000s bucket is empty and the 9000s has two. So the escalation is not defied to the very
end — the behaviour runs for ~6,400 log lines past the first warning and then ceases. Whether it
ceased BECAUSE of the escalation cannot be read from this: 76 escalations were emitted across the
whole span, so there is no before/after to compare. What stands is that the warning does not stop
it promptly, not that it never stops.

**The message is not the problem, and that is the finding.** It already gives both exits verbatim
— "DROP those steps (or the chain). If delivery genuinely needs this coverage, ask the backend
lane to implement + register the endpoint FIRST." On top of that the verifier prompt names
`registryhub_list_endpoints` and registered/implemented **30 times**. Thirty mentions plus a
targeted, early, repeated escalation did not move the behaviour. This is NOT the
#682/#690/#694/#707 class where the text named a problem without naming a resolution — here the
text is good and is ignored, so a wording fix cannot help. Worth recording plainly, because
wording is what almost every neighbouring fix in this file did, and writing a thirty-first
sentence is the reflex to resist.

**Only a run can settle which mechanism actually stops it.** Both change verification semantics,
so neither is guessed at here:

  * **ENFORCEMENT / auto-drop** — register the chain minus the offending steps and say so
    ("registered 4 of 5 steps; step[2] PUT /api/profiles/{id} dropped, not in the contract").
    Gets coverage moving; the risk is that a silently thinner chain tests less than the author
    intended, or nothing at all.
  * **ACCEPTANCE / file the gap** — turn the Nth rejection into a work item for the backend lane
    (or a pending consumer) so the demand is dispatched ONCE instead of repeated 62 times. The
    risk is the framework inventing contract the requirements never asked for.

**Cheapest observation.** Implement ENFORCEMENT behind a flag and, in one run, count total
registration attempts and failures, bucket the rejected endpoint by log position, and check
whether the stripped chains still fail their assertions. A working deterrent shows the buckets
DECAYING after the first escalation — today they grow 8 → 14 → 18 → 22. If attempts drop toward
the number of distinct causes and the stripped chains still catch real defects, enforcement is
right; if they pass vacuously, acceptance is the answer instead.

---

## 34. r147 FINAL — what the run settled, and what its NOT SEENs are worth

~~r147 ended on the shutdown watchdog without delivering.~~ **WRONG, and it was my measurement
that was wrong, not the run.** r147 DID deliver: `codehub_releases.json` holds `1.0.0` with notes
"Final delivery: delivery gate fully clear.", and the log carries the delivery marker once.

I checked `releases` while the run was still going — around line 9000 of an eventual 12237 — saw
an empty store, and reported "no delivery" both here and to the user. The release happened in the
3000 lines after I looked. The lesson is narrow and mechanical: **a store read mid-run is a
snapshot, not a result**, and nothing about an empty one distinguishes "never happened" from "not
yet". The run had not even exited when I called it.

What IS true from the same evidence: `fast_release` never appears, so the release came through
the ordinary path, and the run did end on the shutdown watchdog afterwards.

**And correcting it upgrades #711 from a near-miss to a delivered one.** r147's six rounds are
final — no judgement followed my mid-run read — so round 6 stands as the last:

    gating 0.700   live 0.3817   genre_category 0.08   player 0.03

and the run released on it. **But 0.3817 overstates it, and the overstatement is #713's.** Four
of the twelve screens shared the landing page's capture, so their 0.05/0.08/0.05/0.03 measure
that page, not themselves. Over the eight screens actually photographed the mean is **0.5463**.
The honest gap is 0.700 against 0.5463 — 0.15, still under the 0.65 bar, so #711 holds — and the
two findings COMPOUND rather than stacking independently. Checked the two worst pages in the
released tree before concluding: `GenreCategoryPage.jsx` is 45 lines with three fetch/useEffect
sites and `PlayerPage.jsx` is 87 with five, against the top-scoring `LandingPage.jsx`'s 38. They
are not stubs; their scores were simply measured on the wrong page. `release-v1.0.0` is cut at `93d1a3d`, exactly ONE commit past round
6's `9e606251d`, differing by four one-line frontend edits — so 0.3817 is what shipped, and **no
round ever judged the released commit at all**. #711 previously rested on r146's milder 0.67
against 0.6409; the delivered r147 case is 0.700 against 0.3817.

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
| #696 #701 | NOT SEEN, **and meaningful** | both were in the build and r147 DID deliver, so the conditions genuinely did not arise |
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

## 38. #713's real scale — a quarter of every fidelity number is measured on a shared page

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

**Fixed: #714** (`visual_fidelity.py`, "and STOP THE PHANTOM REMEDIATION") — the cross-reference
was missing, which is its own small instance of the problem this file keeps recording. The
finding was written up here in full and the fix carries its own number in the code, and nothing
connected the two, so a reader arriving at either end could not reach the other.

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

## 37b. RETRACTED — the tests were missing by MY oversight, not by policy

Noticed while committing #716 and worth stating because it changes what a reader of this
branch can verify:

    test files on disk        330
    tracked by git            112
    untracked                 218
    written this session      23  (#691-#716) — ALL untracked

`.gitignore:38` does carry a rule with a rationale — "Dev test suites — kept local only, not part
of the shipped pipeline repo", added in `3b71e33` on 06-18 — and I stopped there and called it
policy. **That was wrong, and one more query would have caught it.** Dating every tracked file's
ADD commit:

    tracked tests added 08-12    74
    tracked tests added 08-13    38
    all 112 added AFTER the 06-18 rule

and, on a third pass because the second was also wrong, by number band:

    band        tracked   untracked
    450-499        0         29
    500-549        1         37
    550-599       13         51
    600-649       49          0
    650-699       53          0
    700-749       14          0

**The established practice is to force-add framework-fix tests, overriding the ignore, and it
begins at #600.** From #600 up, every numbered test is tracked with none missing; below #550
almost none are; 550-599 is the transition. My "#548-#690 are all tracked" was itself wrong —
51 files in that range are not — but the conclusion survives on the corrected basis: the
practice is complete from #600 onward and mine, #691-#716, were the only gap in it. So the inconsistency is not "112 legacy files against a local-only policy"; it is that I
used `git add -A`, which respects `.gitignore`, where every fix from #548 to #690 was force-added.
Not a policy question at all, and not the user's to decide: an oversight of mine, 23 files wide.

**Fixed:** the 23 numbered tests for #691-#716 are force-added, restoring the continuity. Left
alone deliberately: the ~195 unnumbered files (`test_anthropic_prompt_caching.py` and the like),
which are the scratch suites the rule is actually about — my first attempt swept all 218 in, which
would have committed a pile of local experiments alongside the provenance.

**The consequence is a communication gap, not a defect.** Every commit in this session ends with
a line like "17 tests. 3438 pass". Those tests are the EVIDENCE for the claim the commit makes,
and by policy they stay on one machine — so the reader gets the assertion without the thing that
backs it, and cannot re-run it after a refactor. The 112 tracked files make it worse by being
inconsistent: a reader who sees tests in `agent/tests/` reasonably assumes the rest are there too.

**Three wrong assertions in one thread, each corrected by the next query, is the lesson.**

    1. "the tests are local-only by policy"        — the rationale was real, the practice was not
    2. "#548-#690 are all tracked"                 — 51 in that range are not
    3. "the ~195 untracked are scratch suites"     — 117 of them are numbered framework tests

Each was stated with the confidence of the one measurement behind it, and each fell to one more
measurement. Same shape as #708's stale `kind='standard'` objection and #713's stale capture-list
claim, but three times in a row on one small question — the give-away being that every wrong
version was reached by reading ONE thing (a rationale, a min/max, a filename pattern) where the
right one needed a distribution.

---

## 78. bug_triage audited — four hypotheses, four falsified, one benign hazard found

The user opened `bug_triage.py` again, so it got a second pass. Four ways it could be broken were
checked and **all four are fine**; recording them so the file is not re-mined a third time.

**1. `list_endpoints` is dead code, harmlessly.** `_registryhub_endpoints` tries
`registryhub.list_endpoints()` first — and **no `def list_endpoints` exists anywhere in the
tree**, so that branch can never be taken. It falls through to `get_endpoints()`, which returns
the full store. My concern was #303's COMPACT rows dropping `provider`; they do not apply here,
and the corpus confirms the field is present on **4120 of 4283** endpoint records (96%).

**2. `registry.schema_hub` exists** — `hub_registry.py:194` aliases it to `self.registryhub` —
and both `get_table` and `list_tables` are real methods on it. Table routing works.

**3. `resolve_owning_agent`'s call site is guarded** (`try/except` in `bug_tools`) and has a
keyword fallback behind it, so an unresolvable bug still routes.

**4. The import that looked fatal is not.** `bug_tools` does
`from multi_agent.runtime.bug_triage import resolve_owning_agent` — a TOP-LEVEL `multi_agent`,
which under the launcher's `PYTHONPATH=$REPO/agent` raises `ModuleNotFoundError`, inside a bare
`except` that would silently null the owner. I had the finding written. Then I checked
`sys.path`: **`main.py:197` inserts the `llm_generator` directory at startup**, so `multi_agent`
IS a valid top-level package in a real run, and the import succeeds. Reproduced both ways to be
sure. **Falsified — and it would have been a large, confident, wrong finding.**

**The hazard that IS real, and is currently benign.** That dual path means the same file lives in
`sys.modules` under two names, as **two distinct module objects with two copies of module-level
state**. Verified for four modules — `bug_triage`, `visual_fidelity`, `delivery_gate`,
`registryhub` — all four are `a is b → False`. Today it costs nothing: every duplicated global is
a CONSTANT (`_LANE_BY_PATH_SEGMENT`, `_LANE_BY_EXTENSION_741`, `_UI_SMOKE_EVIDENCE_CHECKS`,
`_VIEWPORT`, `_CV646`) and none is written at runtime — the single `_VIEWPORT[` hit is a read.

**Cheapest observation.** No probe, because there is nothing to count yet. The condition to watch
is structural: **the day any of these modules gains a module-level CACHE or registry, it will
silently exist twice**, and the two copies will disagree. That is worth remembering before adding
one, and it is the sort of thing that presents as an impossible bug.

---

## 77. Mining r149's deviations — one dead end, one near-miss, nothing live

Two angles closed against r149, recorded so neither is re-opened.

**The `deviations` lead is empty for r149.** My own note says `deviations` beats `missing`
because it carries FUNCTIONAL failures (auth bounces, blank SPAs) in framework-generated text.
r149 has 65 deviations and **all 65 are judge-written visual critique** — "Header: implementation
adds an extra 'Browse' nav item", "Nav: active 'Home' lacks the pill background" — with **zero**
framework route-level entries. That is consistent rather than surprising: r149's app rendered
(no blank screens), so the detectors that write those texts had nothing to say. Corpus-wide only
two such detectors ever appear in a persisted verdict — `redirected to /login` (43 across 11
runs) and `rendered BLANK` (27 across 7) — and both are known classes (#655, #75a/#737).

**A near-miss worth recording as method.** Two other branches write route-level deviations and
appear in NO verdict: #657's profile-picker stall and the `could not be captured` catch-all. I
searched for `profile picker` and `who's watching` and got zero — but the actual text is
`PROFILE PICKER` and `who's-watching`, so **my search was case- and punctuation-sensitive and
missed a live string**. Re-run correctly, it is still 0 of 116 verdicts and 0 logs.

**And then the age control saved it from being a finding.** #657's text was introduced
**08-12 23:31, with only 5 runs since**. Zero hits over 5 runs is not evidence of a dead branch;
it is the same "too young to call" verdict already recorded for #576 and #615. A checker line now
counts it so a later run settles it — a hit means profile selection does not persist, which is
#657's whole diagnosis.

**Cheapest observation.** `#657 picker stall` in section A. Until the count of post-08-12 runs is
meaningfully above 5, its silence means nothing either way.

---

## 76. #759 — sweeping THIS session's fixes for the defect #758 just found

#758's lesson generalises to my own work, so it was applied to it. For every fix #736-#758:
does it emit a log signature, and does the checker grep for it? Six had neither:

    #741  #742  #744  #745  #747  #754

**#747 is a false positive** — #758 logs it, under 758's number rather than 747's. The other
five change DATA rather than emit text, and the right instrument for those is a measurement, not
a log line: five new warnings saying "I ran" would be noise, and #758's point is EVALUABILITY,
not volume. So they became artifact probes in the checker (section E), and they already answer
things about r149:

    #744 completed bugs hidden from open list   7 of 7 completed bugs still read bug_state=open
    #745 retro would count these as closed      7 fixed; the retro would have reported closed=0
    #742 affected_endpoint parseable            2 of 2 well-formed — n<10, proves nothing
    #741 bugs routed by extension alone         0 of that shape this run
    #754 compose path resolves                  13 'missing files' — r149 PREDATES the fix

**r149 confirms #744 and #745 at 100% in a single run.** Every one of its seven fixed bugs still
carried `bug_state=open`, so every one was a phantom "open P0" to `list_open_bugs`, and the
retrospective would have reported that this run closed nothing. The corpus said 616 and 127-of-129;
one run says 7 of 7 and 0.

**And I wrote the #754 line wrong on the first pass.** It printed "the cwd fix did not cover this
call path" for a run that predates the fix — a verdict where the data supports only a baseline.
The checker's own header says GONE/STILL is not self-interpreting and to check the build date
first; I wrote the line that ignores it. Corrected to demand the date check in the note itself.

**Cheapest observation.** Section E runs free on every future run. The one to watch is #754: on a
post-fix run, any non-zero `missing files` count is a call path the resolution missed, and the
pre-fix baseline is 13.

---

## 75. #758 — #747 shipped silent, so its first live run proved nothing

Closing two of this document's own recorded probes against r149, now that it is known to be a
FINISHED run.

**#742 — no verdict, and the honest answer is n=2.** The corpus baseline is 449 of 1129
`affected_endpoint` values parseable (40%). r149 produced **two**, both well-formed. Two samples
say nothing about a prompt-surface change and I am not recording it as an improvement.

**#747 — the data was there and the effect is unmeasurable.** 15 of r149's 29 ui_page records
carry `metadata.reference_image`, and #747 was in the build (committed 16:24, run launched
16:56). So the declaration path had 15 chances to bind a screen — **and #747 logs nothing**, so
there is no way to tell whether a single binding came from the declaration or from the token
heuristic that has always been there.

That is the same defect class this session has been closing all along (#722's
"silence meant three things", #723, #748's captured-and-withheld cause): **an improvement nobody
can observe firing cannot be evaluated, and item 67's own open question — "do the declaration and
the guess ever disagree?" — is unanswerable without a line in the log.**

#758 adds it, with the levels chosen to match what each case is worth:

  * **agreement → INFO.** The lane stated what the gate would have guessed; that is provenance.
  * **disagreement → WARNING.** The declaration and the heuristic pick different pages, so the
    heuristic has been binding a reference to the WRONG page — silently, in every run before
    this one. That is the finding item 67 was reaching for, and it now announces itself.

**Cheapest observation.** Two greps on the next run: `#758 declaration bound` counts how many
screens the lane STATED rather than the gate guessing, and `#758 declaration OVERRULES` is the
one that matters — every hit is a screen that has been scored against the wrong reference for the
entire corpus, and the corpus baseline for it is unknowable precisely because the line did not
exist.

---

## 74. #757 — why r149 delivered nothing, and a latch I nearly shipped

Reading r149 properly as a FINISHED run, one line explains its whole outcome:

    delivery gate has not gone green in 85min since the contract built
    (now failing ['validation_ui_evidence_failed'])

**My own #752 was the sole blocker**, for 85 minutes, and the run ended having delivered nothing.
Two questions follow, and they have different answers.

**Was the block CORRECT? Yes.** r149's store holds 34 validation records: **33 `success` and one
`failure` — `validation:ui_flow:login_to_browse`, updated 1786758171, the NEWEST record in the
entire run.** Not a stale entry: the last word on login→browse was "failed", which is exactly
what `isAuthenticated not implemented (auto-stub)` throwing on 9 screens (#753) produces. The app
was defective, the gate stopped it, and r149 delivering nothing was the right outcome. That is
the second data point on "are the blocks right", and it is in favour.

**Could the block ever have been CLEARED? Not reliably — and that is #757.** Validation records
are a HISTORY and nothing retires one, so a flow that failed early and passed later kept blocking
forever on the strength of the old entry. A gate that cannot be cleared is a latch, and I rejected
the other two candidates at 45% and 70% for being exactly that. Superseding by NAME is the store's
own rule (`validation:<task_id>` is last-write-wins), so the gate now reads the history the way
the store means it: the newest word on each flow decides.

**I went looking for a latch and found the block was sound.** The hypothesis was wrong and the
hardening is real — both are recorded, because "I assumed stale, the record said newest" is the
part worth keeping.

**A second defect, from the same line.** r149's warning read `passed ? / failed ?` — the fallback
for all 19 records, because none of `page`/`route`/`name` is set in metadata. **A gate that
cannot say WHICH page failed cannot be acted on.** The record's own `name`
(`validation:ui_flow:login_to_browse`) carries it and is now used.

**And the blast radius I quoted for #752 was wrong.** Item 70 recorded "6 of 148 runs — 4%, a
gate". That was measured with `evidence.check`, which is **None** on every record in the raw
store; the check kind lives in the NAME. Re-measured correctly: **22 of 123 runs (17%)** would
block, and #757's superseding does not reduce it, because in those runs the failures were never
answered. The samples are not marginal — r2 fails 11 of 12 flows, r7 fails 4 of 4 — so 17% is
still a gate rather than a halt, but the number in item 70 is corrected here.

**Cheapest observation.** The gate now names the failing page in its own warning, so the next run
answers "which flow" without any digging. #750 and #751 remain unfired.

---

## 73. #756 — r149 was NOT killed, and the three new gates got their first real exercise

**Retracting my own previous turn.** I reported r149 as killed mid-work. It was not. It printed

    [main-exit] main() returned 1

at line 21,062 of 21,088, having run its full 6527.4s to `Status: FAILED`. The 26 lines after the
marker are asyncio tasks that were already in flight. The crash-forensics file — **Fix #55, which
already existed and which I should have read before theorising** — records `clean interpreter
exit pid=1396182` for exactly that pid.

**The cause was my own tooling.** `check_pending_experiments.sh` tested
`tail -5 "$LOG" | grep [main-exit]`: a POSITION test for a whole-file fact. It stamped a finished
run with the "this is a snapshot" banner, I read the banner as evidence of a kill, and spent a
turn on a death that never happened — including a corpus-wide investigation of "94 of 149 runs
were killed" that rested on it. Fixed to grep the whole file; the banner still fires for a run
that has printed the marker nowhere, which is what #717 built it for.

Two further corrections fall out. **"This machine kills long tasks" is false**: clean runs reach
246 minutes and the no-marker population has a MEDIAN of 41 with 24 under half an hour — there is
no wall, and long runs finish more often, not less. And **"39% die at an LLM call"** was me
reading one printed example as a pattern: only 1 of 94 has the `AssertionError` storm, and
`LLM.anthropic` is 39% of last-lines against a 27% base rate — a 1.4x lean, not a cause.

### What a genuinely finished r149 says about the three gates

Read as a completed run, an ABSENCE is finally evidence:

    #752  UI evidence contradicts        LIVE x8   -> blocked the gate 8 times
    #750  DELIVERY VETOED                NOT SEEN  -> correctly did not fire
    #751  failed task blocks             NOT SEEN  -> no failed task at the cut
    #740  console error captured         LIVE x6
    #748  compose failure cause          LIVE x5
    #739  UI evidence is thin            LIVE x15
    #749  owner-scoped delivered reads   DATA clean

**#750 not firing is the result I most wanted.** r149's six visual rounds carry **zero blank
screens** (live mean 0.62, under the 0.65 bar) while the console reported
`isAuthenticated not implemented (auto-stub)` on 9 screens. So: console errors present, app
rendering — and the veto stayed silent. That is exactly the discrimination it was narrowed to
make, and the narrowing is what made the decision safe to take. A blanket "blackout blocks" rule
would have had nothing to distinguish here.

**#752 blocked, and blocked correctly.** Eight `validation_ui_evidence_failed` entries, on a run
whose auth predicate threw on nine screens. r149 cut no release. This is the first end-to-end
exercise of a gate that this session turned from reporting to blocking, and the app it stopped
was genuinely defective.

**Cheapest observation.** #750 and #751 are still unfired. #750's silence here is informative
(the right kind), but neither has yet been seen to BLOCK, and the open question — how many blocks
are RIGHT — now has exactly one data point, in #752's favour.

---

## 72. #755 — RETRACTION: "X of X runs released" was every run, because of a bootstrap document

The largest correction of the session, and it lands on numbers I have quoted in five items and in
the justification for three gates.

Chasing why r149 died, I asked how often runs end without `[main-exit]`. The marker predates the
whole corpus (introduced 06-15; oldest log 07-30) and `main()` prints it on all three exit paths,
so the question is sound. **94 of 149 runs never print it.** Testing whether the PROCESS or only
the LOG had died, I compared release timestamps against the log's last write — and got "91 of 94
have no usable release record", which was itself wrong, and led me to the real error.

**Every `codehub_releases.json` in the corpus is non-empty**, because every one carries a
bootstrap document:

    {"version": 1, "last_modified_by": "ensure_codehub_document", "last_modified_at": ...}

A real release record looks nothing like it — `{"id": "1.0.0", "tag": "1.0.0", "source":
"integration", "branch": "release-v1.0.0", "branch_sha": ..., "created_at": ...}`. My release
test was `r.get("tag") or r.get("version")`, so **the bootstrap document's `version: 1` scored as
a release tag and every run counted as released.**

Corrected, with `tag` as the predicate:

    runs in the corpus                                       149
    runs that actually cut a release                          29    (19%)
    frontend runtime-crash signature   14 runs  ->  released   3    (I said 14 of 14)
    unresolved P0 bug                  86 runs  ->  released  15    (I said 90 of 90)
    a task in status `failed`          20 runs  ->  released   4    (I said 20 of 20)

**Do the three gate decisions survive?** Yes, and I checked rather than assumed. #751 blocks 4
releases instead of 20 — still the narrowest candidate. #743's open-P0 option would block 15 of
the 29 real releases (52%), so "a halt, not a gate" holds from the corrected side too. #750 rests
on r148, which released independently of any of this. **The decisions stand; five stated numbers
did not, and they are now corrected at every site** — orchestrator.py's veto comment,
delivery_gate.py's #743 docstring and both #743 warnings, two test docstrings, the checker line,
and items 62/70 above.

**The bigger fact this uncovered.** Only **19% of runs ever release**, and 63% never reach
`main()`'s exit. Every corpus statement in this document was computed over a population where
four out of five runs produced no app — including mine. That does not invalidate the defect
findings (those are about mechanisms, and most were verified against source or a single named
run), but it does mean "the corpus" is not a corpus of finished runs, and no rate quoted over it
should be read as a rate over deliveries.

**Cheapest observation.** `tag` is the predicate; `version` is a bootstrap artefact. Any future
question of the form "how many runs released" must use the former. The 63%-no-`main-exit` finding
is left OPEN: I could not establish whether those processes were killed or merely stopped logging,
because the newer-files test is contaminated by later git activity and no release lands after a
log dies in any of the 94.

---

## 71. r149 was KILLED, and its 108 surviving minutes paid for two fixes (#753, #754)

**RETRACTED by item 73 — the run finished normally.** What this section originally said was that
r149 had been killed. It had not: it printed `[main-exit] main() returned 1` at line 21,062 of
21,088, ran for its full 6527s, and exited cleanly. I reached the wrong conclusion because the
checker's finished-test read only the last 5 lines (#756). Everything below about WHAT the run
found is unaffected; only the cause of its ending was wrong.

Read under #717's rule — a signature that FIRED is evidence, an absent one is not a conclusion —
seven of this session's fixes ran for the first time: `#739` x15, `#743` x13, `#752` x8, `#740`
x6, `#748` x5, plus `#711`/`#713`/`#723`. Two produced facts nothing could see before.

### #753 — the framework's own repair stub crashed every page that imported it

`#740` kept the browser console for the first time, and it said:

    uncaught: isAuthenticated not implemented (auto-stub) (on 9 screen(s): browse_by_languages,
    browse_home, games, genre_category ...); uncaught: getActiveProfileId not ...

`repair_frontend_api_exports` reconciles names a component imports from `api.js` against what it
exports, and gave any unmatched name a stub that THROWS. The function's own comment records the
same defect once already: stubbing `apiGet`/`apiPost` "made every projected page throw
'apiGet not implemented (auto-stub)'" — patched for those two names only. **The general case
still bit, and it took #740 to make it visible at all.**

The costs are not symmetric: a throw takes down the whole React tree, so the page renders
nothing — unjudgeable, unremediable, and pre-#750 it shipped. Now it logs a `console.error`
naming the missing implementation and returns a shape inferred from the name (`is*`/`has*` →
`false`, list-ish → `[]`, else `null`). A wrong guess degrades to the same crash the throw
already produced, never worse. This is **not** the fabricated-fallback rule relaxed: that rule is
about an app inventing product DATA, and this invents no rows.

### #754 — a path checked in one directory and used in another

`#748` made 5 boot failures name their cause:

    CRITICAL:podman_compose:missing files: ['generated/netflix-web-r149/docker/docker-compose.yml']

and the file is right there, 3464 bytes. `_resolve_compose_file` verified it with `exists()`
against the PARENT's cwd and returned the path as given; `start_run` then handed that string to a
subprocess whose cwd IS `generated_dir`, where a relative path cannot resolve. **The error reads
as "missing file" and is a cwd mismatch.** Both the compose path and the cwd are now resolved
from one value. The corpus holds **216 recorded boot failures and not one said why** —
`compose_stderr` had one writer and zero readers until #748. This is the first defect that
finding paid for.

**Cheapest observation.** Both fixes need a run that gets further than r149 did. #750/#751 are
still unverified: r149 never reached a delivery cut, so their absence from its log means "did not
get there", not "did not fire". The three blocking gates remain unexercised end-to-end.

---

## 70. #750/#751/#752 — the decision was taken: three gates now BLOCK. Items 56/58/62 CLOSED.

User-approved, all three. Everything found in #736-#749 reported and decided nothing, and the
corpus says what that costs (**numbers corrected by item 72**): of 149 runs only **29 ever cut a
real release**; 14 carry a frontend runtime-crash signature and **3 released**; 86 carry an
unresolved P0 bug and **15 released**. r148 cut v1.0.0 with the SPA throwing
`TypeError: (void 0) is not a function` on every route.

Each blast radius was measured before flipping it, and **one of the three was deliberately split
rather than switched on whole**:

    ENABLED
      #750  blackout past the refund cap AND console errors   would have caught r148
      #751  a task in status `failed`                          20 of 148 runs   (13%)
      #752  UI evidence that both passes and fails             22 of 123 runs   (17%, corrected in item 74)
    NOT ENABLED — measured, and a halt rather than a gate
      any open P0 bug (#743)                                   90 of 129 runs   (70%)
      UI evidence MISSING entirely (#671's matrix)             67 of 148 runs   (45%)

**#750 — the veto.** Every branch of `_visual_release_decision` returns `"release"`; an escape
answers "have we waited long enough", which is not a question a blank page has a good answer to.
So it is a veto placed FIRST, dominating even #558's fast path (the one that fires before every
time floor). Its condition only became measurable this session: "the capture blanked" alone is
#75a's business and can be the harness rather than the app — precisely why item 56 sat open —
but "blanked past the refund cap AND the browser raised an uncaught error" is not ambiguous, and
#740 is what made the second half observable. The latch clears the moment one capture renders, so
a lane that fixes the crash still ships. **This can end a run with no release at all. That is the
trade, and it is why it needed a decision rather than a default.**

**#751 — `failed` blocks, open P0 does not.** `fail_task` is authorised and requires a reason, so
the status means "attempted and did not work", unlike `pending` which can mean nobody looked. A
lane clears it by completing the task or cancelling it if it was wrong.

**#752 — contradicted evidence blocks, missing evidence does not.** Item 58 asked for both halves;
measuring them separately is what makes it safe. A run whose UI evidence both passes and fails
needs no matrix to interpret — the app said both things — so it blocks unconditionally. Absent
evidence stays behind #671's `tasks/tasks.yaml` condition. Also canonicalised the status spelling
while doing it: the raw store carries `success` 1198, `passed` 310, `failure` 252, and a record
that skipped #193/#236's normaliser must not read as neither now that this is load-bearing.

**Two guards of my own caught me while writing this.** The `_visual_fast_release_args` exact-
equality tests failed on the new `app_dead` key — kept as exact equality deliberately, since that
is what caught the addition. And the fixed-width-source-window guard rejected a `g[i:i + 1400]`
slice in the new test; anchored on a real boundary instead. That is its seventh catch this session.

**Cheapest observation.** Every one of these is now visible in a run log by its check name:
`unresolved_failed_tasks`, `validation_ui_evidence_failed`, and #750's "DELIVERY VETOED" line. The
number that matters is how many blocks turn out to be RIGHT — a blocked run that would have
shipped a working app is a pure loss, and no artifact can answer it. The corpus baselines to judge
against are the three percentages above.

---

## 69. Two hypotheses falsified, one method retired, and the delivered apps audited clean (#749)

A turn with no defect in it, recorded in full because three of these would otherwise be re-mined.

**Falsified: "the framework reads kickoff keys the lanes never write."** The mirror of #748, and
the shape of #730. A sweep said `data_model` (13 reads) and `backend` (10) never appear in any
hub record. They do — my vocabulary only indexed ONE level of nesting, and kickoff drafts sit
deeper, in `workhub_documents` (142 records) and eventhub events (1422). Replaying the real read
path (`_collect_drafts` → `backend` → `api_endpoints`/`data_model.tables`) over the corpus:
**138 of 141 runs resolve endpoints or tables**, 2 miss the backend draft entirely. No defect.
The one-level index is the same failure as the `payload.metadata.bug_artifacts` miss in item 61
and the `metadata["priority"]` miss in item 56 — third time this session, always the same cause.

**Method retired: "framework reads what nobody writes", statically.** Redone with a full
recursive vocabulary (462,515 keys), 79 reads still look unmatched — and the list contains
`blocking_average_live`, which certainly exists, in `design/visual_gate/` rather than
`shared/hubs/`. The reads are on in-memory dicts and non-hub artifacts as often as on hub
records, and nothing cheap tells them apart. **The method cannot answer the question**; it is
recorded as unusable rather than left to look unexplored.

**#749 — the delivered backends are clean, and the probe that says so is now permanent.** My
memory's standing rule is to audit the delivered app even after a green gate (#569 was a live
leak in r134's shipped `/api/search`). A crude first pass flagged 85 of 135 delivered
`custom_routes.py`, and every sample was noise: an owner column in a JOIN condition or in the
SELECT list says nothing about scoping. Tightened to "the owner column appears in NO predicate,
in a GET handler, with no Python-side scoping either" the answer is **0 of 135**.

That zero was then checked rather than believed, which matters because the tightening added a
broad exclusion that could easily over-reject: a planted unscoped handler IS flagged, and a
scoped one is NOT. So the result is real: **no delivered backend has a GET handler reading a
per-user table without an owner predicate.** The #566s/#591/#598/#569 line holds across the whole
delivered corpus.

It is wired into `check_pending_experiments.sh` as section D, printing `P0` with the offending
statements if a future run regresses and `DATA … clean` otherwise — a clean audit is only worth
anything if it keeps being true.

**Cheapest observation.** Section D runs on every future run for free. The corpus baseline it
prints is 0 of 135, so any `P0` line is a regression with the statement already quoted.

---

## 68. #748 — the reason the app would not boot was captured and withheld

#747's shape, swept properly: **every hub field that is WRITTEN and never READ.** For each store,
every key appearing in ≥80 records whose name never occurs as a string literal anywhere in the
tree. Three candidates out of the whole corpus:

    runhub_runs.compose_stderr                216 records, ALL 216 non-empty
    codehub_checks.evidence.http_status       133
    workhub_tasks.evidence.contract_test_...   95

`compose_stderr` has exactly **one writer and zero readers**, and it is never filler — all 216
carry the real cause, e.g. `CRITICAL:podman_compose:missing files: ['…/docker-compose.yml']`.
Meanwhile the EVENT everything downstream reacts to carried the bare label:

    self.update_run_status(run_id, "aborted", compose_stderr=(up_result.stderr or "")[:500])
    self._emit("run_completed", run_id, {"reason": "compose_up_failed"}, priority="high")

The orchestrator and the lanes were told the app would not boot and not why, with the answer
sitting in a field beside them. Same shape as #677 (1778 bare "Connection refused"), #690 and
#740 — the diagnosis exists at the moment of failure and is kept from whoever must act on it.

Fixed: logged, and carried in the event payload alongside the returncode. The store write is
unchanged, and the empty-stderr case — the one that reads as "no information" and is exactly when
a hint is worth most — gets an explicit hint instead of a blank.

**The other two are left alone deliberately.** `evidence.http_status` and
`evidence.contract_test_recorded` are audit fields on records a human or a later query reads;
#733 already established that `evidence` persists extra keys verbatim BY DESIGN. Unread is not
the same defect there: nothing is making a decision without them.

**A recurring trap, now closed in the tests rather than re-hit.** Two assertions failed on
implicit string-concatenation SEAMS: a message split as `"…so every "` / `"check after this…"`
keeps its quote characters, so a whitespace-collapsed view reads `every " "check` and the
assertion fails on punctuation that is not in the message. Third occurrence this session; the
test now closes the seam (`re.sub(r'"\s*\n\s*"', "", …)`) before matching.

**Cheapest observation.** Any run whose app fails to boot: the log line names the cause instead
of `aborted`. The corpus baseline is that 216 boot failures were recorded and none of them said
why in the log — so a single future occurrence with a cause attached settles it.

---

## 67. #747 — the lane declares which reference each page matches, 1182 times, and the gate guessed

**This is the user's own proposal, and the data to honour it has been arriving all along.**
Earlier this session: 「这个具体navigate到具体哪个页面,和哪个参考图对比…要不直接让实现他的
frontend agent来传输呢…最终目标是设立的所有参考对比都达标」. The frontend agent already
transmits it.

Found by generalising #742's shape — a tool parameter declared free-form whose value a consumer
parses. Sweeping every `PARAMETERS` block for an `object` param with no `properties` gave 6
candidates; the one that mattered was `metadata` on `kickoff_declare_ui_page`. Asking what agents
actually put there, over the corpus, gives only three keys ever — and one of them is the answer:

    ui_page records carrying metadata.reference_image                1182
    ... naming a file that exists in that run's design/references/   1119   (94.7%)
    distinct values                                                    54
    (the other two keys: seeded_from_design 902, notes 210)

`map_reference_screens` links a design screen to an app route, and its most authoritative layer
(#416) INFERS that link from token overlap between the screen name and a ui_page's name —
because it assumed nothing states it. `load_ui_pages` projected each record to
`{name, route, component}` and **dropped `metadata` at the door**, so the declaration never
reached the mapper. The framework has been guessing next to an explicit answer, 1182 times.

Fixed: the declaration is now the top layer, ahead of #416, matched on the STEM — the 63 values
that do not resolve are almost entirely an extension mismatch (`landing.png` declared,
`landing.jpg` staged), and a declaration that is right about WHICH screen should not be discarded
over a file suffix. Both existing exclusions are preserved exactly: an overlay name (#128) or a
transient interaction-state name (#542a) is never given a page route or promoted, declaration or
not, and a declared route the app does not serve is still ignored (#416's no-404 rule).

**Two of my own errors, both from asserting instead of looking.** The projection fix went into
the wrong place first — I edited the intermediate `items` list while the function rebuilds the
records one loop later in `out.append`, so the field was dropped again and the test failed with
`KeyError: 'reference_image'`. And the exclusion tests asserted `route != "/account"`, which
failed: an overlay DOES get a route, from the generic filename→route fallback that predates all
of this. What #128/#542a own is never inheriting a PAGE link and never being PROMOTED — the
assertion is on `advisory`, with a non-vacuity case proving `advisory` is not True for everything.

**Cheapest observation.** This is the first fix in the arc that acts on the user's design
proposal with existing data, so the number to watch is direct: next run, how many screens get
their route from the declaration rather than the guess, and do the two ever disagree? A
disagreement is the interesting case — it means the token heuristic has been binding a reference
to the wrong page, and the corpus cannot say how often because the declaration was never read.

---

## 66. #746 — a guard that has been taking a decision silently for 255 runs

A different sweep, aimed at the class this session keeps producing: **a detector that cannot
fire** (#712's dead branch, #716's unmatchable pattern, #734's vacuous guard, #715's wrong
shape). Method: every numbered log call in `runtime/`, grepped against every run log, keeping the
ones with no hit whose fix PREDATES the oldest run.

**The first version of the sweep was wrong and is worth recording as such.** A regex over
double-quoted strings beginning `#NNN` matched docstrings as well as log calls: 93 "warnings",
88 of them "never fired" — meaningless for text that is not a log line. Re-done over the AST,
taking only the first string argument of a `.warning`/`.error`/`.info` call: **18 calls, 10 with
no hit.** Seven are mine from today and postdate every run. Dating the other three against the
corpus window (oldest log 07-30, newest 08-14 11:37):

    #254  hub_registry.py    introduced 07-21   ALL 255 logs    0 hits
    #576  scaffolder.py      introduced 08-11   ~14 runs        0 hits
    #615  deliverability.py  introduced 08-14   3 runs          0 hits   (item 54's finding)

#254 is the one youth cannot explain, and reading it explains the zero:

    _log = getattr(self, "_logger", None)
    if _log is not None:
        _log.warning("#254: refused to downgrade …")

**`_logger` is set nowhere.** The name appeared exactly once in the module — in that read — and
the module had no `logging` import at all. The line was unreachable from the day it was written.

This is not a missing log line. `record_validation_result` REFUSES the write and returns
`downgrade_rejected: True`, discarding an LLM agent's evidence-free `failure` so it cannot erase
the framework's measured pass — the r51 incident #254 exists to prevent, where the verifier
overwrote 7 deterministic rows within 33 seconds and the run aborted 117 minutes later on a
WORKING app. That guard has been making its decision invisibly ever since. Nobody could tell
whether it fires, how often, or whether it is protecting a real pass or masking a real failure.
Same shape as #691's silent skip, #696's invisible load failure, #722's silence-means-three-things.

**Two of my own test errors this time, both instructive.** The fixture built its "deterministic"
standing record as `{"execution_mode": "deterministic"}` — which reads like the right thing and
is not: `_is_deterministic_evidence` keys on `deterministic_runtime_evidence`, so no refusal
happened and the test failed for the wrong reason. And the premise-check counted occurrences of
`_logger`, which measured **my own new comment** (6 == 1) and then the warning TEXT. Counting a
word was never the right instrument; the claim is that nothing BINDS the name, so it is now an
AST assignment check, with a planted-assignment probe proving it is not vacuous.

**Cheapest observation.** Next run, does `#254` appear? Either answer is informative and neither
was available before: a hit means the guard is load-bearing and we can finally see how often; no
hit across a run that had evidence-free verifier failures means the r51 path no longer occurs and
the guard is now historical. `#576` and `#615` stay on the list — both are too young to call, and
`#615`'s silence is exactly item 54's open question.

---

## 65. Sweeping #745's pattern across every hub store — two inert, one falsified, none live

#745 named a shape worth sweeping for: **a field written once at creation, advanced only by a
call almost nobody makes, and read by a consumer that treats it as current.** The tell is a
status vocabulary whose terminal values are nearly absent. Every `status`/`state`/`verdict` field
in every hub store, over the 148-run corpus:

    workhub_tasks.status              13268   completed 10247  in_progress 1377  cancelled 869
    codehub_checks.status              6469   recorded 4205  success 1702  passed 310  failure 252
    registryhub_endpoints.status       4104   implemented 4047  defined 51  deprecated 6
    registryhub_verification_chains    3651   passing 3140  registered 267  failing 151
    registryhub_ui_components.status   2469   implemented 1805  defined 664
    registryhub_ui_pages.status        2298   implemented 1788  defined 510
    registryhub_contract_tests.verdict 2026   pass 2011  fail 15
    runhub_runs.status                 1492   completed 1276  aborted 216
    codehub_branches.status             328   active 328
    milestones.status                   185   pending 139  active 30  delivered 16

Three candidates matched the shape. **None is a live defect, and saying so is the point** — this
is recorded so the same three are not re-mined.

**`codehub_checks.status` — hypothesis falsified.** `recorded` is 65% of the store and is not a
verdict, and the gate decides the build checklist with an EXACT match:
`all_passing = all(s == "success" ...)`. Three spellings exist in the store (`success` 1702,
`passed` 310, `failure` 252), so a `passed` build check would read as not-passing. Checked before
claiming it: `build:*` checks use **only** `success` (491) and `failure` (68) — never `passed`.
The three-spelling problem is confined to `validation:*`, which is read through #193/#236's
normaliser (`success` → `passed`). `artifact.recorded` (4204 of the 4205) is a step-pipeline
artifact record, not a verdict. **No defect.** I would have reported one had I stopped at the
vocabulary mismatch.

**`codehub_branches.status` — inert.** 328 of 328 are `active`: the purest form of the tell, one
value ever observed. It is written in exactly one place (`service.py:238`,
`existing.get("status") or "active"`) and **no code reads it**. Inaccurate but consequence-free.

**`milestones.status` — inert, and explained.** 129 of 141 released runs have no milestone that
ever reached `delivered`. The cause is in `orchestrator.py:1327-1329`: a milestone is marked
delivered only when a LATER one starts, so **the final milestone of every run is never marked**,
by construction — and for the single-milestone runs that are the proven path, that is the only
milestone. The corpus agrees exactly: multi-milestone runs show `active` + `delivered`, i.e. all
but the last. The only reader of the field is that same advance logic, so nothing decides on it.

Deliberately NOT fixed. Marking the final milestone at the release cut would be a release-path
edit (#706's hook is where it would go) for zero behavioural gain, and the release path is the
last place to accept risk for a record-accuracy improvement. It is worth knowing about for the
reason this session keeps re-learning: **a record that reads "pending" for a delivered run is
exactly the kind of artifact that produced wrong conclusions here** — `verdict.json`'s high-water
merge erasing r148's blackout being the expensive example.

**Cheapest observation.** None of the three needs a run. What WOULD be worth one line of a future
run's log is whether `codehub_checks` ever records a `build:*` check as `passed` rather than
`success` — the moment it does, the gate's exact match becomes the defect I wrongly expected, and
the corpus baseline is 0 of 559.

---

## 64. #745 — the retrospective told 102 runs that nobody ever fixed anything

The same root as #744, found by asking which OTHER consumers read `bug_state` without the task
status. `retro_aggregator._bug_stats` counts `closed` only when `bug_state == "closed"`:

    bugs that ever reached bug_state == "closed"        6
    bug tasks whose STATUS is completed               818
    runs whose retrospective reports `closed: 0`   127 / 129
    ... of those, runs that DID fix bugs              102     ← reported as zero

The retrospective is the framework's own self-assessment and an input to what the next run learns
from. It was telling 102 runs that their entire remediation effort produced nothing. Fixed the
same way — derive from the field that is maintained. `cancelled` stays excluded, because #672
measured 55% of cancellations as duplicates and a deduped bug was never fixed.

One ordering detail is now pinned rather than left implicit: the branch is
`if closed … elif escalated`, so a bug that was escalated and then completed counts as CLOSED.
That is the right reading and it is decided entirely by branch order, which is exactly the kind
of thing a later edit flips without noticing.

**The other `bug_state` readers were checked and need nothing.** `base.py:909` and
`hub_pulse.py:862` both iterate `list_open_bugs()`/`list_bugs_assigned_to()`, so #744 already
fixed their population; they only display the field afterwards.

**The pattern, stated so it can be swept for.** Both defects are the same shape: **a field
written once at creation, advanced only by a call almost nobody makes, and read by a consumer
that treats it as current.** The tell is a status vocabulary whose terminal values are nearly
absent from the corpus — `closed` 6, `fix_verified` 1, `triaged` 1 out of 1477. Any other
lifecycle field in the hubs is worth the same one-line check: count its terminal values across
the corpus and compare against the thing that actually finishes.

**Cheapest observation.** No run needed for the fix. What a run would show is the retro line
itself: `closed` should now be non-zero on any run that remediated anything, and if it is still
0 while bug tasks completed, the derivation is reading a different store than the one the
retrospective is built from.

---

## 63. #744 — 62% of the "open P0 bugs" that defer delivery are already fixed

The one live-behaviour defect in this stretch: everything else here reports, this one **decides**,
and it decides against the runs that did the work.

`list_open_bugs` filtered on `metadata.bug_state` alone. That field is set at creation and moved
only by `update_bug_state`/`close_bug`, which almost nobody calls. Across the 1477 bug tasks in
the 148-run corpus:

    open 1201   assigned 224   escalated 41   closed 6   fix_proposed 3   triaged 1
    fix_verified 1

**Six ever reach `closed`.** Completing the TASK does not touch `bug_state`, so 616 tasks sit at
`status=completed` with `bug_state=open`, and `OPEN_STATES` counts both `open` and `assigned`.
Two fields encode one lifecycle and only one is maintained, so they drift by construction.

On the population the delivery path actually reads:

    open P0s by bug_state alone           821   across 120 runs
    ... also excluding a terminal status  310   across  90 runs
    already fixed but counted as open     511   (62%)

**Why it decides.** `collect_open_p0_by_source` (#630) is built on this list; its result becomes
`bugs["p0"]`; and that value's only use is
`verdict = "PASS" if bugs["p0"] == 0 else "DEFECTS"`, a verdict the delivery gate reads. A run
that fixed every P0 still scored DEFECTS and deferred, because the fixed bugs kept
`bug_state=open`. #630's widening was right and is not the fault here — the verifier files 207 of
314 P0s and was invisible to the old narrow count — but the stale field turned the widened gate
hardest against exactly the runs that had remediated.

Fixed by excluding a terminal TASK status from the open list. `failed` is deliberately NOT
terminal: an attempted fix that did not work leaves the bug outstanding, the same reading #743
takes of that status. The `bug_state` filter is unchanged and still excludes `closed`/`escalated`
— #744 adds a condition, it does not relax one.

The blast radius is the reverse of items 56/58/62: those three would make delivery HARDER and
need a decision. This one makes it correct in the direction it was already trying to go, so it
needed none.

Also note what did NOT break: no existing test failed. `list_open_bugs` had coverage for its
`bug_state` filter and none for a completed task, which is why the drift lived this long.

**Cheapest observation.** Next run, the squad line already prints both numbers —
`verdict=%s: %d open P0 (%d from test-users)`. Compare `open P0` against the count of bug tasks
whose status is non-terminal; they should now agree. If a DEFECTS verdict still names a bug whose
task is completed, the terminal set is missing a status this corpus does not contain.

---

## 62. #743 — bug tasks are excluded from the gate and delegated to a gate that isn't

**A correction first.** Earlier in this session I wrote "the delivery gate reads no task status
or priority at all" (items 56, 58). That is wrong in the general form: `incomplete_required_tasks`
calls `wh.list_tasks()` and filters on `pending`/`in_progress`. The truth is narrower and worse,
and it is written in that function's own docstring:

    Ad-hoc `task_*` … are NOT structural kickoff kinds — they are governed by their own gates
    (visual deferral, deliverability) and are deliberately excluded here so this gate never
    double-blocks them.

The exclusion is right in shape; a bug should not double-block. But for `kind='bug'` **the
delegation goes nowhere.** Checked rather than assumed: `deliverability.py` contains no `bug`
string at all, and `delivery_gate.py`'s only bug-kind or severity comparison is #743's own.

**Corpus, restricted to `metadata.kind == 'bug'` — 1477 bug tasks in 129 runs:**

    completed 818   pending 363   cancelled 140   in_progress 139   failed 17
    P0 only:  completed 443,  genuinely open 317,  cancelled 99
    runs ending with an unresolved P0 bug      90
    of those, runs that RELEASED               90        100%

So the P0 option is dead from this direction too — 90 of 129 is a halt, not a gate. That is the
same verdict item 56 reached from the all-kinds side (124 of 148), now confirmed on the narrower
population where the stale structural tasks cannot inflate it.

**`failed` is the signal worth a decision.** `fail_task` is authorised (creator, claimer, or
orchestrator only) and REQUIRES a reason, so the status means an attempt was made and did not
work — where `pending` can just mean nobody reached it. Only **20 of 148 runs (13%)** end with
one, and **4 of those released** (item 72 corrects an earlier "all 20"), carrying things like
*"Frontend Dockerfile uses registry-blocked
base images"*, *"Record the missing critical UI flow validations (blocks delivery)"* and
*"Landing page (/) renders a stub"*.

Landed: `unresolved_bugs` in the gate payload plus two warnings — one for FAILED tasks with their
`fail_reason`, one for open P0 bugs. Decides nothing, same disposition as #711/#715/#738/#739.

**Cheapest observation, and the decision.** This is now the third gate-tightening waiting on the
same call, and they should be decided together because they are the same trade in three places:

    item 56   a post-cap BLACKOUT blocks delivery          would have caught r148
    item 58   ui_smoke stops being existential             would have caught r148
    item 62   a FAILED task blocks delivery                13% of runs; 4 of them released

The blast radii are known for all three. What no artifact can answer is how many of those blocks
would have been RIGHT — a blocked run that would have shipped a working app is a pure loss, and
only a run that is allowed to hit the block can tell us.

---

## 61. #741/#742 — 216 bugs in the corpus are owned by nobody, and both causes are readable

`resolve_owning_agent` tries the endpoint, then the table, then the files. Measured over the
1467 bugs in the 148-run corpus — `bug_artifacts` lives at `payload.metadata.bug_artifacts` on a
workhub `task_created` event, **not** at `payload.bug_artifacts`, which is where I looked first
and got a confident zero out of 299,279 events:

    resolved to a lane     1251
    owned by NOBODY         216      of which 131 carry no affected_files at all

**#742 — the endpoint slot is mostly unparseable.** Of the 1129 bugs that set
`affected_endpoint`:

    449  match a registered endpoint exactly
    339  have nothing path-shaped after the method
    308  carry prose inside the path — "GET /api/titles?kind=series (or however the shows
         page filters titles)", "frontend nginx"
     20  differ only in the parameter NAME (/titles/{title_id} vs /titles/{id})
     13  name a path that is not registered

**57% of the values a parser depends on are not parseable**, and the tool contract says why:
`bug_artifacts` was advertised as the bare string `"failing_test, stack_trace,
affected_endpoint, affected_files, expected, actual, ..."` — slot names, no shape. Same family
as #732/#733, and the same fix: publish a `properties` block, state the exact form of the two
slots that are PARSED rather than merely read, and say where the uncertainty is supposed to go
(`description`) so a rule that forbids does not leave the model stuck.

I expected the parameter-name mismatch to be the story — the delivery gate has `_norm_gate_path`
for exactly that (`/api/notes/{id}` ≡ `/api/notes/{}`) and triage does bare `==`. It is 20 of
1129, **1.8%**. Normalising is still right, but it was not worth reporting as the cause, and I
would have if I had stopped at the first plausible-looking gap.

**#741 — a path that names no lane still names a language.** #626 routes by path SEGMENT, which
by construction cannot help a path written relative to the app root, and those dominate what is
left: `src/App.jsx` (11), `src/pages/BrowseHomePage.jsx` (5), `src/api.js` (3),
`custom_routes.py` (2). Extension as a strict FALLBACK routes **25 more** (22 frontend, 3
backend). `.js`/`.ts`/`.mjs` are excluded on purpose: a Node backend uses them, and a
wrongly-routed bug burns the wrong lane's cycle — worse than the 7 extra routes it would buy.
Anything under `app/backend/` already carries its segment and never reaches the fallback.

This also corrected one of #626's own assertions. It pinned
`find_owning_agent_for_file("src/components/BackendStatus.jsx") is None`, but #626's finding is
"never the BACKEND" — `None` was an accident of the segment rule, and `frontend` is the right
answer for a `.jsx` file. The test now states the invariant.

**Cheapest observation.** #742 is a prompt-surface change and only a run can score it: next run,
what fraction of `affected_endpoint` values parse? The corpus baseline to beat is **449/1129 =
40%**. #741 needs no run — it is proven against the recorded paths.

---

## 60. #740 — the capture drives a browser to every route and threw the console away

There was no `page.on("console")` and no `"pageerror"` anywhere in `visual_fidelity.py`. The gate
navigates a real browser to every declared route, every remediation round, and discarded the
single most diagnostic signal on the page. A crashed SPA could therefore only be described by its
SYMPTOM — *"route X rendered BLANK — the SPA never hydrated"* — and the remediation task handed
to the lane said *"fix the page's mount/data load, not its styling"*.

r148 shows the cost. Its frontend threw `TypeError: (void 0) is not a function` on every
authenticated route. The capture saw ten blank shells and said so at 11:13:19; the error TEXT
reached the lane only because the verifier separately drove a browser and read the console, nine
minutes later at 11:22:16.

Corpus, over the 148 task stores:

    runs whose tasks carry a frontend runtime-crash signature      14
    of those, runs that RELEASED                                   14
    of those, released with the crash task still open               9
    runs carrying `(void 0) is not a function` specifically         5

**A frontend runtime crash has never once stopped a release.** Reading the console does not stop
one either — this is diagnosis, not a gate — but it puts the cause into the artifact the lane is
handed instead of leaving it to be rediscovered by whoever drives a browser next.

Bounded on purpose: 5 distinct messages per screen, 300 chars each, `error`-level console entries
and uncaught exceptions only, so a page looping an error cannot flood the verdict. Errors are
attributed to the screen being navigated (set before the `goto`, not after), attached to each
screen's record as `console_errors`, appended to the blank-capture deviation, and summarised once
per pass **grouped by message** — one broken import crashes every route, and twelve identical
lines read as twelve problems.

**Cheapest observation.** Next run: does `#740` fire, and does the grouped line name one error
across many screens or many errors? If a blank capture ever reports NO console error, that is the
interesting case — it would mean the shell is empty for a reason the browser did not raise
(a mount that renders nothing, a route that matched nothing), and the deviation text should stop
implying a crash.

---

## 59. Item 55's open question, answered: visual remediation works, weakly

Item 55 recorded that the effectiveness of visual remediation **has never actually been
measured**, because every delta I had computed came from blackout rounds. With the instrument
understood, the measurement is possible offline. Two round classes are excluded, both for
reasons established this session and neither of them a judgement call: **blackout** rounds
(#737 — half or more screens at 0.00, the capture produced no page) and **#713 fall-through**
rounds (three or more screens under 0.10 at once, the capture photographed another page).

Per-screen deltas between consecutive rounds whose `code_state` actually changed, split by
whether the screen was below the bar and therefore named in the remediation task:

    run    usable rounds     targeted (named)          control (already passing)
    r146        9/9          up 9  down 2  same 49     up 2  down 2  same 25
    r147        5/6          up 4  down 2  same 25     up 1  down 2  same 14
    r148        3/12         up 0  down 0  same  8     up 0  down 1  same  3
    -----------------------------------------------------------------------------
    total                    up 13 down 4  same 82     up 3  down 5  same 42
                             net +9 over 99 obs        net -2 over 50 obs

**Remediation works, and the sign is right**: a named screen is three times more likely to rise
than to fall, while an unnamed one drifts slightly down. That is the first direct evidence in the
arc that the loop does anything at all. It is also weak: **83% of named screens do not move**, so
a round of remediation shifts roughly one screen in six.

This closes item 55's question and RETRACTS the alarming version of it. My earlier reading —
targeted screens moving *less* than untargeted ones, the three most reachable pages never moving
— was entirely an artefact of r148's nine blackout rounds, and r147's apparent net-negative was
the #713 fall-through. Both are withdrawn.

It does NOT close item 54's half, which is a different question: the lane holding information
(`/api/titles`'s `query: {kind, limit}`, fetched 28 times) and not using it. Fidelity remediation
moving one screen in six says nothing about whether a *contract* fact gets acted on.

**Cheapest observation.** The 83% flat rate is the number to attack next, and it is not yet
decomposable offline: `rounds.jsonl` exists for only 4 runs, so 99 observations from three runs is
the whole corpus. Any run that produces clean (non-blackout, non-fall-through) rounds enlarges it.

---

## 58. #739 — one working page certifies the whole UI, so item 13's planned fix is not enough

The third path by which r148 shipped a dead app, and the one that changes an existing entry.

The verifier reported `run_validation PASS 13/13` and `ui_smoke on landing + login PASS` while
the SPA crashed on 12 of 14 pages. `_ui_smoke_pass` explains it in one word: **`any`**. One
passing UI-evidence record satisfies the whole UI requirement, and a FAILING record is never
consulted — six failing `ui_flow` records sit next to two passing `ui_smoke` records and the
verdict is True. Landing and login are the two unauthenticated pages, i.e. the two that did not
crash.

**But the predicate is not even reached.** #671 already measured that the UI-smoke requirement
has never been evaluated: it sits behind `task_suite_exists`, and `tasks/tasks.yaml` exists in
**0 of 144 runs**. That is item 13, whose recorded next step is "enforcing the matrix needs a
live run to validate".

**r148 falsifies that plan.** Switching the matrix on would have changed nothing here — landing
and login passed, so `ui_smoke_pass` is True with or without enforcement, and the app that
crashed on every route still delivers. So item 13's fix is necessary and *insufficient*: the
predicate must stop being existential at the same time, or enforcement buys a green light on the
exact failure that motivates it. Recorded here rather than switched on, because both halves
together are a real gate-tightening and neither can be validated offline.

What landed now is the measurement beside the verdict — `ui_evidence_breadth` in the gate
payload plus a warning when a True verdict sits on top of failing UI records. Same disposition
as #711/#715/#738: says what the verdict rests on, decides nothing.

**Cheapest observation.** Next run: does `#739` fire, and what is the passed/failed split? That
is the input the item 13 decision has always been missing — nobody has ever seen how much of an
app its "UI smoke pass" actually covers, because the number did not exist until now.

---

## 57. #738 — the stale-build detector would have called r148's stale build CLEAN

Chasing #737's root cause: why did the crash survive the whole run? The P0 says it plainly, and
a lane wrote this by hand because nothing in the framework did:

    PRIOR FIX (task_17fc0b5257) DID NOT LAND. The deployed bundle hash + error signature are
    IDENTICAL to before. This means one of: (a) the fix targeted the wrong file, (b) the
    frontend docker image was not rebuilt, (c) Vite build cache served the stale bundle.

So the lane fixed it and the container kept serving the pre-fix bundle. That is precisely what
#715 exists to catch — and **#715 would have reported this build CLEAN**. It compares ROUTE
LITERALS: it asks whether every route the source declares appears in the served bundle. r147's
collapse renamed four routes, so #715 sees it. r148 renamed nothing; a bug fix simply never
reached the container, so `known_routes` is fully present, `_missing715` is empty, and #722
prints *"served build matches the source"* over an app that renders nothing. **A false all-clear
is worse than the silence #722 was built to end.**

Checked before claiming the detector was missing: #715/#722 were committed at 11:54 and 11:51 on
08-14, after r148's 10:44:39 build cutoff and after the run finished at ~11:37. So r148 never had
them, and the checker's three `NOT SEEN` lines for #715 are honest rather than a bug. The gap is
in what #715 measures, not in whether it ran.

#738 adds the other half, mechanically, from the observation the lane had to make by hand: Vite
content-hashes its asset filenames (`index-C3zHFyCT.js`), so if the frontend source moved and the
served asset names did not, the container is serving a build from before the edit. Keyed on the
last commit that TOUCHED `app/frontend`, not on HEAD — most commits in a run are backend or docs
and legitimately leave the bundle alone, so a HEAD key would fire nearly every round. Reports
only, exactly like #715: a stale serve does not mean the app is broken, it means the measurement
is of the wrong build. Extracted as a pure predicate so the decision is testable without a
container; the first round of a run has no prior and can never be stale.

**Cheapest observation.** Next run: does `#738` ever fire, and when it does, does the round that
follows show a different bundle name? Both are one grep. The falsifier to watch for is a fire on
a round where the frontend commit moved for a reason that cannot change the bundle (a comment, a
test file under `app/frontend`) — if that turns out to be common, the key needs narrowing from
the subtree to the built sources. That cannot be settled offline: the delivered tree has no
`dist/`, because it is built inside the container.

---

## 56. #737 — r148 shipped v1.0.0 with a frontend that crashed on every route

**This overturns "delivery is solved".** I said it earlier in this session, on the evidence that
r146/r147/r148 all released v1.0.0 with endpoints and chains green. r148's release is worthless:
its SPA threw `TypeError: (void 0) is not a function` on every authenticated route, and the
framework cut the release anyway, calling the gate clear.

The mechanism, which is the fixable part. #75a refunds a wholesale blank capture, bounded by
`_TRANSIENT_REFUND_CAP` so a genuinely blank app cannot defer forever — correct. Past the cap the
refund branch stops returning, `capture_transient` stays True, and every screen arrives at 0.00.
**A 0.00 can never beat its best-so-far, so `_improved` is False by construction and
`plateau_rounds` climbs once per blackout round.** #138's escape reads that as a flatline:

    11:13:19  10 of 12 screens blank -> refunded (transient 1/3)
    11:14:49  same 10 blank          -> refunded (transient 2/3)
    11:18:16  same 10 blank          -> refunded (transient 3/3)     cap exhausted
    ...five more blackout rounds, each incrementing plateau_rounds...
    11:36:46  deferral RELEASED (escape ... PLATEAU 5 no-improvement rounds - #138 early escape)
    11:36:47  FINAL DELIVERY: gate clear -> cut release v1.0.0

**The blackout was the truest signal in the run, and it was consumed as evidence of stability.**

It was not a capture glitch. The verifier found it independently at 11:22:16 and broadcast
"1 P1 frontend bug filed (JS runtime error on /browse, /signup)". Four P0 tasks were still OPEN
at the cut — "All authenticated UI routes crash: '(void 0) is not a function' — empty #root",
"SPA crashes on ALL routes", "Frontend runtime crash on 12/14 pages", and "P0 REMEDIATION: ..."
created at **11:31:34, five minutes and thirteen seconds before the release**, whose description
reads *"DELIVERY IS BLOCKED BY THIS ONE BUG. Verifier confirmed 6 critical UI flows fail"*.

Fixed: a blackout round neither increments nor resets `plateau_rounds`. Narrow by design —
`total_judgments` and `last_judgment_at` still advance, the round is still judged and remediated,
and the wall-clock and total-judgment escapes still bound the run. It removes a false accelerant;
it does not add a way to hang, and it does not by itself stop a broken app from shipping.

**Corpus.** 8 of 116 runs with a `verdict.json` end with `blank>=2` or half their screens at
0.00: r121, r125, r30, r43 (11 of 12 screens at zero), r49, r60 (11 of 13), r68, r72. **r148 is
not among them** — #500's high-water merge had already erased its blackout from the persisted
record — so 7% is a floor. The log-side probe is thinner (only 2 of the retained `gm_*.log`
files contain a blank refund at all), which is why the fix rests on the mechanism plus r148
rather than on a frequency estimate.

### Two things this does NOT fix, one of which is the user's call

**(a) A wrong claim of mine, corrected here.** I reported that task priority is never persisted —
"13,416 tasks, every one `priority: None`". That was a FIELD-LOCATION error, the exact failure
my own notes warn about: `create_task` stores it at `metadata["priority"]` (service.py:246), and
the corpus reads P2 8502 / P0 3630 / P1 1124 / P3 12. Priority is fine. I dumped the record's
top-level keys, saw `metadata` sitting in the list, and concluded absence without opening it.

**(b) The delivery gate does not look at open bugs at all.** `delivery_gate.py` never reads a
task's status or priority; its five checks are artifacts, code footprint, hub registration,
contract alignment, and the build checklist. Whether it SHOULD is a real decision, and the naive
version is not viable — measured over the corpus:

        gate hard-blocks on any open P0                124 of 148 runs (83%) blocked
        ... narrowed to P0s whose text names a crash    63 of 148 runs (42%) blocked

83% is not a gate, it is a halt. And task hygiene is the reason: r148's open P0s include eleven
stale `Fix breaking change in GET /api/...` left `in_progress`. So "block on an open P0" is out.
The framework's own capture is far better evidence than its task store — it PHOTOGRAPHED the
blank page — which is what makes a blackout-based block the candidate worth considering.

**Cheapest observation, and the decision.** The fix is proven offline against r148's recorded
sequence; no run is needed for it. What needs a decision is narrower and sharper than the P0
question: **should a blackout that persists past the refund cap BLOCK delivery outright?** It
would have stopped r148 shipping a dead app. It can also newly fail runs whose capture — not
app — is broken, and #711r's warning about exactly that class is why this is not being done
unilaterally. A run would then measure the cost: how often a post-cap blackout is the app versus
the capture. Until that is decided, r148's outcome remains reachable: the escape is slower, but
nothing yet refuses to ship a frontend that renders nothing.

---

## 55. #736 — #711 compared a 2-screen mean against a 12-screen one, every time it ever fired

Chasing "does the lane act on the remediation it is handed?" through the artifacts, because that
is the question item 54 left open and it is answerable offline. The route was: per-screen deltas
between rounds → restrict to rounds where `code_state` actually changed → split by whether the
screen was BELOW the bar (i.e. named by remediation) or above it.

    targeted by remediation     up 6   down 14   same 101      moved 17%
    not targeted (control)      up 1   down 11   same  23      moved 34%

Targeted screens moved LESS than untargeted ones, which is the wrong sign, and the three that
never moved at all were `browse_home`, `movies`, `new_and_popular` — the most reachable pages in
the app, not the unphotographable interaction states of item 40.

**All of that is an artefact and is withdrawn.** The captures tell the real story: 66 screenshots
in r148 reduce to 15 distinct images, and from 11:13:19 the live scores of ten screens read
`0.00` for the remaining nine rounds. They are BLANK CAPTURES, and the framework already handles
them correctly — it names them, classifies them transient, and refunds the attempt:

    [blank capture: browse_by_languages, browse_home, games, genre_category, movies, my_list,
     new_and_popular, player, shows, title_detail] — blank capture, attempt refunded (transient 1/3)

Both averages filter `blank is True`, so nothing is polluted: `blocking_average_live` = 0.4250 is
exactly `(landing 0.45 + login 0.40) / 2`, the only two screens that captured. Correct arithmetic.

**What is NOT correct is #711, which I added earlier this session.** Its only condition is a
`>= 0.05` gap between the gating average and the live one, with no check that the two cover the
same screens — and a blank capture makes them cover wildly different populations. So at 11:13:19
and again at 11:14:49 it announced

    #711 the gating average has left the app behind: blocking_average 0.6190 vs
    blocking_average_live 0.4250 (gap 0.1940)

which is a 12-screen mean minus a 2-screen mean: composition, not divergence. Across every log in
the corpus **#711 has fired 2 times and 2 of 2 are this artefact — a 100% false-positive rate over
its entire firing history**, on a round the framework had already labelled and refunded.

Fixed by restricting the gating mean to the screens the capture actually scored, with no tuned
constant (#656's disposition). A real divergence still fires: #713's r147 case is four routes
falling THROUGH to the landing page, which are captured and scored, so they stay in both
populations — pinned as a negative control in the tests, alongside the case where most screens
blank AND the survivors genuinely regressed.

**A second defect fell out of it.** #711r had measured the sentence "A release authorised on the
former ships the latter" false — the release path reads the RETURNED dict, the current capture,
not the persisted high-water number — and struck it through in the comment. But the warning kept
PRINTING it verbatim, so every reader of a real run log was still told the withdrawn claim, for
two fixes. It is now out of the emitted text, replaced by the half #711r left standing plus the
correction. The test that guarded it asserted the sentence was PRESENT; that assertion was
certifying a withdrawn claim, which is precisely #726's trap, and the first draft of #736's own
test file repeated it. Both now check for its ABSENCE.

**Cheapest observation.** No run needed for the fix — it is proven against r148's recorded
numbers. What a run WOULD settle is the question this item started from and did not answer,
because the instrument was broken: with the blank rounds excluded, does remediation move the
screens it names? Every delta measured above came from a blackout, so the honest state is that
**the effectiveness of visual remediation has never actually been measured**, and item 54's
"does the lane act on what it holds" is still open on both counts.

---

## 54. RETRACTED — the frontend HAD the parameters. It did not use them.

The user asked the obvious question: the agent declares an endpoint, testing and consumption read
the declaration, so where is the problem? Following it retires the diagnosis behind #729-#735.

**The frontend fetched the full record, after the backend wrote it, and ignored what it said.**

    11:01:18   backend registers /api/titles with schema.query = {kind, limit}
    11:01:56   frontend calls registryhub_get_endpoint on it — 38 seconds later
    11:04:54   frontend's last such call; 28 in total for this one path (r147: 24)

`registryhub_list_endpoints` does strip the schema (#303, "~85% of each row"), but that is not a
wall: full detail is one call away and the frontend made it, repeatedly. It read the raw record,
so the `query` vs `request` key name never mattered to it. Then it wrote six pages that fetch
bare `/api/titles`.

**So three claims I built on are false:**

    "the contract does not declare query params"   r148 declared them, under `query`
    "the frontend has no contract basis"           it fetched that basis 28 times
    "the key mismatch blocks the frontend"         the frontend reads the record, not our keys

**What the key mismatch DID block is narrower and worth keeping.** #708b exists to say, in the
identical-content report, "this endpoint already accepts these filters and the pages pass none".
It reads `schema.request`, so r148's `query` made it silent — the one mechanism that pushes this
fact AT the lane instead of waiting to be queried. #730's fold restores that. **Its value is not
recovering lost information; it is letting the only report that volunteers the information see
it.** I described it as the former, and that was wrong.

**The real problem is a different class.** Not a plumbing gap — the lane held the parameters and
did not use them. That belongs with #664's finding (30 prompt mentions plus 76 escalations moved
nothing) rather than with anything a declaration or a published vocabulary can fix. #727's
adoption probe is the nearest live instrument: it measures whether a lane acts on something it is
told, which is the same question.

**Cheapest observation.** Next run, with #730 folding: does #708b fire on the catalogue group,
and if it does, does the lane then pass a filter? The first half is plumbing and should now work.
The second half is the actual open question, and no amount of declaring answers it.

---

## 53. #735 — "can it declare freely now?" The honest answer was no, until the caller was told

The user asked whether the agent can now declare freely instead of us fixing one possible problem
per run. Tracing it: **no**, and the gap was one step past where I had stopped.

    #731's warning            -> the run LOG, which a human reads afterwards
    register_endpoint returns -> the stored record, which says success

So an invented key was still dropped **silently from the caller's point of view**. Publishing the
vocabulary (#732/#733) removes the NEED to guess, but a lane that invents anyway learns nothing,
and the cadence stays "run once, a human reads the log, fix one word" — exactly what was objected
to.

**Fixed: #735.** The return now carries `_unread_schema_keys` and a `_note` naming what the
framework does read. Not a rejection: the registration stands and the key is KEPT, because #730's
`query` proved an invented word can be the better one. What changes is WHEN the caller finds out —
the same tool call instead of the next run.

**The accurate scope, which is narrower than the question.** This is not "declare anything and it
works" — that needs the framework to map arbitrary words semantically, which is the thing that
cannot be built. It is "declare anything and find out immediately what actually takes effect."
The loop closes inside a turn; it does not disappear.

**Two defects in the first version, both caught by its own tests:**

  * `for k in (schema or {})` iterated a STRING's characters when schema was `"junk"` — though
    the real contract turned out to be that `register_endpoint` rejects a non-dict schema
    upstream, so my degenerate case was asserting the wrong thing too;
  * the block sat ABOVE `_endpoints.update(...)`, so the note went into the stored contract and
    into the `endpoint_registered` event. Framework chatter has no place in a record other agents
    read. Moved below the write.

**Cheapest observation.** Next run: `_unread_schema_keys` in a tool result means a lane invented
a key AND was told within the turn. Whether it then re-registers under the published name is the
real measure of whether this closes the loop — and it is visible in the same log.

---

## 52. Auditing my own guards: which are proven, and which only look it

Two guards this session shipped able to report a clean pass while blind — #716 let #727's dead
pattern through, and #734's first sweep skipped every tool name containing a digit, so a planted
violation went unseen. Twice is a pattern, so rather than wait for a third I audited all six
guards built here for whether their non-vacuity is DEMONSTRATED or assumed:

    guard   proven how
    #716    FIRED twice on real changes (caught #713's ambiguous selector; was itself taught by
            #727's dead pattern, which it had passed)
    #719    FIRED on #721 and #724 — code carrying a number the document did not
    #717    never fired, but tests BOTH directions: a log with `[main-exit]` and one without
    #726    planted-violation control, written with it
    #734    planted-violation control, added after the control caught it vacuous
    #720    never fired, one-way assertion only  ← the only unproven one

**"No control" is not the same as "vacuous".** A guard that has actually fired on a real change is
better evidenced than one with a synthetic control, and #717's two-direction test is a control in
substance. So the audit's output is one addition, not six: #720 now empties its registry and
requires every shared key to be reported, which fails if the sweep sees nothing.

**Cheapest observation.** None — this is settled by reading. Recorded because the instinct on
finding two blind guards is to add controls everywhere, and four of the six did not need one; the
work was in telling which.

---

## 51. The same shape twice, and only one of them should be folded

#730 folded `schema.query` into `schema.request` because the lane declared query parameters under
its own word and nothing read them. Sweeping for the same shape found a second instance
immediately — and it must NOT be folded, which is the part worth recording.

    key              declared           read by anything   fold?
    schema.query     r148 x3            no                 YES — #730
    schema.headers   r148 x6            no                 NO

`schema.headers` is `{"X-Profile-Id": "integer?"}` on six endpoints, and three facts from the
code say leave it alone:

  * the `?` marks it OPTIONAL;
  * the backend has a correct default — `_resolve_profile_id`'s own docstring: "(a) If
    X-Profile-Id header is set AND belongs to this user → use it", falling back to the caller's
    first profile otherwise;
  * `chain_executor` already refuses to take `Authorization` from a step, on the stated grounds
    that "a step-supplied one would quietly change actor and defeat the ownership probes
    (#591/#663)". **`X-Profile-Id` is also an identity.** Auto-injecting it would have the
    framework decide who the caller is on the probe's behalf.

So the two cases differ on what the data DOES: **query parameters are inert and folding one back
only makes a filter visible; a header selects an actor.** Same symptom, opposite disposition —
and the default reaction to "declared but unread" is to wire it up, which here would be wrong.

**A trend worth noting under it.** Both keys appear in r148 and in neither earlier run. The lane
is getting BETTER at declaring its contract, and the framework's reading surface has not kept up.
#730 closed one gap; the other is closed deliberately.

**Looked for a third instance and found the MECHANISM instead.** `registryhub_tables`,
`registryhub_ui_pages` and `registryhub_consumers` have **zero** declared-but-unread fields — not
luck. `register_endpoint`'s tool PARAMETERS pin every sibling by name and type
(`method`/`path`/`provider`/`status`), while `schema` is declared as a bare `{"type": "object"}`
with no `properties` and no `required`. **Synonyms can only accumulate where the vocabulary is
open, and `schema` is the only open field.** That narrows the earlier framing: it is not that the
framework's reading surface lags generally, it is that one free dict has no agreed sub-key
vocabulary, so each reasonable invention costs a run to discover.

Three ways out: pin `schema.properties` and reject unknowns; keep folding case by case (#730);
or a standing check. Rejecting is wrong on this evidence — `query` is a BETTER name than
`request` for query parameters, and refusal discards good information to enforce a vocabulary.

**Built: #731, the soft form**, which needs no decision because it changes no behaviour: on
registration, a schema carrying sub-keys nothing reads is logged, kept, and the message points at
where a fold would go. The known set is exactly the six sub-keys r146/r147/r148 actually use, so
**all three historical runs produce zero warnings** — a new signal that fires on old data is noise
on arrival. The signal is reserved for the next synonym, which is the moment the information is
cheapest to act on.

**THE USER RETIRED BOTH #730 AND #731 AS THE ANSWER, and was right.** An agent inventing new
endpoints and new words is NORMAL. Discovering each invention one run at a time does not
converge, and synonym matching cannot work at all: today it is `query`; a completely unrelated app
will produce `params`, `queryParams`, `filters`. #730 is a hardcoded fold for one word and #731's
known set was induced from three netflix runs — both are corpus-shaped patches on a structural
gap.

**The gap: the framework never published the slots it reads, at the point of the call.** The tool
declared

    "schema": {"type": "object"}

with the description "Register/update RegistryHub endpoint and schema." The model was asked for
"a schema" and had to GUESS the key names. r148 guessed `query` — a better word than the one every
consumer reads — and the declaration was stored and invisible for a run.

**Fixed: #732.** `registryhub_register_endpoint`'s PARAMETERS now name `request`, `response`,
`response_key` and `auth_required` with descriptions, including what `request` means for a GET
(the query parameters, `?` for optional) and what omitting it costs. `tooling.py` states that
"Every tool advertises PARAMETERS to the model … the same text the model was shown", so this lands
exactly where the guessing happened.

**Why this is app-independent, which the previous two were not.** The four slots belong to the
FRAMEWORK's contract, not to any app's domain — so the declaration travels with the tool to every
future generation, netflix or otherwise. No corpus, no synonym table, no per-run discovery.

**Invention stays legal.** No `additionalProperties: false`: the model may still coin a key, and
the description says extra keys are stored faithfully but acted on by nothing. What changes is
that it no longer HAS to guess. #731 keeps reporting anything outside the published set, and its
known set now DERIVES from #732's declaration (plus `query` and `headers`, both already
reckoned with) rather than from words one corpus used.

**Swept for the same shape and found a SECOND case with a worse history.** 16 tool parameters
across 13 tools are declared as a bare `{"type": "object"}`, 9 with no description at all. Most
are genuinely free metadata, so opacity is fine — the discriminator is whether the framework
READS particular sub-keys. `codehub_record_check.evidence` does, and its description said
**"Free-form mapping"**, actively inviting the divergence:

    what it reads   evidence.summary, evidence.execution_mode, and a nested evidence.metadata
                    whose `check` and `flow` decide UI-flow coverage and the retry decision
    what it said    "Free-form mapping with check output, links to logs, step counts, etc."

**And it has already cost an outage.** #193's own comment: writers "often nest the check kind
under `evidence['metadata']` — while every reader reads `metadata.get('check')`. **ui_flow records
were therefore INVISIBLE** to `_has_passing_ui_evidence` / `flow_coverage` / the retry decider /
remediation-task creation, and **the UI gates cleared only via the functionally_validated
waiver**." Patched by normalising both spellings — the same repair #730 made for `query`, a year
earlier and with heavier consequences.

**Fixed: #733**, publishing the read slots in the description while keeping the free-form
allowance. Two instances now share one cause and one cure: the framework reads specific keys of an
object it advertised as unstructured.

**Made into a rule rather than waiting for a third instance: #734.** Both cases share one
invariant — *a parameter whose description CLAIMS free-form must not be one the framework reads
keys of*. A guard sweeps every object-typed tool parameter and fails on any that advertises
freedom while naming no slots. Zero violations today, which is the point: it is satisfied now and
fires on the next one, without needing a corpus or a synonym table.

**The guard was vacuous when first written, and I only found that because I ran the control after
building it.** Its sweep matched tool names with `[a-z_]+`, so `browser_check_a11y` and
`browser_a11y_tree` — real tools — were invisible, and the planted violation went unseen while
the guard reported a clean pass. Fixed to `[a-z0-9_]+`, with a test for the blind spot and a
permanent non-vacuity control. **A guard whose non-vacuity is assumed is worth less than none**,
and this is the second time this session that writing one produced a false clean (the first was
#716 passing #727's dead pattern).

**Stated limits.** "Names a slot" is detected by a backtick, a proxy rather than a parse; and the
rule catches a CLAIM of freedom, not opacity — a bare `{"type": "object"}` with no description is
not flagged, because most of the 16 such parameters are genuinely free metadata and flagging all
of them would cry wolf on correct decisions.

**The gap is ONE cell, and splitting the counts shows it.** Classifying every endpoint by surface
(framework-fixed `/auth`, `/health`, `/api/v1/*` versus lane business `/api/*`) and by method:

                        r146      r147      r148
    lane   POST        4/4       4/4       4/4     never faltered
    lane   GET         3/11      0/11      0/11    the only gap, and it decayed
    fixed  POST        3/8       5/8       2/8
    fixed  GET         0/5       1/6       0/5

Three things fall out. **The lane has never failed at body-shaped declarations** — 4/4 in every
run — so this was never "the lane cannot declare", it is that GET query parameters were never
asked for. **r146's three GET declarations are business endpoints** (`/api/titles`, `trending`,
`search`), not framework ones, so the lane HAS done it and then stopped, which is #729's
convergence-toward-the-instruction reading confirmed from the other side.

And the third corrects an assumption of mine: **the framework's own fixed surface is not fully
declared either** (POST 3/8, 5/8, 2/8). I had been treating it as the always-complete control
group. Its GETs are `/health` and `/api/v1/tenants` — endpoints with no query parameters — so
empty is CORRECT there and this is not a defect; what is wrong is only my use of it as a
reference point.

**So the probe is now scoped to business GETs.** A denominator including the fixed surface
measures the wrong thing, since those are correctly empty. `tools/check_pending_experiments.sh`
reads 3/11, 0/11, 0/11 on the three runs, matching the manual count.

**Cheapest observation.** Next run: the business-GET ratio moving off 0/11 means the published
slots landed. Also check evidence carrying `metadata.check` rather than a top-level `kind`. If a
NEW synonym appears anyway, #731 names it and #735 tells the caller within the turn — and that
would mean publishing the vocabulary is not sufficient either, which is worth knowing before
anyone builds a third patch.

**Cheapest observation.** None; settled by reading. What a run adds is whether the lane keeps
inventing keys — a third synonym would change the calculus from "fold the one that matters" to
"the read surface needs a general answer".

---

## 50. #728 — pages calling each other's endpoints, and why every audit passed

Chasing a line in r148's #700 report that I had noticed and not followed: `/browse/genre/:genreId`
and `/my-list` both fetching only `/api/my-list`.

**It is a real shipped bug.** `GenreCategoryPage.jsx:27` fetches `/api/my-list` — click any genre,
see your watchlist — while `GET /api/genres/{id}/titles` is registered, implemented, and called by
nothing.

**Why nothing caught it is the useful part.** The page also DECLARED
`apis_used: ['GET /api/my-list']`. Code and declaration agree, so every consistency audit passes;
they agree on the wrong thing. Only #700 noticed, and it reported the symptom ("these routes
render identical content") rather than the cause.

**It is a rotation, not a slip:**

    r146   genre_category -> /api/my-list,  my_list -> /api/titles,  title_detail -> /api/genres
    r147   none
    r148   genre_category -> /api/my-list,  title_detail -> /api/genres

Each page holding the next one's endpoint. r147 having zero, on the same framework and prompt,
is what makes it avoidable rather than inherent — and is the negative control a detector needs.

**Fixed: #728**, report-only beside #700. The criterion is purely structural and needs no product
standard, which is why it is wired rather than filed for a decision: a page whose declared APIs
share NO path word with its own route, while an implemented endpoint DOES, is wrong under any
reading.

**Deliberately narrower than the neighbouring question.** 12 of 16 implemented business endpoints
are declared by no page at all in r146 and r148 (2 in r147) — `GET /api/search`,
`GET /api/titles/trending`, `GET /api/continue-watching`, `DELETE /api/my-list/{id}` and more. The
backend implements them, the chains pass on them (32/32 in r148), and no UI reaches them. Whether
an endpoint without a UI caller is a defect is a judgement about product scope, and it is the
user's — recorded here, not enforced.

**Two defects in the detector, both caught by its own output before it shipped**, and both would
have made it worse than nothing: without stemming, `genre` and `genres` were different words and
it reported a clean ZERO on the run whose bug motivated it; with alphabetical ranking, it
suggested `GET /api/genres/{id}/titles` over `GET /api/titles/{id}` for `/title/:id`, pointing at
the wrong endpoint. Now ranked by token overlap, and back-tested to reproduce 3 / 0 / 2 exactly.

**CORRECTED, and the correction demotes this item.** I wrote that these crossings are the cause
of r148's identical-content groups. They are the cause of ONE. r148 has three groups and #728
explains only the two-route one:

    /browse/genre/:genreId + /my-list                          -> #728 (crossed endpoint)
    /browse, /browse/languages, /games, /movies, /new, /shows  -> NOT #728
    /browse, /games, /movies, /new, /shows                     -> NOT #728

`/movies` fetching `GET /api/titles` is not a crossing — that IS its endpoint. It shares content
with `/games` and `/shows` because none of them passes a filter. #728 correctly stays silent
there: no `/api/movies` exists to suggest, so it does not invent one.

Counting both runs that carry a #700 report at all (the detector only began reporting this
session, so the sample is two):

    r147   2 identical-content groups,  0 crossings
    r148   3 identical-content groups,  2 crossings

**Five groups, of which #728 explains one.** r147's row is the decisive one: two groups with zero
crossings means the dominant cause is not "calls the wrong endpoint" but "calls the right endpoint
without a filter" — item 32's territory, itself blocked a step earlier on the contract no longer
declaring `request` query params (empty in r147/r148, populated in r146).

**So the two are orthogonal and the larger one is untouched.** #728 is worth keeping — it catches
a real shipped bug and r147's zero is a clean negative control — but anyone who fixes it expecting
the "half the pages look identical" symptom to go will find the six-route group exactly where it
was. That misreading is why this is recorded rather than quietly corrected.

**Cheapest observation.** The next run prints `#728 <page> declares … while <endpoint> is
implemented and used by nothing` beside #700's group. #700 firing WITHOUT #728 is the expected
majority case, not a detector failure.

---

## 49. 8 of 20 reference screens are states the gate cannot reach at all

The user proposed that the frontend lane — the agent that implemented the page — should declare
which route to visit, which reference to compare against, and WHAT ACTION to perform to reach the
state. Measuring the gap that proposal closes, on r148:

    reference screens (images only)        20
      with a matching ui_page              12
      with none                             8

    account_menu   browse_home_rows   card_hover_preview   card_preview
    player_controls   rate_dialog   shows_genres_menu   title_episodes

**All eight are interaction states** — an opened menu, a scrolled view, a hovered card, a modal,
player chrome. The capture only navigates, so it reaches none of them and scores the base page
against a reference showing the overlay. `card_hover_preview` is the measured case: BLOCKING in 36
of 54 appearances, maximum 0.40, zero passes against a 0.65 bar (item 40).

**So "every declared reference comparison passes" is currently unreachable** — not because the
lane builds badly, but because 8 of 20 states have no path in. That reframes item 40 from "what
do we do about screens that can never pass" to "they were never unreachable in principle, only
unreached by a capture that cannot act".

**Why the proposal is sound, and this is the part worth recording.** Letting the implementer
describe the test sounds like #566z (a lane authoring its own unsatisfiable expectation). It is
not, and the difference is ownership of the STANDARD: the gate scores against `screen["path"]`,
the orchestrator-side ORIGINAL outside the lane's workspace; `design/references/` is only a
lane-visible copy. The lane can say how to REACH a state; it cannot alter what the state is
compared to. A wrong action produces a capture that does not match the fixed reference and scores
badly, so there is no way to win by lying.

**Two of the three parts already exist.** `map_reference_screens` already takes the lane's
registered `ui_pages` as its most authoritative layer (#416), and the reference binds by
normalised filename (`browse_home_page` ↔ `browse_home.jpg`). Only the ACTION is missing, and
`goto` (visual_fidelity.py:1770) and `screenshot` (:1867) sandwich a live Playwright page.

**Where the declaration would live — both candidates measured, and neither is ready.**

    carrier                      dedicated tool   gates/advances   lane fill rate
    ui_pages                     kickoff_declare  yes              r146 1, r147 14, r148 4
                                 _ui_page                          (of 13 / 27 / 16 — the rest
                                                                    written by orchestrator)
    reference_image_manifest     none             no — AUX key     2 of 146 runs

`reference_image_manifest` looked ideal: the semantics fit exactly, the framework already refuses
a manifest whose paths were not actually opened with `view_image` (base.py:601, so it cannot be
authored from memory), and its list-of-dicts form ALREADY parses `{"path": ..., ...}` and ignores
unknown keys — a `reach` field needs no parser change. But it is an AUX kickoff key, and
`has_aux_content`'s own docstring says these have "NO dedicated kickoff_declare_* tool" and are
"NOT buildable substance (don't advance the phase)". **The lane not writing it is not decay; it
was never required to.** 2 of 146 runs is what fully-optional looks like.

`ui_pages` has the tool and the gate, and I recommended it on that basis — then checked
`created_by` and found the lane writes 4 of r148's 16 records, 14 of r147's 27, and 1 of r146's
13. **The table is mostly orchestrator-populated and the lane's share swings 1 → 14 → 4.**

**So the blocker is not which carrier to choose.** Neither is a place the lane reliably fills, and
#664 already measured what does not fix that: the verifier prompt names its registry 30 times and
an escalation fires 76 times, and the behaviour does not move. Item 36 counted 137 of 290 tools
never called. A `reach` field on either carrier becomes the 138th mechanism that exists and is not
used unless declaring it is **required and visible when missing**.

**Open, and the user's to decide — now with the coupling visible.** What happens to a reference
screen the lane does NOT declare a path for:

  * **advisory** retires item 40's permanent blocker, but at the measured fill rates it would
    silently drop all 8 interaction screens in the first run — hiding the problem, not fixing it;
  * **blocking** keeps the bar, but wedges every run on those 8 until the lane actually declares.

Both are unsafe while declaration is optional, which makes "make declaring reliable" the
prerequisite rather than a follow-up.

**Cheapest observation — BUILT as #727, declaration only.** `kickoff_declare_ui_page` now accepts
two optional fields, flat per the tool's own "no nested JSON" convention:

    reference   basename of the reference image this state corresponds to, when it differs
                from the page id
    reach       ordered "verb:selector" steps performed after navigating and before the
                screenshot — hover / click / scroll / wait, capped at 12

Neither is required, nothing consumes `reach` yet, and no gate behaviour moves — a test asserts
`visual_fidelity.py` does not read it. That is the point: the next run measures ADOPTION (how many
of the 8 interaction screens get a declaration) without risking either failure mode above.

**The probe was void as first written, and catching that is the point of writing it down.** A
field the lane has never been told about cannot be adopted, so it would have measured 0 — and my
reading rule said 0 means "enforcement is the prerequisite". That inference does not hold: #664's
lesson (wording does not move behaviour) was earned on an instruction repeated 30 times, and
cannot be applied to one never written. Checked before assuming: `reach` appeared 11 times in the
frontend prompt and every one was the English word ("reachable", "a user reaches"). The prompt now
introduces the field as rule 5c, with the measurement that motivates it, the verbs, and the safety
property — that a wrong `reach` scores WORSE, so it is not a way to choose your own number.

Read the next run as: **8 declared** means the lane does it when asked and the consuming half is
safe to build; **0-2 declared** now means what I originally claimed, because the instruction
exists — this would be the 138th optional mechanism and enforcement, not wording, is the
prerequisite.

**And the probe's own checker line was wrong too, in the same shape, one turn later.** It grepped
for `"reach"` WITH quotes. #725 renders a list argument as its shape, so a run writes
`reach=[1]` — no quotes — and the quoted form matched only the dict key in `hub_tools.py`.
**#716 passed it**, because #716 asks whether a pattern exists in SOURCE, which is a different
question from whether it matches a LOGGED line. Corrected to `reach=`, registered in #716's
`RUNTIME_BUILT` table with its construction site (`tooling.py`'s `f"{_k}={...}"`), and #716 now
also refuses any pattern that is a bare quoted identifier — the specific spelling that caused it.

Three instances of one mistake in three consecutive turns: a probe whose target did not exist
yet (the prompt never mentioned `reach`), a reading rule resting on that, and a pattern matching
a source literal instead of the log. Each was caught before a run, which is the only reason they
cost nothing — the same three after a run would have cost a run each.

**And the obvious follow-up: did the same shape contaminate the OLDER probes, whose readings this
session already acted on?** All three mistakes were in patterns added this session; the 23 older
ones had never been checked this way. Of those, 10 match a real r145-r148 log and 13 have never
matched — and "never matched" is exactly the ambiguity that hid #713's dead pattern.

Checking all 13 by whether their fragments can be produced at all (folding adjacent string
literals, since a pattern split across two f-strings can never appear): **21 of 23 are sound**,
and the only two that cannot be found in source are `] business_chain:` and `reach=` — the two
already registered as runtime-constructed with their construction sites. **So no older probe has
the #727 shape, and this session's readings of r145-r148 stand.**

**Stated at its real strength, which is weaker than the sample check.** "Fragments present in
folded source" shows a pattern is not obviously unproducible; it does not prove the fragments
appear together on one line. The sample-line table is the stronger instrument and covers this
session's probes; extending it backwards is worth doing when an older probe's NOT SEEN is about
to carry an argument.

**Corrected while measuring:** my first count said 9 of 21. `spec.md` is markdown, not a screen —
I listed the directory without filtering to images. It is scored 0 times, so the framework
excludes it correctly and the "incidental finding" was mine, not the framework's.

---

## 48. A retraction has two failure modes, and I hit both

#611 improved my fix instead of obstructing it, which prompted a self-audit: did I weaken any
guard this session? The sweep — every test MODIFIED rather than created, and every assertion
deleted — found no weakening, but it found the two ways a retraction goes wrong, one of each.

**Mode 1: the retraction deletes evidence that outlives the claim.** #712's rewrite removed 20
assertions. Nineteen asserted the withdrawn claim and went correctly. One did not:

    assert all(b >= a for a, b in zip(R146_GATING, R146_GATING[1:]))

r146's persisted gating series IS monotonically non-decreasing, that was never withdrawn, and
**#711 still rests on it**. What survived asserted only that the PHRASE "monotonically
non-decreasing" appears in a comment — a test of my prose. Restored under #711 on all three runs'
real series, with the contrast that makes it a finding: the persisted series never falls in any
run, the live series falls in every one.

**Mode 2: the retraction leaves tests certifying the withdrawn claim.** The mirror, found by
looking for it. #711's consequence was withdrawn by STRIKING THROUGH rather than deleting, so the
sentences remain in the source — and two tests still asserted their presence:

    assert "A release authorised on the former ships the latter" in ...
    assert "r146 DELIVERED at gating 0.67" in b

Both passed, both were green, and both now read as certifying a claim I had withdrawn one commit
earlier. Renamed and rewritten to assert the presence AND the strike-through, so the suite states
"this was said and then withdrawn" rather than "this is the finding".

**The rule the two modes share.** Striking through is the right way to retract — the reasoning
stays visible — but it leaves the withdrawn text greppable, so any test anchored on that text
silently changes meaning. A retraction is not finished when the claim is marked; it is finished
when every assertion about the claim has been re-pointed at either the surviving fact or the
retraction itself.

**Swept, and there was a third instance.** Applying the rule to EVERY retraction rather than the
two that produced it: six struck-through claims in the production tree, two of them referenced
from tests. One reference asserts the retraction (correct). The other is not an assertion at all
— it is the module DOCSTRING of `test_duplicate_route_content_615.py`, stating #708's retired
`kind='standard'` objection as current reasoning, in a file that predates the finding. Nothing
greps a docstring, so it outlived the retraction by a day in the place a reader is most likely to
take it as established. Struck through with the measurement that killed it, and pinned by a test.

**So the rule generalises past assertions.** A claim is retracted only when every COPY of it —
comment, docstring, test name, checker note — points at the surviving fact or the retraction.
Copies in prose are the easiest to miss precisely because no tooling looks at them.

**And past retractions, to any measurement that was overturned.** Sweeping test docstrings for
the claims this session disproved found a FOURTH instance, and the worst of them:
`test_gate_sees_every_p0_630.py` opened with "Blast radius 4 of 21, the deferral is exactly what
'bug-free' asks for". Item 22's sweep records `4 of 21` as **the one claim in it that does not
reproduce** — re-derivation gives 22 of 27 at run end, 20 of 27 at first release, roughly five
times higher. That figure is not decoration: it is the justification for DEFERRING a release.

It had been sitting in a test docstring since before this session, in a file whose tests all pass,
which is the most convincing place a wrong number can live. Struck through with the re-derivation
AND with the re-derivation's own limits (only 15% of these bugs carry `triage_history`, so the
probe over-counts), and pinned by a test.

**The pattern across all four.** Every instance was prose, none was an assertion, and all four
were green the whole time. The tooling this session added — #716's pattern check, #719's
cross-reference guard — reads code and the document. Nothing read the sentences in between.

**Fixed: #726**, which now does. It holds a registry of claims this session measured false and
requires any surviving copy — in `llm_generator/` or in `tests/` — to carry a correction marker
within 900 characters:

    kind='standard'                                     ~~ / RETIRED / STALE / seed_dataset
    Blast radius 4 of 21                                ~~ / does NOT reproduce
    A release authorised on the former ships the latter ~~ / RETRACTION / is WRONG
    a single lucky pass never triggers a release        TRUE as written / #712r / ~~

A second test requires each claim to still EXIST somewhere, so an entry cannot be satisfied by
deleting the reasoning — which is the thing item 48 argues against.

**Its limits, stated rather than discovered later.** It cannot judge a NEW claim; it only keeps
settled ones settled, and every entry is added by hand after a measurement overturns something.
That is the honest ceiling of a text check.

**Four is tested, not provisional.** The session produced twelve retraction commits, so a
four-entry registry looks unfinished. Six more overturned phrasings were run through the same
sweep — "accelerates rather than tapering", "160 attempts", "did not deliver", "the capture list
is stale", "routes did not resolve", "clear the checker" — and produced **zero** genuine unmarked
copies. Four covers what actually exists in the tree.

**The trial also found the guard's real failure mode, which is not false negatives.** Both
apparent hits were false alarms caused by a marker list narrower than the correction's own
wording: one claim sits in a two-column table whose right column IS the correction, the other is
#718's comment quoting #713's sentence in order to refute it — the quotation trap that has caught
four assertions in this session. A guard that cries wolf trains a reader to ignore it, so the
rule is now written into the file: **when adding an entry, take the markers FROM the correction
that is already there, never invent them in advance.**

**Verified non-vacuous.** A guard over prose is easy to write so that it can never fire, so the
control is permanent: planting an unmarked copy in a scratch directory must make the sweep name
it (`probe.py`), and striking the same copy through must silence it. Both are tests.

**Cheapest observation.** None; this is settled by reading. Recorded because the next retraction
in this file will have the same three exits and none is obvious from inside one.

---

## 47. A hard limit on offline analysis: tool ARGUMENTS are recorded nowhere

Twice this session I asked "what did the lane actually send to this tool?" — once for
`register_seed_data` (item 33's territory) and once for `registryhub_register_endpoint` (item
32's contract mismatch). Both times I answered it from a grep and both times the answer was
wrong, because the thing I was grepping is prose. Rather than record that as a personal lapse a
third time, here is the sweep of every artifact a run leaves:

    the run log            tool NAMES in prose, AND — corrected below — up to three SCALAR
                           arguments per call. Structured ones: NO.
    [tool-io] lines        `read returned 53,787 chars (~13k tokens)` — return SIZE only. 53
                           lines in r148. Arguments: NO.
    progress_events.jsonl  4 events in r148: generation_start, phase_start, phase_complete,
                           generation_complete. Arguments: NO.
    .memory/*.jsonl        19 records in r148, zero containing `args` or `arguments`.
    the hub stores         the RESULT of a call, never its input.

**CORRECTED one commit later, and the correction is the fix.** "Recorded nowhere" was wrong. The
dispatch DOES log arguments — `_log_tool_call` builds up to three `name=value` pairs — but its
filter read:

    elif not isinstance(_v, (str, int, float, bool)):
        continue

so every dict and list was skipped in silence. Both values I needed were dicts (`schema`,
`sample_excerpt`), which is why the log showed only names. I had read the absence in the artifacts
without reading the code that writes them, and concluded a limit where there was a filter.

**Fixed: #725** — but not the way I first wrote it, and #611 is why. My first version logged a
truncated `repr`, which broke `test_a_non_scalar_value_is_skipped_not_dumped` — a test that
exists to stop a deep structure being dumped into the line, and it was right to fire. The shape
was all I ever needed, so #725 renders KEYS ONLY, one level deep, eight keys max:

    schema={"request": {"kind": "string?", "genre": "string?"}, "response_key": "items"}
        →  schema={request:{…},response_key}

    sample_excerpt=[{...}, {...}, {...}]   →   sample_excerpt=[3]

No value ever leaves the argument, #611's line-length discipline holds, and "were the query
params sent at all" is answerable — which is exactly what items 32 and 33 need.

**So the original claim, narrowed to what is true:** Every question of
that shape is run-dependent by construction, not by my failing to look hard enough — and the
`#NNN` counts that look like call counts are mention counts, which is item 36's trap wearing a
different hat.

This bounds several open items. Item 32's contract mismatch (the store has query params in r146
and none in r147/r148 while all three backends filter) cannot have its origin established from
disk. Item 33's `register_seed_data` question is the same shape. Both need instrumentation, not
more grepping.

**Cheapest observation.** One line at the tool-dispatch boundary logging `name(args)` at DEBUG,
capped. It would have answered both questions and costs nothing when the level is off. Whether
that is worth the log volume is a judgement about run cost, not a measurement — which is why it
is recorded here rather than added.

---

## 46. #724 — and the question that dissolves #706 rather than answering it

Following item 43 out: if `main` is a divergent framework-only copy, does anything depend on it?

**Nothing that ships does.** Every `release-v1.0.0` across r146, r147 and r148 is an ancestor of
`integration` and of NEITHER `main`. No code reads the `main` branch's content by name. So the
promotion has never affected a delivered artifact, in any run, and its two failures (#706's wrong
hook, #721's merge conflict) cost the product nothing.

**What it does affect is a promise.** `promote_integration_to_main`'s own docstring says "`main`
becomes the verifier-blessed reference … teams that want 'only ship verified' can deploy from
`main`". Today `main` points at a framework skeleton with no lane work in it — precisely the tree
nobody should deploy. The promise is not merely unkept; it points the wrong way.

**Fixed: #724**, the smaller sibling. `create_branch_at`'s docstring said release branches "must
capture a snapshot of `main`" — measurably false, and it recommends the worst available tree to
whoever adds the next caller. Corrected, with the old sentence kept as an attributed quotation.
Both existing call sites pass `start_point` explicitly, so the misleading `="main"` default is
inert today; a test now fails if a third caller starts relying on it.

**The decision, which is not mine.** Two coherent options, and the evidence for both is now in:

  * **move the ref** (`git branch -f main integration`) — keeps the promise, no conflicts, loses
    nothing measurable, and is safe only while #691b keeps recovering the MCP subtree (r146,
    pre-#691b, is the run where it would have discarded three real files);
  * **withdraw the promise** — if nobody deploys from `main`, then `main` is fork residue and
    #706, #706b and #721 can all be removed rather than repaired.

**Cheapest observation.** Not a measurement — the repository cannot see whether an external
consumer deploys from `main`. There is no code consumer; that does not rule out a human one.

---

## 45. The shape, swept — and why #707 and #711 are left alone

Four times this session a detector's silence turned out to mean three different things (#691's
silent skip, #696's invisible load failure, #712's dead branch, #715's two-warnings-no-third).
Rather than wait for the fifth, sweeping every detector added in #691-#722 for a warning path
with no clean path:

    #707   2 warnings, 0 info
    #711   2 warnings, 0 info
    #712   withdrawn (#712r)
    #713   2 warnings, 0 info   ← the one that bit
    #715   fixed by #722

**#713 bit on the same day the guard against it was built.** Reading r148 I wrote "#713 NOT SEEN,
and meaningful — zero duplicate groups". That is right, but only because I independently hashed
the twelve PNGs; had I not, "the hashing raised" and "results was empty" would have read
identically to "all distinct". A detector guarding the validity of 26% of all fidelity scores
should not need a second opinion. **Fixed: #723**, an INFO on the clean path naming how many
captures were checked.

**#707 and #711 are deliberately NOT given one, and the reason is the difference that makes the
rule useful.** The question is not "does this detector stay silent when clean" — most do, and
should. It is **"does anyone READ the silence as a result?"**

    #713   the checker has a line for it, and I drew a conclusion from its absence   -> fix
    #715   built expressly to answer item 34; its silence was the answer             -> fixed (#722)
    #711   fires on a THRESHOLD (gap >= 0.05). Silence means "the gap is small",
           which is the ordinary state and nobody reads it as a verdict             -> leave
    #707   fires when the backstop had to invent an asset. Silence means the lane
           did it properly — again the ordinary state                                -> leave

Adding an INFO to those two would be noise dressed as rigour. The rule earns its keep only where
a reader is entitled to treat absence as evidence, which is exactly the four cases that bit.

**Cheapest observation.** None — this is settled by reading, and the sweep is recorded so the
fifth instance is checked against this table rather than fixed reflexively.

---

## 44. #722 — and r148's full accounting, which is what surfaced it

r148 finished (`[main-exit]`, 12347 lines), so its absences are now readable. Build cutoff
10:44:39; #707, #711, #712, #713, #714 and #715 were all introduced before it and are IN. #718
(11:16) and #721 (11:46) are not.

| signature | r148 | reading |
|---|---|---|
| #711 | **LIVE x2** | 0.6190 vs 0.4250, gap 0.194 — the divergence announced, below the bar |
| #706 refusal | **LIVE x1** | fired with an empty reason → #721 |
| #700 | LIVE x98 | up from r147's 37 |
| #691 + #691b | LIVE x1 each | the recovery still works |
| #664 | LIVE x22 | down from r147's 76 |
| #684 #685 #686 #687 | GONE, all four | third run running |
| #712 | NOT SEEN | in the build, condition AROSE (round 6: 0.656 / 0.61 / bar 0.65), did not fire — the dead branch, already withdrawn as #712r |
| **#713** | **NOT SEEN, and meaningful** | hashing r148's 12 captures gives **zero** duplicate groups, against r147's one group of five |
| #714 #707 | NOT SEEN | in the build; their conditions did not arise |
| #715 | NOT SEEN, **and it proves nothing** | → #722 |

**#713's clean negative is the substantive one.** r147 had five screens sharing the landing
page's image; r148 has none. If the cause were structural — the gate's screen→URL map — it would
recur. It did not, which supports item 34's surviving hypothesis that r147's collapse was a
transient source-vs-served lag rather than a permanent defect.

**But #715 cannot corroborate it, and that is a defect of its own.** #715 exists precisely to
answer source-vs-served, and it has two warning branches and no third. Silence therefore covers
three states: probe ran and matched, probe never ran, probe skipped by a guard. Grepping r148 for
"#715" returns six hits, all of them timestamp milliseconds. The check built for this question
told us nothing about the run.

Same shape as #691's silent skip, #696's invisible load failure and #712's dead branch — the
most-repeated finding of this session, landing on a fix written to address it.

**Fixed: #722** — an INFO line on the clean path naming how many routes were verified. Not a
warning: a clean probe is provenance, not news. What changes is that "checked, matched" and
"never checked" stop looking identical.

**Cheapest observation.** Next run: if `#715 served build matches the source` appears alongside
zero duplicate captures, source-vs-served is corroborated. If it appears and duplicates appear
too, the hypothesis is dead and item 34 needs re-opening.

---

## 43. #721 — the refusal built to say WHY reported an empty reason

r148 finished and fired #706's refusal branch once:

    promotion did not happen (promotion merge conflict: )

The class, and nothing after the colon. #706 logs `(False, info)` distinctly from a raised
exception precisely on the argument that the callee "declines and names why", and the one failure
mode it exists to explain reports nothing.

**Cause, verified rather than assumed.** It read `p.stderr`. Building a real conflict — two
branches editing one file, then `git merge`:

    rc = 1
    stdout:  Auto-merging f.txt
             CONFLICT (content): Merge conflict in f.txt
             Automatic merge failed; fix conflicts and then commit the result.
    stderr:  (empty)

So the detail was always going to be blank, in every run, on the only path that reaches it.

**Fixed: #721.** It asks git for the paths rather than parsing prose — `diff --name-only
--diff-filter=U` lists exactly the unmerged ones — capped at six with a count, falling back to
stdout, then stderr, then a literal "no detail" so the message can never end in a bare colon.

**What it does NOT tell us yet, and this is the open part.** r148's promotion failed on a
conflict between `integration` and `main`, and with the detail empty we still do not know which
paths. #706 was wired on the premise that promoting after the cut is safe because `main` merely
follows; a conflict means the two have diverged in content, not just position. Whether that is
the stranded `mcp_server` subtree (#691's territory) or something broader is unknown.

**An offline attempt to shortcut this, and why it does not count.** The repository is still on
disk, so I copied it, checked out `main`, and ran the same merge: **rc=0, zero conflicts**. That
looks like a refutation and is not one. The promotion runs mid-run, and `integration` kept
receiving commits afterwards — so my merge tested the FINAL pair of commits, not the pair that
existed when the promotion fired. Same error class as reading a store mid-run (item 34): the
measurement was clean, the object was wrong. Recorded because "I reproduced it and it merged
fine" would have closed this item on nothing.

What the sequence DOES rule out: `promote_integration_to_main` checks out `main` first and
returns `checkout main failed: …` when that fails (auto_commit.py:1204-1206). r148's message was
the merge branch, not the checkout branch, so the checkout succeeded and a real merge was
attempted.

**Also worth recording: #706 has never once completed.** Three runs, three outcomes — r147 took
the other release path (fixed by #706b), r148 reached the right hook and refused on this
conflict, and `main..integration` still reads 31 there. The hook works; the merge has never
landed.

**ANSWERED OFFLINE after the failed shortcut — it is the second branch.** Redoing the merge at
the commits that existed AT 11:36:47 (integration `faf8e6c2f`, main `4ef333854`) rather than at
the final pair: **rc=1, 16 conflicting files**, and none of them is `mcp_server/*`:

    backend/main.py   backend/seed_data.json   frontend/index.html   frontend/src/App.jsx
    every page component (Browse*, Games, GenreCategory, Landing, Movies, MyList,
    NewAndPopular, Player, Shows, TitleDetail)   frontend/src/services/api.js

That is the whole app. And main's one divergent commit, `4ef3338` at 11:00:51, is a "framework
delivery: backend skeleton + frontend infra + projections" — it wrote the entire skeleton onto
`main` while the lane's work went to `integration`. **This is #691's mechanism at full scale:**
#691 caught the `mcp_server` subtree; the same fork strands a whole parallel framework-only copy
of the app.

**So `main` is not behind `integration` — it is a divergent version of the same files, and a
merge is the wrong operation.** Measuring what main actually contributes:

    run    main..integration   integration..main   files main has that integration lacks
    r146          34                  1                          3   ← the mcp_server trio
    r147          40                  1                          0
    r148          31                  1                          0

`main`'s only unique contribution has ever been the stranded MCP subtree, and **#691b already
recovers that into integration** — which is why r147 and r148 read zero. With #691b in place,
integration's tree strictly supersedes main's.

**What #706 should do instead, and why it is not done here.** Move the ref (`git branch -f main
integration`) rather than merge: it achieves exactly "main follows integration", costs no
conflict resolution, and loses nothing measurable because main contributes no unique file. The
safety of that rests entirely on #691b continuing to recover the subtree — r146, before #691b,
is precisely the run where a ref-move would have discarded three real files. That coupling makes
it a release-topology decision rather than a bug fix, so it is recorded with its evidence rather
than applied.

**Cheapest observation.** None needed for the diagnosis; it is settled. What a run would add is
confirmation that #721 prints these same paths, and that the zero-unique-files property holds on
a fourth run.

---

## 42. #712 WITHDRAWN, and #711's consequence with it — I checked the wrong dict

r148 disconfirmed #712 the first time the condition arose, and following that back invalidates
the consequence I drew from #711 as well. Both fixes stay (their warnings are real); both claims
about RELEASE are withdrawn.

**What r148 showed.** Round 6: `blocking_average` 0.656, `blocking_average_live` 0.61, bar 0.65 —
exactly the latch condition #712 described. #712's warning fired **zero** times. It cannot fire:
`result` has no `blocking_average_live` key at all, because `run_visual_fidelity`'s body never
mentions one. A dead branch guarding a claim, and the claim was false too.

**The two dicts.** There are two numbers named `blocking_average`:

    RETURNED by run_visual_fidelity   _blocking_similarity_average(results) — the CURRENT
                                      capture, blocking screens only, never merged
    PERSISTED by _persist_verdict     computed over #500's `merged` best-per-screen — the
                                      high-water mark, monotonically non-decreasing

`_persist_verdict` takes `results` and writes to disk; it does not touch the returned dict. And
`_visual_fast_release_args` reads `gate.last_result` — the RETURNED one.

**So:** the counter reads a value that CAN fall, the reset IS reachable, and #558's original
sentence ("a round below the bar resets the count") was right all along. #712 is withdrawn and
#558's wording restored.

**And #711's consequence goes with it.** The divergence is real — the persisted record IS a
high-water mark that drifts from the live capture, and warning about it is worth doing, which is
why #711's warning stays. But "a release authorised on the former ships the latter" is false: the
release path never reads the persisted number. The r146 "delivered at 0.67 while its screens sat
at 0.6409" and r147 "delivered at 0.700 against 0.5463" claims are withdrawn — those are
persisted figures, not the ones that authorised anything.

**What cannot be recovered.** The value that DOES authorise a release — the current blocking-only
average — is persisted nowhere. So "what number released r146" is unanswerable from artifacts,
which is why these claims are withdrawn rather than re-measured.

**The mistake, stated plainly.** I verified monotonicity from `rounds.jsonl`, which is the
persisted record, and then reasoned about a counter that reads a different dict. Two numbers, one
name. Every measurement I took was correct; the object I took it from was not the one in the
causal path.

**Cheapest observation.** Log the returned `blocking_average` beside the persisted one for one
run. If they diverge — and they must, one being merged — then every quality judgement made from
`verdict.json` this session (including mine) describes the record rather than the app.

**The generalisation, which is the only reusable part.** Six keys carry the same name in both
dicts — `blocking_average`, `coverage`, `min_similarity`, `passed`, `screens`, `summary` — and at
least three of them mean different things. Anyone reading these artifacts needs this table, and I
did not have it:

| artifact field | contains | so it is |
|---|---|---|
| `rounds.jsonl` → `live` | built from `results` | the CURRENT capture |
| `rounds.jsonl` → `blocking_average` | from the verdict, over `merged` | the HIGH-WATER mark |
| `rounds.jsonl` → `blocking_average_live` | `_live_average` | the CURRENT mean |
| `verdict.json` → `screens` | `merged` | BEST-EVER per screen |
| `verdict.json` → `passed` | `bool(passed) or _merged_passed` | merged-optimistic |
| returned dict → `blocking_average` | `_blocking_similarity_average(results)` | the CURRENT capture |
| returned dict → `passed` | `passed` | un-merged |
| the PNGs on disk | the capture itself | CURRENT |

Re-checking this session's analyses against it: #713 read PNG hashes off disk, so it is
unaffected. #718's `card_hover_preview` figures came from `verdict.json` `screens` and are
therefore BEST-EVER — the true current scores can only be lower, so "maximum 0.40, never passes"
is a floor and the finding is strengthened, not weakened. The 0.5463 recomputation used
`rounds.jsonl` `live`, which is current, and stands.

---

## 41. #711 CONFIRMED LIVE in r148 — announced, not reconstructed

r148 is the first run carrying #711, and it fired twice while still running:

    #711 the gating average has left the app behind:
         blocking_average 0.6190 vs blocking_average_live 0.4250 (gap 0.1940)

**Recorded mid-run on purpose, and only because of the direction.** #717 says a growing log
cannot be read as a result — but that rule is about ABSENCE. A signature that has fired has
fired; nothing later un-fires it. A positive is durable, a negative is provisional, and this is
the positive half.

The gap is the largest of the three measured:

    r146   0.67   vs 0.6409   0.029   (delivered)
    r147   0.700  vs 0.5463   0.154   (delivered, corrected for #713 contamination)
    r148   0.6190 vs 0.4250   0.194   (announced by the detector itself)

And it fired BELOW the bar — gating 0.6190 has not reached 0.65 — which is more useful than the
r146/r147 cases, not less: the divergence becomes visible before it can authorise anything. The
whole point of #711 was that both numbers were already computed and nothing compared them; here
the comparison happens while there is still time to act on it.

**What this does NOT settle.** Whether the gate should read the live mean is still open, still
coupled to item 40 (screens that can never be photographed), and still not mine to decide. What
r148 removes is any doubt that the divergence is real, reproducible, and large.

---

## 40. #718 — the gate blocks on a screen it cannot photograph, and has 36 times

Following "r147's four screens were never actually photographed" out to the corpus. Hashing every
run's gate screenshots and grouping by image, then reading each group's ROUTE, splits #713's
detection cleanly in two — and the larger half is not a defect at all.

**Four reference screens map to ONE route:**

    browse_home   browse_home_rows   card_hover_preview   account_menu   ->  /browse

so an identical capture is EXPECTED. The rates say so: `browse_home_rows` shares its image in
**53 of 53** runs, `card_hover_preview` 53 of 57, `account_menu` 19 of 23. These are INTERACTION
STATES — a scrolled view, a hovered card, an opened menu — reachable only by ACTING on `/browse`,
and the capture only navigates. The gate photographs the base page and scores it against a
reference showing the overlay.

**And they block.** `card_hover_preview` is a BLOCKING screen in 36 of its 54 appearances, and
across those 36:

    maximum 0.40    median 0.30    times it cleared the 0.65 bar: ZERO

`account_menu` is advisory in all 22 of its appearances — correct handling, and proof the
framework can classify these when it recognises them. `browse_home_rows` blocks in 22 of 52.
Removing all three lifts the mean run's average by +0.0208 and the extreme by +0.1785.

**Why #595 missed them.** It demotes reference frames holding TWO OR MORE open overlays ("not a
state the app can be in"). One overlay is below the threshold, so a single hover or a single open
menu sails through as an ordinary page.

**This reframes #711 and #712 rather than adding to them.** #500's high-water merge, #558's
fast-release and the plateau escapes are not simply leniency — they are what lets a run finish
when part of the measurement is structurally broken. Strip every escape and those 36 runs could
never release on the gate's own terms.

**Fixed: #718**, and only the reporting. The two cases now get different messages (`#713b` for
the shared-route case, saying plainly that a low score there is the GATE's limitation and not the
app's). Nothing is demoted: an overlay screen is real product and dropping it loses coverage.

**Only a decision can settle the rest, and it is now coupled.** Whether the gate should read the
live mean (#711/#712) cannot be answered without also deciding what to do with screens that can
never pass — demote them to advisory like `account_menu`, teach the capture to perform the
interaction, or accept that the escapes are load-bearing. Picking one changes what the other
means.

**Cheapest observation.** Mark `card_hover_preview` advisory for one run and compare
`blocking_average_live` and the release path against a matched run. If the run releases on the
ordinary path instead of an escape, the escapes were carrying this screen.

---

## 36. The recurring shape, swept: 137 of 290 tools have never been called

Three times this session I stumbled on the same thing — an instrument built for a problem,
never pointed at it — and each time I found it by accident. Sweeping all 290 tool `NAME`s against
every run log (~~a name appears in a log only when the tool is CALLED, so zero means never
called~~ — the parenthetical is wrong and is corrected below; the CONCLUSION survives it):

    tools defined                      290
    never called in 253 runs           137  (47%)

**The instrument, stated correctly, because the obvious reading of it is unsound in one
direction.** A bare-name grep counts MENTIONS, not calls, and this session already has the
counter-example: `register_seed_data` appears in 34 run logs and was never called once — the
mentions are the delivery gate demanding it and an agent grepping the app source for it. So:

    never mentioned  =>  never called          SOUND — nothing can call what is never named
    mentioned        =>  called                UNSOUND — see register_seed_data

The 137 therefore stands as a lower bound on never-called, which is the only direction this
item's triage uses. What does NOT follow is the complement: the other 153 are "mentioned", not
"used", and anyone tempted to read them as a healthy-tool list should re-measure. A marker-based
count is no better without care — `check_inbox` logs 132 `✅` and zero `🔧` in r147, while
`apply_patch`, `edit`, `docker_up` and `deliver_project` log NEITHER marker despite obviously
running, so a marker sweep UNDER-counts (187) exactly as the name sweep OVER-counts (137).

**Audited, and nothing else rested on the unsound half.** Having found the false justification I
checked every place the inference appears, in this file and in the tree, before assuming the
damage was local:

    EXPERIMENTS_PENDING:480   `save_task_suite` 0 of 253 -> "not called, not even mentioned"
    workhub/service.py:90     `submit_plan` 0 of 253 -> "has never run"
    plan_decision.py:147      conditional phrasing, no count

All three use the SOUND direction (zero ⇒ never called); none concludes "used" from a nonzero
count. So the correction removes a wrong reason without disturbing a single conclusion, and this
particular thread is closed rather than merely paused.

**That number is not a defect list, and reading it as one would be the mistake.** Most of the 137
are legitimately situational: `docker_down`, `interrupt_process`, `terminate_agent_team`,
`request_plan_changes` — you call them when the circumstance arises and it usually does not.

**The actionable subset is the one with a matching, MEASURED problem.** All three of this
session's finds have that shape, and it is the triage rule for the rest:

    docker_inspect_image        "containers show stale content"   occurring in 81% of runs  -> #715
    search_icons/search_photos  source an asset you lack          8 of 27 delivered runs    -> #707
    promote_integration_to_main promote after verification        130 of 146 runs diverged  -> #706

So the question to ask of each remaining name is not "is it used" but "is the problem it names
happening". **Three candidates checked, all three rejected — which is what makes the rule worth
having:**

| candidate | the problem it names | measured | verdict |
|---|---|---|---|
| `compare_screenshots` | the gate's similarity is LLM-judged, and a judge failure returns 0.0 — a phantom zero of the #713 kind | `judge JSON unparseable` and its siblings occur **once in the whole corpus** | not a live gap |
| `extract_components` | per-component specs from a screenshot | design-prep already emits them — "20/20 reference screens decomposed into per-component build specs" in **159 runs** | redundant, not missing |
| `log_search` / `log_analyze` | structured log analysis | lanes grep logs by hand **262 times**, but nothing shows those greps failing | an alternative path, not a defect |

The `compare_screenshots` one is worth keeping for a reason beyond its verdict: the fidelity score
IS an LLM judgement ("Deterministic in wiring — route mapping, capture, thresholding — LLM only in
the judging"), and a judge failure falls through to `similarity: 0.0`. That is structurally the
same phantom-zero as #713 and it simply never fires. Worth knowing it exists before someone reads
a 0.0 as a blank page.

| `db_query` / `db_schema` | schema/column errors the lane cannot diagnose | "column does not exist" 9, "relation does not exist" 3, "no such table" 0 — **12 in 253 runs** | not a live gap |
| **`wait_for_service`** | "Prevents test failures due to services still starting up" | `Connection refused` **1801 / 113 logs**, `ERR_CONNECTION_REFUSED` 605, `not ready` 320, `BLOCKED at docker_up` 122 | **HIT — qualified** |

**All five candidates now checked: four rejected, one hit, and the hit needs discounting.**
`wait_for_service` has 0 calls in 253 runs while the failure it exists to prevent is the corpus's
largest transport class. But era-splitting it, as every other claim in this file has been:

    Connection refused   r<100  932 across 68 logs
                         r100+  757 across 34 logs      <- still live
                         r145 6 · r146 0 · r147 2

The 1801 is dominated by history, and the newest three runs show 6, 0 and 2. So this is a real
but SHRINKING gap, not another 81%-of-runs finding. Worth noting for its own sake: **#677 fixed
this class by improving the message** ("1778 bare Connection refused" was its premise) **while a
tool built to PREVENT the failure sat unused** — the diagnosis was wired and the prevention was
not, which is the same asymmetry in a different form.

The sweep's honest yield: the rule found three real cases when applied to things I had already
stumbled on, and produced four rejections and one discounted hit when applied cold to the
remaining candidates. That ratio is the point — it discriminates, and 137 unused tools is not 137
defects.

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

**The contract line is FALSE for the two newest runs, and that changes the shape of this item.**
It was verified on r146. Checking all three:

    run    contract request for GET /api/titles                    backend kind-filter sites
    r146   {kind, genre, language, limit, offset}                              1
    r147   (empty)                                                             1
    r148   (empty)                                                             2

r147 and r148 IMPLEMENT filtering and DECLARE nothing. The implementation kept the capability —
r148 even extended it, its `custom_routes.py` carrying `WHERE kind = :kind` against a
module-level `_TITLE_COLS` constant with every user value bound — while the registered schema
carries no query params at all.

**The CAUSE is unknown, and two attributions of mine were wrong.** I first called it a framework
regression; `registryhub_register_endpoint` passes the schema through `_coerce_dict_param`, which
converts a string to a dict and strips nothing, so the framework is not dropping it. I then
called it the lane failing to declare, on a grep showing "74 register_endpoint calls in r146, 0
containing 'kind'". **Those are not calls.** They are prose — rejection messages and tool
listings — and the logs do not record this tool's arguments at all. That is item 36's own
documented trap ("mentioned ⇏ called"), which I catalogued and audited others for, and then
walked into.

So: r146's schema did not come from `register_endpoint` as far as the logs can show, and
`update_schema` is never called in any of the three runs. Where it came from is not recoverable
from these artifacts.

**What survives is durable, because it is read from the hub store rather than the log:** the
contract for `GET /api/titles` carries the query params in r146 and carries none in r147 or r148,
while all three backends implement filtering. That mismatch is the finding; its origin is open.

**CAUSE FOUND — it is convergence toward the instruction, not a regression.** The decline is
monotonic and measurable:

    r146   16 GET endpoints,  3 declare query params
    r147   17 GET endpoints,  1
    r148   16 GET endpoints,  0

and the backend prompt's ONLY guidance on endpoint schemas was `schema with response_key`. It
asks for `response_key` and says nothing about request parameters, so a lane declaring exactly
that is following instructions correctly — r146's richer `/api/titles` declaration was the lane
EXCEEDING them. 3 → 1 → 0 is drift toward what was actually asked.

**That distinction decides whether a prompt change can work.** #664 measured that repeating an
ignored instruction does nothing: 30 mentions plus 76 escalations moved no behaviour. This is the
opposite — the instruction is not ignored, it is incomplete, and the lane already does what it
says. Completing it is not the move #664 ruled out.

**Fixed: #729.** The prompt now asks for `schema.request` naming every query parameter a GET
accepts, with the shape and the `?`-optional marker, plus why it matters: a filter implemented and
not declared does not exist to the frontend, the contract audit, or #708b's remediation hint. The
backend already implements them — r148's `list_titles` takes kind/genre/language and its SQL
carries `WHERE kind = :kind` — so the contract was the only broken link.

**WRONG DIAGNOSIS — the lane DID declare them, under another name.** r148's `GET /api/titles`:

    "schema": {"query": {"kind": "string?", "limit": "integer?"}, ...}

`query`, which is the natural word for query parameters. Every consumer reads `schema.request`
— validation_runner:597, database_scaffold:350, scaffolder:517, #708b's filter hint — and
**nothing in the framework reads `schema.query`**. Written, stored, invisible.

**Impact, corrected — it is GET-only.** Listing four consumers made this look like a
system-wide loss, and I said so. It is not. Both heavyweight consumers are method-scoped:
`_probe_body` is called only from `_http("POST", …)`, and `database_scaffold`'s column derivation
opens with `if method != "POST": continue`. And the POST side never lost anything:

    business POST endpoints with a request schema
    r146  4/4      r147  4/4      r148  4/4

So smoke-test bodies and generated table columns were never affected. The loss lands on GET query
parameters alone, which reaches exactly two places: #708b's filter hint and the frontend's basis
for passing a filter. That is narrower than I claimed one turn earlier and does not reduce the
importance — the GET path is what blocks four of the five identical-content route groups — but
"three consumers were starved" was reading the consumption side without checking the data side.

    r146   schema.query 0   schema.request 10
    r147   schema.query 0   schema.request 10
    r148   schema.query 3   schema.request  6

So the "3 → 1 → 0 decline" counted one spelling of two. The decline is real for `request`; the
information was not lost, it moved. My prompt change asked the lane to say `request` — worth
keeping as the canonical spelling, but it was fixing the speaker when the listener was deaf.

**Fixed: #730**, folding `query` into `request` on WRITE. One place instead of four readers, it
recovers the declaration whichever word is chosen, `request` wins on conflict since that is what
consumers act on, and the lane's own wording is left in the record. A test fails if a real
`schema.query` reader ever appears, since the fold would then be redundant.

**Cheapest observation.** Next run: `#729 GETs declaring query params` in the checker now counts
post-fold, so above zero means the chain is whole — declared, folded, visible to #708b — and item
32's route-derived filtering is unblocked at last. Still zero would mean the lane declared under a
THIRD name, which #725's dispatch logging would show.

The consequence is visible in the same run: #708b, which exists to name the filters the contract
declares, correctly found the endpoint record, correctly extracted ZERO optional params, and
correctly said nothing. I spent a while treating that silence as a dead branch of my own before
checking the data. It is not the branch; it is the contract.

And it explains the六-route group r148 reports: with nothing declared, the frontend has no
contract basis for passing a filter, so every catalogue page fetches bare `/api/titles`. **[That
clause is RETRACTED — see item 54: the frontend fetched the full record 28 times and had the
parameters. What was blocked was #708b's report, not the lane's access.]** The
route-derived fix is therefore blocked one step earlier than item 32 assumed — not on the
fidelity trade-off, but on a contract that no longer describes its own endpoint.

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

## 39. Tools no role can reach — one real orphan, and why the obvious guard does not work

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
