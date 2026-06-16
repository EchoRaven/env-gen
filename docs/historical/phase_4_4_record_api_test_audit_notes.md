# Phase 4.4 record_api_test Authorship Lock — Audit Notes (O15)

**Status:** RESOLVED via Path A (bundle-trim). Phase 4.4 record_api_test
authorship lock is SHIPPED with closed-by-construction wiring:
`apihub_record_contract_test` was extracted from `_bundle_apihub_tools`
into a dedicated `_bundle_verifier_contract_tools`
(`multi_agent/tool_bundles.py:451`); `agents_config.yaml:582` grants
`verifier_contract_tools` ONLY to the `verifier` profile. Original
audit BLOCKER (7-of-8 grants raising PermissionError at phase>=4.4)
is structurally eliminated — only the verifier profile holds the tool.
Roadmap O15 row marked SHIPPED 2026-06-01 (verified by re-audit).

**Workflow (original audit):** 5 agents, 159k tokens, 5-minute wall-time.
3-lens adversarial review found 1 BLOCKER + 2 concerns + 1 nit.
Original verdict: NEEDS_FIX → resolved by Path A ship.

---

## Callsite inventory (16 total, post-audit)

| Layer | Count | Where | Actor identity |
|---|---:|---|---|
| Tool wrapper | 1 | `tools/hub_tools.py:976` (`APIHubRecordContractTestTool._run`) | `agent=self._agent_id` (dynamic, runtime-bound) |
| Hub-direct tests | 15 | `test_apihub_accessors.py:96-98`, `test_apihub_contract_test_results_sorted.py:54-151` (×8), `test_hub_architecture.py:49`, `test_hub_pulse.py:62`, `test_codehub_force_merge.py:28`, `test_codehub_premerge_gate.py:29,90` | `agent="verifier"` (literal) |
| Tool-wrapper test (**missed by original Phase 4+ roadmap audit**) | 1 | `test_apihub_tools.py:84` | `agent_id="backend"` (via `create_hub_tools(agent_id="backend", ...)` at line 48) |

The roadmap's original O15 spec listed 8 callsites; the true count
is 16 once `test_apihub_contract_test_results_sorted.py` (added in
commit `841c434f` as O7) and `test_apihub_tools.py` are included.

---

## BLOCKER — production wiring breaks 7 of 8 grants at Phase 4.4 cut-over

### The wiring chain

```
agents_config.yaml
   │ grants apihub_tools to 8 profiles
   │   (orchestrator, design, backend, frontend,
   │    architect_reviewer, visual_reviewer, verifier,
   │    bug_triage_orchestrator)
   ▼
tool_bundles.py:429 (apihub_tools)
   │ includes "apihub_record_contract_test"
   ▼
hub_tools.py:976 (APIHubRecordContractTestTool._run)
   │ calls hub.record_api_test(..., agent=self._agent_id)
   ▼
apihub.record_api_test(...)
   │ at phase>=4.4: allowed_set = {verifier, contract_test_runtime}
   ▼
   ✗ 7/8 grants raise PermissionError
```

### Test fixture proof

`tests/test_apihub_tools.py:48` calls
`create_hub_tools(agent_id="backend", hub_workspace=hubs)`. The
record_contract_test tool test at line 84 then invokes via
`tool_by_name["apihub_record_contract_test"]._run(...)`. The
persisted record has `agent="backend"` — NOT "verifier". Under the
proposed Phase 4.4 gate, this test would fail.

---

## Two reconciliation paths (pick ONE before Phase 4.4 ships)

### Path A — Trim the bundle (preferred, closed-by-construction)

1. In `multi_agent/tool_bundles.py`:
   - Remove `"apihub_record_contract_test"` from `_bundle_apihub_tools`.
   - Add a new `_bundle_verifier_contract_tools` that includes the
     tool.
2. In `multi_agent/agents/agents_config.yaml`:
   - Grant `verifier_contract_tools` ONLY to the `verifier` profile
     (and `contract_test_runtime` if/when that profile exists).
   - 7 other profiles no longer have access to the tool.
3. In `tests/test_apihub_tools.py:48`:
   - Change `create_hub_tools(agent_id="backend", ...)` to
     `agent_id="verifier"` OR add a dedicated
     `_hubs_and_tools_for_verifier(td)` helper that the contract-test
     test uses while other tests keep the backend binding.

### Path B — Coerce at the tool boundary

1. In `hub_tools.py` `APIHubRecordContractTestTool._run`:
   ```python
   if self._agent_id not in {"verifier", "contract_test_runtime"}:
       return ToolResult(error=...)  # tool-level rejection
   ```
   Surfaces the divergence at tool-call time (cleaner error path)
   without changing bundle membership.
2. Same test_apihub_tools.py fixture update as Path A.

Path A is structurally tighter — it removes the ability to call the
tool at all rather than letting the call happen and reject. Path B
preserves more flexibility but leaves the bundle wiring open as a
foot-gun.

---

## Enforcement scope decision (needed before regression test ships)

Phase 4.4 as designed restricts the TOOL layer
(`apihub_record_contract_test`). But 15 of the 16 callsites are
**hub-direct** — they call `hub.record_api_test(...)` directly,
bypassing the tool wrapper. Question:

- **Option 1** (gate at tool only): the 15 hub-direct tests pass
  through unfiltered. Tests stay simpler; the gate enforces against
  agent-driven contract test writes but lets internal / fixture
  callers freely write. Risks: a real agent could write a contract
  test by directly importing `apihub.record_api_test` (bypassing the
  tool) — but agents don't have hub imports in their tool surface,
  so this is theoretical.
- **Option 2** (gate at hub method too): both layers enforce
  consistently. Requires updating 15 test fixtures to either pass
  `agent="verifier"` (they already do — except none currently use
  `agent="contract_test_runtime"` so the allowed_set would still pass)
  OR adding a `strict_actor` flag to the hub method so tests can opt
  out.

Recommend Option 1 for v1 — keeps test churn to zero, aligns the
gate with the actual agent-reachable surface (the tool, not the
hub method).

---

## Regression test design (DEFERRED until reconciliation lands)

Once Path A (or B) + scope decision land, the regression test
should track:

- **Layer A**: each test file calling `hub.record_api_test`
  continues to pass `agent="verifier"` (or `"contract_test_runtime"`).
- **Layer B**: `tool_bundles.py` keeps `apihub_record_contract_test`
  in the verifier-only bundle (NOT the broad `apihub_tools` bundle).
- **Layer C**: `agents_config.yaml` grants the verifier-contract
  bundle ONLY to the verifier (+ contract_test_runtime) profile.

A 3-layer guard like this is the right shape because the real risk
isn't test-fixture drift (Layer A) — it's wiring drift (Layers B+C).
A test-only Layer-A regression would be insufficient; it would have
caught zero of the issues this audit surfaced.

---

## Why this wasn't shipped autonomously

The roadmap tagged O15 as P0 high MANDATORY pre-Phase-4.4 with
effort S — implying a simple "audit + regression test" PR. The
workflow showed the audit is incomplete (8 known callsites became
16 once O7's new tests + the missed tool-wrapper test were
included) and the production wiring needs reconciliation before
any gate can ship.

The fixes are concrete (Path A is the operator-judgment cheapest)
but exceed autonomous-safe scope because:

1. Trimming the bundle changes which agents can call the tool —
   that's a permission decision needing operator awareness.
2. `agents_config.yaml` is config that downstream profiles read —
   changing grants affects every agent profile's surface.
3. Test fixture (`test_apihub_tools.py:48`) currently encodes
   `agent_id="backend"` deliberately — flipping to "verifier"
   changes the test's purpose and may invalidate other coverage.

The next implementer should: (1) decide Path A vs B, (2) decide
Option 1 vs 2 for enforcement scope, (3) land the wiring change as
its own PR, (4) ship the 3-layer regression test mirror of
`test_no_demoted_actor_stubs.py` per the design sketch above.

---

## Out of scope

- **`record_api_test` schema verdict field** (Phase 3.5 / B1
  blocker from `docs/phase_3_mechanism_design_notes.md`). Independent
  upstream change with its own callsite-audit needs — adding a
  `verdict` field to the record shape and time-sorting via
  `list_contract_test_results_sorted` (already shipped at commit
  `841c434f`).
- **Phase 4.4 + Phase 3.5 co-ship** described in the roadmap top-3
  recommendations — both required, but in different PRs since
  Phase 3.5 is schema-additive and Phase 4.4 is wiring-trim.
