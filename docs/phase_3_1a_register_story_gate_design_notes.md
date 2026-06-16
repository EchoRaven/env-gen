# Phase 3.1a `register_story` actor gate — Design Notes (workflow `wx3el8bur` DEFER)

**Status:** DEFER. Workflow `wx3el8bur` (8 agents, 367k tokens, ~13 min)
judge-fast-pathed Candidate D (DEFER) over Candidates A/B/C SHIP options.
No adversarial review run (judge convergence sufficient).

DEFER counter consecutive: 1 (Phase 3.0-bootstrap SHIPPED reset counter,
this is the next DEFER after).

## Verdict

ZERO production callers of `register_story` or `evaluate_story_gate`
exist today. Discovery confirmed:

- `runtime/hub_registry.py:128-129` instantiates `StoryHub` but never
  invokes its methods.
- `runtime/_role_gate_trace.py:16` is a docstring listing — not a call.
- `tests/test_phase_3_story_hub_inert.py` is the only invoker.

A gate here would guard air. `evaluate_story_gate` with zero registered
stories trivially returns `{ok: True, stories: []}` per the Phase 0.3
inert design.

This is the same pattern that produced the Phase 4.5a/b/c DEFER bundle:
lock-without-mechanism + zero-caller = gate-for-gate's-sake.

## Why each SHIP candidate failed

### Candidate A — `{orchestrator}` only at phase>=3.1

Closest of the three SHIP options but wrong on three counts:

1. **Allowed-set too narrow.** Roadmap `docs/phase_4_plus_roadmap.md:20`
   documents `{orchestrator, product, planner}` for 3.1a — not just
   orchestrator. Product + planner are the lanes the roadmap explicitly
   names as story authors; locking them out would force a future
   round-trip.
2. **Invented a new ladder rung.** A picked `phase>=3.1` to preserve
   `test_phase_3_still_inert_byte_identical` (which pins phase=3.0 and
   asserts `baseline == phase3`). The roadmap and
   `docs/phase_3_mechanism_design_notes.md` target `phase>=3.0` with
   the canonical idiom. The right move is to fold into 3.1b once
   preconditions land, not to invent 3.1.
3. **Hand-rolled gate body.** A uses `require_allowed_actor` inline
   rather than the documented canonical `_role_gate.require_actor`
   helper (roadmap O1, line 216). Design-notes C2 explicitly flagged
   this divergence as REJECT-grade.

### Candidate B — `{orchestrator, design}` at phase>=3.1

Invents a `design` admit lane not in the roadmap-canonical
`{orchestrator, product, planner}`. The rationale leans on
`agent_metadata.py:23` ("Creates architecture and specifications") to
justify design as the story author, but the roadmap and
`docs/progressive_elaboration_refactor.md` §Phase 3 consistently frame
stories as planner/product/orchestrator-authored delivery-plan slices,
not design-authored specs. Same threshold-invention + hand-rolled-gate
flaws as A.

### Candidate C — `{orchestrator, design, architect_reviewer}` at phase>=3.1

Three compounding problems:

1. **Invents TWO unsupported admit lanes** (design, architect_reviewer)
   against roadmap-canonical `{orchestrator, product, planner}` on a
   "widest defensible" theory — exactly the opposite of
   closed-by-construction.
2. **Locks `evaluate_story_gate` (read-side) too.** Design notes
   explicitly recommend leaving the gate evaluator open ("document as
   planner responsibility, not runtime-enforced"). Anchor M precedent:
   Phase 4.6 locked only `submit_review` while leaving
   `open_pull_request` / `request_review` / `record_check` open.
3. **DROPS active invariant tests.** `test_phase_3_still_inert_byte_identical`
   + `test_phase_3_still_passes_inert` are currently passing in CI;
   removing them would be a regression of a shipped gate, not a refactor.

## Unblocking conditions for a future ship

Verbatim from the roadmap + workflow judgment:

1. **Phase 3.0-bootstrap** lands (StoryHub plumbing + hub_registry
   injection wired with a real orchestrator/planner caller). **DONE
   2026-06-01 at commit `207dc0c1`** — but the "real orchestrator/planner
   caller" part is not yet present; today's wiring is just the handle.
2. **O1 `_role_gate.require_actor` canonical helper.** Functionality
   already present as `require_allowed_actor` + `require_runtime_actor`
   in `runtime/_role_gate.py`, but the roadmap calls for a
   `require_actor` canonical name that standardizes:
   - `.strip().lower()` actor normalization (closes C2 normalization
     drift)
   - empty-actor fallthrough
   - `PermissionError` text carrying `ELABORATION_REFACTOR_PHASE` + actor
     + allowed-set
   The shipped helpers admit empty-actor fallthrough but the lower-case
   normalization + canonical name are open.
3. **O2 `ResolverFixtureContracts`** at
   `tests/fixtures/phase_resolver_contracts.py` — non-mocking,
   canonical-writer-driven shared test base. PRIMARY correctness gate
   for 3.1b that 3.1a's tests depend on. Roadmap line 217 marks
   READY-to-design (not landed).
4. **Co-ship strategy.** Per
   `docs/phase_3_mechanism_design_notes.md` §"Recommended next-PR
   scope", fold 3.1a INTO 3.1b — the mechanism PR that carries the
   4-namespace resolvers + `evaluate_story_gate` body. 3.1b will
   naturally need an actor gate on `register_story` because that's
   where stories enter the persistence layer.
5. **Optional O5 autogen activation-log.** Eliminates the 3-of-4-file
   lockstep maintenance burden flagged at roadmap line 66. PARTIALLY
   SHIPPED — autogen mechanism table + sync test exist
   (`test_activation_log_autogen_in_sync.py`).

## What changes (if anything) before next attempt

Recommend the next implementer:

- **Land O2 first** (ResolverFixtureContracts base class). It's the
  primary correctness gate for the 4 namespaces + the test pattern
  3.1a/3.1b/3.5/3.9 all consume.
- **Decide on O1 canonical naming.** Either rename
  `require_allowed_actor` → `require_actor` (breaking change to all 11
  shipped gates) OR document the existing shipped names as the
  canonical helpers and skip the rename. The roadmap should be updated
  to match whichever path is chosen.
- **Then ship 3.1a + 3.1b as one PR** with allowed_set
  `{orchestrator, product, planner}` per the documented plan.
  `register_story` gate uses the canonical helper; `evaluate_story_gate`
  stays open (read-side); ResolverFixtureContracts subclass exercises
  the canonical-writer path.

## Workflow stats

- 8 agents, 367k tokens, ~13 min wall-time.
- 3 parallel discovery agents (callers / patterns / intent).
- 4 candidates (A: orchestrator-only / B: orch+design / C: widest /
  D: DEFER).
- Judge picked Candidate D fast-path; adversarial review skipped per
  workflow short-circuit.
- Full output: `/tmp/claude-1052/.../tasks/wx3el8bur.output`.

## Out of scope

- Renaming `require_allowed_actor` → `require_actor` for canonical
  parity. Would touch all 11 shipped gates + helper module + tests.
  Defer until 3.1a/3.1b co-ship demands it.
- Designing/implementing O2 ResolverFixtureContracts here. That's its
  own workflow (depends_on for 3.1b/3.5/3.9 + roadmap-marked P0).
