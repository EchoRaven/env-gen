# O2 ResolverFixtureContracts — Design Notes (workflow `wufqrn61m` DEFER)

**Status:** DEFER. Workflow `wufqrn61m` (15 agents, 602k tokens,
~17 min). Strict 2-refute REJECT threshold tripped: 0 blockers + 2
refutes (both `concern` severity, both fixable by briefing
tightenings). Plan author explicitly noted "All concerns are briefing
tightenings, not structural reversals" — this DEFER artifact captures
every fix so the next attempt can SHIP first-try.

DEFER counter consecutive: 1 (hygiene-sweep SHIP at `50a30803` reset
counter to 0; this is the first DEFER post-reset).

## Verdict at a glance

Winner: **Candidate B** — 4-namespace ABC (api_smoke / ui_flow / table /
mcp) with helpers for ACTIVE namespaces only. Drop helpers for deferred
namespaces (visual → Phase 3.9, endpoint_contract → Phase 3.5) per
closed-by-construction discipline.

Two refutes:

1. **CONSUMER_CHURN (concern, mislabeled refute)** — reviewer's own
   text says "The proposed ABC is NOT over-fitted to hypothetical
   consumers" — they explicitly CONFIRM the winner. The
   `refuted=true` flag appears to refute the lens premise, not the
   winner. Action: Winner B already addresses this by dropping
   `seed_visual_review` + `seed_contract_test_result` from v1.
2. **NON_MOCKING_INVARIANT (concern, real)** — winner's spec is
   silent on prohibiting `unittest.mock`. Roadmap line 40 + 262
   record the original `_assert_no_mocks_below_this_frame()` frame
   guard was dropped in favor of code-review-enforced convention; the
   winner ships none of that defense. Action: add module-docstring
   ban + PR-description reviewer-grep requirement (see "Concerns
   resolved" below).

## Verified helper signatures (canonical-writer pin)

Each helper is one-line delegation to a real production writer
verified at file:line:

| Helper | Canonical writer | Verified at | Reference test |
|---|---|---|---|
| `seed_endpoint_probe(reg, method, path, verdict='pass')` | `apihub.register_endpoint` + `RunHub.start_run(probe_runner=...)` | `apihub.py:160-167`, `runhub/service.py:194-204` | `tests/test_phase_2_5_probe_record_evidence.py:83-145` |
| `seed_ui_flow_result(reg, flow, status='pass')` | `hub_registry.record_validation_result(task_id, status, agent='verifier', metadata={'check':'ui_flow','flow':...})` | `hub_registry.py:254-265` (flatten :271-278; reader re-extract :303) | `tests/test_flow_coverage_gate.py:65-72` |
| `seed_table(reg, table_name, rows)` | `schema_hub.register_table` + `schema_hub.register_seed_data` (asserts `len(rows) >= 5` — no min_seed_rows=0 opt-out) | `schema_hub.py:103-177,338-344`; audit at `seed_audit.py:107-109` | — |
| `seed_mcp_probe(reg, server_name, healthy=True)` | `mcp_registry.register_mcp_server` + `RunHub.start_run(mcp_stdio_probe=callable→raw healthy_detail dict NOT verdict_record)` | `runhub/service.py:202,310,327,335-337` | — |

## ABC surface (revised post-refute)

```python
class PhaseResolverFixtureContracts(ABC):
    """Non-mocking, canonical-writer-driven shared base for Phase-3+
    resolver tests.

    IMPORTANT: subclasses MUST NOT import unittest.mock. Evidence
    must flow through canonical writers (the seed_* helpers below)
    only. Reviewer-grep convention: PR description must affirm
    "no unittest.mock imports in fixture-using tests".
    """
    __test__ = False  # ABC itself is not collected

    @abstractmethod
    def target_key(self) -> str:
        """e.g. 'api_smoke:GET /health'."""

    @abstractmethod
    def declared_record_fields(self) -> set[str]:
        """Set of canonical-writer record fields this resolver reads
        (closes SM1 schema-misread gap by forcing subclass to declare
        upfront)."""

    @abstractmethod
    def build_evidence(self, hub_registry) -> dict[str, Literal['pass','fail','skipped','evidence_pending']]:
        """Returns target_key → status. Status values typed from
        day one (closes CC1 forward-compat with Phase 3.5/3.9 tri-state
        evidence_pending need)."""

    def test_resolver_round_trip(self):
        """Concrete: writer emits declared_record_fields AND state
        round-trips via canonical reader."""
        self.assert_canonical_writer_emits_declared_fields(...)
        # ... round-trip assertion
```

## 4 self-test subclasses

```python
class TestApiSmokeResolverContract(PhaseResolverFixtureContracts, unittest.TestCase):
    __test__ = True
    def target_key(self): return "api_smoke:GET /health"
    def declared_record_fields(self): return {"verdict", "method", "path"}
    def build_evidence(self, reg):
        seed_endpoint_probe(reg, "GET", "/health", verdict="pass")
        return {self.target_key(): "pass"}

class TestUiFlowResolverContract(PhaseResolverFixtureContracts, unittest.TestCase):
    __test__ = True
    def target_key(self): return "ui_flow:login_to_dashboard"
    def declared_record_fields(self): return {"status", "metadata.check", "metadata.flow"}
    def build_evidence(self, reg):
        seed_ui_flow_result(reg, "login_to_dashboard", status="pass")
        return {self.target_key(): "pass"}

class TestTableResolverContract(PhaseResolverFixtureContracts, unittest.TestCase):
    __test__ = True
    def target_key(self): return "table:posts"
    def declared_record_fields(self): return {"status", "metadata.min_seed_rows"}
    def build_evidence(self, reg):
        seed_table(reg, "posts", rows=[{"id":i,"body":f"r{i}"} for i in range(5)])
        return {self.target_key(): "pass"}

class TestMcpResolverContract(PhaseResolverFixtureContracts, unittest.TestCase):
    __test__ = True
    def target_key(self): return "mcp:filesystem"
    def declared_record_fields(self): return {"verdict", "server_name"}
    def build_evidence(self, reg):
        seed_mcp_probe(reg, "filesystem", healthy=True)
        return {self.target_key(): "pass"}
```

## Concerns resolved in next-attempt briefing

- **C1** (registration prerequisites for endpoint + mcp helpers added):
  helpers gate on prior `register_endpoint` / `register_mcp_server`.
- **C2** (mcp_stdio_probe callable shape): returns raw
  `healthy_detail` dict, NOT `verdict_record` — verified at
  `runhub/service.py:335-337`.
- **S1** (seed_table seeds ≥5 non-placeholder rows): no min_seed_rows=0
  opt-out; helper asserts the count.
- **SM1** (schema-misread defense): `declared_record_fields` abstract
  forces subclass to declare upfront + concrete check
  `assert_canonical_writer_emits_declared_fields`.
- **CC1** (forward-compat to Phase 3.5/3.9): `build_evidence` return
  values typed `Literal['pass','fail','skipped','evidence_pending']`
  from day one.
- **NM1** (mock ban): module docstring bans `unittest.mock` imports;
  PR description must affirm "no mocks below O2 frame" (reviewer-grep
  convention replaces the dropped frame-inspection guard from roadmap
  line 40).
- **P1** (nit): mixin pattern with `__test__=False` on ABC.

## Excluded from v1 ship

- `seed_visual_review` — Phase 3.9 deferred namespace. Writer shape
  (similarity_score + state + metadata.route) hasn't been finalized;
  same closed-by-construction discipline that killed prior Candidate C.
- `seed_contract_test_result` — Phase 3.5 deferred namespace. If Phase
  3.5/4.4 amend `record_api_test` to add a top-level `verdict` field
  (per roadmap line 84-90), any pre-built helper would need
  re-verification. Drop from v1 → eliminate the schema-drift risk.

## Tear-down assurance

- `setUp`: `tempfile.mkdtemp(prefix='o2_resolver_')`; `HubRegistry(tmp,
  project_id='p', project_name='P')` per Phase 4.4/4.5/4.6 precedent
  (`tests/test_phase_4_4_record_api_test_role_gate.py:41`,
  `test_phase_4_5_gate_registry_review_role_gate.py:44`,
  `test_phase_4_6_codehub_submit_review_role_gate.py:37`).
- `tearDown`: `shutil.rmtree(tmp, ignore_errors=True)`.
- ABC defines NO setUp/tearDown — that's the subclass's
  responsibility via mixin composition.

## Expected suite delta

Current: 1984/0 at HEAD `50a30803` (per audit `wa5yo72qt`).
After ship: 1984 + 4 self-tests = **1988/0** (the plan briefing said
"2178 existing + 4 = 2182" but that figure was stale relative to the
just-corrected aggregate; actual is 1984 + 4).

## Implementer briefing — next session

1. Read this DEFER artifact + `docs/phase_3_mechanism_design_notes.md:160-211`
   + `docs/phase_3_1b_namespace_resolvers_design_notes.md`.
2. Clone `HubRegistry` construction + setUp/tearDown lifecycle from
   Phase 4.4/4.5/4.6 tests.
3. Clone probe_runner stub return shape from
   `tests/test_phase_2_5_probe_record_evidence.py:83-145`.
4. Clone ui_flow `record_validation_result` shape from
   `tests/test_flow_coverage_gate.py:63-72`.
5. Verify all 4 `declared_record_fields` returns against writer source
   at cited line ranges.
6. Write helpers + ABC + 4 subclasses (5-10 LOC each per subclass).
7. Run miniconda dt env (`/home/haibotong/miniconda3/envs/dt/bin/python`)
   `unittest discover tests` at all 7 phases; assert 1988/0 / all green.
8. O2 ABC ships WITHOUT a `_MECHANISMS` entry — it's test
   infrastructure, not a runtime gate. No
   `test_phase_anchor_inventory.py` update needed.

## What this unblocks once landed

- Phase 3.1a `register_story` actor gate (workflow `wx3el8bur` DEFER) —
  needs O2 base for the gate's test fixture.
- Phase 3.1b 4-namespace resolvers (workflow `w8z0em332` DEFER) —
  the resolver bodies use O2 to drive their conformance tests.
- Phase 3.5 endpoint_contract resolver — adds `seed_contract_test_result`
  on top of O2 ABC.
- Phase 3.9 `visual:<route>` resolver — adds `seed_visual_review` on
  top of O2 ABC.

## Workflow stats

- 15 agents, 602k tokens, ~17 min wall-time.
- 3 parallel discovery agents (canonical-writers / fixture-patterns /
  prior-risks).
- 4 candidates (A: minimal-1-ns / B: full-4-ns / C: utility-fns /
  D: DEFER).
- Judge picked Candidate B (4-namespace ABC).
- 6-lens adversarial: 0 blockers + 2 refutes (both concern-severity,
  both fixable) → strict 2-refute REJECT threshold tripped.
- Full output: `/tmp/claude-1052/.../tasks/wufqrn61m.output`.
