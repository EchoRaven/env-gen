# Phase 1 / 2 / 2.5 Activation Log

Reference doc for the progressive-elaboration refactor mechanisms shipped
across the 2026-05-30 → 2026-06-01 session arc. The system currently has
**16 anchors** (14 active + 2 inert at story_hub.py phase>=3.0) backing
**14 `_MECHANISMS` entries** across 7 thresholds (1.0×3, 2.0×2, 2.5×3,
4.0×2, 4.4×1, 4.5×2, 4.6×1); prompt halves are wired into design /
backend / frontend / database / verifier / orchestrator v3 templates.
This log records what's live, how to activate each phase, where the
tests are, and which commits to point at when auditing.

For the original design intent see
[`progressive_elaboration_refactor.md`](progressive_elaboration_refactor.md).
For the Phase 0.3 anchor inert install see commit `5dbe657e`.

---

## Activation ladder

`ELABORATION_REFACTOR_PHASE` is an environment variable read by
`multi_agent/runtime/elaboration_phase.get_phase()`. Invalid / negative
values fall back to `0.0`. Unset = `0.0` (default).

The ladder is cumulative — each higher phase keeps all lower-phase
constraints active.

| Phase | Effects |
|------:|---------|
| `0.0` (default unset) | v0.x byte-identical. All gates inactive; all prompts render baseline. |
| `1.0` | + `schema_hub.register_table` locked to `{backend, database_worker}`. + `schema_hub.update_table_schema` (sibling) locked to same set. + `schema_hub.register_seed_data` (sibling) locked to `{backend, database_worker, database}` (admits the database resident lane the seed_tools bundle is granted to). `register_table_consumer` deliberately ungated (inverse semantics — consumer side). + design v3 lose-DB block. + backend v3 gain-DB block. + database v3 demotion block. |
| `2.0` | + `apihub.register_endpoint` locked to `{backend}`. + `EventHub.publish_api_requirement` channel activates (frontend→backend handshake). + design v3 lose-API block. + backend v3 gain-API + api_requirement inbox block. + frontend v3 publish_api_requirement block. |
| `2.5` | + `visual_similarity.compute_ssim` server-side body fills (PIL+numpy SSIM). + `RunHub.record_probe` locked to `{runhub}` runtime-only (closes agent-fabricates-evidence path). + `RunHub.start_run` probe loop enriches each `probe_record` with `body_excerpt` truncated to 256B. |
| `3.5` | + `apihub.record_api_test` writes a top-level `verdict` field ("pass"/"fail"/"unknown") derived from result.passed → result.result → result.status_code (in priority order). Original `result` dict preserved. + `story_hub._resolve_endpoint_contract` registered against the `endpoint_contract:<endpoint_id>` namespace — reads `list_contract_test_results_sorted(endpoint_id)[0].verdict` for unambiguous lookup; latest record wins (closes original Candidate C `results[-1]` bug). Phase 3.5 Path B simplified: NO `contract_test_runtime` widening — Phase 4.4 stays `{verifier}`-only. |
| `3.9` | + `gate_registry.list_visual_reviews(route=None)` public helper added. + `story_hub._resolve_visual` resolves the `visual:<route>` namespace, keyed by `metadata.route` (NOT page_key — closes original C1 design error). Inverted phase guard (< 3.9 returns "evidence_pending") so the namespace is always registered (legacy stories don't fail with unsupported_namespace; they go pending instead). SSIM-None → evidence_pending per the compute_ssim contract. Phase 3.9 Path B simplified: NO `visual_similarity_runtime` widening — Phase 4.5 stays `{visual_reviewer}`-only. |
| `4.0` | + `mcp_registry.register_mcp_server` locked to `{backend}`. + `mcp_registry.register_mcp_tool` locked to `{backend}`. `register_mcp_consumer` remains open by wrapper-hedge design. + `live_monitor_server` MCP-server HTTP endpoint default agent flipped to `backend` (was `ui_user`). |
| `4.4` | + `apihub.record_api_test` locked to `{verifier}`. Defense-in-depth behind Path A bundle trim (`_bundle_verifier_contract_tools` + verifier-only `agents_config.yaml` grant). |
| `4.5` | + `gate_registry.submit_design_review` locked to `{architect_reviewer}`. + `gate_registry.submit_visual_review` locked to `{visual_reviewer}`. + `gate_registry.mark_path_intentionally_dead` locked to `{orchestrator}` (Phase 4.5d Path A retire-to-gate_registry — replaces dropped Phase 4.5a/b/c WorkHub bundle). `register_visual_review_task` + `submit_design_for_review` stay open by design. + `live_monitor_server` HTTP review-shim defaults flipped `"ui_user"` → `""` (empty-actor fallthrough preserves UI behavior). |
| `4.6` | + `codehub.submit_review` locked to `pr.reviewers ∪ {orchestrator}` (data-driven allowed_set, unique to this gate). + **Phase 4.6.1**: `codehub.record_check` locked to `{orchestrator} ∪ pr.checks_authorized ∪ pr.reviewers`; `open_pull_request` gained `checks_authorized: list[str]` kwarg mirroring the `reviewers` plumbing. Both gates use PR-lifecycle family inline dict-return shape. `request_review` + `open_pull_request` stay open pending callsite cleanup. + `live_monitor_server.py:3880` HTTP shim default flipped `"ui_user"` → `""`. |
| `4.7` | + `EventHub.publish_human_message` rejects phantom `from_user` (literal `"human_user"` OR empty) — the project's 甲方 (the actual human user id) must be set via `ENVGEN_HUMAN_USER_ID` env var (Path A), `human_user_id=...` kwarg to `HubRegistry`, explicit `from_user="<user_id>"` per-call, OR (Path C 2026-06-01) an authed session cookie on the live_monitor HTTP surface that resolves the username into `body["from_user"]` via `_apply_request_user`. Precedence: Path C > body-supplied from_user > Path A env var > literal "human_user" (rejected). HumanConsole captures the id at construction and threads it through `start_conversation` / `send_message`. |
| `4.11` | + `EventHub.publish_event` (and the 4 wrappers — `publish_agent_reply` / `publish_human_message` / `publish_api_requirement` / `record_agent_status`) gain `caller=<author>` kwarg + run `_phase_4_1c_source_hub_gate`. At phase>=4.11, owner-equals (caller==source_hub) admits OR per-hub sentinel allowlist (apihub admits schema_hub/mcp_registry; workhub admits gate_registry; human_user admits live_monitor/messagebus_bridge) admits. Cross-hub forgery (agent threading caller=story_writer against source_hub=codehub) raises PermissionError. Legacy phantom source_hubs (`system`/`messagebus`/`verifier`/`ui`) admit via empty-caller fallthrough only — migration parked per Path B discipline (follow-up cleanup PR). All 7 hub `_emit` wrappers (apihub/schema_hub/mcp_registry/gate_registry/codehub/workhub/runhub/story_hub) threaded `caller=<hub_name>`. `record_agent_status` deliberately does NOT propagate caller= (source_hub="system" stays parked). Sibling slot to Phase 4.1 subscription-side gate; independently flippable. |

Higher phases (`3.0`, `3.5`) are reserved in `elaboration_phase.py`
constants but no anchors yet exist for them.

---

## How to activate

Shell:
```bash
export ELABORATION_REFACTOR_PHASE=2.5
```

Python test:
```python
with mock.patch.dict(os.environ, {"ELABORATION_REFACTOR_PHASE": "2.5"}):
    # phase-gated behavior active here
    ...
```

Prompt rendering picks up the same value automatically via
`configurable_agent._get_context_vars` which auto-injects
`elaboration_phase` into every Jinja render context.

---

## Anchors and mechanisms

### Anchor A — schema_hub.register_table (Phase 1)

- **Module**: `multi_agent/runtime/schema_hub.py:103+`
- **Mechanism PR**: commit `cf4658f5`
- **Behavior at phase >= 1.0**: rejects `agent` or `provider` values
  outside `{backend, database_worker}` with `PermissionError`. Empty
  identity falls through (test / HTTP / system paths preserved).
- **Tests**: `tests/test_phase_1_schema_hub_role_gate.py` (19 tests).
- **Prompt halves**: design v3 lose-DB block, backend v3 gain-DB
  block, database v3 demotion block (commits `12e355a0`, `bf3adbc6`).

### Anchor A.1 — schema_hub.update_table_schema (Phase 1 sibling)

- **Module**: `multi_agent/runtime/schema_hub.py:188+`
- **Behavior at phase >= 1.0**: rejects `agent` values outside
  `{backend, database_worker}` with `PermissionError`. Empty actor
  falls through. Sibling of register_table; gates the breaking-change
  recorder before delegating to register_table.
- **Closes Phase 1 drift** identified by the Phase 4+ roadmap O15
  audit. Workflow `w7el18fh7` (commit-pending).
- **Tests**: `tests/test_phase_4_2_schema_hub_sibling_gates.py`
  (UpdateTableSchemaGate class, 5 cases).
- **HTTP wrapper note**: `live_monitor_server.apihub_update_table_schema_call`
  default agent flipped `"ui_user"` → `"backend"` to satisfy the gate.

### Anchor A.2 — schema_hub.register_seed_data (Phase 1 sibling)

- **Module**: `multi_agent/runtime/schema_hub.py:326+`
- **Behavior at phase >= 1.0**: rejects `agent` values outside
  `{backend, database_worker, database}` with `PermissionError`.
  The literal `"database"` is in the allowed-set because the
  production `seed_tools` bundle hardcodes that string (workflow
  caught this as BLOCKER 1; widening avoids rejecting 100% of
  production callers).
- **Tests**: `tests/test_phase_4_2_schema_hub_sibling_gates.py`
  (RegisterSeedDataGate class, 6 cases).
- **Scope note**: `register_table_consumer` deliberately remains
  UNGATED at any phase — its `agent` arg identifies the consumer
  (any reading lane), not the table owner. Tests in
  RegisterTableConsumerStaysUngated class verify this invariant.

### Anchor B — EventHub.publish_api_requirement (Phase 2)

- **Module**: `multi_agent/runtime/eventhub.py:159+`
- **Mechanism PR**: commit `9ca2885c`
- **Behavior at phase >= 2.0**: publishes a typed `api_requirement`
  event with `source_hub='eventhub'`, `recipients=['backend']`,
  payload carrying `flow_id`, `needed_data_shape`, `agent`, **kwargs.
  Pre-Phase-2 returns `None`.
- **Tests**: `tests/test_phase_2_api_requirement_channel.py` (17 tests).
- **Prompt halves**: frontend v3 publish_api_requirement block,
  backend v3 api_requirement inbox subscription block (commits
  `12e355a0`, `05dda799`).

### Anchor — apihub.register_endpoint (Phase 2, no Phase 0.3 anchor)

- **Module**: `multi_agent/runtime/apihub.py:140+`
- **Mechanism PR**: commit `bcc0b0ac`
- **Behavior at phase >= 2.0**: rejects `agent` or `provider` values
  outside `{backend}` with `PermissionError`. Same fall-through
  pattern as Anchor A.
- **Tests**: `tests/test_phase_2_apihub_role_gate.py` (18 tests).
- **Note**: did NOT have a Phase 0.3 inert anchor; added the gate
  directly using the established role-gate pattern.

### Anchor C — RunHub.record_probe (Phase 2.5)

- **Module**: `multi_agent/runtime/hubs/runhub/service.py:55+`
- **Mechanism PR**: commit `d232adb7`
- **Behavior at phase >= 2.5**: rejects callers where `agent != 'runhub'`.
  Closes the agent-fabricates-evidence path — only the RunHub runtime
  itself may author probe records when the gate is active. Empty
  agent falls through.
- **Tests**: `tests/test_phase_2_5_record_probe_gate.py` (13 tests).

### Anchor D — visual_similarity.compute_ssim (Phase 2.5)

- **Module**: `multi_agent/runtime/visual_similarity.py`
- **Mechanism PR**: commit `5edf4302`
- **Behavior at phase >= 2.5**: runs Wang et al. 2004 SSIM via
  PIL + numpy. Returns float in `[0.0, 1.0]`. Returns `None` on:
  file missing, PIL/numpy import failure, zero-variance edge cases.
  Auto-resizes the generated image to the reference's dimensions
  before comparison. Global (full-image) SSIM, not windowed.
- **Tests**: `tests/test_phase_2_5_visual_similarity.py` (13 tests).
- **Implementation choice**: custom SSIM rather than scikit-image —
  PIL+numpy are already env-gen deps; scikit-image would be a heavy
  new addition for one function.

### Anchor E — RunHub.start_run probe loop (Phase 2.5)

- **Module**: `multi_agent/runtime/hubs/runhub/service.py:265+`
  (inline anchor inside `start_run`'s probe loop)
- **Mechanism PR**: commit `118732e8`
- **Behavior at phase >= 2.5**: each `probe_record` gains a
  `body_excerpt` field truncated to 256B. Pre-Phase-2.5: bare 9-field
  record (method/path/url/verdict/severity/note/status_code/
  transport_error/latency_ms).
- **Tests**: `tests/test_phase_2_5_probe_record_evidence.py` (7 tests).
- **Note**: this anchor was missed in the initial Phase 0.3
  enumeration which counted 4 anchors. It lives INSIDE `start_run`
  rather than as a standalone method, so a top-level grep missed it.

### Anchor F — story_hub.register_story (Phase 3, INERT)

- **Module**: `multi_agent/runtime/story_hub.py:63-67`
- **Status**: INERT (Phase 0.3-style scaffold). Both branches of the
  `if get_phase() >= 3.0:` block are no-op; the function returns a
  synthetic record marked `_synthetic: True` regardless of phase.
- **No `_MECHANISMS` entry** — by design. The Phase 3 mechanism PR
  will replace the `pass` body with real persistence (JsonStore-backed
  story records + EventHub emit + evidence-target cross-check against
  APIHub / WorkHub / RunHub) and add the row at that time.
- **HubRegistry handle**: `registry.story_hub.register_story(...)` —
  pure delegation to the module-level free function. See "Phase 3.0
  bootstrap" subsection below.
- **Tests**: `tests/test_phase_3_story_hub_inert.py` (24 tests across
  6 classes; 14 original inert + 6 StoryHubClassDelegation + 4
  HubRegistryStoryHubWiring).
- **DEFER docs**: `docs/phase_3_1a_register_story_gate_design_notes.md`
  captures the workflow `wx3el8bur` analysis — the role gate awaits
  the Phase 3 mechanism PR's caller decision + O2 ResolverFixtureContracts.

### Anchor G — story_hub.evaluate_story_gate (Phase 3, INERT)

- **Module**: `multi_agent/runtime/story_hub.py:94-100`
- **Status**: INERT. Both branches return `{"ok": True, "stories": []}`
  pre-Phase-3 baseline. The Phase 3 mechanism PR will walk each
  story's `evidence_targets` and dispatch by namespace
  (`api_smoke` / `ui_flow` / `table` / `mcp`) — but the resolver bodies
  themselves are deferred per workflow `w8z0em332`.
- **No `_MECHANISMS` entry** — by design. Will land when the resolver
  module + the deliverability hook are wired (depends on Phase 3.1a +
  O2 ResolverFixtureContracts).
- **HubRegistry handle**: `registry.story_hub.evaluate_story_gate(...)`.
- **Tests**: shared module with Anchor F
  (`tests/test_phase_3_story_hub_inert.py`).
- **DEFER docs**:
  `docs/phase_3_1b_namespace_resolvers_design_notes.md` (workflow
  `w8z0em332`).

### Anchor H — mcp_registry.register_mcp_server (Phase 4)

- **Module**: `multi_agent/runtime/mcp_registry.py:86+`
- **Behavior at phase >= 4.0**: rejects `agent` or `provider` values
  outside `{backend}` with `PermissionError`. Empty identity falls
  through (test / HTTP / system paths preserved). The production
  tool wrapper `RegisterMCPServerTool` already defaults
  `provider="backend"`; the gate makes that wrapper intent
  load-bearing.
- **Tests**: `tests/test_phase_4_0_mcp_registry_role_gate.py`
  (ServerHalf class, 4 cases).
- **HTTP wrapper note**: `live_monitor_server.apihub_register_mcp_server_call`
  was updated to default `agent="backend"` (previously `"ui_user"`)
  so the live monitor panel keeps working at phase >= 4.0.

### Anchor I — mcp_registry.register_mcp_tool (Phase 4)

- **Module**: `multi_agent/runtime/mcp_registry.py:127+`
- **Behavior at phase >= 4.0**: rejects `agent` or `provider` values
  outside `{backend}` with `PermissionError`. Empty identity falls
  through. Mirrors Anchor H — together these two gates lock the
  backend-authored contract halves (server + tool).
- **Tests**: `tests/test_phase_4_0_mcp_registry_role_gate.py`
  (ToolHalf class, 4 cases; plus ConsumerStaysOpen, 2 cases).
- **Scope note**: `register_mcp_consumer` deliberately remains open;
  its wrapper description ("Consumer agents, typically frontend")
  explicitly admits non-frontend consumer lanes by design.

### Anchor K — gate_registry.submit_design_review (Phase 4.5)

- **Module**: `multi_agent/runtime/gate_registry.py:143+`
- **Behavior at phase >= 4.5**: rejects `reviewer` values outside
  `{architect_reviewer}` with `PermissionError`. Empty reviewer falls
  through (HTTP shim default `""` lets the live monitor panel call
  pass; production caller `architect_reviewer` agent passes literal).
- **Trust surface**: design review verdicts (state=approve /
  needs_revision) carry trust into the delivery gate.
- **HTTP wrapper note**: `live_monitor_server.workhub_submit_design_review_call`
  default flipped `"ui_user"` → `""` to avoid whitelisting the phantom.
- **Tests**: `tests/test_phase_4_5_gate_registry_review_role_gate.py`
  (SubmitDesignReviewGate class, 4 cases).

### Anchor L — gate_registry.submit_visual_review (Phase 4.5)

- **Module**: `multi_agent/runtime/gate_registry.py:305+`
- **Behavior at phase >= 4.5**: rejects `reviewer` values outside
  `{visual_reviewer}` with `PermissionError`. Empty reviewer falls
  through (same HTTP shim pattern as Anchor K).
- **Trust surface**: visual review verdicts (state=approve +
  similarity_score) feed the delivery gate's visual evaluation.
- **HTTP wrapper note**: `live_monitor_server.workhub_submit_visual_review_call`
  default flipped `"ui_user"` → `""`.
- **Scope note**: `register_visual_review_task` +
  `mark_path_intentionally_dead` + `submit_design_for_review`
  deliberately remain UNGATED — they don't author trust-bearing
  verdicts (per workflow Candidate C minimal-verdicts-only scoping).
- **Tests**: `tests/test_phase_4_5_gate_registry_review_role_gate.py`
  (SubmitVisualReviewGate, 4 cases; UngatedSiblingsStayOpen, 3 cases).

### Anchor S — codehub.record_check (Phase 4.6.1)

- **Module**: `multi_agent/runtime/hubs/codehub/service.py` (gate
  at the head of `record_check`).
- **Behavior at phase >= 4.6**: rejects `agent` values outside
  `{orchestrator} ∪ pr.checks_authorized ∪ pr.reviewers` with a
  structured dict-return `{"error": "record_check_role_denied",
  "method": "codehub.record_check", "pr_id": ..., "actor": ...,
  "allowed": [...], "phase_threshold": 4.6, "hint": "..."}` (NOT a
  raise — PR-lifecycle family idiom matching submit_review).
- **Data-model plumbing**: `open_pull_request` gained
  `checks_authorized: Optional[List[str]]` kwarg (mirrors the
  `reviewers` plumbing pattern). When set, those agents are
  admitted in addition to the reviewers + orchestrator fallback.
  Persisted into the pr dict alongside `reviewers`.
- **Empty-actor fallthrough**: un-threaded callsites
  (`hub_registry.py:280/428`, `step_pipeline/helpers.py:189`,
  `live_monitor_server.py:4035` all pass `agent=""` or compute one
  that may be empty) pass via the established empty-actor
  convention.
- **Orphan PR**: when `pr_id` does not exist, the gate falls
  through and `record_check` creates the check row regardless —
  preserves back-compat for the existing record_check semantic
  that doesn't require the PR to exist.
- **Why Phase 4.6.1 ships at threshold 4.6, NOT 4.61**: per the
  `wnjpij4xw` audit recommendation, the repo uses single-decimal
  float thresholds; 4.61 would break granularity and 4.7 is
  occupied. `record_check` is a near-identical instance of the
  PR-LIFECYCLE-ALLOWLIST idiom (`a4cac71f`, Anchor M) applied to
  a sibling method in the same family. Extends the 4.6 row from 1
  to 2 mechanism entries. Mechanism count 22→23.
- **Tests**: `tests/test_phase_4_6_1_record_check_role_gate.py`
  (8 classes, 13 cases): DataModelPlumbing (3 — checks_authorized
  default/explicit/None), PhaseBelow46AdmitsAll (1),
  PhaseAt46OrchestratorAdmits (1), PhaseAt46ReviewerAdmits (1),
  PhaseAt46ChecksAuthorizedAdmits (2 — match + case-insensitive),
  PhaseAt46RandomAgentRejects (2 — dict-return shape + content),
  EmptyActorFallthrough (2 — empty + whitespace), OrphanPRAdmits (1).

### Anchor M — codehub.submit_review (Phase 4.6)

- **Module**: `multi_agent/runtime/hubs/codehub/service.py:335+`
- **Behavior at phase >= 4.6**: rejects `reviewer` values outside the
  data-driven set `pr.reviewers ∪ {orchestrator}` with a structured
  dict-return `{"error": "submit_review_role_denied", ...}` (NOT a
  raise — joins the PR-lifecycle gate family alongside
  merge_pull_request / force_merge_pull_request / resolve_conflict).
- **Trust surface**: PR review verdicts feed `_is_pr_approved` which
  gates merge. Without this gate, hub_tools.py reviewer=self._agent_id
  plumbing lets any agent post approve on any PR.
- **Data-driven allowed_set**: unique among gates so far —
  `allowed = {"orchestrator"} | set(pr.get("reviewers") or [])`. Each
  PR has its own admit list per its own reviewers field.
- **HTTP wrapper note**: `live_monitor_server.py:3880`
  `codehub_submit_review_call` default flipped `"ui_user"` → `""`
  (matches Phase 4.5 review-shim flip).
- **Deferred (per workflow)**: `request_review`, `record_check` stay
  open pending callsite cleanup (live_monitor `"ui_user"` defaults +
  helpers.py `"unknown"` fallback). See workflow `w8dyd6ugx` notes.
- **Tests**: `tests/test_phase_4_6_codehub_submit_review_role_gate.py`
  (5 classes, 11 tests including DataDrivenAllowedSet class that
  verifies different PRs admit different reviewers).

### Anchor R — EventHub publish-side source_hub gate (Phase 4.1c / PHASE_4_11)

- **Module**: `multi_agent/runtime/eventhub.py` (inverted guard
  `if _phase < 4.11:` at the head of
  `_phase_4_1c_source_hub_gate`).
- **Behavior at phase >= 4.11**: ``EventHub.publish_event`` runs the
  source_hub authorship gate. Owner-equals (``caller == source_hub``
  after `.strip().lower()`) admits; per-hub sentinel allowlist
  (``PHASE_4_1C_PUBLISH_SENTINELS``) also admits — e.g. schema_hub +
  mcp_registry publishing under apihub vocab, gate_registry under
  workhub, live_monitor + messagebus_bridge under human_user. Any
  other ``(caller, source_hub)`` pair with non-empty caller raises
  PermissionError with operator-greppable error text
  ("ELABORATION_REFACTOR_PHASE>=4.11").
- **Empty-caller fallthrough**: un-threaded callsites (no `caller=`
  kwarg) pass via the same convention all 21 prior gates use.
  Step A back-compat seam.
- **Per user 2026-06-01 directive**: source_hub semantic chosen over
  caller-threading. The 4 legacy phantom source_hubs (``system``,
  ``messagebus``, ``verifier``, ``ui``) ship with empty sentinel
  sets — admit ONLY via empty-caller fallthrough. Migration to real
  source_hubs is a follow-up cleanup PR (Path B discipline: never
  widen an allowed_set with a principal nobody authors as).
- **Threaded callsites in Step A**: 7 hub `_emit` wrappers (apihub /
  schema_hub / mcp_registry / gate_registry / codehub / workhub /
  runhub / story_hub) thread ``caller=<hub_name>``. ``publish_agent_reply``
  defaults ``caller=agent`` (owner-equals self-publish).
  ``publish_human_message`` accepts ``caller=`` (live_monitor threads
  ``caller="live_monitor"``). ``record_agent_status`` accepts ``caller=``
  for signature symmetry but DELIBERATELY DOES NOT propagate it —
  source_hub stays the parked phantom ``"system"`` until a migration
  PR coins a real source_hub.
- **Threshold value**: 4.11 (not 4.1.1 nor 4.7+1 — uses float
  granularity, sibling slot to 4.1 so subscription-side and publish-
  side are independently flippable).
- **Tests**: `tests/test_phase_4_11_publish_side_source_hub_gate.py`
  (6 classes, 21 cases): GateHelperUnit (6 — phase boundary,
  empty-caller, owner-equals, cross-hub sentinel, cross-hub
  rejection, phantom-legacy admit/reject), GateAtPublishEventCallSite
  (4), GateAtPublishAgentReply (2 — self-publish admit + external
  caller reject), GateAtPublishHumanMessage (3), GateAtRecordAgentStatus
  (2 — caller= deliberately not propagated), SentinelMapCoverage
  (4 — locks the sentinel map shape).

### Anchor Q — story_hub._resolve_visual (Phase 3.9 Path B)

- **Module**: `multi_agent/runtime/story_hub.py` (inverted guard
  `if _phase < 3.9:` at the head of `_resolve_visual`).
- **Behavior at phase < 3.9**: returns "evidence_pending" for every
  `visual:<route>` lookup — the namespace IS registered in
  ``_DEFAULT_RESOLVERS`` (so legacy stories that mention `visual:`
  don't fail with `unsupported_namespace_v1`), but no real
  pass/fail verdicts surface until phase>=3.9.
- **Behavior at phase >= 3.9**: keyed by `metadata.route` (NOT
  the opaque page_key — that was the C1 design error per
  ``docs/phase_3_9_visual_route_design_notes.md``). Reads
  ``gate_registry.list_visual_reviews(route=<route>)``; for each
  matching page maps:
    * status="approved" + latest approve review's similarity_score
      ≥ metadata.ssim_threshold (default 0.0) → "pass"
    * status="approved" + similarity_score < threshold → "fail"
    * status="approved" + similarity_score is None → "evidence_pending"
      (Phase 3.9 invariant: SSIM-None is pending NOT fail per
      compute_ssim's documented contract — None on import / file /
      zero-variance failure)
    * status="rejected" / "needs_revision" → "fail"
    * status="pending" / "reviewing" / missing → "evidence_pending"
  When multiple pages exist for the same route (re-registered after
  a fix), the most recently updated page wins.
- **Why Path B (simplified)**: Path A would widen Phase 4.5
  `submit_visual_review` to
  `{visual_reviewer, visual_similarity_runtime}` and introduce a
  new phantom runtime principal. Per user 2026-05-31 decision,
  Path B skips the widening and ships independently — the
  `visual_similarity_runtime` row stays parked in
  `phantom_runtime_registry.md` until a real SSIM-based
  programmatic reviewer component is introduced.
- **Companion helper**: `gate_registry.list_visual_reviews(route=None)`
  — public listing helper that returns every visual_review page
  (any status), optionally filtered to a single `metadata.route`.
  Newly added to gate_registry alongside the resolver.
- **Tests**: `tests/test_phase_3_9_visual_route.py`
  (5 classes, 16 cases): ListVisualReviewsHelper (3 cases),
  ResolverRegistry (1), ResolverPhaseBaseline (2 — phase<3.9
  always pending), ResolverActive (7 — no-pages / pending-page /
  approved-high / threshold-fail / metadata.route-not-page_key /
  empty-key / missing-accessor), StoryGateEndToEnd (3 — pass /
  pending / pre-3.9 pending-not-unknown).

### Anchor P — apihub.record_api_test verdict-field amendment (Phase 3.5 Path B)

- **Module**: `multi_agent/runtime/apihub.py:486+` (the second
  `if _phase >= X:` block in record_api_test, sharing `_phase =
  _get_phase()` with the Phase 4.4 authorship gate above).
- **Behavior at phase >= 3.5**: derives an explicit top-level
  ``verdict`` ("pass" / "fail" / "unknown") from the writer's
  result dict in priority order: ``result.passed`` → ``result.result``
  → ``result.status_code``. Original ``result`` dict is preserved
  unchanged. Below phase 3.5 the verdict field stays "unknown" —
  the resolver treats this as evidence_pending so the story gate
  doesn't approve on ambiguous evidence.
- **Why Path B (simplified)**: Path A would widen the Phase 4.4
  authorship gate to ``{verifier, contract_test_runtime}`` and
  introduce a new phantom runtime principal. Per user 2026-05-31
  decision, Path B skips the widening and ships independently —
  the ``contract_test_runtime`` row stays parked in
  ``phantom_runtime_registry.md`` until a real runtime caller is
  introduced.
- **Resolver companion**: ``story_hub._resolve_endpoint_contract``
  registered against the ``endpoint_contract:<endpoint_id>``
  namespace in ``_DEFAULT_RESOLVERS``. Reads
  ``list_contract_test_results_sorted(endpoint_id)[0].verdict`` —
  the latest record wins (closes the original Candidate C
  ``results[-1]`` bug).
- **Tests**: `tests/test_phase_3_5_endpoint_contract.py`
  (4 classes, 22 cases): VerdictDerivation (11 cases covering all
  3 derivation rules + precedence + original-dict preservation),
  ResolverRegistry, EndpointContractResolver (7 cases including
  latest-wins + missing-accessor fallback), StoryGateEndToEnd
  (3 cases pass/fail/pending).

### Anchor O — eventhub.publish_human_message (Phase 4.7-slim Path A)

- **Module**: `multi_agent/runtime/eventhub.py:428+`
- **Behavior at phase >= 4.7**: rejects `from_user` values that are
  empty OR equal to the legacy literal `"human_user"` (case-insensitive),
  raising `PermissionError`. Real user IDs admit normally. Empty-actor
  fallthrough is NOT preserved here on purpose — the whole point of
  this gate is to surface "operator forgot to set 甲方" loudly
  instead of silently emitting messages no agent can address.
- **Trust surface**: agents reading `payload.from_user` reply by
  addressing that field. In a multi-user pipeline, sending with
  `from_user="human_user"` causes agent replies to be misrouted (all
  conversations look like they're from one user). Path A enforces a
  real id flows through.
- **HumanConsole wiring**: `HumanConsole.__init__` now accepts a
  `default_user_id` kwarg, falls back to `ENVGEN_HUMAN_USER_ID` env
  var, and finally to the legacy `"human_user"` literal (which
  triggers the gate at phase>=4.7 — operators see the misconfig).
  `HubRegistry.__init__` plumbs the kwarg as `human_user_id=...`.
  `start_conversation` and `send_message` default `from_user` to
  `self._default_user_id` (was: literal `"human_user"`).
- **Path C SHIPPED 2026-06-01** (commit-pending): session-derived
  identity for the live_monitor HTTP surface lands as a 5-LOC
  extension to `_apply_request_user` at
  `live_monitor_server.py:4680+`. When a request carries a valid
  session cookie, the session username is stamped onto
  `body["from_user"]` (mirroring the Cutover 35 `body["agent"]`
  override). The shims `start_conversation_call` /
  `send_message_call` no longer default to the `"human_user"`
  literal phantom — they pass `body.get("from_user") or None` so
  HumanConsole's Path A chain (env var) takes over when no Path C
  identity is supplied. **Precedence**: Path C (authed session) >
  body-supplied from_user > Path A (env var) > "human_user"
  literal (which the 4.7 gate then rejects). The
  session-identity-wins-over-body-supplied-value invariant
  mirrors the existing `agent`-override: an authed user cannot
  spoof a different identity via the request body.
- **Tests**: `tests/test_phase_4_7_human_console_identity.py`
  (4 classes, 14 cases — Path A coverage) +
  `tests/test_phase_4_7_path_c_session_identity.py` (4 classes,
  8 cases — Path C coverage: `_apply_request_user` writes both
  fields, shims drop the `"human_user"` phantom default, Path A
  still works when Path C absent, dispatch layer invokes
  `_apply_request_user`).

### Anchor J — apihub.record_api_test (Phase 4.4)

- **Module**: `multi_agent/runtime/apihub.py:450+`
- **Behavior at phase >= 4.4**: rejects `agent` values outside
  `{verifier}` with `PermissionError`. Empty identity falls through
  (test/system paths preserved). The method signature default is
  `agent="verifier"` so callers that omit the kwarg also satisfy
  the gate by default.
- **Wiring**: defense-in-depth on top of Path A (commit `7272a2fc`)
  bundle trim — `apihub_record_contract_test` lives in
  `_bundle_verifier_contract_tools`, granted only to the `verifier`
  profile in `agents_config.yaml`. The bundle trim closes the
  agent-reachable path; this hub-method gate catches hub-direct
  callers (tests, future internal callers).
- **Tests**: `tests/test_phase_4_4_record_api_test_role_gate.py`
  (4 classes, 10 cases) + the existing
  `tests/test_phase_4_4_contract_test_wiring.py` 3-layer regression
  guard from Path A.

### Phase 3.0 bootstrap — StoryHub class + HubRegistry attachment (Phase 0.3 prep)

NOT a phase mechanism — no `_MECHANISMS` entry, no new anchor. This is
the architectural prep that gives Anchors F + G (currently
module-level `register_story` / `evaluate_story_gate` in
`runtime/story_hub.py`) a HubRegistry handle parallel to
`registry.gate_registry` / `registry.schema_hub` / `registry.mcp_registry`.

- **Module**: `multi_agent/runtime/story_hub.py` (new `StoryHub` class
  below the existing free functions). `multi_agent/runtime/hub_registry.py`
  (new `self.story_hub = StoryHub(eventhub=self.eventhub)` between the
  SchemaHub block and HumanConsole block).
- **Behavior**: zero behavior change. `StoryHub.register_story` and
  `StoryHub.evaluate_story_gate` are pure one-line delegations to the
  module-level free functions, which remain the single source of truth.
  Anchors F + G still live in the free functions; the class methods
  contain no new `if get_phase() >= 3.0:` anchor.
- **Why a class at all pre-Phase-3**: lets Phase 3 mechanism PR add
  store-by-reference kwargs to `__init__` (following the GateRegistry
  `pages_store=workhub.stores.pages` shape) + `attach_<peer>` setters +
  `_emit` helper later WITHOUT churning the test surface — the 14
  inert tests in `test_phase_3_story_hub_inert.py` import the free
  functions and remain authoritative.
- **Peer pattern**: mirrors GateRegistry / MCPRegistry / SchemaHub
  (shares-by-reference, no `hub_dir`, no own stores, no
  `get_versions`/`snapshot`/`_emit` yet). Does NOT mirror RunHub (which
  is state-OWNING; takes `hub_dir`, builds stores, has
  `attach_<peer>` setters, participates in versions/snapshot). Picked
  the stateless peer per Reviewer-2 PATTERN_PARITY refute against the
  original Winner C — workflow `w3dr8s11l` REJECT + SHIP_WITH_REVISIONS
  collapse, 16 agents 506k tokens.
- **Tests**: `tests/test_phase_3_story_hub_inert.py` gains two new
  classes (StoryHubClassDelegation, 6 cases; HubRegistryStoryHubWiring,
  4 cases). Original 14 inert tests preserved byte-identically.
- **Source-of-truth invariant**: replacing the `pass` bodies in
  module-level `register_story` / `evaluate_story_gate` automatically
  lights up both legacy free-function callers AND
  `registry.story_hub.*` callers because class methods are pure
  delegations.

---

## Prompt-side phase blocks

Four v3 agent prompts render phase-conditional blocks driven by the
auto-injected `elaboration_phase` context var. Each uses the same
Jinja pattern: an internal macro `_phase_<role>_block(phase)` that
returns `""` at default phase and announcement text at the relevant
threshold; the block is appended to the `mandate=` field via Jinja
`~` string concat.

| Agent | Block name | Activates at | Says |
|-------|-----------|-------------:|------|
| design v3 | `_phase_ownership_block` | `>=1.0` and `>=2.0` | DB ownership moved to backend (1.0); API ownership moved to backend (2.0) — document requirements in README instead of writing specs. |
| backend v3 | `_phase_acquisition_block` | `>=1.0` and `>=2.0` | YOU now own spec.database.json + apihub_register_table; spawn database_worker via define_team_agent (1.0). YOU now own spec.api.json + check api_requirement inbox + handshake CB (2.0). |
| frontend v3 | `_phase_negotiation_block` | `>=2.0` only | API contract authoring moved to backend; publish api_requirement events for data needs; circuit breaker after 5 negotiation steps / 600s. |
| database v3 | `_phase_demotion_block` | `>=1.0` only | The legacy `database` resident lane is DEMOTED. Defer unless invoked as `database_worker` via define_team_agent spawn. NEVER use `provider='database'` (gate raises). |

All four are byte-identical to baseline at `phase=0.0` — the macros
return empty strings and the rendered prompt matches the pre-Phase-1
shipped v3 versions exactly.

**Tests**: `tests/test_phase_conditional_prompt_rendering.py` (32
tests). Per-agent block content (design / backend / database /
frontend / verifier / orchestrator) + cumulative-ownership
cross-checks + context-var injection + an
AllV3PromptsRenderAcrossPhases meta-test that renders every v3 prompt
at phases 0/1/2/2.5/3.0 and catches future syntax / baseline /
signature drift. Verifier v3 Phase 2.5 evidence-gate block added in
commit `011c19c1`. Orchestrator v3 phase-1/2/2.5 routing-constraint
blocks added in this commit (workflow `w7p5w5dzl` revised candidate
after the earlier strict REJECT identified two overreach clauses).

---

## Runtime fixes paired with the v3 stack

These are not phase-gated; they fix structural bugs surfaced by v3
prompts running on weaker models.

### `debug.py` defensive mkdir (commit `39c861d2`)

`StructuredLogger.log()` re-mkdirs the parent dir before opening the
file. Defends against the v2 `_relocate_debug_log_to` interaction
that caused 49 FileNotFoundError stalls in pilot validation #2.

### Per-agent `max_steps_per_task_ready` cap (commit `605e2305`)

`configurable_agent` reads `max_steps_per_task_ready` from YAML flags
(default 2000). `messaging.py:_handle_task_ready` uses the per-agent
value instead of hard-coded 2000. Knowledge agent's profile sets it
to 5 so a weaker LLM that ignores v3's wake_contract ("single trigger
→ single action → finish") is still hard-bounded.

---

## Commits in chronological order (this session)

```
d89d8c49 feat(prompts/v3): structured agent prompt skeleton + Knowledge Agent rewrite (event-driven)
92d98837 feat(prompts/v3): Backend Lead v3 prompt — task_ready triggered, no wait/poll
2eadf0c6 feat(prompts/v3): Frontend Lead v3 prompt — two-phase, no poll
39c861d2 fix(debug): defensive mkdir in StructuredLogger.log to survive parent-dir disappearance
911a6452 feat(prompts/v3): Design Agent v3 — spec-as-contract + count discipline + review-gate stop_rule
90a96cda feat(prompts/v3): Database Agent v3 — spec-as-contract + Cutover-21 seed audit + design-vs-dataset clarified
630f6910 feat(prompts/v3): Verifier Agent v3 — structured-check contract + Cutover-10 detect-only boundary
c71b02a2 feat(prompts/v3): Orchestrator Agent v3 — coordinator-role framing + cutover blocks preserved
a7e0bc21 feat(prompts/v3): Phase D — reviewers + workers v3 (6 agents in one batch)
605e2305 fix(runtime): per-agent max_steps_per_task_ready cap; Knowledge=5
cf4658f5 feat(refactor): Phase 1 mechanism — schema_hub.register_table role gate
bcc0b0ac feat(refactor): Phase 2 mechanism — apihub.register_endpoint role gate
9ca2885c feat(refactor): Phase 2 api_requirement EventHub channel
5edf4302 feat(refactor): Phase 2.5 mechanism — visual_similarity.compute_ssim body fill
12e355a0 feat(prompts/v3): Phase 1+2 prompt halves — phase-conditional ownership transfer
05dda799 feat(prompts/v3): Frontend v3 phase>=2.0 — api_requirement publication block
3bb50ee4 test(prompts): phase-conditional render tests for design+backend+frontend v3
d232adb7 feat(refactor): Phase 2.5 mechanism — RunHub.record_probe runtime-only gate
118732e8 feat(refactor): Phase 2.5 mechanism — probe_record body_excerpt enrichment
bf3adbc6 fix(prompts/v3): database v3 phase-conditional demotion at phase>=1.0
```

20 commits. All pushed to `red-env-gen/haibotong-0527-hub-focus-and-tooling-cleanup`.

---

## Activation experiment runway

The phase ladder defaults to `0.0` so production runs preserve v0.x
behavior. To exercise the higher phases:

1. **Phase 1 only** (`ELABORATION_REFACTOR_PHASE=1.0`):
   ```bash
   ELABORATION_REFACTOR_PHASE=1.0 python -m env_generator.llm_generator.main ...
   ```
   Expect: design no longer writes spec.database.json (writes
   requirements to README instead); backend reads README + owns
   schema; database lane defers / acts only when spawned as
   database_worker.

2. **Phase 2** (`=2.0`): everything above + design no longer writes
   spec.api.json; backend owns API + listens for api_requirement
   events; frontend publishes api_requirement events for data needs.

3. **Phase 2.5** (`=2.5`): everything above + server-side SSIM for
   visual fidelity + agent-fabricated probe records rejected + each
   probe_record carries body_excerpt evidence.

Each phase boundary is the **default-OFF + opt-in-via-env** pattern.
No pipeline change is required to flip a phase — change the env var
and re-run.

---

## Test coverage map

| Test file | Tests | Covers |
|-----------|------:|--------|
| `test_phase_0_3_inert_scaffolding.py` | 20 | Anchor install + invariants at phase=0; transition-flip guard. |
| `test_phase_1_schema_hub_role_gate.py` | 19 | Anchor A mechanism. |
| `test_phase_4_2_schema_hub_sibling_gates.py` | 14 | Anchors A.1 + A.2 mechanism; locks update_table_schema (sibling) + register_seed_data (sibling) at phase>=1.0; consumer surface stays ungated by design. |
| `test_phase_2_apihub_role_gate.py` | 18 | apihub.register_endpoint mechanism. |
| `test_phase_2_api_requirement_channel.py` | 17 | Anchor B mechanism. |
| `test_phase_2_5_visual_similarity.py` | 13 | Anchor D mechanism. |
| `test_phase_2_5_record_probe_gate.py` | 13 | Anchor C mechanism. |
| `test_phase_2_5_probe_record_evidence.py` | 7 | Anchor E mechanism. |
| `test_phase_3_story_hub_inert.py` | 22 | Anchors F + G ACTIVE scaffold residue (Phase 3 mechanism shipped at c9a81e22 lifted F + G from inert to active). Remaining 22 tests: 12 import/synthetic-shape/dispatch invariants pre-Phase-3 + 6 StoryHubClassDelegation cases + 4 HubRegistryStoryHubWiring cases. The 2 invariant tests `test_phase_3_still_inert_byte_identical` + `test_phase_3_still_passes_inert` MIGRATED to `test_phase_3_story_hub_mechanism.py` as positive mechanism assertions when the mechanism shipped. |
| `test_phase_3_story_hub_mechanism.py` | 17 | Anchors F + G mechanism (Phase 3 story-gate active at phase>=3.0). Positive analogs of the migrated invariant tests + actor-gate cases ({orchestrator/product/planner} allow + backend reject + empty-actor fallthrough + .strip().lower() normalization) + zero-stories trivially-ok + unsupported_namespace_v1 blocker semantic (uses `audio:` since visual/endpoint_contract now have shipped resolvers) + visual+endpoint_contract pending-not-unknown at pre-3.5/3.9 + class-method routing. |
| `test_phase_3_resolver_fixture_contracts.py` | 6 | Anchors F + G resolver round-trips via O2 PhaseResolverFixtureContracts (commit 0e25cd5c). 4 namespace classes (TestApiSmoke/UiFlow/Table/Mcp Resolver) each declare their own `test_resolver_returns_*` cases (6 `def test_` total in this file); the inherited `test_resolver_round_trip` from the O2 ABC adds 4 more effective tests at run time (10 total executed). Locks the schema-misread defense at test time (declared_record_fields enforces verdict field name). |
| `test_phase_3_story_hub_persistence.py` | 9 | StoryHubStores wiring (commit 763b408f). 5 HubRegistryStoryHubStoresWiring cases (stores attached / stories JsonStore / register persists / story_registered emit / multi-registration) + 4 StoryHubStoresStandalone cases (create / ensure_documents / snapshot / versions). |
| `test_phase_3_deliverability_hook.py` | 6 | Phase 3 story-gate hook in deliverability.compute_deliverability (commit-pending). 2 StoryGateHookAtPhase3 cases (zero-stories trivially ok + unresolvable target produces story[id] blocker) + 1 story-id-format case + 1 pre-Phase-3 no-op case + 2 DeliverabilityReport shape-preserved cases (to_dict keys unchanged + blockers stays List[str]). |
| `test_phase_4_0_mcp_registry_role_gate.py` | 10 | Anchor H + I mechanism; locks server+tool role-gate to {backend}; ConsumerStaysOpen class verifies consumer surface stays open by design. |
| `test_phase_4_4_record_api_test_role_gate.py` | 9 | Anchor J mechanism; locks record_api_test authorship to {verifier} at phase>=4.4; defense-in-depth on top of Path A bundle trim. |
| `test_phase_4_5_gate_registry_review_role_gate.py` | 11 | Anchors K + L mechanism; locks submit_design_review to {architect_reviewer} + submit_visual_review to {visual_reviewer} at phase>=4.5; UngatedSiblingsStayOpen class verifies register_visual_review_task + submit_design_for_review stay open by design. The mark_path_intentionally_dead test in this file was flipped to assert REJECTION when Phase 4.5d shipped — coverage lives in test_phase_4_5d_mark_path_intentionally_dead.py. |
| `test_phase_4_5d_mark_path_intentionally_dead.py` | 6 | Anchor L.1 mechanism (Phase 4.5d retire-to-gate_registry); locks mark_path_intentionally_dead to {orchestrator} at phase>=4.5. 4 MarkPathIntentionallyDeadGate cases + 2 PrePhase4_5BehaviorPreserved cases. |
| `test_phase_4_6_codehub_submit_review_role_gate.py` | 9 | Anchor M mechanism; locks PR review verdicts to pr.reviewers ∪ {orchestrator} at phase>=4.6; PR-lifecycle inline dict-return shape (NOT helper-raise — first gate in this family); DataDrivenAllowedSet class verifies the data-driven allow_set adapts per-PR. |
| `test_phase_4_7_human_console_identity.py` | 14 | Anchor O mechanism; Phase 4.7-slim Path A — locks publish_human_message to non-phantom from_user at phase>=4.7; HumanConsole captures the project's 甲方 (ENVGEN_HUMAN_USER_ID env var or human_user_id kwarg) and threads it through start_conversation/send_message. |
| `test_phase_4_7_path_c_session_identity.py` | 8 | Anchor O Path C extension; live_monitor `_apply_request_user` stamps session username onto `body["from_user"]` so per-request identity replaces the process-wide env-var bridge for the HTTP surface; shims drop the `"human_user"` literal phantom default; Path A still authoritative when no Path C identity supplied (headless/CLI fallback). |
| `test_phase_4_11_publish_side_source_hub_gate.py` | 21 | Anchor R mechanism; Phase 4.1c (PHASE_4_11) publish-side source_hub authorship gate — owner-equals + per-hub sentinel allowlist (apihub admits schema_hub/mcp_registry; workhub admits gate_registry; human_user admits live_monitor/messagebus_bridge); 7 hub _emit wrappers threaded caller=<hub_name>; 4 legacy phantom source_hubs (system/messagebus/verifier/ui) admit via empty-caller fallthrough only (migration parked per Path B); record_agent_status deliberately does NOT propagate caller=. |
| `test_phase_4_6_1_record_check_role_gate.py` | 13 | Anchor S mechanism; Phase 4.6.1 codehub.record_check authorship gate — admits {orchestrator} ∪ pr.checks_authorized ∪ pr.reviewers; open_pull_request gained checks_authorized kwarg (mirrors reviewers plumbing); PR-lifecycle inline dict-return shape; empty-actor fallthrough + orphan-PR fallthrough preserved. Extends Phase 4.6 row 1→2 entries (per wnjpij4xw audit). |
| `test_phase_3_5_endpoint_contract.py` | 22 | Anchor P mechanism + endpoint_contract resolver; Phase 3.5 simplified Path B — apihub.record_api_test derives verdict field at phase>=3.5; _resolve_endpoint_contract reads verdict via list_contract_test_results_sorted (latest wins, closes original Candidate C results[-1] bug). NO contract_test_runtime widening. |
| `test_phase_3_9_visual_route.py` | 16 | Anchor Q mechanism + visual: namespace resolver; Phase 3.9 simplified Path B — story_hub._resolve_visual reads gate_registry.list_visual_reviews keyed by metadata.route (NOT page_key, closes C1 design error); SSIM-None = evidence_pending per compute_ssim contract. NO visual_similarity_runtime widening. Pre-phase-3.9 returns evidence_pending so legacy stories with `visual:` targets go pending instead of failing with unsupported_namespace. |
| `test_phase_conditional_prompt_rendering.py` | 32 | Prompt-side phase blocks for design/backend/database/frontend/verifier/orchestrator + an AllV3PromptsRenderAcrossPhases meta-test rendering 13 v3 prompts × 5 phases as a syntax/baseline guard. |

Aggregate: 247 phase-related tests (+7 O7; +16 O1; +7 Path A wiring; +10 Phase 4.0; +9 Phase 4.4; +14 Phase 4.2; +11 Phase 4.5; +9 Phase 4.6; +11 O11 phase-aware tracer; +10 Phase 3.0-bootstrap StoryHub class + HubRegistry wiring). Full env-gen suite: 1984/0 (at all advertised phases 0 / 2.5 / 3.0 / 4.0 / 4.4 / 4.5 / 4.6 via `unittest discover tests`).

**O11 phase-aware structured tracer** shipped as pure-add infrastructure
(NOT a phase mechanism — no `_MECHANISMS` entry, no anchor). Set
`ENVGEN_ELAB_TRACE=1` to emit one JSON line per role-gate dispatch to
stderr (decision: allowed/denied/bypassed_empty_actor). Hooked inside
`_role_gate.require_allowed_actor` + `require_runtime_actor` (covers
10 gates via helper) + inline at `codehub.submit_review` (1 more,
data-driven allowed_set can't factor to helper). Test seam:
`_override_trace_for_test` / `_clear_trace_override` mirrors
`elaboration_phase._override_phase_for_test`. PermissionError text
byte-identical with tracer ON vs OFF (operator/pilot grep contract
preserved).

---

## Mechanism Inventory (autogenerated)

This table is **generated from** the `_MECHANISMS` tuple in
[`runtime/elaboration_phase.py`](../agent/env_generator/llm_generator/multi_agent/runtime/elaboration_phase.py).
Do not hand-edit between the markers — `tests/test_activation_log_autogen_in_sync.py`
asserts the generated content matches verbatim. If you add a new entry
to `_MECHANISMS`, run that test once; it surfaces the new expected
table content in its failure message and you paste it back here.

<!-- AUTOGEN_MECHANISMS_BEGIN -->
| Threshold | Mechanism | Description |
|----------:|-----------|-------------|
| 1.0 | `schema_hub.register_table` | schema_hub.register_table — table writes locked to {backend, database_worker} |
| 1.0 | `schema_hub.update_table_schema` | schema_hub.update_table_schema — table schema mutations locked to {backend, database_worker} (sibling of register_table; gates the breaking-change recorder) |
| 1.0 | `schema_hub.register_seed_data` | schema_hub.register_seed_data — seed-data writes locked to {backend, database_worker, database} (admits the database resident lane that the seed_tools bundle is granted to) |
| 2.0 | `apihub.register_endpoint` | apihub.register_endpoint — endpoint writes locked to {backend} |
| 2.0 | `EventHub.publish_api_requirement` | EventHub.publish_api_requirement — frontend→backend handshake channel active |
| 2.5 | `visual_similarity.compute_ssim` | visual_similarity.compute_ssim — server-side SSIM comparison (Wang et al. 2004) |
| 2.5 | `RunHub.record_probe` | RunHub.record_probe — runtime-only gate; only 'runhub' may author probe records |
| 2.5 | `RunHub.start_run probe_record enrichment` | RunHub.start_run probe loop — each probe_record gains body_excerpt field (256B cap) |
| 3.0 | `story_hub.register_story` | story_hub.register_story — Phase 3 story-gate authorship lock: allowed_set={orchestrator,product,planner} via _role_gate.require_allowed_actor. Persists canonical record + emits story_registered event when stores wired. |
| 3.0 | `story_hub.evaluate_story_gate` | story_hub.evaluate_story_gate — Phase 3 story-gate evaluator. Walks evidence_targets, dispatches by namespace prefix (api_smoke / ui_flow / table / mcp / endpoint_contract) to resolvers that read canonical writer outputs; aggregates ok=True iff every story status==delivered. visual namespace deferred to Phase 3.9. |
| 3.5 | `apihub.record_api_test verdict-field amendment + endpoint_contract resolver` | Phase 3.5 (Path B simplified): apihub.record_api_test writes an explicit top-level 'verdict' field ('pass'/'fail'/'unknown') derived from result.passed / result.result / result.status_code (precedence in that order). story_hub gains _resolve_endpoint_contract for the 'endpoint_contract:<endpoint_id>' namespace — reads list_contract_test_results_sorted()[0].verdict for an unambiguous lookup. NO contract_test_runtime widening — Phase 4.4 stays {verifier}-only. |
| 3.9 | `story_hub._resolve_visual + gate_registry.list_visual_reviews` | Phase 3.9 (Path B simplified): story_hub gains _resolve_visual for the 'visual:<route>' namespace, keyed by metadata.route (NOT page_key — closes the original C1 design error). Reads gate_registry.list_visual_reviews(route=...) for approved/rejected pages; SSIM-None = evidence_pending per the compute_ssim contract. NO visual_similarity_runtime widening — Phase 4.5 stays {visual_reviewer}-only. |
| 4.0 | `mcp_registry.register_mcp_server` | mcp_registry.register_mcp_server — MCP server registration locked to {backend} |
| 4.0 | `mcp_registry.register_mcp_tool` | mcp_registry.register_mcp_tool — MCP tool registration locked to {backend}; consumer rows remain open per wrapper hedge |
| 4.1 | `EventHub identity gate` | EventHub.subscribe / unsubscribe / unsubscribe_all / mark_read / mark_delivered / mark_all_read — cross-agent mutation prevention; caller-equals-agent ownership check (caller=None / empty-actor falls through per the convention all 14 shipped gates use). Built on O14 chunk-1 caller-kwarg infra (commit b39305ac) |
| 4.11 | `EventHub publish-side source_hub gate` | EventHub.publish_event / publish_agent_reply / publish_human_message / publish_api_requirement / record_agent_status — source_hub authorship gate (per user 2026-06-01 source_hub-semantic choice). Owner-equals (caller == source_hub) OR per-hub sentinel allowlist (apihub admits schema_hub/mcp_registry; workhub admits gate_registry; human_user admits live_monitor/messagebus_bridge). Legacy phantom source_hubs (system/messagebus/verifier/ui) admitted via empty-caller fallthrough — Step A spin-off; migration is follow-up cleanup PR. Sibling to Phase 4.1 (subscription-side); shipped at 4.11 so publish-side is independently flippable. |
| 4.4 | `apihub.record_api_test` | apihub.record_api_test — contract-test authorship locked to {verifier} (defense-in-depth behind Path A bundle trim) |
| 4.5 | `gate_registry.submit_design_review` | gate_registry.submit_design_review — design review verdict authorship locked to {architect_reviewer} |
| 4.5 | `gate_registry.submit_visual_review` | gate_registry.submit_visual_review — visual review verdict authorship locked to {visual_reviewer}; register_visual_review_task stays open by design (mark_path_intentionally_dead lifted to its own gate at Phase 4.5d) |
| 4.5 | `gate_registry.mark_path_intentionally_dead` | gate_registry.mark_path_intentionally_dead — Phase 4.5d (Path A retire-to-gate_registry): coverage-allowlist verdict authorship locked to {orchestrator}. Replaces the Phase 4.5a/b/c WorkHub retire bundle (architectural finding: WorkHub is producer-side; the actual verdict surface is here on gate_registry) |
| 4.6 | `codehub.submit_review` | codehub.submit_review — PR review verdict authorship locked to pr.reviewers ∪ {orchestrator}; open_pull_request/request_review stay open pending callsite cleanup (ui_user defaults). record_check NOW gated at Phase 4.6.1 (sibling slot extending the 4.6 row) |
| 4.6 | `codehub.record_check` | codehub.record_check — Phase 4.6.1: PR-check authorship locked to {orchestrator} ∪ pr.checks_authorized ∪ pr.reviewers. open_pull_request gained checks_authorized kwarg mirroring the reviewers plumbing pattern. Empty-actor fallthrough (un-threaded callsites: hub_registry.py:280/428, step_pipeline/helpers.py:189, live_monitor_server.py:4035). PR-lifecycle family inline dict-return shape (NOT raise). Sibling to Phase 4.6 submit_review; extends 4.6 row from 1→2 entries (per the wnjpij4xw audit recommendation — single-decimal float thresholds preserved; record_check is a near-identical instance of the PR-LIFECYCLE-ALLOWLIST idiom applied to a sibling method in the same family). |
| 4.7 | `eventhub.publish_human_message` | eventhub.publish_human_message — Phase 4.7-slim Path A: from_user must be non-phantom (no legacy 'human_user' placeholder) AND the project must know its 甲方 (the actual human user id, captured at HubRegistry init via ENVGEN_HUMAN_USER_ID env var). Long-term Path C is session-derived identity from live_monitor cookie/auth. |
<!-- AUTOGEN_MECHANISMS_END -->

Source of truth: `_MECHANISMS` tuple at `agent/env_generator/llm_generator/multi_agent/runtime/elaboration_phase.py`.
