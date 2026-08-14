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

**Cheapest observation.** One run: does `tasks/tasks.yaml` ever appear?
`task_definition_tools.py` targets it and `tasks/action_space.yaml`; if the writer is
unreachable, the matrix should key on something that exists.

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

**Cheapest observation.** One run: grep for reads of `design/crops/`. If only the design analyst
writes them and nothing reads them, stop writing a crop for an empty region — and 4.9 GB of
mostly-unread PNGs is worth revisiting separately.

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

**Sharpest single case.** `registryhub_pending_consumers` has BOTH a writer
(`register_consumer(..., pending=True)` queues a consumer whose endpoint does not exist yet) and
readers (`list_stale_pending_consumers`, whose result drives `my_stale_pending_consumers` in
every hub pulse and gates three branches there). An internal caller at registryhub.py:1365 does
pass `pending=True`. Yet the store is empty in 144 of 144 runs, so the pulse field is always
empty and those branches never fire.

**Only a run can settle.** Whether the queue is empty because pages always declare endpoints
that already exist (benign, and the mechanism is simply idle) or because the 1365 call site is
unreachable. Both produce an identical empty store on disk.

**Cheapest observation.** One run: log at registryhub.py:1365 whether the branch is entered, and
count `register_consumer` calls whose endpoint is absent. If the branch never runs while absent
endpoints do occur, the pending path is dead and the pulse should stop reading it.

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

**Only a run can settle.** Whether the scaffold writes into a worktree that never reaches the run
root, or writes to the root and something later removes it. A removed worktree leaves no trace,
so the artifacts cannot separate the two — and the registry's `implemented` is written from the
write's own return value, so it cannot witness the loss either.

**Cheapest observation.** One run: log `orch.output_dir` at the `write_mcp_server` call and stat
`mcp_server/` again at delivery. If the path differs, it is a worktree-merge gap; if it matches
and the directory is gone, something deletes it.

**Related, deferred with it.** The delivery gate has `deliverability_failed_mcp_probes` but does
not require the surface to exist. Requiring it would have failed 27 of the 35 delivered runs, so
it is a tightening of the same class as item 13, not a blind switch.

---

## 19. Older, still unresolved

- **#644 viewport.** Two measured targets conflict: 796px matches the reference image aspect,
  981px matches its content fraction. Changing to 796px took `_measured_deviations` error from
  +9.1% to +23%, so it was reverted. Settling this needs a run at each candidate width scored by
  the real judge, not by pixel arithmetic.
- **#641 round-ledger recommendation at release.** Needs one run's `rounds.jsonl` to validate
  the "a better state was available" selection.
- **`_auto_approve_threshold = 3`.** An unmeasured tuned constant, now newly relevant because
  #658 made the path above it live for the first time. No corpus data exists on plan step
  counts (the path never ran). One run's plans would give the distribution.

---

## Next actions that are still offline-checkable

1. ~~**#658 follow-up.**~~ Done — no subscriber exists; see item 6 and #659b.
2. **`llm_func` annotation.** `utils/memory.py:357` declares `Callable[[str], str]` with the
   comment "Async function" beside it and `await` at the call site; the only caller passes
   `async def`. One-line annotation fix, no behaviour change.
3. **The 363 `bad-function-definition` reports** are overwhelmingly `X: SomeType = None` where
   the annotation should be `Optional[...]`. Mechanical, zero-risk, and each one currently hides
   real `bad-argument-type` findings downstream.
