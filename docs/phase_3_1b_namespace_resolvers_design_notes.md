# Phase 3.1b 4-namespace resolvers + deliverability wiring — Design Notes (workflow `w8z0em332` DEFER)

**Status:** DEFER. Workflow `w8z0em332` (8 agents, 318k tokens, ~6.4 min)
judge-fast-pathed Candidate D (DEFER) over A/B/C SHIP options. No
adversarial review run.

DEFER counter consecutive: 2 (Phase 3.1a + 3.1b back-to-back). One more
DEFER triggers the loop stop condition.

## Verdict

Phase 3.1b would ship a gate that guards air, repeating the exact
failure mode that DEFERed 3.1a ~1 hour ago (commit `a93c11f7`) and the
4.5a/b/c WorkHub bundle (`d1492907`). Four reinforcing reasons:

1. **Zero production callers** for `register_story` today — confirmed
   by grep: only `story_hub.py` itself, `hub_registry.py:128-129`
   (instantiation only, no method invocation), and
   `_role_gate_trace.py:16` (docstring catalog string). An
   evidence-walker over an empty story list is byte-identical to the
   current inert return `{ok: True, stories: []}`.
2. **Roadmap inverts**: `docs/phase_4_plus_roadmap.md:21` explicitly
   lists 3.1b's depends_on as `{3.1a, O2}`. 3.1a is in DEFER (commit
   `a93c11f7`). Shipping the consumer before the producer inverts the
   dependency order.
3. **O2 not landed.** `docs/phase_3_mechanism_design_notes.md` records
   TWO concrete schema-misread regressions that exist BECAUSE Candidate
   C earlier tried this "ship resolvers without canonical-writer-driven
   fixtures" path:
   - BLOCKER B1: `endpoint_contract` reading a non-existent `verdict`
     field
   - Concern C1: visual keying off `page_key` when the writer stores
     `metadata.route`
   The 4 namespaces carry the same regression class today without O2.
4. **Canonical writers not pinned.** Record shapes per namespace need
   documentation BEFORE resolvers read them
   (`probe['verdict']` vs `probe['result']`?,
   `validation_result['result']` vs `['status']`?).

## SHIP candidates rejected

### Candidate A — full 4-namespace + O2 base + deliverability wire in one PR

Violates roadmap depends_on (skips O2-first ordering). Designs the O2
ABC against 4 hypothetical resolvers simultaneously — exactly the
"shared ABC churns when 5th namespace lands" failure mode A's own
self-acknowledged risk admits. "Single mechanism row" framing is
review-management, not real risk reduction: the gate still guards air
today.

### Candidate B — 1 namespace (api_smoke) + minimal O2

Acknowledged silent-pass risk (R1) is the gate-for-gate's-sake hazard:
pass-through for ui_flow/table/mcp means a non-api_smoke-only story
gets `ok=True` with zero verification. Also ships WITHOUT O2 landed
first, so even the api_smoke resolver is schema-misread-vulnerable.
B's own R7 explicitly defers the deliverability fold, meaning operators
see NO surface change today — satisfying the "guards air" DEFER
criterion regardless of B's framing.

### Candidate C — O2 base class ALONE (no resolvers shipped)

**Closer to correct** — IS the O2 unblocker per roadmap line 217 — but
**mislabeled as 3.1b**. C ships only the ABC + self-test, not the 3.1b
story-gate mechanism. C's own risks confirm fragility:

- R1 admits the shared smoke method misfires on the single self-test
  subclass.
- R3 admits `HubRegistry(tmp_path)` side effects may slow the suite.
- R4 admits helper signatures (`runhub.run_start/run_complete`,
  `record_validation_result`) were not end-to-end verified.

**C is the right NEXT step, not the right 3.1b scope.** Picking C
confuses the dependency for the dependent. Recommendation: spin C out
as its own "O2 ResolverFixtureContracts" PR.

## Unblocking conditions for Phase 3.1b

Sequence (must land in this order):

1. **O2 ResolverFixtureContracts** at
   `tests/fixtures/phase_resolver_contracts.py` — non-mocking ABC with
   canonical-writer helpers (`seed_endpoint`, `seed_table`,
   `seed_visual_review`, `seed_ui_flow_result`, `seed_successful_run`).
   Self-test subclass exercises one shipped resolver to validate the
   pattern. Risks R1/R3/R4 must be addressed before merge.
2. **Phase 3.1a register_story actor gate** co-shipped with 3.0
   bootstrap's first real caller. Allowed-set = `{orchestrator, product,
   planner}` via canonical `_role_gate.require_actor` helper (whether
   that's a rename of existing `require_allowed_actor` or a new name).
3. **Canonical writer record shapes documented**. Pin the field names
   for each of the 4 namespaces:
   - `api_smoke`: read `apihub.list_contract_test_results(endpoint_id)`
     — confirm `verdict` field exists today (it does after Phase 4.4
     ship per commit `7272a2fc`).
   - `ui_flow`: read `record_validation_result` — confirm field name
     (status vs result vs ok).
   - `table`: read `schema_hub` + seed audit — confirm seed-audit
     record shape.
   - `mcp`: read MCP probe records — confirm field name.
4. **Real story author exists.** Either:
   - An orchestrator code path that calls `registry.story_hub.register_story(...)`
     during normal delivery flow, OR
   - A planner/product agent v3 prompt that includes a `register_story`
     call as part of the delivery-plan slice.
5. **Deliverability hook design.** Pin where in `deliverability.py`
   `evaluate_story_gate` plugs in (workflow discovery suggested
   `deliverability.py:241-242` as the natural site, parallel to
   `_flow_coverage_summary`).

## Risk if shipped anyway

Schema-misread regression class (BLOCKER B1 / concern C1 redux): a
resolver that reads `probe['verdict']` when the writer stores
`probe['result']` will silently return `evidence_pending` for every
real probe and `delivered` for every empty-probes story — inverting the
gate's intended semantics. O2 was explicitly engineered to prevent
this. Deliverability already enforces six other signals (RunHub
success, probe pass-rate, coverage, seed audit, visual reviews, flow
coverage), so deferring 3.1b loses zero attack surface.

## Out of scope

- Spinning C (O2 ResolverFixtureContracts) out as its own PR this
  session — the loop directive sequences `Phase 3.1a → 3.1b → final
  audit`, and shipping O2 off-queue would expand scope. Reserve for a
  follow-up session with explicit user signal.
- Designing the canonical writer schema lock-in — that's the work that
  belongs in the O2 PR.

## Workflow stats

- 8 agents, 318k tokens, ~6.4 min wall-time.
- 3 parallel discovery agents (evaluator-shape / namespaces / O2-status).
- 4 candidates (A: full / B: 1-ns api_smoke / C: O2-only / D: DEFER).
- Judge picked Candidate D fast-path; adversarial review skipped.
- Full output: `/tmp/claude-1052/.../tasks/w8z0em332.output`.
