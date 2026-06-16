# Historical design docs

This directory archives docs from the **ELABORATION_REFACTOR_PHASE** era
(2026-04 → 2026-06-02). That refactor staged 22+ runtime gates behind a
single env-var dial (`PHASE_LEGACY` → `PHASE_4_7`), giving A/B safety as
each ownership move shipped.

**As of 2026-06-02 the phase machinery has been removed**. The highest-
phase behavior is now permanent and unconditional:

- backend owns `spec.database.json` + `spec.api.json`
- design owns UI/UX artifacts only
- verifier authors contract tests; only RunHub authors probe records
- gate_registry, story_hub, mcp_registry, codehub: authorship locked
  to documented lanes
- EventHub subscription/publish identity gates always on

These docs are retained for **operator reference**: incident write-ups,
ladder rationale, and the historical reasoning behind specific
allowlists. They are NOT load-bearing for any current code path.

If you need the prior gating semantics for an investigation, look here
first; the code itself no longer references them.
