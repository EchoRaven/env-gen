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

  **What is now open is a decision, not a measurement.** The recommendation fired and the run
  shipped r9 anyway — by design, "it changes no decision taken here" — so r146 is the 25th
  instance of the pattern its own note quotes (#618: 24 of 39 runs deliver worse than their own
  best). Whether the bounded escape should ship the BEST recorded round instead of the last one
  is a release-policy change, and #641 has now produced the evidence to argue it with.
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
     All **18** instantiation sites in the tree pass one — zero omit it — so the attribute is
     never actually None. Latent at worst. One of those classes both guards
     (`if not self.workspace:`) and dereferences unguarded elsewhere, so the INCONSISTENCY is
     real even though the crash is not.
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
