# Phase 2.5 Test Hygiene Audit

**Date:** 2026-05-31
**Trigger:** Meta-validation run of the full test suite under
`ELABORATION_REFACTOR_PHASE=2.5` to discover hidden phase=0 assumptions.
**Result:** 1999 pass / 60 fail / 0 error. Suite is healthy at phase=0
(2059/0) but reveals 60 tests carrying an unintended dependency on
pre-Phase-2 actor semantics.

---

## Scope

15 test files affected. Failure counts per file:

| File | Failed |
|------|--------|
| `test_apihub_accessors.py` | 7 |
| `test_autonomous_delivery_gate_deliverability_fold.py` | 7 |
| `test_apihub_seed_registration.py` | 6 |
| `test_apihub_l1_write_time_gate.py` | 6 |
| `test_codehub_premerge_gate.py` | 6 |
| `test_apihub_strengthen.py` | 4 |
| `test_apihub_table_tools.py` | 4 |
| `test_codehub_force_merge.py` | 4 |
| `test_apihub_tools.py` | 3 |
| `test_apihub_tables.py` | 3 |
| `test_apihub_tables_breaking_change.py` | 3 |
| `test_apihub_pending_consumers.py` | 2 |
| `test_codehub_suggest_reviewers.py` | 2 |
| `test_bug_triage_resolver.py` | 2 |
| `test_apihub_breaking_change_creates_task.py` | 1 |
| **Total** | **60** |

---

## Root cause

The 60 failures split into TWO related mechanisms, both stub-name
demotion under the Phase 1 + Phase 2 ownership refactors:

### Mechanism A — `apihub.register_endpoint` rejecting `agent="design"`

```text
PermissionError: register_endpoint: ELABORATION_REFACTOR_PHASE>=2.5
restricts apihub.register_endpoint to ['backend'];
got actor='design'.
```

Phase 2.0 ownership refactor (commits `2eadf0c6` + `39c861d2`) demoted
the `design` role from being allowed to call
`apihub.register_endpoint`. Only `backend` may register endpoints at
phase >= 2.0. Stub `agent="design"` triggers the gate.

### Mechanism B — `schema_hub.register_table` rejecting `agent="database"`

```text
PermissionError: register_table: ELABORATION_REFACTOR_PHASE>=2.5
restricts schema_hub.register_table to ['backend', 'database_worker'];
got actor='database'.
```

Phase 1.0 ownership refactor demoted the bare `database` role; only
`backend` or `database_worker` may register tables at phase >= 1.0.
Stub `agent="database"` triggers the gate. (Discovered while running
the deliberate sweep — original audit only documented Mechanism A.)

### Per-file distribution (stub counts, not failure counts)

| File | `design` | `database` |
|------|---------:|-----------:|
| `test_apihub_seed_registration.py` | 0 | 13 |
| `test_apihub_l1_write_time_gate.py` | 8 | 0 |
| `test_apihub_strengthen.py` | 7 | 0 |
| `test_apihub_tables.py` | 5 | 0 |
| `test_apihub_tables_breaking_change.py` | 3 | 2 |
| `test_apihub_table_tools.py` | 3 | 1 |
| `test_apihub_tools.py` | 3 | 0 |
| `test_apihub_pending_consumers.py` | 2 | 0 |
| `test_codehub_suggest_reviewers.py` | 2 | 0 |
| `test_codehub_premerge_gate.py` | 2 | 0 |
| `test_autonomous_delivery_gate_deliverability_fold.py` | 2 | 0 |
| `test_apihub_breaking_change_creates_task.py` | 1 | 0 |
| `test_codehub_force_merge.py` | 1 | 0 |
| `test_bug_triage_resolver.py` | 0 | 2 |

Where neither pattern appears in a failing file, the failure is
indirect (e.g. setup helper or fixture references the stub) — re-grep
that file individually.

### Common gate body pattern

Both hubs use the same shape: explicit-non-allowed raises; empty falls
through. Test fallback paths that DON'T pass an explicit `agent` keep
working at any phase, because:

```python
actor_id = (agent or provider or "").strip().lower()
if actor_id and actor_id not in allowed:   # explicit + not allowed = block
    raise PermissionError(...)
```

The 60 tests fail because they pass `agent="design"` / `agent="database"`
EXPLICITLY as setup stubs — these were placeholders from the era before
the gates existed.

## The fix pattern

Three equivalent fixes; pick the one closest to test intent:

1. **Drop the `agent` kwarg.** When the test doesn't care about actor
   identity, calling `hub.register_endpoint("GET", "/path", schema={},
   provider="backend")` (no explicit agent) lets the gate fall through.
   This is the lowest-churn fix and matches "I don't care who"
   semantics.

2. **Switch to a current-ownership actor.** Match the realistic actor
   under the new ownership model:
   - `apihub.register_endpoint`: switch `design` → `backend`.
   - `schema_hub.register_table`: switch `database` → `database_worker`.
     ⚠️ Some tests assert on `record["registered_by"] == "database"`
     (e.g. `test_apihub_seed_registration.py:40`). When switching actor
     name, update those assertions to match — this is a 2-edit fix,
     not a pure replace_all.

3. **Pin the test to phase=0.** Use
   `os.environ["ELABORATION_REFACTOR_PHASE"] = "0.0"` in `setUp` if the
   test is specifically locking down pre-Phase-2 behavior. Rare — most
   of these tests aren't.

### Sweep progress (live)

| Commit | File | Status |
|--------|------|--------|
| `d786fdd0` | `test_apihub_accessors.py` | clean (design→backend) |
| `d15ec838` | `test_apihub_breaking_change_creates_task.py` | clean (design→backend, 1 site) |
| `d15ec838` | `test_codehub_force_merge.py` | clean (design→backend, 1 site) |
| `d15ec838` | `test_apihub_pending_consumers.py` | clean (design→backend, 2 sites) |
| _this commit_ | `test_apihub_l1_write_time_gate.py` | clean (design→backend, 8 sites) |
| _this commit_ | `test_apihub_strengthen.py` | clean (design→backend, 7 sites) |
| _this commit_ | `test_apihub_tables.py` | clean (design→backend, 5 sites) |
| _this commit_ | `test_apihub_tools.py` | clean (design→backend, 3 sites) |
| _this commit_ | `test_codehub_premerge_gate.py` | clean (design→backend, 2 sites) |
| _this commit_ | `test_codehub_suggest_reviewers.py` | clean (design→backend, 2 sites) |
| `ad19e60e` | `test_autonomous_delivery_gate_deliverability_fold.py` | clean (design→backend, 2 sites — includes 1 schema_hub.register_table call where backend is also valid) |
| _this commit_ | `test_bug_triage_resolver.py` | clean (database→database_worker, 2 sites — `provider="database"` assertions untouched since function reads `provider` not `agent`) |
| _this commit_ | `test_apihub_table_tools.py` | clean (mixed: agent_id="database"→"database_worker" + 3 schema_hub stubs design→database_worker + line 79 update_table_schema + 2 assertion updates because tool wrapper propagates agent_id into provider field) |
| _this commit_ | `test_apihub_tables_breaking_change.py` | clean (mixed: 3 design + 2 database → database_worker; no assertions on agent name) |
| _this commit_ | `test_apihub_seed_registration.py` | clean (13 database→database_worker + 1 assertion update at line 40: `registered_by=='database'`→`'database_worker'`) |

**Sweep complete: 15/15 files clean.** All Mechanism A + Mechanism B
stub usages converted to current-ownership actor names. Suite metrics:

| Mode | Pass | Fail |
|------|------|------|
| Phase 0 (default CI) | 2059 | 0 |
| Phase 2.5 (full activation) | 2059 | 0 |

**Post-sweep verification (commit `50ccd029`):** After adding the
sweep-state regression guard (`test_no_demoted_actor_stubs.py`, 4
tests), the matrix expanded to verify all advertised phases:

| Mode | Pass | Fail |
|------|------|------|
| Phase 0 (default CI)        | 2063 | 0 |
| Phase 2.5 (full activation) | 2063 | 0 |
| Phase 3.0 (inert scaffold)  | 2063 | 0 |

Phase 3.0 passes because the Phase 3 scaffold (`runtime/story_hub.py`)
is `_synthetic` — the dispatch fires inert anchors but doesn't enforce
new gates. Once Phase 3 lands a real mechanism, this row will need
re-verification.

**Recommendation:** the next operator-side action is to add
`ELABORATION_REFACTOR_PHASE=2.5 pytest tests/` to CI alongside the
default phase=0 run. This locks in the clean state and prevents
re-drift when Phase 3 lands.

## Do NOT touch

`test_phase_2_apihub_role_gate.py` uses `agent="design"` intentionally
to verify the gate REJECTS design. That's the gate test itself — its
`design` calls are load-bearing assertions, not stubs.

Other files like `test_workhub_design_review.py`,
`test_eventhub_transcript.py`, `test_hub_consistency_policy.py` use
`agent="design"` for legitimate design-actor-specific behavior. Verify
intent before changing.

---

## Why this audit document, not a sweeping fix

60 file edits across 15 test files is reversible but large. Each call
site needs eyes-on judgment — fix-1 (drop kwarg) preserves test
semantics best, but a small minority of these tests might secretly
depend on `agent="design"` flowing through to a side-effect somewhere
(e.g. ownership tracking, audit log). A purely mechanical sed would
miss that.

The right next step is a deliberate sweep — file by file — that the
operator can run during waking hours and review per-commit, rather
than autonomous overnight mass-edits.

When that sweep runs:
1. Pick a file.
2. Apply fix-1 (drop kwarg) as default.
3. Run that file with `ELABORATION_REFACTOR_PHASE=2.5 pytest tests/<file>.py`.
4. Verify it passes; verify it ALSO passes at phase=0 (i.e. no env var).
5. Commit + push.

After all 15 files are clean, drop this audit doc OR convert it into a
permanent regression test:

```bash
ELABORATION_REFACTOR_PHASE=2.5 pytest tests/  # expect 0 failures
```

Adding that to CI would prevent the same drift from re-emerging when
Phase 3 lands.

---

## Suite metrics at audit time

| Mode | Pass | Fail |
|------|------|------|
| Phase 0 (default — current CI) | 2059 | 0 |
| Phase 2.5 (this audit) | 1999 | 60 |

The 60-failure delta is entirely the `agent="design"` stub pattern.
No deeper runtime bugs surfaced.
