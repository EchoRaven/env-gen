# Pipeline Supervision Charter

Governing standard for the env-gen pipeline. The reviewer (Claude, in a /loop)
supervises every round against THIS document + `docs/plan_kickoff_refactor.md`.
Trust the code, never the status doc. This is a living doc — update it here first
if the target shifts.

---

## 0. Role

Primary role: **reviewer**. Expanded mandate: **supervise the whole pipeline toward
the goal** — flag architectural drift from the target SDLC, not just code bugs.
Review-on-change via the supervision loop (watches `docs/refactor_status.md`).
The reviewer does NOT implement; it verifies, probes, and steers.

## 1. The Goal

A pipeline that generates web environments that are: **(a) low-bug, (b) feature-complete,
(c) produced by a clear, auditable development process.** The proof of the goal is a real
end-to-end generation that passes its milestone acceptance gates — not a green unit suite.
(End-to-end has never succeeded; take2 stalled at 13min/0 ticks. Closing that is the point.)

## 2. Target Architecture — the hybrid SDLC (decision)

Not agile-vs-spiral as a binary. The model is:

> **Iterative-incremental backbone + spiral risk-first M1 (walking skeleton) +
> contract-first / acceptance-at-kickoff as the cross-cutting discipline.**

Rationale (grounded in this pipeline's real failure classes):
- **Contract drift / integration breakage** (frontend calls an endpoint backend didn't build;
  field-name mismatch) → killed by **contract-first**.
- **Big-bang generation that never runs** → killed by **walking skeleton + per-slice verify**.
- **Spec drift / missing features** → killed by **global feature inventory up front, incremental build**.
- **LLM context/attention limits** → small, verifiable per-agent tasks beat monolithic ones →
  favors **vertical slices**, not horizontal layers.

## 3. Milestone Model

- **M1 = walking skeleton (risk-first).** Thinnest end-to-end slice that exercises every layer:
  `auth + 1 core entity + 1 CRUD flow + boots in docker + 1 passing smoke test`. Minimal features,
  but the whole stack wires up and RUNS. De-risks the #1 unknown ("does it run end-to-end").
- **M2…Mn = vertical feature slices.** Each milestone adds a feature slice (a few endpoints +
  their UI + their tests) that is independently runnable and verifiable. **Vertical, never
  horizontal** (no "all backend, then all frontend" — that re-creates big-bang).
- **Re-kickoff per milestone** carries the prior milestone's verification results forward, so
  drift is caught and corrected early (agile retro + spiral evaluate).
- **Global plan at M1, incremental execution.** The M1 kickoff derives the FULL feature inventory
  (all entities/flows from requirements) and lays out ALL milestones up front, even though one is
  built at a time. Coverage is planned globally → guards feature-completeness.

## 4. Core Discipline — contract-first + acceptance-at-kickoff (highest leverage)

The single biggest bug-reducer for generated code:
- The kickoff **registers the milestone's API/data/auth contract to APIHub BEFORE any
  implementation task is dispatched.** Every agent codes against the same registered contract →
  the contract-drift bug class is structurally eliminated.
- The **verifier writes machine-checkable acceptance predicates per critical flow DURING the
  kickoff** (before build). Those predicates are the milestone gate. This is ATDD/test-first at
  milestone granularity — build is judged against predicates defined ahead of it, not invented after.

## 5. Kickoff Meeting — required outputs (per milestone)

Each milestone's kickoff MUST produce:
1. **Contract delta** — API endpoints + data model + auth, **registered to APIHub**.
2. **Task tree** — WorkHub tasks with `owner` + `depends_on` + `kind` (the workflow).
3. **Acceptance predicates** — verifier-authored, machine-checkable, per critical flow.
4. **Definition of Done** for the milestone.
5. (M1 only) **Global milestone plan** — full feature inventory + slice ordering.

## 6. Per-round Review Rubric (what the reviewer verifies each round)

**A. Correctness (trust code, not doc):** independently confirm each claimed change at file:line;
REFUTE with counter-evidence where the claim is wrong.

**B. Guardrail integrity:** the roster-consistency invariant
(`agent/tests/test_roster_consistency_invariant.py`) must stay **non-vacuous** — probe by injecting
a synthetic phantom (inject → run → confirm RED → remove) whenever a round touches prompts/tools/gates.
No false-green.

**C. Cleanup discipline (carried over — user-directed):** no fallback / no back-compat;
delete-don't-skip; no phantom-ID defaults; small closed-by-construction tests, not exhaustive
matrices; prompts/docs describe the new world only. If a caller breaks, fix the caller, not a shim.

**D. Architecture alignment (the supervision layer):** does the round advance §2–§5?
- Is work contract-first (contract registered before implementation)?
- Are slices vertical and independently verifiable (not horizontal layers)?
- Are acceptance predicates defined at kickoff, before build?
- Is M1 a true walking skeleton (runs end-to-end), not a feature dump?
- Is the legacy design-submit-review flow being DELETED as kickoff replaces it (not left as a
  dead branch the LLM might still follow)?
- Flag any architectural drift loudly, even if the code is locally correct.

**E. Progress toward goal:** state, each round, how much closer we are to a real end-to-end
generation passing its acceptance gates.

Review is written to `docs/refactor_review.md` with sections: CONFIRMED FIXED / REFUTED /
NEW RESIDUES / ARCHITECTURE ALIGNMENT / DECISIONS NEEDED FROM USER.

## 7. Definition of Done — "GOAL MET" (loop stop condition)

The supervision loop stops only when the pipeline **demonstrably meets the goal**: a real
end-to-end generation runs through the kickoff→build→verify process and **passes its milestone
acceptance gates** (low-bug: gates green; feature-complete: full inventory covered; clear process:
the milestone task tree + kickoff artifacts are auditable). At that point the reviewer writes
`VERDICT: GOAL MET` on its own line in the review file. Until then, keep supervising.

## 8. Standing Risks to Watch

- Contract drift / field-name mismatch across agents (the dominant generated-code bug class).
- Coordination stalls / polling (the 19-hour stall; design-stall-until-kickoff-wired).
- Spec drift (model reframes the domain; wrong entity/endpoint counts).
- Oversized files growing further (orchestrator.py will grow with run_kickoff — keep kickoff
  helpers modular: roadmap_validator / cross_check_suite / arbitration_table / ready-set as a
  pure function, separate from the polling loop).
- False-green: unit suite passing while the real path is broken (the recurring lesson — always
  probe + trust the code).
- No end-to-end signal until run_kickoff is wired — first real validation waits until then.

## 9. Roster Decision Record (2026-06-02)

**Proposal considered:** merge 7→5 lanes — design+frontend → "UI lane"; verifier+debugger → "quality lane".
**Decision: REJECTED for now; do NOT re-roster before a green M1 smoke.** (Evidence-based, 3-agent analysis.)
- **design+frontend — do not merge.** `spec.ui.json` is a cross-cutting *release contract* the
  orchestrator, deliverability gate, and verifier flow-coverage all gate on — NOT just frontend's input.
  The kickoff `ui_pages_vs_user_flows` cross-check is deliberately adversarial between two independent
  authors; the split suppresses the documented v2 spec-drift pathology. Backend's data+API precedent does
  NOT transfer (it merged two spec artifacts under one owner with no other consumers; this would merge
  spec-author + implementer across a contract three lanes consume).
- **verifier+debugger — do not merge.** Cutover-10 detect/triage/fix is a deliberate integrity firewall
  (a detector that owns disposition can rationalize its own findings). One-directional producer/consumer
  with opposite runtime disciplines (single-pass-no-poll vs queue-pumper); debugger is lean + M2-only.
- **Reframe:** coordination cost is concentrated in the **4 kickoff SECTION owners**, not the 7 lanes.
  Non-attendees (debugger, knowledge) are cheap; merging them barely reduces real complexity. The only
  merge that shrinks the kickoff machinery is an *attendee* merge — highest blast radius, destroys a
  separation. The 7-lane roster is not carrying much fat.
- **Timing:** re-rostering mid-Phase-C invalidates the pending 8d smoke and destroys the clean diagnostic
  (can't attribute an 8d failure to kickoff-wiring vs re-roster). Revisit ONLY after a green M1, and even
  then the payoff is small.

---

*Living doc. The supervision loop surfaces charter gaps as Phase C reveals reality; update here first.*
