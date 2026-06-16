# Phase 3.5 endpoint_contract namespace — Design Notes (SHIPPED Path B)

**Status:** ✅ SHIPPED at `e1053908` via **Path B simplified**
(2026-06-01). The original DEFER below was based on the assumption
that 3.5 must co-ship with a widened Phase 4.4 admitting
`contract_test_runtime` — Path B sidesteps this entirely: ship the
resolver + verdict-field amendment now without touching the
`{verifier}`-only allowed_set. The phantom stays parked indefinitely
per `phantom_runtime_registry.md` until a real runtime caller is
introduced. Anchor P at `apihub.py:486+`.

**Original DEFER rationale (preserved for context):** Phase 3.5
enables the `endpoint_contract:<endpoint_id>` resolver in story_hub,
but ships as a **co-ship with Phase 4.4** per the roadmap R2
round-11 critique (line 86): shipping 3.5 alone gates no authorship,
recreating BLOCKER B1's failure class one layer up. Phase 4.4
(`record_api_test` authorship lock) is already SHIPPED at the 14th
mechanism. Phase 3.5 mechanism + resolver implementation remains the
open work.

This doc captures what the next implementer needs.

## What ships in Phase 3.5

Per `docs/phase_4_plus_roadmap.md` lines 84-90:

1. **`record_api_test` verdict-field amendment** at `apihub.py:442-451`:
   write an explicit top-level `verdict` field derived from:
   - `result.get("passed")`, OR
   - `result.get("result") == "pass"`, OR
   - `200 <= status_code < 400`

   Original `result` dict is preserved unchanged (forward+backward compat).

2. **`list_contract_test_results_sorted(endpoint_id, by='created_at',
   desc=True)`** — SHIPPED at commit `83fc0fea` per the prior O7
   audit. The accessor returns endpoint_contract evidence sorted so
   the resolver consumes `[0]` (latest) reliably.

3. **`endpoint_contract:<endpoint_id>` resolver in story_hub** —
   adds a 5th namespace handler to `_DEFAULT_RESOLVERS`:

   ```python
   def _resolve_endpoint_contract(reg, target_key):
       endpoint_id = target_key[len("endpoint_contract:"):].strip()
       results = reg.apihub.list_contract_test_results_sorted(endpoint_id)
       if not results:
           return "evidence_pending"
       latest = results[0]
       # Phase 3.5 verdict-field amendment makes this lookup non-ambiguous
       if latest.get("verdict") == "pass":
           return "pass"
       if latest.get("verdict") == "fail":
           return "fail"
       return "evidence_pending"
   ```

4. **Story-hub resolver registry registration**:
   - Add `"endpoint_contract:"` → `_resolve_endpoint_contract` to
     `_DEFAULT_RESOLVERS` in `runtime/story_hub.py`.

5. **Tests**:
   - Subclass `PhaseResolverFixtureContracts`:
     `TestEndpointContractResolver(PhaseResolverFixtureContracts,
     unittest.TestCase)` with `target_key="endpoint_contract:<id>"`,
     `declared_record_fields={"endpoint_id", "verdict", "created_at"}`,
     `build_evidence(reg)` seeds via canonical
     `apihub.register_endpoint` + `apihub.record_api_test`.
   - Mechanism test: two contract_test records written 100ms apart for
     the same endpoint_id; resolver must see the **later** record's
     verdict (closes the original Candidate C `results[-1]` bug per
     roadmap line 89).
   - Status-helper count bump: 17→18 mechanisms (the
     verdict-field amendment is a new `_MECHANISMS` row at phase=3.5).

## Why this hasn't shipped autonomously

The Phase 3.5 work itself is mechanical, but the schema-misread
regression class it introduces is high-stakes:

- `record_api_test` has **8+ existing callsites** (per the O15
  callsite audit). Every site already passes `agent="verifier"`, so
  the Phase 4.4 authorship gate doesn't break them. But the
  **verdict-field amendment** changes the persisted dict shape — any
  downstream consumer that does `record.get("status")` instead of
  `record.get("verdict")` silently breaks.
- The `result.get("passed")` / `result.get("result")` / `status_code`
  derivation rules need an audit pass against every existing test
  fixture so the derivation matches what the current pipeline writes.

This is exactly the BLOCKER B1 / concern C1 schema-misread class that
O2 ResolverFixtureContracts (commit `0e25cd5c`) was engineered to
prevent. A TestEndpointContractResolver subclass with
`declared_record_fields={"endpoint_id", "verdict", "created_at"}`
catches any writer drift at test time — but the **derivation rules
themselves** need to be verified against production fixtures (e.g.
the `tests/test_hub_pulse.py:62` callsite that probably uses
`status_code` rather than `passed`).

## Unblocking conditions

1. **Schema migration audit**: enumerate every existing
   `record_api_test` callsite + check what fields each one writes into
   `result`. The verdict derivation rule order
   (`passed → result==pass → 200≤status_code<400`) must cover every
   real call shape.
2. **TestEndpointContractResolver subclass** ready to use O2 seeds.
3. **`_role_gate.require_runtime_actor` upgrade**: Phase 4.4 already
   admits `{verifier}`; co-shipping requires expanding to
   `{verifier, contract_test_runtime}` (matches Phase 2.5
   `record_probe` runtime-only idiom). `contract_test_runtime` is a
   phantom identity today — needs to be a real runtime principal
   before the gate widens to admit it.

## Workflow stats

(No workflow run yet for Phase 3.5; this doc establishes the briefing
so the next workflow can pre-bake the 8-callsite audit fixes as
Candidate A.)

## What's NOT in scope here

- Phase 4.4 widening to `{verifier, contract_test_runtime}` — needs
  the runtime principal pinned first.
- Phase 3.9 visual namespace (separate doc).
- Phase 3 mechanism itself — SHIPPED at commit `c9a81e22` /
  `763b408f` / `72e3d2d7`.
