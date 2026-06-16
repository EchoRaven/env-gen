# Phase 4+ Roadmap — env-gen SDLC Elaboration Refactor

**Status:** DRAFT — incorporating R2 round-11 critique findings (REVISE_MINOR x3)
**Last updated:** 2026-05-31
**Owner:** Implementer + R2

---

## 1. Headline Summary

The roadmap finishes Phase 3 (story-bundle delivery gate) before closing the ownership-refactor backlog across the remaining hubs, with critical infrastructure landing first as orthogonal optimizations. Phase 3.1 ships the verification-bundle mechanism with 4 safe namespaces (`api_smoke`, `ui_flow`, `table`, `mcp`) only after the ResolverFixtureContracts base class + `_role_gate` helper module land; Phase 3.5 fixes the upstream `record_api_test` verdict-field schema and lights up `endpoint_contract`, while Phase 4.4 (its authorship backstop) is elevated to P0 and **must co-ship** to avoid recreating BLOCKER B1's failure class one layer up. Phase 3.9 lights up the visual namespace via `metadata.route` in parallel with Phase 4.3 (visual-submitter authorship gate, elevated to P1), then the Phase 4 block closes the remaining 53 `KNOWN_DEFERRED_TO_EXT` pin set.

---

## 2. Roadmap Table

| Phase | Title | Priority | Effort | Value | Depends On | Risk |
|---|---|---|---|---|---|---|
| **3.0-bootstrap** | StoryHub instance plumbing + hub_registry injection | P0 | S | critical | O1, O2 | Architecture-only; zero gate semantics |
| **3.1a** | `register_story` actor gate + StoryHubStores | P0 | M | critical | 3.0-bootstrap, O1 | Schema-misread regression class — ResolverFixtureContracts is primary correctness gate |
| **3.1b** | 4 namespace resolvers + `evaluate_story_gate` wired into deliverability | P0 | L | critical | 3.1a, O2 | AND-of-blockers + no-required-stories silent no-op; surface `story_count=0` loudly |
| **3.5** | `record_api_test` verdict-field amendment + `endpoint_contract` namespace | P0 | M | high | 3.1b, **4.4 (co-ship)**, O7 | Verdict-derivation correctness against 8 existing callsites; additive only |
| **4.4** | APIHub contract-test authorship lock (`record_api_test` + `register_consumer`) | **P0** (was P1) | M | high | 3.5 co-ship, O1, **O15 (callsite audit)** | Structural backstop for 3.5's resolver; must co-ship with 3.5 to prevent BLOCKER-B1-redux |
| **3.9** | Story-gate visual namespace via `metadata.route` | P1 | M | high | 3.1b, **4.3 (co-ship)** | Identity-key drift; SSIM-None must NOT be treated as failed |
| **4.3** | gate_registry review-lifecycle submitter gate (visual-first) | **P1** (was P2) | M | high | 4.0, 3.9 co-ship, O1 | Same authorship-spoof class as 4.4↔3.5; must co-ship with 3.9 |
| **4.0** | MCP registry ownership lock | P0 | S | high | O1, O2, O3 | Smallest external-surface hub; validates `_role_gate` helper at low blast radius |
| **4.1** | EventHub subscription identity gate (subscribe/unsubscribe/mark_read) | P0 (elevated) | M-to-L | high | O1, **O14 (caller-threading pre-phase)** | Caller-kwarg signature change propagates through ~5 callsite families |
| **4.1b** | EventHub publish-side identity gate (publish_human_message / publish_agent_reply / record_agent_status) | P1 | M | high | 4.1 | Same spoof class as 4.1; ships alongside |
| **4.2** | schema_hub data-write surface lock (update_table_schema / register_seed_data / register_table_consumer) | P0 | S | high | O1 | Closes Phase 1 drift via breaking-change recorder; allowed-set design needs revisit per critique |
| **4.5a** | WorkHub planning surface (create_page/create_plan/create_task/archive_page) | P1 | L | high | O1 (not 4.0) | Fixtures pass `agent=''` (empty fallthrough handles); hot path |
| **4.5b** | WorkHub state surface (claim_task / set_task_priority / link_task_to_pr / link_task_to_apis) | P1 | M | high | 4.5a | task.claimed_by lookup adds store read on hot path |
| **4.5c** | WorkHub collaboration surface (comment / react / update_block / record_decision / etc.) | P1 | M | medium | 4.5b | page.attendees lookup; lowest-value of the 4.5 tier |
| **4.6** | CodeHub commit/PR/check authorship parity | P1 | M | high | O1 (parallel to 4.5) | Clone merge_pull_request:518-535 byte-for-byte |
| **4.7-slim** | HumanConsole `from_user` identity gate (slim, no attestation primitive) | P2 | S | medium | 4.1 | Mirror eventhub subscription pattern; no new infra |
| **5.0** | **Behavioral-evidence track kickoff (placeholder, scope-TBD)** | P3 | TBD | TBD | 4.6 | Sentinel only — keeps the 10 missing evidence types visibly queued |

**Status as of 2026-06-01** (commits on branch `haibotong-0527-hub-focus-and-tooling-cleanup`):

| Row | Status | Commit / Notes |
|---|---|---|
| 3.0-bootstrap | ✅ SHIPPED | `207dc0c1` — StoryHub class + HubRegistry attachment |
| 3.1a | ✅ SHIPPED (co-shipped with 3.1b) | `c9a81e22` — actor gate `{orchestrator, product, planner}` inside Phase 3 mechanism ship |
| 3.1b | ✅ SHIPPED | `c9a81e22` (mechanism) + `72e3d2d7` (deliverability hook) — 4 namespace resolvers + evaluate dispatch wired |
| 3.5 | ✅ SHIPPED (Path B simplified) | `e1053908` — verdict-field amendment in `apihub.record_api_test` + `endpoint_contract:<endpoint_id>` resolver in story_hub. **Path B**: NO widening of Phase 4.4 to admit `contract_test_runtime` — phantom stays parked indefinitely per phantom_runtime_registry.md until a real runtime caller is introduced. Anchor P. |
| 4.4 | ✅ SHIPPED | Pre-flight bundle-trim `7272a2fc` + mechanism `1018fa28` + audit notes `18ecee23` |
| 3.9 | ✅ SHIPPED (Path B simplified) | `f2eb4569` — `visual:<route>` resolver in story_hub + `gate_registry.list_visual_reviews` public helper, keyed by `metadata.route` (closes original C1 design error). **Path B**: NO widening of Phase 4.5 `submit_visual_review` to admit `visual_similarity_runtime` — phantom stays parked until a real SSIM runtime caller exists. Anchor Q. |
| 4.3 | ✅ SHIPPED | `e40ae472` — submit_design_review + submit_visual_review locks. **LABEL DRIFT**: git commit message says "Phase 4.5" but matches roadmap row 4.3 (visual-first review-lifecycle submitter gate). The earlier session's "Phase 4.5" label included both review gates + the workhub bundle which actually maps to roadmap rows 4.5a/b/c (now DEFERed). |
| 4.0 | ✅ SHIPPED | `675ebf69` — mcp_registry ownership locks |
| 4.1 | ✅ SHIPPED | `b39305ac` (O14 chunk-1 caller-threading) + `19b3c2a6` (gate) + `dc3d972d` (5-family callsite threading) |
| 4.1b | ✅ SHIPPED (different scope) | `a9fb1ff6` — `prune_read_inbox` sibling extension. **SCOPE DIVERGENCE**: roadmap row text says "publish_human_message / publish_agent_reply / record_agent_status" publish-side gate; what shipped was the sibling INBOX-side extension. The publish-side gate now lands as Phase 4.1c (row below). |
| 4.1c | ✅ SHIPPED (Step A, source_hub semantic) | `<head>` — `EventHub.publish_event` source_hub-authorship gate at phase>=4.11 (PHASE_4_11 const). Per user 2026-06-01 directive: source_hub semantic chosen over caller-threading (hub-internal authorship; lower risk). Owner-equals (caller==source_hub) OR per-hub sentinel allowlist (apihub admits schema_hub/mcp_registry; workhub admits gate_registry; human_user admits live_monitor/messagebus_bridge). 7 `_emit` wrappers threaded with `caller=<hub_name>`. Legacy phantom source_hubs (system/messagebus/verifier/ui) admit via empty-caller fallthrough only — migration parked per Path B (follow-up cleanup PR). `record_agent_status` deliberately does NOT propagate caller= until "system" is migrated. Anchor R. |
| 4.2 | ✅ SHIPPED | `028f3044` — schema_hub sibling gates (closes Phase 1 drift) |
| 4.5a | ⏸ DEFER (retired via 4.5d Path A) | `docs/phase_4_5_workhub_design_notes.md` (workflow `wzzr5iyx7`). Architectural finding: WorkHub's whole surface is producer-side per PR 3 of hub-responsibility-split plan — no verdict-authoring surface to gate. Retired via Path A (4.5d below). |
| 4.5b | ⏸ DEFER (retired via 4.5d Path A) | Same design notes; bundled architectural finding applies. Retired via 4.5d Path A. |
| 4.5c | ⏸ DEFER (retired via 4.5d Path A) | Same design notes; bundled architectural finding applies. Retired via 4.5d Path A. |
| 4.5d | ✅ SHIPPED (Path A retire) | `3a768740` — `gate_registry.mark_path_intentionally_dead` authorship lock `{orchestrator}`. Path A retire-to-gate_registry replaces the dropped 4.5a/b/c WorkHub bundle (architectural finding: WorkHub is producer-side; the actual verdict-authoring surface is here on gate_registry). Anchor L.1. |
| 4.6 | ✅ SHIPPED (submit_review + record_check; 4.6.x expansion partial) | `a4cac71f` shipped submit_review with PR-lifecycle inline dict-return idiom. **Phase 4.6.1 SHIPPED** `<head>`: `codehub.record_check` locked to `{orchestrator} ∪ pr.checks_authorized ∪ pr.reviewers` with new `checks_authorized` data-model plumbing on `open_pull_request` mirroring the `reviewers` pattern; closes audit `wnjpij4xw` Blocker 2 (no checks_authorized field). DEFER counter back to 0. Remaining 4.6 expansion candidates (`request_review` / `open_pull_request` / `record_commit` / `resolve_conflict` / `create_release` / `register_agent_repo`) stay DEFER per `phase_4_6_expansion_design_notes.md` — workflow `wvimglo1v` found the bundle would BREAK production (register_agent_repo bootstrap; runhub phantom; resolve_conflict + create_release already gated; record_commit tautology). |
| 4.7-slim | ✅ SHIPPED (Path A + Path C) | Path A bridge `960dc566` — `eventhub.publish_human_message` 甲方 identity gate at phase>=4.7. Path C `<head>` — live_monitor `_apply_request_user` stamps session username onto `body["from_user"]` for per-request identity; shims drop the `"human_user"` literal default. Precedence: Path C > body > Path A env var > "human_user" (rejected). Anchor O. |
| 5.0 | 🅿 PARKED | Sentinel only; roadmap text says "do not start until Phase 4.6 stabilizes". Phase 4.6 expansion blocked on cleanups above; revisit after Phase 4.6.1 + 4.6.2 ship. |

**Runtime stall bugs fixed 2026-06-01** (not in the Phase table but identified during audit `w241o5bwn`): `9a015dc7` stash-pop trap closed-by-construction + `48a1471a` step-start merge_conflict → WorkHub remediation task + `2e518079` observer-loop exponential idle backoff. Together eliminate the May 29 19-hour facebook-clone stall pattern.

**Mechanism count as of head pending**: 23 mechanisms across 12 phase thresholds (1.0×3 / 2.0×2 / 2.5×3 / 3.0×2 / 3.5×1 / 3.9×1 / 4.0×2 / 4.1×1 / 4.11×1 / 4.4×1 / 4.5×3 / **4.6×2** / 4.7×1).

**2026-06-01 session arc** (head `f2eb4569`, branch pushed):
- `3a768740` Phase 4.5d Path A retire — mark_path_intentionally_dead gated; replaces 4.5a/b/c bundle
- `960dc566` Phase 4.7-slim Path A — HumanConsole 甲方 identity bridge via ENVGEN_HUMAN_USER_ID
- `e1053908` Phase 3.5 Path B — endpoint_contract namespace + verdict-field amendment (no contract_test_runtime widening)
- `f2eb4569` Phase 3.9 Path B — visual:&lt;route&gt; namespace via metadata.route (no visual_similarity_runtime widening)

Both Path B ships deliberately **DID NOT** widen the relevant allowlist with a phantom principal — `contract_test_runtime` + `visual_similarity_runtime` stay parked in `phantom_runtime_registry.md`. Path B discipline: never widen an allowed_set with a principal nobody authors as.

---

**Dropped from prior synthesis** (per critique):
- `require_stories` config flag in 3.9 — DEFERRED C3 says "leave as planner responsibility for v1"; no pilot evidence of silent skips yet.
- 3.9 invented `visual_ssim_threshold` default `0.85` — no calibration evidence; require explicit project config or annotate as TBD.
- `_assert_no_mocks_below_this_frame()` frame guard in ResolverFixtureContracts — novel frame-inspection mechanism with no shipped precedent; replace with code-review-enforced convention.

---

## 3. Per-Phase Detail

### Phase 3.0-bootstrap — StoryHub instance plumbing

**What it does.** Converts `runtime/story_hub.py` from module-level functions (`register_story` at line 40, `evaluate_story_gate` at line 78) to a `StoryHub` class owned by `hub_registry`, threading `hub_registry` as kwarg through both public entry points. Updates the elaboration_phase dispatch wiring at lines 274-360 to know how to find it. Pure architecture, zero gate semantics, both branches still converge on the inert no-op today.

**Why it matters.** The rejected Candidate C design referenced `_resolve_active_store` and `_resolve_eventhub` as injection points that were never defined. Without this pre-phase, Phase 3.1 has to bundle both an architecture decision AND the mechanism body, doubling design surface area. By landing instance-plumbing as a no-op first, the Phase 3.1 PR can focus entirely on the actor gate + StoryHubStores write semantics.

**Anchors:** `multi_agent/runtime/story_hub.py:11-100`, `multi_agent/runtime/elaboration_phase.py:274-360`.
**Test plan:** existing `test_phase_0_3_inert_scaffolding.py` continues to pass; new test asserts `hub_registry.story_hub` is an instance and that `register_story(...)` / `evaluate_story_gate(...)` are still no-ops at phase=0.
**Risk:** zero behavioral change, but signature churn across all imports. Mitigation: keep old module-level wrappers as `__getattr__` shims for one phase.

---

### Phase 3.1a — `register_story` actor gate + StoryHubStores

**What it does.** Lands `StoryHubStores` as a byte-for-byte clone of `RunHubStores` (JsonStore with `m.set(story_id, record, actor)` write pattern — NOT the `{**m, story_id: record}` antipattern the design notes flagged). At `phase>=3.0`, `register_story` raises `PermissionError` unless actor (normalized via `.strip().lower()`) is in `{orchestrator, product, planner}` via the `_role_gate.require_actor` helper. Empty-actor fallthrough preserved.

**Why it matters.** Closes the authorship surface for stories before any resolver consumes them — same closed-by-construction pattern that worked for Phase 0.2 + the spike. Without this gate active before 3.1b lands, the planner-actor invariant is just convention.

**Anchors:** `multi_agent/runtime/story_hub.py`, `multi_agent/runtime/elaboration_phase.py:374-387` (append `(3.0, 'StoryHub.register_story', 'story authorship locked to {orchestrator, product, planner}')`).
**Test plan:** new `tests/test_phase_3_register_story_gate.py` with ResolverFixtureContracts subclass; canonical writer test asserts `m.set` mutation pattern not `{**m, ...}`. Append to `_MECHANISMS` + update `tests/test_phase_anchor_inventory.py` per comment at lines 372-373.
**Risk:** allowed-set drift between MEMORY.md / `_MECHANISMS` / activation log. Mitigation: autogen-activation-log optimization (O5) eliminates 3-of-4-file lockstep.

---

### Phase 3.1b — 4 namespace resolvers + deliverability wiring

**What it does.** Implements the 4 safe namespace resolvers (`api_smoke:<METHOD> <PATH>`, `ui_flow:<flow_name>`, `table:<name>`, `mcp:<server_name>`) per the Candidate-C-as-trimmed spec. `evaluate_story_gate(hub_registry)` walks stories, resolves each target via the namespace dispatcher, returns `{ok, stories[]}` with `story_status = delivered` iff every target passed. Wires into `deliverability.compute_deliverability` at `phase>=3.0` AFTER the existing 6 signals, AND-of-blockers semantics. **Defers** `visual:<route>` (Phase 3.9) and `endpoint_contract:<endpoint_id>` (Phase 3.5) — those resolvers raise `ValueError` with a pointer to their respective phases.

**Why it matters.** Lights up the verification-bundle mechanism that ties intent (user_intent string) to evidence (probe records, flow records, seed audits, MCP probes) via a planner-curated bundle. This is the closing-of-the-loop the R2 round-11 brief identified as the highest-value Phase 3 work.

**Anchors:** `multi_agent/runtime/story_hub.py`, `multi_agent/runtime/deliverability.py:187-256` (append after signal #7).
**Test plan:** ResolverFixtureContracts subclass for each of the 4 namespaces — constructs real fixture records via canonical writers (`RunHub.start_run`, `seed_audit.audit_seed_data`, `compute_flow_coverage`, MCP stdio probe orchestration), asserts each resolver returns `passed`. Surface `story_count=0` loudly in `format_phase_status` output to prevent the silent-no-op trap.
**Risk:** schema-misread regression class (BLOCKER B1 / concern C1). Mitigation: ResolverFixtureContracts base class (O2) is the primary correctness gate; non-mocking, canonical-writer-driven.

---

### Phase 3.5 + Phase 4.4 (co-shipped) — verdict field + authorship lock + endpoint_contract activation

**What they do together.** Phase 3.5 amends `record_api_test` at `apihub.py:442-451` to write an explicit top-level `verdict` field derived from `result.get('passed')` OR `result.get('result')=='pass'` OR `(200<=status_code<400)`; original `result` dict unchanged (forward+backward compat). Adds `list_contract_test_results_sorted(endpoint_id, by='created_at', desc=True)` while leaving `get_contract_test_results` stable. Enables `endpoint_contract:<endpoint_id>` resolver in StoryHub reading the sorted accessor. **Phase 4.4 co-ships**: `record_api_test` allowed = `{verifier, contract_test_runtime}` only — mirrors Phase 2.5 `record_probe` runtime-only idiom. `register_consumer` allowed = `{backend, frontend}`.

**Why they must co-ship.** Shipping 3.5 alone activates the `endpoint_contract` resolver but leaves record authorship spoofable by any agent — recreating BLOCKER B1's failure class one layer up (broken-by-authorship rather than broken-by-shape). The R2 round-11 critique flagged this as a P0 sequencing issue. Shipping 4.4 alone gates authorship but leaves the schema bug in place.

**Anchors:** `multi_agent/runtime/apihub.py:442-451`, `apihub.py:508` (sort accessor), `apihub.py:324` (update_schema), `apihub.py:336` (register_consumer), `multi_agent/runtime/story_hub.py`, `multi_agent/runtime/elaboration_phase.py:374-387`.
**Test plan:** ResolverFixtureContracts subclass writes two `record_api_test` records for the same `endpoint_id` 100ms apart and asserts the resolver sees the later one's verdict regardless of insertion order (catches the original Candidate C `results[-1]` bug). Callsite audit (O15) sweeps the 8 existing callers — all currently pass `agent='verifier'` per grep, so the allowed-set is safe.
**Risk:** verdict-derivation rule must be correct for every existing record shape. Mitigation: derivation is ADDITIVE (original result dict unchanged); the 8 callsites (`hub_tools.py:976`, `test_hub_architecture.py:49`, `test_codehub_force_merge.py:28`, `test_apihub_accessors.py:96-98`, `test_hub_pulse.py:62`, `test_codehub_premerge_gate.py:29,90`) all pass `result={'passed': bool, ...}` which produces correct verdict under derivation.

---

### Phase 3.9 + Phase 4.3 (co-shipped) — visual namespace + visual-submitter authorship gate

**What they do together.** Phase 3.9 enables the `visual:<route>` resolver in StoryHub — iterates `hub_registry.gate_registry` visual_review pages (`kind=='visual_review'`), indexes by `metadata['route']` (NOT `page_key` — that was C1's design error), passes iff matching page `status=='approved'` AND (when `compute_ssim` returned a non-None score) `metadata.get('ssim_score') >= project.visual_ssim_threshold` if explicitly configured. **SSIM-None is evidence_pending, NOT failed** (compute_ssim returns None on import/file/zero-variance failure per its contract). Phase 4.3 co-ships: `submit_visual_review` allowed = `{orchestrator, visual_reviewer, verifier, visual_similarity_runtime}`; `mark_path_intentionally_dead` allowed = `{orchestrator, verifier}`; `register_visual_review_task` allowed = `{frontend, verifier}`; `submit_design_review` allowed = `{orchestrator, verifier, design_reviewer}` ∪ `page.attendees`.

**Why they must co-ship.** Same authorship-spoof class as 3.5↔4.4. Without 4.3, any agent can author a `submit_visual_review(status='approved')` record at phase>=3.9 that the resolver trustingly consumes as evidence. The critique flagged 4.3's prior P2 priority + post-3.9 sequencing as a priority inversion.

**Anchors:** `multi_agent/runtime/gate_registry.py:118-380`, `multi_agent/runtime/visual_similarity.py`, `multi_agent/runtime/story_hub.py`.
**Test plan:** ResolverFixtureContracts subclass constructs real record via `register_visual_review_task` + `submit_visual_review` and asserts `route` lookup works against `metadata.route`. SSIM-None test asserts evidence_pending status (not failed). Programmatic-review path uses the new `visual_similarity_runtime` identity (mirrors `runhub` identity for `record_probe`).
**Risk:** identity-key drift (gate_registry stores `route` in `metadata.route` — future PRs could move it). Mitigation: fixture-contract test asserts the exact path. `project.visual_ssim_threshold` is project-config-only with no default — explicit opt-in.

---

### Phase 4.0 — MCP registry ownership lock

**What it does.** At `phase>=4.0`, gates 3 MCP registry methods via `_role_gate.require_actor`. `register_mcp_server` + `register_mcp_tool` allowed = `{backend}`; `register_mcp_consumer` allowed = `{backend, frontend}`. Empty-actor fallthrough preserved (bootstrap paths from compose are unaffected).

**Why it matters.** Only ungated external-surface hub. Smallest blast radius of the Phase 4 set — validates `_role_gate.require_actor` helper at low risk before 4.1/4.5 use it on hot paths. Closes 3 entries in `KNOWN_DEFERRED_TO_EXT` at the runtime layer (structural backstop pattern).

**Anchors:** `multi_agent/runtime/mcp_registry.py:86,127,171`.
**Test plan:** `tests/test_phase_4_mcp_role_gate.py` with ResolverFixtureContracts subclass. Append to `_MECHANISMS` + update `tests/test_phase_anchor_inventory.py`.
**Risk:** low — byte-for-byte clone of `register_endpoint` gate pattern.

---

### Phase 4.1 — EventHub subscription identity gate

**What it does.** Adds `caller` kwarg (default `''` for fallthrough) to `subscribe:217`, `unsubscribe:260`, `unsubscribe_all:282`, `mark_read:445`, `mark_all_read:485`. At `phase>=4.1` raises `PermissionError` if `caller and caller != subject_agent`, with explicit allowlist exception for `caller in {orchestrator, eventhub}`. Closes 3 eventhub_* EXT entries.

**Why it matters.** Per the gap survey, eventhub is "the biggest gap" — `agent` is the SUBJECT of the subscription, NOT verified against the caller. Today any agent can `unsubscribe_all(agent='backend')` and silently sever another agent's feed. The R2 round-11 critique elevated this from P1 to P0 because the spoofability hazard is canonical and the 4.0→4.1 "pattern validation" dependency was a weak rationale.

**Anchors:** `multi_agent/runtime/eventhub.py:217,260,282,445,485`.
**Pre-phase O14 callsite-threading sweep (mandatory):** `hub_tools.py` (eventhub_subscribe_call wrapper), `communication_tools.py:1347`, `team_runtime/reasoning.py:285`, `agent_spawn_service.py:392-393` (terminate_agent path), `live_monitor_server.py` HTTP shim. Without these, the gate only catches the in-memory test surface, not the live spoof vector.
**Test plan:** `tests/test_phase_4_1_eventhub_caller_gate.py` covers each callsite family.
**Risk:** hot path; caller-threading is a SIGNATURE CHANGE across ~5 callsite families. Effort revised from M to M-to-L per critique.

---

### Phase 4.1b — EventHub publish-side identity gate

**What it does.** At `phase>=4.1b` (or co-shipped with 4.1), gates `publish_human_message:317`, `publish_agent_reply:343`, `update_thread_summary:636`, `record_agent_status:690`. Each takes a `caller` kwarg; raises `PermissionError` if `caller and caller != from_user/agent_id` argument with the same `{orchestrator, eventhub}` exception.

**Why it matters.** Same trivially-spoofable class as 4.1 — `from_user` / `agent_id` arguments are unverified. Closes the publish-side half of the eventhub gap that the gap survey explicitly called out but the prior roadmap synthesis omitted.

**Anchors:** `multi_agent/runtime/eventhub.py:317,343,636,690`.
**Test plan:** mirrors 4.1.
**Risk:** same caller-threading work as 4.1; co-shipping bounds it.

---

### Phase 4.2 — schema_hub data-write surface lock

**What it does.** At `phase>=4.2`, gates the three schema_hub write entry points that bypass `register_table`'s Phase 1 gate.
- `update_table_schema:180` allowed = `{backend, database_worker}` — closes the breaking-change-recorder side channel at `schema_hub.py:197-204` which fires BEFORE `register_table`'s inner re-entry.
- `register_seed_data:287` allowed = `{backend, database_worker, database, seed_generator}` — per critique, the v3 `database_agent.j2:186` calls without explicit `agent=` (empty fallthrough handles), but a Phase-1-style demotion grace period means a `'database'` caller is also legitimate.
- `register_table_consumer:213` allowed = `{backend, frontend}`.
Empty-actor fallthrough preserved; mirror `register_table` message format.

**Why it matters.** Closes the canonical Phase 1 drift identified in the gap survey — under Phase 1 today, an actor can call `update_table_schema(agent='design')` and side-effect via the breaking-change recorder BEFORE the inner `register_table` gate fires. Also locks seed-data write surface (precondition for Phase 5+ data-realism evidence).

**Anchors:** `multi_agent/runtime/schema_hub.py:180,213,287`.
**Test plan:** ResolverFixtureContracts subclass + breaking-change-recorder ordering test (writes are gated BEFORE the recorder fires).
**Risk:** allowed-set design needs revisit; critique flagged the `{database_worker, seed_generator}` set as too narrow against existing prompts.

---

### Phase 4.5a/b/c — WorkHub mutation-surface ownership lock

**What it does.** Three sub-PRs to bound test sweep.
- **4.5a planning:** `create_page:36`, `create_plan:113`, `create_task:198`, `add_task_to_plan:834`, `archive_page:795`, `set_project_info:989`, `set_project_phase:1014` — allowed = `{orchestrator, planner, design}`.
- **4.5b state:** `claim_task:238`, `set_task_priority:405`, `link_task_to_pr:671`, `link_task_to_apis:686`, `fail_task:283`, `cancel_task:300` — allowed = `{orchestrator, task.claimed_by}`.
- **4.5c collaboration:** `comment:617`, `react:887`, `update_block:716`, `insert_block_after:733`, `update_plan_metadata:814`, `remove_attendee:903`, `record_decision:923`, `share_implementation:1045` — allowed = `page.attendees ∪ {orchestrator}`.

**Why it matters.** Closes 25 of 53 `KNOWN_DEFERRED_TO_EXT` entries. WorkHub is the hot path for every agent — 3-sub-PR rollout bounds test-sweep risk per critique recommendation.

**Anchors:** `multi_agent/runtime/hubs/workhub/service.py` per-line entries above.
**Per-critique sequencing fix:** depends_on changed from `Phase 4.0` to `O1 (_role_gate helper)` only — workhub and MCP are independent surfaces. 4.5a→4.5b→4.5c serialized internally because 4.5b reads `task.claimed_by` which 4.5a's `create_task` gate populates.
**Test plan:** sub-PR per tier, ResolverFixtureContracts per group. Many existing fixtures pass `agent=''` (empty fallthrough handles).
**Risk:** highest behavioral risk in roadmap. `task.claimed_by` lookup adds store read on hot path — measure before committing.

---

### Phase 4.6 — CodeHub commit/PR/check authorship parity

**What it does.** At `phase>=4.6`, brings remaining CodeHub methods up to `merge_pull_request:500` parity (lines 509-535 is the canonical template). `record_commit:150` allowed = `{branch.owner, orchestrator}`; `open_pull_request:180` allowed = `{author == branch.owner, orchestrator}`; `submit_review:335` allowed = `pr.reviewers ∪ {orchestrator}`; `record_check:443` allowed = `{ci_runtime, verifier, orchestrator}` (CI runtime-only, mirrors `record_probe`); `resolve_conflict:737` / `create_release:875` / `ensure_branch:129` / `register_agent_repo:117` allowed = `{orchestrator, branch_owner}`.

**Why it matters.** Closes 5 codehub_* EXT entries. `record_check` gate is particularly important for the Phase 5+ behavioral-evidence track — today any agent can write a "passing" CI check that deliverability could consume.

**Anchors:** `multi_agent/runtime/hubs/codehub/service.py:150,180,335,443,117,129,737,875`.
**Per-critique sequencing fix:** depends_on changed from `Phase 4.5` to `O1` only — workhub and codehub are independent hubs and can ship in parallel post-O1.
**Test plan:** clone `merge_pull_request:518-535` byte-for-byte; ResolverFixtureContracts per method.
**Risk:** `branch.owner` / `pr.reviewers` lookup adds store reads on commit path.

---

### Phase 4.7-slim — HumanConsole `from_user` identity gate

**What it does.** Mirrors the Phase 4.1 caller-threading pattern (no new attestation primitive). At `phase>=4.7`, gates `start_conversation:22`, `send_message:72`, `mark_resolved:128` — accepts new `caller` kwarg, raises `PermissionError` if `caller and caller != from_user` argument, with exception for `caller in {orchestrator, human_console_runtime}`.

**Why it matters.** Per critique: the prior synthesis dropped Phase 4.7 because "attestation primitive itself is new infra without a clear design," but the simpler grounded fix is to mirror the eventhub subscription-identity pattern. Without this, `human_console.py:22-72` accepts `from_user='human_user'` default with no verification — a known-unfixed spoof vector that would fall off the radar without explicit tracking.

**Anchors:** `multi_agent/runtime/human_console.py:22,72,128`.
**Test plan:** mirrors 4.1.
**Risk:** low; small surface, mirrors validated pattern.

---

### Phase 5.0 — Behavioral-evidence track kickoff (placeholder)

**What it does.** Sentinel entry only — no runtime work in this phase. Names the 10 missing evidence types from the CURRENT CAPABILITIES survey as a visibly queued track: semantic flow oracles, state-tying probes, property/fuzz probes, authz cross-user matrix, performance baselines, security baseline (header/cookie/CORS scan + JWT validation + SAST), frontend reality probes (Playwright trace capture), visual diff scoring (wire `compute_ssim` into deliverability signal #7), mutation/regression evidence, MCP tool-call probes.

**Why it matters.** Per critique: the summary correctly noted these belong "in a separate behavioral-evidence track after the ownership refactor stabilizes," but without an explicit Phase 5.0 sentinel, the work falls off the radar. This entry keeps it visible without committing to scope.

**Anchors:** N/A (placeholder).
**Test plan:** N/A.
**Risk:** N/A; scope-TBD intentionally.

---

## 4. Orthogonal Optimizations

| ID | Title | Priority | Effort | Value | Status / Blocked-By |
|---|---|---|---|---|---|
| **O1** | `_role_gate.py` helper module — `require_actor(method_name, actor, allowed, phase)` for allowlist idiom + documented `runtime-only` and `owner-equals` variants (NOT one function — three idioms per critique) | P0 | S | critical | **READY**; blocks 3.1a, 4.0, 4.1, 4.1b, 4.2, 4.3, 4.4, 4.5a/b/c, 4.6, 4.7-slim |
| **O2** | `ResolverFixtureContracts` shared base class at `tests/fixtures/phase_resolver_contracts.py` — non-mocking, canonical-writer-driven. **Frame-inspection guard dropped per critique** (replaced with code-review convention). | P0 | M | critical | **READY**; blocks 3.1b, 3.5, 3.9 |
| **O3** | Phase-coupling preflight CI matrix — full suite at phases `[0.0, 1.0, 2.0, 2.5, 3.0]` gated to PRs touching `runtime/` or `tests/test_phase_*`; pin failure-set HASH per phase (not raw counts) | P0 | M | high | **READY**; **blocks all Phase 4.x landings** per critique |
| **O4** | Invert `test_monitor_call_gate_invariant` detector to fail-closed (TODO at `agent/tests/test_monitor_call_gate_invariant.py:383-390`) — auto-closes EXT pins as gates land | P1 | S | high | **EXT-DEFER** per the TODO's own marker (line 388: "This inversion is EXT scope and is not landed in the shipped narrow-scope invariant"); 1423-LOC test-file refactor with surface to surface latent verb-free mutators (`amend` / `purge` / `rename_page`) — requires explicit human-in-loop scope decision, NOT autonomous safe. Workflow `wn35cnasy` infra-failed mid-flight 2026-06-01 |
| **O5** | Auto-generate `docs/phase_*_activation_log.md` table between `<!-- AUTOGEN_MECHANISMS_BEGIN/END -->` markers from `_MECHANISMS`; `tests/test_activation_log_autogen_in_sync.py` enforces parity | P1 | S | medium | **SHIPPED** (autogen markers in `docs/phase_1_2_2_5_activation_log.md`; 4-case sync test in `agent/tests/test_activation_log_autogen_in_sync.py`; verified 2026-06-01 by audit `wa5yo72qt`) |
| **O6** | `_resolve_actor(agent, provider, default)` helper — eliminates ~15 LOC duplication, closes C2-flagged normalization drift | P2 | S | medium | **READY**; folds into O1 |
| **O7** | `apihub.py:558-567` time-sort helper — `list_contract_test_results_sorted(endpoint_id, *, by='created_at', desc=True)` method; `get_contract_test_results` at `apihub.py:552-556` stable | P1 | S | medium | **SHIPPED** (already in tree; 7 tests at `test_apihub_contract_test_results_sorted.py` green; audit workflow `w4nwdh020` confirmed APPROVED 2026-06-01); unblocks 3.5 |
| **O8** | Drop dead LWWMap migration code in `json_store.py:87-101` + `_unwrap_lwwmap`; ship `tools/migrate_jsonstore.py` for stragglers | P3 | S | low | READY; orthogonal |
| **O9** | Replace 2.0s `_time.sleep` at `hubs/runhub/service.py:477` with `_poll_alive(proc, deadline=2.0, interval=0.05)` — saves 2s × (N-1) wall-time on multi-MCP sessions | P2 | S | medium | READY; orthogonal |
| **O10** | Enable `pytest-xdist` (`-n auto --dist=loadfile`) — halves CI wall-time | P2 | S | medium | READY; orthogonal |
| **O11** | Phase-aware structured tracer — `ELABORATION_REFACTOR_PHASE_TRACE=1` emits `{phase, gate_name, file:line, actor, decision}` JSON per dispatch | P2 | M | medium | READY; orthogonal |
| **O12** | Delete `agent/tests/run_regressions.py` thin pytest delegate (44 LOC fossil) | P3 | S | low | READY |
| **O13** | Hoist `deliverability.py` per-mechanism `_summary` helpers into Protocol-based plugin registry — future deliverability additions become one-liners | P2 | M | medium | READY; blocks Phase 5.0 deliverability extensions |
| **O13b** | **Wire `compute_ssim` into `deliverability.py` signal #7 (visual) as a SECOND consumer** — not "move to experimental" (rejected per critique: compute_ssim IS wired into `user_gates.py:212-241,465`, the original opt was based on a false premise) | P2 | S | medium | READY; blocks Phase 3.9 SSIM tie-in (informational only) |
| **O14** | **EventHub caller-threading pre-phase sweep** — thread `caller` kwarg through `hub_tools.py` (subscribe_call wrapper), `communication_tools.py:1347`, `team_runtime/reasoning.py:285`, `agent_spawn_service.py:392-393`, `live_monitor_server.py` HTTP shim | P0 | M | high | **MANDATORY** pre-Phase-4.1 per critique |
| **O15** | **`record_api_test` 16-callsite audit + verifier-identity sweep** (audit found 16 sites, not 8) — resolved via Path A bundle-trim: `apihub_record_contract_test` extracted from `_bundle_apihub_tools` into dedicated `_bundle_verifier_contract_tools` (`tool_bundles.py:451`); `agents_config.yaml:582` grants tool ONLY to verifier profile. Closed-by-construction at the bundle layer | P0 | S | high | **SHIPPED** (Phase 4.4 shipped with Path A; original BLOCKER structurally eliminated; verified 2026-06-01) |
| **O16** | `BlockerCode` enum / canonical templates module — extract from `deliverability.py:198-211` f-string blockers (orchestrator's `_validate_delivery_gate` anchored-substring-matches today, fragile) | P2 | S | medium | READY; orthogonal |

---

## 5. Top 3 Recommended Next Ships

### Recommendation #1 — Ship O1 + O2 + O3 as a single pre-Phase-3 infrastructure PR

**Rationale.** All three are zero-runtime-semantics infrastructure that compound across every Phase 3 and Phase 4 entry. **O1** (`_role_gate.py` helper module with three idiom variants) unblocks all 8 Phase 4.x ownership gates and the Phase 3.1a `register_story` gate — eliminating ~50 LOC of duplicated allowlist code while standardizing the `.strip().lower()` normalization, empty-actor fallthrough, and `PermissionError` message format that R2-round-11 flagged as drifting between `schema_hub:128-138`, `apihub:160-167`, and `runhub:55-72`. **O2** (ResolverFixtureContracts base class, frame-guard dropped) is the primary correctness gate that would have caught both BLOCKER B1 (endpoint_contract reading a non-existent verdict field) and concern C1 (visual reading non-existent page_key) on Candidate C — without it, Phase 3.1 ships with the same schema-misread failure class. **O3** (phase-coupling preflight CI matrix with hashed failure sets) prevents another 60-failure surprise at phase>=2.5 like the one that motivated the 15-file hygiene sweep in commit 50ccd029. Effort S/M/M, value critical/critical/high.

### Recommendation #2 — Ship Phase 3.0-bootstrap + Phase 3.1a as two small PRs

**Rationale.** The original Phase 3.1 was over-scoped at L per critique — splitting into 3.0-bootstrap (instance plumbing + hub_registry injection, zero gate semantics) and 3.1a (`register_story` actor gate + StoryHubStores byte-for-byte clone of RunHubStores) bounds risk and matches the R2-recommended Phase 0.3-style inert-then-active pattern that has shipped cleanly 6 times now. Each piece is independently reviewable, <300 LOC, and closed-by-construction. 3.1b (4 resolvers + deliverability wiring + `_MECHANISMS` append) then follows as the second PR with a clean focus on namespace correctness and the deliverability-side wiring, gated by O2's ResolverFixtureContracts.

### Recommendation #3 — Co-ship Phase 3.5 + Phase 4.4 as a single PR

**Rationale.** This co-ship pattern mirrors the closed-by-construction discipline the project has used since the Phase 0.2 pre-pilot fix-set. Shipping 3.5 alone activates the `endpoint_contract` resolver but leaves record authorship spoofable by any agent — recreating BLOCKER B1's failure class one layer up (broken-by-authorship rather than broken-by-shape). The co-ship requires: (a) the 8-callsite audit O15 (all currently pass `agent='verifier'`, sweep is bounded), (b) the additive verdict-field derivation rule (original `result` dict unchanged, forward+backward compat), (c) the new `list_contract_test_results_sorted` accessor with `get_contract_test_results` stable, (d) the `{verifier, contract_test_runtime}` allowed set on `record_api_test`, (e) the `endpoint_contract` namespace resolver in StoryHub. The ResolverFixtureContracts test for `endpoint_contract` writes two records for the same `endpoint_id` 100ms apart and asserts the resolver sees the later one's verdict regardless of insertion order — exactly the kind of test that would have caught the original Candidate C bug.

---

## 6. Intentionally Out of Scope

The following items were considered and **explicitly excluded** from the Phase 3-4 horizon:

1. **The 10-item behavioral-evidence track** (semantic flow oracles, state-tying probes, property/fuzz, authz matrix, latency budgets, security baseline, frontend reality probes, visual diff scoring, mutation/regression evidence, MCP tool-call probes) — real product value but each item invents new infrastructure (body fuzzers, Playwright orchestration, paired-read endpoint heuristics, latency budget tables, SAST runners) that lacks grounding in shipped patterns. Tracked as Phase 5.0 sentinel only. **Do not start until Phase 4.6 stabilizes.**

2. **`require_stories` mandatory-registration flag at phase>=3.x** — DEFERRED C3 explicitly says "leave as planner responsibility for v1" and "only IF real pilots show stories being silently skipped." No pilot evidence yet; would add surface area before signal.

3. **SSIM threshold default `0.85`** — no calibration evidence cited in any audit. Require explicit `project.visual_ssim_threshold` opt-in or leave as TBD until pilot-derived.

4. **`_assert_no_mocks_below_this_frame()` frame-inspection guard in ResolverFixtureContracts** — novel mechanism with no shipped precedent; frame inspection is fragile. Replaced with code-review-enforced convention. May revisit as "followup hardening" optimization after O2 v1 lands.

5. **HumanConsole identity attestation primitive** (the "verified human identity" version) — explicitly out of scope; the slim Phase 4.7 caller-kwarg mirror is the grounded fix. The full attestation primitive can be revisited as a Phase 5+ item if the slim version proves insufficient.

6. **`update_table_schema` / `update_schema` / `update_block` etc. full ownership matrix beyond actor gates** — page.attendees and pr.reviewers lookups are bounded scope (Phase 4.5c, 4.6). Cross-hub authorization (e.g., "design can edit workhub pages owned by frontend") is deferred until at least one real pilot demonstrates the need.

7. **`_BRANCH_TRACE` -> production telemetry pipeline** — O11 ships the local JSON tracer; piping to a structured logging backend is a separate operational concern.

8. **Phase 0.6 (rollback protocol) and Phase 0.7 (inert-anchor compliance)** — process artifacts, not runtime mechanisms. Captured implicitly through O2 (ResolverFixtureContracts) and O5 (autogen activation log).

---

## Appendix A — Key Files Referenced

- `/data/common/haibotong/env-gen/docs/phase_1_2_2_5_activation_log.md`
- `/data/common/haibotong/env-gen/docs/phase_2_5_test_hygiene_audit.md`
- `/data/common/haibotong/env-gen/docs/phase_3_mechanism_design_notes.md`
- `/data/common/haibotong/env-gen/docs/known_deferred_ext.md`
- `/data/common/haibotong/env-gen/agent/env_generator/llm_generator/multi_agent/runtime/elaboration_phase.py` (lines 374-387: `_MECHANISMS`)
- `/data/common/haibotong/env-gen/agent/env_generator/llm_generator/multi_agent/runtime/story_hub.py` (lines 11-100: inert scaffold)
- `/data/common/haibotong/env-gen/agent/env_generator/llm_generator/multi_agent/runtime/deliverability.py` (lines 187-256: 7 signals)
- `/data/common/haibotong/env-gen/agent/env_generator/llm_generator/multi_agent/runtime/user_gates.py` (lines 212-241, 465: existing `compute_ssim` consumer — critique-confirmed)
- `/data/common/haibotong/env-gen/agent/tests/test_monitor_call_gate_invariant.py` (lines 531-585: `KNOWN_DEFERRED_TO_EXT` 53-entry pin set)
