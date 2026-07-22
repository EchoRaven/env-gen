# forgingground-gen — full pipeline review, weak points & fix plan
Date: 2026-07-21 · Author: code review (Netflix bring-up context) · Scope: `agent/env_generator/llm_generator/multi_agent/`

Source: 6 focused read-only code reviews (design convergence, orchestrator/kickoff wakes,
implementation lanes+UI wiring, verification/delivery/debugger, context/condensation/phase).
No generation run was used — all evidence is from code. Line numbers cite files as of this date.

---

## 1. End-to-end architecture map

Lifecycle is **KICKOFF → IMPLEMENTATION → VALIDATION → DELIVERY**, driven by a deterministic
`run()` loop in `orchestrator.py`; the LLM lanes do the authoring, the framework does the gating.

1. **Design prep (pre-kickoff, blocking).** `orchestrator.py` run() awaits `_compile_reference_materials`
   → `write_skeleton_design_system` (deterministic measured skeleton) → `_spawn_design_analyst`
   (one-shot subagent, **blocking up to 1800s**, `orchestrator.py:2280`) → fallback
   `run_design_prep` single-shot enrich → `complete_design_system` deterministic completion floor
   (`design_prep.py:689`). Output `design_system.json` is consumed by frontend scaffold
   (`frontend_scaffold.py:1688`), the visual gate (`visual_fidelity.py:180`) and requirements.
2. **Kickoff.** Orchestrator chairs a meeting; lanes author the contract via `kickoff_declare_*`;
   `finalize_kickoff` (`run_kickoff.py:1829`) registers the canonical endpoint/table set to
   RegistryHub (status `defined`) and mints the impl task tree. `KickoffBootstrapGate` keeps
   backend/frontend/verifier/debugger dormant until finalize (`workflow_policies.py:165`).
   "In kickoff" = `not kickoff_finalized_signal(...)` (`preconditions.py:478`).
3. **Implementation (concurrent, contract-coordinated).** `_dispatch_implementation_phase`
   (`kickoff_driver.py:708`) fans out `task_ready` to backend AND frontend together. Both wire
   against the **contract** (RegistryHub), not against each other's code. Backend self-declares
   `register_endpoint(status='implemented')` (`registryhub.py:220`); frontend `implemented` is
   **code-audited** (`frontend_audit.py:633`). Truth is reconciled to served-code by
   `backend_audit.sync_endpoint_statuses` (`backend_audit.py:202`) in the heal pipeline.
4. **Validation.** Deterministic `_maybe_run_framework_validation` (~60s cadence) →
   `FrameworkValidation.maybe_run` (`framework_validation.py:419`) gates on
   `all_business_endpoints_implemented` (`lifecycle.py:143`) then runs api_smoke (docker boot +
   live probe of every business endpoint + business_chain). A pass records a RunHub run = the
   delivery evidence. Visual-fidelity gate runs after api_smoke passes (`visual_fidelity.py:1504`).
5. **Delivery.** Only the deterministic `_maybe_framework_deliver` cuts a release, gated on
   `validate_delivery_gate` (`delivery_gate.py:1013`) with a final hard re-check that raises
   `RuntimeError` if not ok (`orchestrator.py:1769`). The LLM `deliver_project` only sets an event.

Cross-cutting: a resident-agent poll (`base.py:715`, 0.5s) wakes lanes on subscribed hub events;
a message-count condenser (`generator_memory.py:1333`) summarizes history at step boundaries.

---

## 2. Weak points (ranked, with evidence)

### Tier 1 — burns the key / stalls the run (fix first)

**W1. design_analyst is a redundant, blocking stage that doesn't converge.**
The subagent has no `max_steps`/tool budget (`agents_config.yaml:1617`), an open-ended prompt goal
("measure EVERY component", `design_analyst.j2:66,99,117`), and the global stuck-detector is OFF
(`base.py:495`, `enable_stuck_detection=False`). It grinds vision calls for up to 30 min, still on
"Step 1/2000", then times out to the fallback — which already produces the authoritative doc.
It is **not on the correctness path** (deterministic enrich + completion floor do the same job,
`design_prep.py:613,689`). Net cost of its failure: a 30-min serialized block + wasted key.
*Observed live in r3 (~880 vision calls, 0 writes) and, per code comments, in runs 5–6.*

**W2. Orchestrator wake-storm during kickoff/design.** The orchestrator alone has **no
`KickoffBootstrapGate`** (`agents_config.yaml:196-203`), so unlike the impl lanes it is not
suppressed pre-finalize. It subscribes **live** to `endpoint_implemented` (`agent_subscriptions.py:34`)
and `meeting_decision_added` (`:41`); each such event during design/kickoff triggers a full LLM
step that concludes "ineligible during kickoff" and stops. On rate-limited GPT-5.6 these idle
wakes spend scarce quota on nothing. (r3: 146 idle stop-cycles.) The `meeting_decision_added`
wake is vestigial — synthesis is actually driven by pure-Python `_drive_kickoff_to_completion`.

**W3. Condensation thrash on large-context models.** `should_condense_messages` triggers on raw
**message count > 50** (`generator_memory.py:1333`, `base.py:579`), keeps 28, and the ~7-stage
pipeline adds 6–12 messages/step → re-condenses every 2–4 steps, each an **LLM call**, even on
1M-context models whose real budget (~2.5M chars, `model_limits.py:145`) is nowhere near full.
No cooldown, no token guard. The modern per-model char sizing governs only the *masking* layer
(`llm.py:206`, `step_runner.py:808`), which never talks to the condenser.

**W4. Condensation handoff is phase-blind.** Every condense injects a hardcoded "RESUME NOW:
write code" directive (`generator_memory.py:323`) regardless of `_active_phase` — so during
kickoff the coordinating orchestrator is repeatedly told to "write code," by the W3 thrash loop.

### Tier 2 — app-quality gaps (the "complete functionality / all UI wired / matches screenshots" goals)

**W5. Runtime per-control correctness is advisory-only.** `control_exercise.py` is the only
mechanism that catches "a control that renders but does the WRONG thing — posts to the wrong
endpoint, shows success on a failed call, navigates nowhere" (`control_exercise.py:1-20`). It is
exposed only as an optional LLM tool (`control_audit.py:17`) at the test-user agent's discretion,
**feeds no hard delivery gate**. Deterministic enforcement falls back to *static* checks that
can't see a bound-but-wrong-wired control. This directly undercuts the "every UI control wired to
a real backend action, no dead links" requirement.

**W6. Visual-fidelity judge is effectively non-blocking and gameable.** ±0.3–0.4 self-admitted
judge noise (`visual_fidelity.py:916`), a **sticky one-time-pass latch** (`:1452`, regression
caveat at `:1447`), a guaranteed "escape → deliver below threshold" path (`orchestrator.py:297,2792`),
and it is **not** in `validate_delivery_gate.failed_checks` — so it can only delay a release, never
fail one. The judge is also instructed to ignore content/empty-states (`:611`), so a
visually-plausible but wrong UI scores high. Undercuts "match every reference screenshot exactly."

**W7. Two divergent dead-control token lists.** `frontend_audit._HANDLER_TOKENS` recognizes the
default `api.`/`await api` service style (`frontend_audit.py:46`), but the inline check in
`validation_runner.py:747` uses a shorter hardcoded list that **omits** them → the same page gets
inconsistent dead/alive verdicts across gates. A stale copy.

**W8. Backend `implemented` is self-declared; the finish-gate reconcile is default-OFF.** Status
flips on the lane's own `register_endpoint` with no code check (`registryhub.py:220`); the demote-
unserved reconcile runs only if `ENVGEN_SYNC_STATUS_AT_FINISH` is set (`preconditions.py:95`).
Between a lane's `finish` and the post-merge heal audit, `all_business_endpoints_implemented` can
be driven by unverified flags. (api_smoke is the real backstop, but the signal can mislead gates.)

### Tier 3 — robustness / hygiene

**W9. Delivery waivers can flip a red final gate green.** `_final_gate_drift_waiver`
(`orchestrator.py:1786`) forces `ok=True` for `business_chain_failing`/`verification_checklist_not_ready`
within 900s of a fresh clear verdict; `convergence_grace` (`delivery_gate.py:902`) extends the
abort deadline. A real regression coinciding with a recent clear is indistinguishable from benign drift.

**W10. `validation_ready_signal` latches and cannot regress** (`preconditions.py:512`). A business
endpoint declared/registered after the latch — or one a UI control targets that's never implemented
— won't re-gate validation. Compounded by kickoff `dead_endpoint_severity="info"` default
(`cross_check_suite.py:170`).

**W11. `_all_business_endpoints_have_route_code` escape matches only a coarse resource token**
(`orchestrator.py:2313`, OR-branch at `:2482`) — no METHOD/variant check, so a specific variant a
UI control calls can be unserved while delivery opens.

**W12. Debugger churn + unlatched re-block.** Post-finalize `run_completed` still wakes the
debugger and burns rounds; `bug_triage` is ungated and the verifier's `bug_create` has no
validation gate; `validation_phase_reached` is unlatched (`preconditions.py:630`) → false re-block
in multi-milestone runs, and fail-open on error.

**W13. Per-page `apis_used` is matched against the whole concatenated source tree**
(`frontend_audit.py:279,353`), so "page X wires endpoint Y" isn't proven per-page — reinforces W5.

**W14. Dead code.** The entire `context_management.py` `AdvancedContextManager` stack (~1000 lines,
incl. an unused `TaskPhase` enum) is instantiated (`base.py:589`) but never called. Misleading.

**W15. Scattered/transient phase truth.** `_active_phase` is a per-lane string set only while a
handler is on the stack, restored via 9 hand-maintained pin/restore pairs; no global "run phase".
Fragile invariant (already the documented cause of the "drift into get_document instead of coding"
bug, `base.py:800`). No `design` phase exists.

---

## 3. Fix plan (sequenced; each is a small, testable diff)

Guiding principle (agreed): surgical fixes over architectural rewrites; do **not** re-introduce a
first-class `design` phase (it was retired in round 8e.1 for a chicken-and-egg deadlock, and the
sequencing it would give already exists — design already runs before kickoff).

### Phase A — stop wasting the key + unblock the pipeline (do first; ~1 day)

- **F1 (W1):** In `_spawn_design_analyst` path, lower `ENVGEN_DESIGN_ANALYST_TIMEOUT` default
  `1800`→`300` (`orchestrator.py:2280`) **and** add an env gate to skip the subagent entirely and
  go straight to `run_design_prep` + `complete_design_system` (`orchestrator.py:2207`). Default the
  subagent OFF for now — the deterministic path is authoritative. *Supersedes the design_analyst
  allowlist commits already staged (ea2458f/25a8484): those enabled the vision tools that caused
  the over-analysis; with the subagent off they're moot but harmless.*
- **F2 (W2):** Move the orchestrator's `endpoint_implemented` (`agent_subscriptions.py:34`) and
  `meeting_decision_added` (`:41`) subscriptions to `delivery="inbox_only"` (the no-wakeup mode,
  `:162`), keeping `kickoff_facilitate_request`/`kickoff_detail_request` live. Verify no
  post-kickoff handler needs a *live* `endpoint_implemented` (analysis says no; the coordination
  tick polls). Kills the wake-storm.
- **F3 (W3):** Gate `should_condense_messages` on `resolve_ctx_working_chars(model)` chars instead
  of raw message count (`generator_memory.py:1333`), and add a min-steps-between-condensations
  guard (e.g. ≥6). Aligns the condenser with the masking layer; kills the thrash on 1M models.
- **F4 (W4):** Make condensation phase-aware — skip it (or swap the RESUME directive) while
  `_active_phase == "kickoff"` (`step_runner.py:228`, `generator_memory.py:323`).

Phase A removes the three big key-burners (30-min design block, idle orch wakes, re-condensation
LLM calls) and lets a run flow kickoff→impl→validation cheaply. Re-run Netflix after this.

### Phase B — enforce app quality (the Netflix "complete/wired/pixel-faithful" goals; ~2–3 days)

- **F5 (W5+W13):** Promote per-control correctness from advisory to a **delivery gate**: run
  `control_exercise` deterministically in the validation runner over the seeded app and feed its
  verdict (dead / off-contract / 5xx-swallowed) into `deliverability` blockers. This is the single
  highest-leverage quality fix for "every UI control wired to a real backend action."
- **F6 (W7):** Dedupe the dead-control token list — have `validation_runner.py:747` import
  `frontend_audit._HANDLER_TOKENS` instead of its own stale copy.
- **F7 (W6):** Decide the visual judge's role: either (a) keep advisory but **report it honestly**
  (don't imply pixel-match is gated), or (b) tighten — remove the sticky pass latch, raise
  `min_similarity`, and stop instructing it to ignore content — if we want it to actually gate
  fidelity. Recommend (a) + a small similarity-floor block for the landing/browse hero screens.
- **F8 (W8):** Default `ENVGEN_SYNC_STATUS_AT_FINISH` ON (or always run the served-code reconcile
  at finish) so `implemented` reflects served routes before the signal drives any gate.

### Phase C — robustness/hygiene (opportunistic; ~1–2 days)

- **F9 (W9):** Tighten the two hard-gate waivers — require the "recent clear verdict" to be for the
  *same* contract revision, not just within 900s.
- **F10 (W10/W11):** Make `validation_ready_signal` re-open when new business endpoints register
  post-latch; replace the coarse-token route-code escape with a METHOD+path-variant check.
- **F11 (W12):** Latch `validation_phase_reached` like `validation_ready_signal`; gate the
  verifier's `bug_create` and `bug_triage` on validation phase to stop pre-validation churn.
- **F12 (W14/W15):** Delete the dead `context_management.py` manager stack; add a single
  read-only `run_phase()` helper as the source of truth (leave the pin/restore for now).

---

## 4. Notes / carry-overs
- Already staged, unpushed on `feat/netflix-metagen-sidecar` (needs your push — agent egress 403):
  sidecar v14/v15/v16 (`auto_rate_limit`) + design_analyst allowlist (superseded by F1).
- GPT-5.6 (`gpt-5-6-sol-genai-responses`) works (text+tools); rate limit is tight — Phase A's
  key-burn removal matters most for staying under it. Fable/5.5 currently access-denied on the key.
- Recommend implementing **Phase A only**, then re-running Netflix to measure before Phase B/C.
