# Refactor review — reviewer's latest

## SUPERVISOR NOTE — Round 8f (Spiral) proposal assessed: ADOPT AS TARGET, do NOT build now; orphaned facilitate.py flagged

**Verdict (3-agent panel + my own verification):** the Spiral multi-round kickoff is the right TARGET
architecture (it attacks contract-drift during authoring and is the only design that consumes the
already-computed reviser map — today the 8c driver throws that map away, so conflict = dead run). But
do NOT build/wire it now, and a chunk of it is already half-landed headless.

**🔴 DECISIVE FINDING (verified in the working tree):** ~60% of 8f is ALREADY WRITTEN and RUNTIME-HEADLESS —
the 8b headless-coordinator mistake re-created one layer up.
- `runtime/kickoff/facilitate.py` (351 LOC, untracked `??`) exists + exported from `kickoff/__init__.py`;
  `messaging.py` (M) has `_handle_kickoff_facilitate_request` (:387) + `_handle_kickoff_revision_request` (:790);
  subscription + orchestrator/backend prompt macros reference it.
- **BUT the driver `_drive_kickoff_to_completion` never calls facilitate** — `orchestrator.py:865`
  imports ONLY `run_kickoff`; grep facilitate/request_revision/advance_round in orchestrator.py = 0.
  So facilitator turn + revision rounds are built+subscribed+prompt-backed but **never on the driven path**.
- **Zero facilitation tests** → the 2110-green suite masks it (false-green, the recurring lesson).
- Carries a **back-compat shim** (facilitate.py:281,337 "pre-8f.1 / legacy / Defaults to 1") — violates
  the project's own no-back-compat / delete-don't-skip discipline.

**Why not now:** M1 has NEVER run green (8d pending). Building a ~700-LOC multi-round protocol (4-9× tokens,
a NEW facilitator-LLM hang point inside the kickoff critical path that 8c deliberately made pure-Python)
on an unproven base compounds unknowns + destroys the clean 8d diagnostic (can't attribute a failure to
simple-kickoff vs spiral). Same reasoning as §9 (roster). Charter §2 spiral = milestone-model discipline,
which the single-round kickoff already satisfies; multi-round intra-kickoff is an ENHANCEMENT, not required.

**DECISIONS TAKEN (autonomous) — ordered path:**
- **Gate 0:** get the orphaned `facilitate.py` + messaging facilitate branches OUT of the 8d path (stash/remove)
  so the 8d smoke tests ONLY the simple single-round kickoff — clean baseline.
- **Gate 1:** run the pending 8d M1 smoke to GREEN first (walking skeleton). No spiral lands until
  `_drive_kickoff_to_completion` is proven to drive a real run end-to-end.
- **Increment 1 (after green M1, highest value):** wire `facilitate.request_revisions` into the driver —
  on `conflict`, run ONE bounded revision round (consume the existing reviser map; `_collect_drafts`
  absorbs proposal_v2 via last-write-wins), re-poll `try_synthesize`, fall to `synthesize_fallback` only
  after `max_rounds`. Discipline: outer 1200s timeout stays the hard wall and starts at
  `start_kickoff.started_at` (NOT reset per round); max_rounds=3; facilitator-turn deadline → fail-loud
  (no stub contract); **delete the pre-8f.1 back-compat shim**; add facilitation tests (conflict→1 revision→
  re-synth; max_rounds→fail-loud).
- **Increment 2+ (nice-to-have docs):** MILESTONE/ROADMAP/BRIEFING via `write()` + conventions, deferred;
  retro→roadmap→M{n+1} loop only matters once M2 exists (correctly last).

**Loop watch:** flag if `facilitate` gets wired into the driver BEFORE the 8d smoke is green.

---

## ROUND 8c (three breaks fixed) — CLEAN PASS on the corrected scope; GO for the 8d smoke

*(Cleanup FULL SIGN-OFF, round 5, stands separately.)* **Mode: autonomous.**
**Verification:** my own run (51 new+invariant tests green; 2110 sweep, no regression; driver +
handler + prompt-delete + fallback read directly; guardrail re-probed RED). Trust code, not doc.

**Verdict:** the corrected 3-fix scope from round 8b landed correctly and is well-tested in
isolation. The headline win is **structural**: the kickoff is no longer headless *and* the legacy
fallthrough can no longer fire — because the driver blocks the resident lane until the contract is
registered. The fixes are unit-proven; per this whole arc's lesson (**unit-green ≠ runtime-engaged**)
the re-run smoke is the only real proof. **It is architecturally sound → GO for the 8d smoke.**
Not GOAL MET (smoke pending).

## CONFIRMED FIXED (file:line, verified)
- **#1 driver + structural §6.D enforcement:** `orchestrator.py:614` awaits
  `_drive_kickoff_to_completion(handle)`; `:626` `if receipt["phase"] != "finalized": raise
  RuntimeError`. The resident lane is **not entered with a pre-contract state** — even if the LLM
  *wanted* to dispatch `task_ready` early, it gets no turn until `finalize_kickoff` registered the
  contract. Driver (`:821`) polls `try_synthesize` → `finalize_kickoff(agent="orchestrator")` on
  ready; `started_at is None` check at `:863` (the real `or 0.0` bug they caught — genuine testing).
- **#2 attendee handler:** `messaging.py:370` `if msg_type == "kickoff_request": _handle_kickoff_request`
  (`:618`) renders the agent's `kickoff_response_prompt` macro and runs one LLM turn → `add_meeting_decision`.
- **#3 legacy dispatch retired:** orchestrator v3 prompt — legacy `db_spec` example gone, 7 "DO NOT
  dispatch task_ready / DO NOT call plan(add_task)" rules; 10-test absence-pin green. The 3 residual
  `add_task` mentions are the *forbidding* instructions, not examples.
- **timeout/fallback folded in** (my round-8a finding): `KICKOFF_TIMEOUT_SEC=1200`,
  `KICKOFF_POLL_INTERVAL_SEC=5`, `synthesize_fallback` emits `kickoff_failed` + `kickoff_fallback_used`;
  conflict/validation_failed/timeout → fallback → `phase="timeout_fallback"` → driver raises = **loud abort** (not silent degrade). ✅
- 2110 sweep, no regression; orchestrator §8 (driver on the class, kickoff fns stay pure); guardrail RED.

## REFUTED / NEW RESIDUES
None blocking. Surgical prompt rewrite leaves a residual-bleed *risk* (legacy phrasing elsewhere in
the 958-line prompt the 6 edits didn't touch) — but it's mitigated structurally: the driver blocks
the legacy path regardless of what the prompt says. Defer a deeper prompt pass to 8d **only if** the
smoke shows the LLM still attempting legacy dispatch (it shouldn't get the chance).

## ANSWERS TO YOUR 5 QUESTIONS (autonomous)
1. **3-fix shape + pins:** Agree, endorse. Don't weaken the pins — the source-inspection guard on the
   `kickoff_request` branch and the prompt-absence tests are exactly the closed-by-construction style
   the charter wants. Keep them.
2. **conflict/validation_failed fatal→fallback, reviser loop deferred to 8d:** OK to defer. For M1's
   tiny contract a conflict is unlikely, and a **loud abort** (fallback→RuntimeError) is the correct
   behavior — far better than synthesizing a degraded contract. Prove the happy path first; the
   reviser loop is genuinely more surface and belongs after the kickoff runs once. Confirmed the
   abort is loud (`:626` raises on non-finalized). ✅
3. **Surgical prompt rewrite:** Fine for now — the structural driver-block is the real guarantee, the
   prompt is belt. No full rewrite yet; revisit in 8d only on observed bleed.
4. **max_steps=50 for the attendee response:** Tighten to ~10-15. The macro is "run once then
   finish()"; 50 is a loose net that could burn tokens on a confused LLM. ~10-15 fails faster while
   allowing read-refs→draft→add_meeting_decision. Minor; the smoke will show the real count. Non-blocking.
5. **Commit:** see DECISIONS NEEDED — it's the user's call; I won't commit.

## DECISIONS TAKEN (autonomous)
- **Round 8c ACCEPTED — clean pass.** All 3 fixes verified; structural §6.D enforcement is the win.
- **GO for the 8d re-run smoke.** 8c is architecturally sound; the smoke is the GOAL gate and the only
  proof the kickoff engages at runtime. Cost is ~$5-20 of the provisioned key — justified: this is the
  first real shot at a passing M1 end-to-end, the entire arc built for it. **Apply round-8b discipline:
  stop at the first new break, surface it cleanly, don't push past.** Watch (per the implementer's 8d
  plan): kickoff_request reaches all 4 attendees → their `.agent_logs/` populate → each
  `add_meeting_decision` lands → `kickoff_complete` fires → `finalize_kickoff` returns `finalized` →
  contract in APIHub BEFORE any task_ready → design never role-gated → docker boot → smoke passes.
- Tighten the attendee max_steps to ~10-15 (minor, optional before the smoke).

## DECISIONS NEEDED FROM USER
**Commit strategy (I will not commit without your ask — system rule).** The working tree carries
rounds 5→8c uncommitted, which is itself a risk (a lot of unsaved work). Your call:
(1) squash to one round-8c snapshot (simplest; buries granular history), (2) replay round-by-round
(preserves history; more work), (3) leave uncommitted. I lean (1) if you don't need granular history,
but it's yours. Worth deciding soon so the work isn't at risk.

## PROGRESS TOWARD GOAL
The runtime-engagement gap the first smoke exposed is closed and structurally enforced. `GOAL MET` now
hinges on the 8d smoke: if the kickoff completes and the M1 walking skeleton (auth + 1 entity + 1 CRUD
+ docker boot + smoke) passes its acceptance gates, that's GOAL MET. If it surfaces the next break,
I'll pin it precisely. This is the closest the pipeline has been to a real passing run.
