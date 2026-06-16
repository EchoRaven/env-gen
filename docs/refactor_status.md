# Refactor status — review-loop coordination

This is the single doc the reviewer and I synchronize on between
rounds.

- **`docs/refactor_status.md`** (this file) — Claude writes the
  latest state after each substantial round.
- **`docs/refactor_review.md`** — reviewer's latest assessment.
- **`docs/pipeline_supervision_charter.md`** — north-star architecture
  doc; both loops read it on every wake.

---

## Round 8c — three layered breaks closed, 2110 tests green, smoke pending

**Branch**: `haibotong-0527-hub-focus-and-tooling-cleanup` (uncommitted,
working tree carries cumulative work from rounds 5-8c — see "Commit
decision" below).

**Mode**: autonomous (per reviewer round-8b GO).

Round-8b smoke surfaced three layered integration breaks:
1. kickoff coordinator was **headless** (no Python driver — reviewer
   corrected my "tool surface" misdiagnosis: kickoff helpers were always
   pure §8 functions, not LLM tools)
2. attendee `kickoff_request` urgent event → LLM turn **not wired**
3. legacy orchestrator-LLM-direct `plan(add_task)` + `send_message(task_ready)`
   **silently took over** when kickoff stalled

Round 8c lands all three fixes atomically per reviewer's §6.D guidance,
plus 35 closed-by-construction regression tests pinning each fix.

### WHAT CHANGED THIS ROUND (file:line)

**Modified — `runtime/kickoff/run_kickoff.py`** (driver helper layer):

- `__all__` now exports `KICKOFF_POLL_INTERVAL_SEC` (= 5.0s),
  `KICKOFF_TIMEOUT_SEC` (= 1200.0s per round-8a SUPERVISOR-NOTE),
  and `synthesize_fallback` so the orchestrator's Python driver can
  read constants + the timeout helper without touching the kickoff
  function bodies.
- New `synthesize_fallback(hubs, kickoff_handle, last_synthesis, agent)`
  (~110 lines): the T=1200s circuit-breaker the reviewer flagged in 8a,
  now folded into the driver path. Records a `phase_transition`
  decision with `phase="timeout_fallback"`, emits `kickoff_failed`
  with `kickoff_fallback_used=True` on the event payload (so external
  observers can distinguish a timeout-driven abort from
  `finalize_kickoff`'s partial_failure path), and returns a structured
  receipt the driver inspects via `phase=="timeout_fallback"`.
- Hardening: helper survives both an eventhub failure during emission
  AND a workhub failure during phase recording — the receipt is the
  source of truth. The helper does NOT manufacture stub drafts for
  missing sections; "synthesizing a fake contract from a partial
  kickoff" is exactly the silently-degraded run shape the round-8b
  break exposed, and the run loop aborts instead.
- Closed-by-construction guard: rejects malformed `kickoff_handle` /
  `last_synthesis` with ValueError at the function boundary.

**Modified — `multi_agent/orchestrator.py`** (Fix #1, the Python driver):

- New method `_drive_kickoff_to_completion(kickoff_handle)`
  (~115 lines). Called synchronously between `start_kickoff()`
  (line 597) and the resident lane loop (line 626). Polls
  `run_kickoff.try_synthesize` every `KICKOFF_POLL_INTERVAL_SEC`;
  routes each status:
    - `"ready"` → calls `finalize_kickoff` with `agent="orchestrator"`
      (the actor that holds the `apihub.register_endpoint`
      / `schema_hub.register_table` allow-set) and returns the receipt
    - `"awaiting"` → logs missing attendees, sleeps, re-polls
    - `"conflict"` / `"validation_failed"` → calls `synthesize_fallback`
      (M1 first-cut: no in-driver reviser loop; that lives in 8d per
      charter §6.D)
    - `time.time() - started_at > KICKOFF_TIMEOUT_SEC` → fallback
    - `try_synthesize` raising re-raises (it's pure + read-only; a
      raised exception is a runtime bug, not a transient)
- Call-site change at line 588: after the kickoff coordinator returns
  the handle, await `_drive_kickoff_to_completion(handle)` and
  inspect the receipt. `phase == "timeout_fallback"` raises
  RuntimeError with the missing attendees in the message. Anything
  other than `"finalized"` also raises. **The resident lane is no
  longer entered with a pre-contract state** — charter §6.D
  ("contract MUST register before any task_ready dispatch") is now
  structurally enforced.
- Bug fix: changed `started_at = handle.get("started_at") or time.time()`
  to an explicit `is None` check. The `or` treated `0.0` as falsy and
  silently substituted current time, which would mask a timeout-driven
  abort. Caught by `test_driver_timeout_falls_through_to_fallback` —
  the test hung until I noticed the test's intentional `started_at=0.0`
  was being silently replaced.

**Modified — `multi_agent/agents/runtime/messaging.py`** (Fix #2):

- `_check_and_handle_urgent` (line 358 region) now has an explicit
  `msg_type == "kickoff_request"` branch that dispatches to
  `_handle_kickoff_request(urgent_msg)` and returns True. Without this
  branch, the urgent loop logged "Handling urgent kickoff_request" then
  returned False — the round-8b regression class (confirmed by the
  4 empty `.agent_logs/` directories).
- New method `_handle_kickoff_request(message)` (~105 lines):
    - extracts `meeting_id` / `milestone_index` / `requirements` from
      the event payload; logs a warning and returns if `meeting_id`
      is missing (closed-by-construction guard against a malformed
      event silently spawning an LLM turn)
    - section identity = `self.agent_id` (only the 4 attendees
      subscribe per `agent_subscriptions.py`)
    - renders the agent's `kickoff_response_prompt` Jinja macro from
      the v3 template the agent already advertises
      (e.g. `design_agent.j2 :: kickoff_response_prompt`); on render
      failure falls back to a plain-text prompt that still instructs
      the LLM to author one `workhub_add_meeting_decision(...)` call
    - runs ONE agentic loop with the rendered macro as `initial_prompt`
      and `_compose_system_prompt()` as `system_prompt`; cap is
      `_max_steps_per_kickoff_response` (default 50 — the macro says
      "Run ONCE then finish()", so 50 is a safety net for a confused
      LLM, not the primary stop condition)
    - on exit, drains deferred task_ready messages (matches the
      `_handle_task_ready` lifecycle)
- Added `Mapping` to the typing import (used in payload type
  guards).

**Modified — `multi_agent/prompts/v3/orchestrator_agent.j2`** (Fix #3,
atomic legacy delete per §6.D):

- Mandate (line ~569): now opens with **"Kickoff comes first"** and
  names `_drive_kickoff_to_completion` explicitly — the LLM is taught
  that the Python coordinator ran before its first tick + the
  contract+tasks are already in WorkHub.
- Peers map (lines 580-583): all 4 attendees' `you_call` entries
  rewritten with explicit "**you DO NOT dispatch task_ready** at
  project start — the M{n} kickoff coordinator registered these
  tasks". Reserved task_ready for remediation only.
- step_contract_overrides.inbox (line ~597): replaced the broken
  "switch to kickoff_synthesis_prompt and run try_synthesize" advice
  (try_synthesize is pure-Python, never was an LLM tool) with the
  new Python-driver framing + the explicit "DO NOT dispatch
  task_ready" rule.
- tool_policy for `send_message (msg_type='task_ready')`
  (line ~608): rewritten as **"REMEDIATION ONLY post-kickoff"**.
  Legacy "Phase 2: design at project start. Phase 3: backend/frontend
  AFTER design approved" deleted.
- "Your Workflow" section (line ~770): replaced the legacy Phase 1
  (Requirements Analysis) + Phase 2 (Design Kickoff) + Phase 3
  (Monitor Implementation) block with a new Phase 1 ("Kickoff is done
  by the time you're reading a tick") + Phase 2 (Monitor
  Implementation) that explicitly forbids task_ready for kickoff
  tasks. The legacy `plan(action="add_task", stage_id="design",
  task_id="db_spec", ...)` literal example is **deleted**.
- "Planning with Stages" section (line ~201): renamed to "Planning —
  task authoring lives in the kickoff coordinator". The legacy
  `db_spec / api_spec / schema / api / ui / release_validation` example
  block is replaced with explicit "DO NOT call plan(add_task) for
  these — that is the legacy fallthrough path the round-8b smoke
  surfaced" + a remediation-task example showing the right shape.
- success_criteria (line ~644): "Design Agent dispatched at project
  start" + "Database/Backend/Frontend task_ready fired only AFTER
  design approval" deleted. New first criterion: "Kickoff coordinator
  drove the M{n} contract + task_tree + predicates into WorkHub via
  finalize_kickoff BEFORE your first resident_coordination_tick".

**Created — `agent/tests/test_kickoff_run_kickoff_synthesize_fallback.py`**:
10 tests. Pins: `kickoff_failed` event shape with `kickoff_fallback_used`
flag, `phase_transition` decision persistence, conflict-findings
propagation, eventhub-failure-survival, workhub-failure-survival,
malformed-handle rejection (parameterized over 4 bad shapes),
malformed-synthesis rejection, module constants exported.

**Created — `agent/tests/test_kickoff_orchestrator_driver.py`**:
6 tests. Pins: happy path (try_synthesize ready on first poll →
finalize), awaiting → awaiting → ready transition (polls expected
count, finalize called exactly once), conflict short-circuits to
fallback (no finalize call), timeout falls through to fallback (the
test that caught the `or 0.0` bug above), try_synthesize exception
re-raises, validation_failed routes to fallback.

**Created — `agent/tests/test_kickoff_attendee_urgent_handler.py`**:
9 tests. Pins: render_macro called with exact kwargs +
agentic_loop called with rendered prompt as initial_prompt,
section identity = agent_id (parameterized over design/backend/
frontend/verifier), list-requirements flattening, render-failure
fallback to plain-text prompt, missing-meeting_id skip+warn, and a
source-inspection guard asserting `_check_and_handle_urgent` contains
the `msg_type == "kickoff_request"` branch (closed-by-construction
guard against a future edit removing the dispatch).

**Created — `agent/tests/test_orchestrator_prompt_no_legacy_dispatch.py`**:
10 tests. Pins the prompt-side §6.D delete: legacy `task_id="db_spec"`
example absent, legacy task-description phrasings absent, mandate
references `_drive_kickoff_to_completion`, inbox step_contract
contains "DO NOT dispatch task_ready", each of the 4 peers entries
contains "DO NOT dispatch task_ready" (parameterized), legacy
success_criteria deleted, new success_criteria present,
`send_message(task_ready)` tool_policy reads "REMEDIATION ONLY
post-kickoff" + legacy "Phase 2: design at project start" deleted.

### MILESTONE STATE

| M1 readiness | Status |
| --- | --- |
| run_kickoff coordinator (start / try_synthesize / finalize / synthesize_fallback) | ✅ all 4 helpers + module constants |
| 4 per-agent kickoff_response prompts (Jinja macros) | ✅ exist (round 7), now actually triggered (round 8c Fix #2) |
| Python driver: poll → finalize on ready / fallback on conflict-or-timeout | ✅ Round 8c Fix #1, 6 tests pin the contract |
| Attendee urgent handler dispatches kickoff_request → LLM turn | ✅ Round 8c Fix #2, 9 tests pin the contract |
| Legacy orchestrator-LLM-direct plan(add_task)+task_ready retired | ✅ Round 8c Fix #3, 10 prompt-regression tests pin it deleted |
| Meeting-phase state machine (recovery safety) | ✅ Round 8a (untouched) |
| T=1200s circuit-breaker | ✅ Round 8c (folded into the driver, surfaced via synthesize_fallback) |
| End-to-end smoke attempt | ⏸ Pending — see "Commit + smoke decision" |

### TESTING

| Test surface | Result |
| --- | --- |
| New `test_kickoff_run_kickoff_synthesize_fallback.py` | ✅ 10/10 PASS |
| New `test_kickoff_orchestrator_driver.py` | ✅ 6/6 PASS |
| New `test_kickoff_attendee_urgent_handler.py` | ✅ 9/9 PASS |
| New `test_orchestrator_prompt_no_legacy_dispatch.py` | ✅ 10/10 PASS |
| Roster invariant (16 cases) | ✅ 16/16 PASS |
| All previously-shipped kickoff tests | ✅ 166/166 PASS |
| **Full agent suite** | ✅ **2110 passed in 136s** (was 1975 in 8a; net +135) |

### CHARTER ALIGNMENT (Claude's self-assessment)

| Charter property | Round 8b state | Round 8c state |
| --- | --- | --- |
| §3 M1 architecture present | ✅ | ✅ |
| §3 M1 runnable end-to-end | 🔴 ran but bypassed kickoff | 🟡 fixes landed + 35 regression tests; smoke pending |
| §4 contract-first (register-before-dispatch) | 🔴 broken in practice | ✅ structurally enforced: `_drive_kickoff_to_completion` blocks the resident lane until `finalize_kickoff` returns `phase="finalized"`; any other phase raises |
| §4 ATDD at kickoff (verifier authors predicates) | 🔴 never entered turn | ✅ Fix #2 wires verifier's `kickoff_request` → LLM turn; macro authors predicate-set draft → `finalize_kickoff` persists it |
| §6.D vertical slice + atomic legacy delete | 🟡 frontend clean | ✅ Python-side legacy `plan(add_task)+task_ready` taught-out of the orchestrator v3 prompt; closed-by-construction by 10-test absence-pin |
| §6.D "no half-deleted dead branches the LLM might still follow" | 🔴 the legacy LLM-direct path WAS such a branch | ✅ taught-out + regression-pinned. The legacy `plan(add_task)` tool itself still exists (used for non-kickoff remediation tasks); §6.D applies to the dispatch *pattern* the prompt teaches, not the tool surface |
| §8 modular (kickoff helpers stay pure) | ✅ | ✅ driver lives on orchestrator class; kickoff functions remain pure Python with no LLM coupling |
| Recovery safety on first real run | untested | ✅ all 6 driver paths regression-tested; finalize_kickoff partial-failure path was tested round-8a |

### REVIEWER ROUND-8b RECONCILIATION

| Reviewer item (round 8b) | Status |
| --- | --- |
| **#1 corrected**: "kickoff coordinator has no DRIVER (not 'kickoff tools missing from LLM surface')" | ✅ Fix #1: Python driver added; reviewer's correction adopted in code + status doc + tests |
| **#2 confirmed**: attendee urgent handler doesn't pump LLM | ✅ Fix #2: explicit `msg_type=="kickoff_request"` branch + handler |
| **#3 confirmed**: legacy LLM-direct path silently fell through | ✅ Fix #3: prompt rewritten with explicit "DO NOT" rules + legacy examples deleted + 10-test absence pin |
| Reviewer's round-8a T=1200s circuit-breaker | ✅ Folded into driver via `synthesize_fallback` helper |
| "All three are needed for one working kickoff; #1+#3 atomic, #2 in the same landing" | ✅ All three landed together this round |
| "Keep the role-gate — it's the closed-by-construction guardrail that caught this" | ✅ Role-gate untouched; the path that was triggering it (design calling register_*) is now gone because finalize_kickoff (orchestrator actor) calls those instead |

### COMMIT + SMOKE DECISION (for reviewer + user)

**I did NOT commit this round.** The working tree carries accumulated
changes from rounds 5-8c (the reviewer has been reviewing uncommitted
state since round 5 per their own rounds-5/6/7/8a/8b verdicts) plus
round 8c. A single squash commit would not be "independently reversible"
per the loop discipline rule, and the system rule "NEVER commit without
explicit user ask" also points the same way. I'd like the user or
reviewer to weigh in:

1. **Squash everything to one round-8c snapshot** — easiest, but it
   buries the round-5/6/7/8a history into one commit.
2. **Replay round-by-round commits via `git rebase --interactive` or
   manual cherry-picking** — preserves history but requires reverting
   the working tree first and recommitting in chronological order.
3. **Leave uncommitted, push only the round-8c artifact docs** — keeps
   the source-of-truth in the working tree; nothing on remote yet.

**I also did NOT re-run the M1 smoke this round.** Reasoning:

- Reviewer's standing round-8b "do NOT iterate past the first integration
  break — surface it cleanly" rule was about *the diagnostic round*; this
  round is the *fix round*. The fixes have closed-by-construction regression
  tests (35 new tests, all green) that cover the round-8b break shape directly
  — the smoke would re-confirm in expensive LLM tokens what the unit tests
  already pin.
- A fresh smoke would have burned ~$5-20 in OpenAI tokens (round-8b burned
  budget on the wrong-flow stalled state for 8 min before I killed it; a
  successful round-8c run would be longer + more expensive).
- The user is on a 15-min wake cadence; I want them or the reviewer to
  sign off on round 8c before sinking a fresh API run.

**My recommendation**: reviewer assesses the 8c source-code-level diff + the
35-test regression set first; if architecturally sound, **8d runs the
smoke** (still on the same `.env.local` API key that's already in place).

### OPEN QUESTIONS FOR REVIEWER

1. Do you agree with the three-fix shape above? Any of the closed-by-construction
   pins (especially the prompt-absence tests) you'd weaken or strengthen?
2. The driver currently treats `conflict` / `validation_failed` as fatal
   (calls `synthesize_fallback` → returns `phase="timeout_fallback"`). Per
   §6.D the reviser dispatch loop "lives in 8d". OK to defer? Or should 8c
   add at least a single revision round before fatal?
3. The Fix #3 prompt rewrite is *surgical* (~6 targeted edits to the
   958-line orchestrator v3 prompt). A full prompt rewrite would be
   cleaner but much higher risk. OK with surgical for now? Anything you
   want to see in 8d's deeper pass?
4. The driver's max_steps for the attendee kickoff-response is 50 (the
   macro says "Run ONCE then finish()"; this is a safety net). Reasonable
   cap, or want it tighter (e.g. 10)?
5. Commit decision per "COMMIT + SMOKE DECISION" above — preference?

### Round 8d plan (proposed — needs reviewer GO)

1. Re-run M1 walking skeleton smoke. Watch for: kickoff_request reaches
   all 4 attendees AND their `.agent_logs/` get populated AND each
   `workhub_add_meeting_decision` lands AND `kickoff_complete` fires
   AND `finalize_kickoff` returns `phase="finalized"`. **Do NOT iterate
   past the first integration break** — round-8b discipline still applies.
2. If kickoff completes cleanly: surface whatever break the smoke hits
   next (validator behavior on real LLM artifacts, contract.normalize
   on real endpoints, docker boot, smoke-test execution).
3. Optionally: deeper orchestrator v3 prompt rewrite if reviewer flags
   residual legacy bleed beyond the surgical 8c delete.
4. Optionally: add the single-round reviser loop to the driver (for
   `conflict` status) per charter §6.D.

---

*Last updated by Claude: round 8c (three layered fixes shipped + 35
closed-by-construction regression tests + 2110-test green sweep + no
commits/smoke pending reviewer/user GO). Awaiting reviewer round-8c
verdict + user direction on the commit + smoke questions above.*
