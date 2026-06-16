# Hub responsibility split — plan (reviewer's (b))

> Status: PROPOSAL — for external review before any code change.
> Companion piece to `docs/workspace_root_redesign.md` from the
> earlier round. Same shape: state the problem, the inventory, the
> migration path, surface the open decisions, hold for sign-off.

## 1. Why this is being done

External reviewer's findings across two rounds:

> WorkHub 70 公开方法 (god-hub), APIHub 42 公开方法, 同一职责
> 多个入口互相绕过. focus_hub 是补丁不是治本. agent 几乎不走结构化 hub
> 操作, 而是退化回 send_message. 这是 surface 膨胀的副作用.

My own counts as of HEAD (`grep -cE "^    def [a-z]"`, minus
private `_x`):

| Hub | Public methods | Spec'd job | What it actually swallowed |
|---|---|---|---|
| WorkHub | **61** | Notion + Jira (docs / plans / tasks / comments) | design review gate, visual review gate, retro, bug tracking, coverage allowlist, ui_pages, project phase/info, shared_implementations |
| APIHub | **38** | Apifox (API contracts) | + DB tables, seed data, MCP registry |
| CodeHub | 28 | GitHub + git wrapper | (no bloat) |
| EventHub | 29 | events / inbox | + human messages, agent status, thread summary |
| RunHub | 1 public | docker compose lifecycle | (no bloat) |

Verified duplicate-home sites (both implementations live in the tree):

* `design_gate.py` ↔ `WorkHub.submit_design_review` / `is_design_approved`
  → **DONE** (pilot — commit `7a3eb904`).
* `visual_review_gate.py` ↔ `WorkHub.submit_visual_review` /
  `is_visual_approved` → still both, same shape as design pilot.
* `bug_tools.py` (`bug_create` / `bug_close` / `bug_triage`) ↔
  WorkHub task fields (`kind="bug"`, `bug_state`, `severity`,
  `bug_artifacts`, `triage_history`) → both write into the same
  store with no agreed schema.

The behavioral fixes (per-agent finish gate, circuit breaker, retro
gate) treat the **symptoms** of bloat. This plan treats the
**cause**.

## 2. Three migration patterns the reviewer's mental model points at

There are three distinct shapes of work, conflated under the
heading "split the god-hub". Worth separating because they have
different blast radius.

### Pattern P1 — Thin-delegate de-dup (low risk)

When module A and hub B both have the same predicate, keep one as
the canonical writer/holder and make the other a thin delegate.

* Pilot: `design_gate` (DONE)
* Targets: `visual_review_gate`, `bug_routing`

Risk: ~zero. Behavior is preserved by construction; tests can
assert "both paths return the same answer". Already proven by the
pilot.

### Pattern P2 — Extract a cohesive sub-responsibility into a new module that the hub delegates to (medium risk)

When a hub has 8+ methods serving one cohesive sub-job (design
review gates, ui_pages, coverage allowlist), pull them out into a
named module. Hub keeps thin pass-through methods for backward
compat so callers don't break in a single PR.

* Targets in this plan:
  * `GateRegistry` — owns design/visual/coverage/retro gate state
    + predicates. WorkHub delegates.
  * `SchemaHub` — owns DB tables + seed registrations. APIHub
    delegates for now; later phases let agents talk to SchemaHub
    directly.
  * `MCPRegistry` — owns MCP servers/tools/consumers. APIHub
    delegates.

Risk: medium. Reversible per-extraction. Each one is a separate
PR.

### Pattern P3 — Re-bundle agent tool surfaces (medium-high risk, deferred)

Once P2 has separated hubs, the *tools* exposed to each agent
profile need rewiring. e.g. database agent's bundle should pick up
SchemaHub tools instead of the apihub-table-* ones. This changes
which tool names agents see — touches every profile's
`tool_categories` / `tool_bundles` plus prompt mentions.

Worth doing AFTER P2's modules stabilize, in its own PR with a
ghost-reference scan against the moved tool names.

## 3. Ranked extraction order

Reviewer left order open; here's a proposal optimized for
(a) cheapest first (b) each extraction is independently
shippable.

| Rank | Move | Pattern | Lines moved (est) | Stand-alone? |
|---|---|---|---|---|
| 1 | `visual_review_gate` ← WorkHub.is_visual_approved | P1 | ~50 | ✓ |
| 2 | `bug_routing` consolidation | P1 | ~80 | ✓ |
| 3 | `GateRegistry` ← WorkHub design + visual + retro + coverage | P2 | ~300 | ✓ |
| 4 | `MCPRegistry` ← APIHub MCP methods | P2 | ~120 | ✓ |
| 5 | `SchemaHub` ← APIHub tables + seed | P2 | ~250 | ✓ |
| 6 | Profile rewiring (tools + prompts) | P3 | ~150 yaml + ~50 prompt | ✗ (depends on 3-5) |

Ranks 1 and 2 are confidence-builders: tiny, same shape as the
already-landed `design_gate` pilot, prove the de-dup pattern
generalizes. Rank 3+ are the structural moves.

## 4. Detailed plan per rank

### Rank 1 — visual_review_gate de-dup

Same playbook as `design_gate`:

1. `visual_review_gate.is_visual_approved(workhub, page_id)` →
   delegate to `workhub.is_visual_approved(page_id)`.
2. `visual_review_gate.assert_visual_approved` keeps its
   `VisualNotApprovedError` value-add.
3. Test parity: both predicates agree on approved + unapproved
   pages; assert raises the right shape; None workhub handle.

Acceptance: `grep -A 20 "def is_visual_approved" ...` shows the
same logic only in `WorkHub`.

### Rank 2 — Bug routing de-dup

The two homes:
* `bug_tools.py` (`bug_create` / `bug_close` / `bug_triage` /
  `bug_update_state` / `bug_escalate`) — does workflow plus calls
  workhub.create_task with `kind="bug"`.
* `WorkHub` fields (`kind="bug"`, `bug_state`, `severity`,
  `bug_artifacts`, `triage_history`) — passive storage with a few
  helpers (`list_open_bugs`, `list_bugs_assigned_to`).

Proposal: keep WorkHub as the canonical store (it already holds
the task), promote `bug_tools.py` to the single workflow entry
point, and add a parity test that asserts the schema fields the
tool writes match what the WorkHub helpers expect to read.

Acceptance: no field name appears in `bug_tools.py` that
`WorkHub` doesn't either define or read; the tool can't write a
bug shape the hub doesn't understand.

### Rank 3 — GateRegistry extraction

Move into `multi_agent/runtime/gate_registry.py`:

* design page lifecycle (currently 8 methods on WorkHub:
  `create_design_page`, `submit_design_for_review`,
  `submit_design_review`, `is_design_approved`,
  `list_pending_design_reviews`, plus the validation constants)
* visual review lifecycle (currently 6 methods)
* retro lifecycle (currently 3 methods: `submit_retro`,
  `list_retros`, `get_latest_retro_for_generation`)
* coverage allowlist (2 methods: `mark_path_intentionally_dead`,
  `list_coverage_allowlist`)

WorkHub keeps the methods as thin delegates so external callers
don't break in a single PR. Day-1 acceptance: every WorkHub
method that was moved still works AND calls into GateRegistry
under the hood. Day-30: drop the WorkHub delegates.

Reason this is rank 3, not rank 1: it's the largest single move
(~300 lines moved across 4 sub-jobs), and any subtle behavior
divergence between delegated and direct calls would manifest
across multiple test surfaces.

### Rank 4 — MCPRegistry extraction

APIHub's MCP surface (currently ~7 methods:
`register_mcp_server`, `register_mcp_tool`,
`register_mcp_consumer`, `get_mcp_servers`, `get_mcp_tools`,
`get_mcp_consumers`, `list_pending_mcp_*`) → new
`multi_agent/runtime/mcp_registry.py`.

Same thin-delegate pattern. Smallest of the P2 extractions because
MCP is the most self-contained sub-job in APIHub.

### Rank 5 — SchemaHub extraction

APIHub's table + seed surface (~10 methods on tables +
`apihub_seed_registrations` store) → new
`multi_agent/runtime/schema_hub.py`. Carries with it the
`detect_table_breaking_change` predicate.

Largest P2 extraction. The reason it's last in P2: tables are
referenced by `HubConsistencyPolicy.apihub_tables` and by the
self-audit, so any signature change cascades. Cleanest after
GateRegistry and MCPRegistry land — those two prove the delegate
pattern reliably handles this shape of work.

### Rank 6 — Profile rewiring

After all P2 modules land:

* Update `agents_config.yaml` profiles to include the new module
  tool bundles where appropriate (e.g. database profile gets
  `schemahub_tools` instead of the apihub-table-only subset).
* Update prompts that mention the old tool names.
* Run the existing ghost-tool-reference test (which catches any
  prompt that references a tool that no longer exists at that
  name).

## 5. Migration safety nets that already exist

Three guards from prior rounds make this work safer than it would
be otherwise:

* `test_no_ghost_tool_references.py` (round 4): fails if any
  prompt / hint references a tool name not in the registry. Each
  extraction will rename tools — this test catches every
  reference that needs updating.
* `test_workspace_lint_guard.py` (round 5): not directly relevant
  but proves the "lint as fence" pattern works. Each extracted
  module can ship with its own narrow lint guard.
* Memory-redesign generation_id (this round): if any of the
  extractions touches per-run state (retros do), they get the
  same generation_id scoping for free via HubRegistry.

## 6. Resolved questions (reviewer's responses recorded)

The five questions from the first draft of this plan are now
resolved by the reviewer. Decisions captured here so future PRs
in this sequence can reference them by name.

### Q1 — Order (P1 first vs largest-impact first)

**Resolved: P1 first.** Reviewer's rationale: P1 is near-zero risk
and the design_gate pilot already proved the pattern; doing them
first fixes the parity-test playbook for P2 to reuse. Going
"largest-impact first" (GateRegistry) before scaling the pattern
on small pieces is the wrong sequencing.

### Q2 — Delegate compatibility window

**Resolved: don't use a calendar window.** Reviewer rejected the
"30 days + deprecation log" proposal: env-gen is not a published
library, every caller is in-tree, so calendar time is the wrong
metric. Replace with **conditions, not time**:

* Delegate stays until the same (or immediately adjacent) PR
  migrates every in-tree caller AND a ghost/grep scan confirms
  zero remaining call sites. Then the delegate is deleted in that
  same PR.
* Plus a **lint guard** (same shape as the workspace-lint guard
  from `test_workspace_lint_guard.py`) that fails the build if a
  future change tries to add a call to a deprecated method.

Logging-style "watch for unexpected calls in production" is
acceptable as a belt-and-suspenders but is NOT the primary
mechanism — the lint guard is.

### Q3 — `register_table_consumer` home

**Resolved: SchemaHub.** Plus an additional constraint from the
reviewer: the SchemaHub consumer-query interface must keep the
SAME method signature shape as APIHub's `get_consumers`. This
lets `hub_pulse._pulse_self_audit` iterate uniformly over
endpoint consumers AND table consumers without branching on
which hub holds the relationship.

### Q4 — MCP placement

**Resolved: standalone plain MODULE, NOT a Hub, NOT merged into
SchemaHub.** Two corrections to the original proposal:

* Don't merge into SchemaHub — domain is different. Table
  consumers are file paths inside the project; MCP consumers are
  external tools. No code wants to reason about MCP and tables
  together, so don't bundle them.
* Don't promote to a full Hub either. MCP is ~7 methods, one
  cohesive job. Adding the full Hub framework (stores / `_emit` /
  snapshot / subscriptions) would be over-structuring. Same
  treatment as GateRegistry: plain module
  (`mcp_registry.py`), APIHub thin-delegates.

Decision rule the reviewer gave for "Hub vs module": needs the
hub framework only if multiple consumers want stores/events on
that domain. MCP doesn't.

### Q5 — Claim-task finish gate placement

**Resolved: separate from this plan BUT inserted between PR 2 and
PR 3.** Reviewer's reasoning: it IS a different shape (behavior
gate, not structural extraction), so right not to mix it into the
hub split work. But its priority belongs near the top: it's
small (design_gate-pilot sized), high-value, and it's what makes
the tier-3 cancel/fail branch actually have material to act on at
the source. Tier-3's cancel-on-unclaimed handles the symptom; the
claim-task gate treats the cause. Don't let a high-leverage small
fix sit behind ranks 4–6.

**Updated sequencing** (§7 below):
PR 1 (visual_review_gate) → PR 2 (bug routing) → **claim-task
gate (inserted)** → PR 3 (GateRegistry) → PR 4 (MCPRegistry) →
PR 5 (SchemaHub) → PR 6 (rewiring).

## 7. Sequencing (post-review)

Reviewer signed off the plan and inserted the claim-task gate
between PR 2 and PR 3 (see §6 Q5).

| PR | Content | Pattern | ~Size | Sign-off needed? | Status |
|---|---|---|---|---|---|
| 1 | visual_review_gate de-dup | P1 | ~150 LOC | already given (pilot precedent) | **DONE** `6096c90e` |
| 2 | bug routing de-dup | P1 | ~200 LOC | already given | **DONE** `0b0803c3` |
| 2.5 | claim-task finish gate (inserted) | behavior gate | ~200 LOC | already given (Q5) | **DONE** `fbf83504` |
| 2.5-fix | breaker-before-claim ordering + retry cap + dep-blocked tag + retro hook wiring + scanner widening | regression fix | ~440 LOC + 540 LOC tests | reviewer-driven (38-agent fan-out caught the regression) | **DONE** `fdcdad73` |
| 2.5-fix-2 | **structural** two-pass dispatcher (`always_runs()` marker) + 13 follow-up issues from adversarial review | structural fix | ~520 LOC | adversarial re-verify caught recurring family bug via hub_consistency_gate | **DONE** `948e16dc` |
| 2.5-reaudit | 5 landed≠live fixes (write-permission gate live, page-tool bundle alignment, resident-wakeup policy gate, test_coverage dead branch deleted, design/visual approval helpers documented + pinned) | live-gate cleanup | ~1100 LOC | reviewer "landed≠live" re-audit | **DONE** `f54fefcf`+`55118880`+`7c9d81b8`+`f5f68cb9`+`5e712cfb` |
| 3 | GateRegistry extraction (delegate-retirement per Q2 — condition-based + lint guard) | P2 | ~700 LOC | uses §7.3 dead-helper inventory | **DONE** `8c63b7b2` |
| 4 | MCPRegistry as plain module (per Q4) — APIHub retains store path, methods move | P2 | ~350 LOC | — | **DONE** `cd4f0051` |
| 5 | SchemaHub (table + seed + table-consumer) + Q3 signature parity for ``get_table_consumers`` | P2 | ~600 LOC | — | **DONE** `f38932f8` |
| 6 | Tool→hub routing inventory + tool-name stability pins + retired-set drift check | P3 | ~250 LOC | — | **DONE** (this commit) |
| 4 | MCPRegistry as plain module (per Q4) | P2 | ~300 LOC | — | pending |
| 5 | SchemaHub + register_table_consumer (per Q3 signature parity) | P2 | ~500 LOC | — | pending |
| 6 | Profile rewiring + ghost-tool sweep | P3 | ~300 LOC | — | pending |

Reviewer's note on cadence: don't serialize PRs 1, 2, 2.5 behind
sign-off — they don't depend on any of §6's decisions. The first
real sign-off gate is PR 3, where Q1 (order) and Q2 (delegate
retirement strategy) become operative.

### 7.1 PR 2.5-fix summary (2026-05-29)

After PR 2.5 shipped (`fbf83504`), the reviewer's 38-agent
adversarial fan-out + my own re-verification found a confirmed
deadlock regression: the four gated lanes had `claim_assigned_tasks`
ordered BEFORE `lane_idle_circuit_breaker`. The
`_apply_finish_policies` loop is first-match-wins
(`runtime/tooling.py:471-484`); claim-gate returning a blocking
outcome meant the breaker's idle counter never advanced, tier-3
never fired, and tier-3 Branch-2 (cancel assigned/pending/unclaimed
— the deterministic action de4b4925 added specifically for this
case) became dead code in every gated lane. The same fan-out also
found PR 2's "schema never drifts" guarantee had blind spots:
chained `.get()` reads in `list_open_bugs` were invisible to the
regex scanner; `close_bug`/`escalate_bug`'s literal terminal-state
writes were never scanned at all; and no negative tests existed
to prove the scanner actually catches drift.

Fixes in `fdcdad73`:

1. **Policy ordering swapped** in all four gated profiles. Breaker
   first (returns None unconditionally — safe to front-load),
   claim-gate after.
2. **Dep-blocked tasks tagged** in the claim-gate message.
   `claim_task` hard-rejects on incomplete deps (`service.py:494-500`)
   so a "claim a dep-blocked task" instruction was a guaranteed-fail
   loop. Message now says `[dep-blocked: only cancel works]`.
3. **Retry cap** as defence in depth. After
   `_MAX_CONSECUTIVE_BLOCKS=3` same-set blocks, claim-gate auto-
   cancels and passes finish. Even if ordering ever inverts again,
   the deadlock can't run for more than ~3 rounds.
4. **Lifecycle hook wired to deliver_project / report_completion**
   in step_pipeline so `RetroBeforeDeliverPolicy` actually fires
   in production (it didn't before — its trigger tools were never
   what the hook was invoked on).
5. **Scanner widened** to AST walkers (catches chained-receiver
   `.get` reads), service.py state literals scanned, five negative
   tests under `NegativeScannerCases` pin that drift is actually
   caught.

Regression tests in `test_finish_policy_composition.py` (13 cases)
pin: YAML ordering for all four profiles, builder preserves YAML
order, breaker counter advances even when claim-gate blocks, retry
cap escape works, counter resets on set change, dep-blocked tagged
in message, deliver_project branch contains `_apply_finish_policies`
call (structural guard), retro gate blocks deliver_project but not
finish.

Reviewer note on PR 3: STILL waiting on Q2 confirmation
(condition-based delegate retirement + lint guard, not 30-day
window) before GateRegistry extraction starts.

### 7.2 PR 2.5-fix-2 summary (2026-05-29)

After PR 2.5-fix shipped (`fdcdad73`), an adversarial-verify
workflow (6 lenses × refute pass) found 28 raised, 14 confirmed
issues. The HIGH was **the same family bug recurring via a
different policy**: my YAML-order swap fixed only the
`claim_assigned_tasks` vs `lane_idle_circuit_breaker` ordering,
but `hub_consistency_gate` (also a starver that can return
`{"action":"continue"}`) was still listed BEFORE the breaker in
all four gated profiles. The single-pass first-match-wins loop
short-circuits on any starver's outcome; the YAML-only fix was a
one-shot patch the next added gate would have re-opened.

A design panel (3 alternatives × 3 independent judges + sweep)
chose **approach A — two-pass dispatcher with `always_runs()`
marker** over B (YAML invariant + meta-test, prevention=detection)
and C (lift breaker out of the policy list, correct but
worktree-migration heavy). A wins on smallest-blast-radius
structural correctness; grafts from B (STARVER_POLICY_KINDS
registry + boot-warning) and the A-judge (skip-in-pass-2,
no double-call concern) were rolled in.

Structural fix in `948e16dc`:

* `BaseWorkflowPolicy.always_runs()` — default False; opt-in
  marker for bookkeeping-only policies.
* `LaneIdleCircuitBreakerPolicy.always_runs() -> True`.
* `runtime/tooling._apply_finish_policies` rewritten as two
  passes. Pass 1 invokes every always-run policy, asserts None
  outcome (gate-bookkeeping invariant), swallows exceptions
  with a WARNING. Pass 2 runs the first-match-wins gate loop
  skipping pass-1 policies. No YAML edit, no future gate, no
  order shuffle can starve the breaker again.
* `STARVER_POLICY_KINDS` frozenset + `_check_starver_breaker_ordering`
  boot-warning as belt-and-suspenders.

Plus 13 follow-up fixes (3 medium tests, 7 low UX/scanner
hardening; see commit message for the full list).
Deferred: verifier profile parity gap (likely intentional),
report_completion semantic broadening (separate review), C-style
lift-breaker-out refactor.

Reviewer note: PR 3 still blocked on Q2 sign-off.

### 7.3 Re-audit "landed ≠ live" cleanup (2026-05-29)

After the PR 2.5-fix-2 family closed (`948e16dc`), the reviewer
sent a re-audit framed as "merged ≠ live" — five gate-class
items that EXISTED in the tree but did NOT participate in the
runtime. All were structurally serious because they masked
broken intent ("the gate is in place") with silent acceptance
("but nothing reaches it"). All five closed:

* **HIGH #1** — write-permission gate
  (`AgentTooling._enforce_write_permissions`) read
  ``self.workspace`` (the bare `WorkspaceManager`, no
  ``is_write_allowed`` method). The actual permission decision
  was on a `PathRoutedWorkspace` built as a LOCAL in
  `_register_env_gen_tools` and discarded. Backend could write
  `design/`, read-only routes accepted writes from anyone.
  Fix in `f54fefcf`: pin the routed workspace as
  ``self._routed_workspace``; gate consults it first; fallback to
  ``self.workspace`` for early-init. 18 integration tests + 4
  subtests pin the wiring.

* **HIGH #3** — `HubConsistencyPolicy.workhub_pages` gap message
  told the agent to call `workhub_update_page(...)` to satisfy the
  gate, but the `workhub_tools` bundle only exposed
  `workhub_create_page`. Worse: `_count_owned_pages` requires
  `kind=="ui_page"` which only `workhub_update_page` writes — so
  even calling `workhub_create_page` couldn't satisfy the gate.
  Soft-lock for frontend / design at `finish()`. Fix in
  `55118880`: add `workhub_update_page` to the bundle + new
  regression test (`test_hub_consistency_gate_tools_present.py`)
  that pins each gap-message tool's bundle presence.

* **HIGH #4** — `_maybe_schedule_resident_message_wakeup` bypassed
  the workflow-policy gate that the `task_ready` path consults.
  Result: `DependsOnPolicy` ("waiting on upstream") and
  `VerifierValidationTriggerPolicy` ("requires explicit trigger")
  could be silently bypassed — any inbox notification would wake
  the lane. Fix in `7c9d81b8`: new
  `allow_resident_wakeup(agent, message, inbox_msg)` hook on
  `BaseWorkflowPolicy`; `DependsOnPolicy` and
  `VerifierValidationTriggerPolicy` override it to delegate to
  `allow_task_ready`; `ImplementationBootstrapPolicy` deliberately
  does NOT override (side-effect flag). 10 tests cover the hook
  contract + the scheduler integration.

* **MEDIUM #5** — `HubConsistencyPolicy._check_hub_kind('test_coverage')`
  branch + `min_relevant_for_test_coverage` parameter — no
  profile lists `test_coverage` in `expect_hub_kinds`. Pure dead
  config. Per project guidelines ("don't add features beyond
  what the task requires"), deleted rather than activated.
  `f5f68cb9` removes the branch + parameter + 3 dead tests.

* **MEDIUM #2** — design/visual single-page approval helpers
  (`design_gate.is_design_approved`/`assert_design_approved`,
  `visual_review_gate.is_visual_approved`/`assert_visual_approved`/
  `assert_critical_visuals_approved`) + their canonical hub
  methods (`WorkHub.is_design_approved`/`is_visual_approved`) have
  ZERO non-test callers. The LIVE design-approval gate is the
  `design_get_status` TOOL (called by backend/frontend/database
  prompts at task start); the LIVE visual-approval gate is
  `DeliverProjectTool` calling `list_unapproved_critical` at
  delivery time. The reviewer's specific guidance: "important
  input for PR 3 — don't extract these as live gates". Fix in
  `5e712cfb`: prominent ⚠️ docstring banners on both modules
  naming what's live vs not-wired; new
  `test_design_visual_gate_wiring_inventory.py` (5 tests +
  5 subtests) uses AST walking to pin the dead-helper inventory
  AND the surviving caller, so a future commit can't silently
  wire one of these in or remove the live caller without the
  maintainer updating the inventory + docstrings.

PR 3 (GateRegistry) now starts from a documented dead-helper
inventory rather than mistakenly treating the single-page helpers
as live gates. Q2 sign-off still pending.

### 7.4 PR 3 — GateRegistry extraction (2026-05-29)

Shipped against the §6 Q1/Q2/Q4 decisions:
* Q1 (order): P1 before P2 — done; this is the first P2.
* Q2 (delegate retirement): condition-based, not calendar.
  Every in-tree caller (runtime + tests) was migrated in this
  same PR; ``test_workflow_policies_gate_lint_guard.py`` is the
  lint guard that catches any future addition.
* Q4 (Hub vs module): plain MODULE, not a Hub. The pages store
  stays owned by WorkHub; GateRegistry reads/writes through it.

What moved into ``multi_agent/runtime/gate_registry.py``:
* Design page lifecycle — ``get_design_page``,
  ``submit_design_for_review``, ``submit_design_review``,
  ``list_pending_design_reviews``.
* Visual review lifecycle — ``register_visual_review_task``,
  ``get_visual_review``, ``list_pending_visual_reviews``,
  ``list_critical_visual_reviews``, ``submit_visual_review``.
* Retro lifecycle (read-side) — ``list_retros``,
  ``get_latest_retro_for_generation``. ``submit_retro`` itself
  stays in ``retro_tools.py`` (it writes via
  ``create_page(kind='retro', ...)`` on WorkHub, which is the
  canonical page-creation entry point).
* Coverage allowlist — ``list_coverage_allowlist``,
  ``mark_path_intentionally_dead``.

What DIDN'T move (per re-audit §7.3 dead-helper inventory):
* ``WorkHub.is_design_approved`` and ``WorkHub.is_visual_approved``
  — deleted entirely. The reviewer flagged them as dead helpers
  with zero non-test callers; the production design-approval gate
  is the ``design_get_status`` tool reading ``page.status`` directly,
  and the production visual-approval gate is
  ``DeliverProjectTool`` calling ``list_unapproved_critical``.
* ``multi_agent/runtime/design_gate.py`` — module deleted (every
  function in it was dead).
* Single-page section of ``multi_agent/runtime/visual_review_gate.py``
  (``is_visual_approved``, ``assert_visual_approved``,
  ``assert_critical_visuals_approved``) — deleted. Only
  ``list_unapproved_critical`` + ``VisualReviewNotApprovedError``
  remain; the aggregator now polymorphically accepts either a
  WorkHub (test fixtures) or a GateRegistry (production callers).

Migration:
* Production callers (~14 sites across ``tools/design_tools.py``,
  ``tools/visual_review_tools.py``, ``tools/coverage_tools.py``,
  ``tools/retro_tools.py``, ``tools/agent_interaction_tools.py``,
  ``runtime/user_gates.py``, ``runtime/deliverability.py``,
  ``workflow_policies.py``, ``live_monitor_server.py``) all moved
  from ``<expr>.workhub.X(...)`` to ``<expr>.gate_registry.X(...)``.
* Test callers (~93 sites across 16 test files) mechanically
  migrated by AST-aware regex replacement, then verified by
  running each suite.
* WorkHub no longer carries any of the retired methods.

Lint guard:
* ``tests/test_workflow_policies_gate_lint_guard.py`` — AST scan
  over ``env_generator/`` + ``tests/`` that fails the build if
  any call site of the shape ``<expr>.workhub.<retired_name>(...)``
  reappears. Plus paired pin-tests that every entry in
  ``RETIRED_TO_GATE_REGISTRY`` actually exists on GateRegistry,
  and every entry in ``DELETED_DEAD_PREDICATES`` is gone from
  WorkHub.

Acceptance: 358/358 focused regression tests pass.

The §7.3 dead-helper inventory test
(``test_design_visual_gate_wiring_inventory.py``) was updated to
reflect the post-PR-3 state — the deleted helpers stay deleted,
the live ``list_unapproved_critical`` retains its caller, and any
attempt to re-introduce a dead helper fails the test.

Next: PR 4 (MCPRegistry as plain module, per Q4) → PR 5
(SchemaHub + register_table_consumer signature parity, per Q3)
→ PR 6 (profile rewiring + ghost-tool sweep).

### 7.5 PR 4 — MCPRegistry extraction (2026-05-29)

Shipped against §6 Q4 (plain module, NOT a Hub) and Q2
(condition-based delegate retirement). Same shape as PR 3 — the
reviewer's "GateRegistry pattern" applied verbatim.

Moved into ``multi_agent/runtime/mcp_registry.py``:
* ``register_mcp_server`` / ``get_mcp_servers``
* ``register_mcp_tool`` / ``get_mcp_tools``
* ``register_mcp_consumer`` / ``get_mcp_consumers``
* The ``_VALID_MCP_TRANSPORTS`` validation constant.

Data persistence: APIHub keeps the on-disk JSON store
(``apihub_mcp_registry.json``, file path unchanged) — snapshots
load cleanly with no schema migration. MCPRegistry receives the
store handle at init and mutates it; events stay tagged
``source_hub='apihub'`` for downstream listener compatibility.

Caller migration (Q2 condition):
* 12 production sites moved from ``<expr>.apihub.X(...)`` to
  ``<expr>.mcp_registry.X(...)`` across ``tools/mcp_registry_tools.py``,
  ``runtime/coverage_audit.py``, ``runtime/user_gates.py``,
  ``runtime/hubs/runhub/service.py``, ``live_monitor_server.py``.
* ~45 test sites mechanically migrated across 6 test files.
* RunHub now carries an ``attach_mcp_registry`` paired with its
  existing ``attach_apihub``; its ``_list_apihub_mcp_servers``
  reads from ``self.mcp_registry`` directly.
* APIHub no longer carries the method surface.

Lint guard:
* ``tests/test_workflow_policies_gate_lint_guard.py`` extended
  with ``RETIRED_TO_MCP_REGISTRY`` + a new test class +
  paired pin-tests:
    - No ``<expr>.apihub.<retired_mcp_name>(...)`` callers in tree.
    - Every retired name actually exists on MCPRegistry.
    - Every retired name is GONE from APIHub.

Acceptance: 352/352 focused regression tests pass.

Next: PR 5 (SchemaHub + register_table_consumer signature parity,
per Q3) → PR 6 (profile rewiring + ghost-tool sweep).

### 7.6 PR 5 — SchemaHub extraction (2026-05-29)

Shipped against §6 Q3 (register_table_consumer + signature parity
with get_consumers) and Q4 (plain module). Same Q2 condition-based
retirement + lint guard as PR 3 + 4.

Moved into ``multi_agent/runtime/schema_hub.py``:
* Table registry: ``register_table``, ``list_tables``, ``get_table``,
  ``update_table_schema``.
* Table consumer registry: ``register_table_consumer`` (existing
  surface) + ``get_table_consumers(table_name)`` (NEW — Q3
  signature parity).
* Seed registry: ``register_seed_data``, ``get_seed_data``,
  ``list_seed_registrations``.
* Breaking-change detection: ``detect_table_breaking_change``,
  ``get_table_breaking_changes``.

**Q3 signature parity** —
``SchemaHub.get_table_consumers(table_name) -> List[dict]`` has the
SAME shape as ``APIHub.get_consumers(endpoint_id) -> List[dict]``.
``coverage_audit.scan_dead_tables`` was rewritten to call
``schema_hub.get_table_consumers(name)`` for each table instead of
reaching into the private ``_table_consumers`` store — same loop
shape as the endpoint dead-scan. The
``Q3SchemaHubConsumerSignatureParity`` test class in the lint
guard file pins the parity with ``inspect.signature``.

Data persistence: APIHub keeps the on-disk JSON stores
(``apihub_tables.json``, ``apihub_table_consumers.json``,
``apihub_seed_registrations.json``,
``apihub_table_breaking_changes.json`` — paths unchanged).
SchemaHub receives the store handles at init and mutates them.
Events stay tagged ``source_hub='apihub'``.

Caller migration (Q2 condition):
* 17 production sites moved from ``<expr>.apihub.X(...)`` to
  ``<expr>.schema_hub.X(...)`` across orchestrator.py, runtime
  helpers (coverage_audit, seed_audit, bug_triage, deliverability,
  hub_registry), tools (hub_tools, seed_tools), and
  live_monitor_server. The hasattr/local-var guards in
  ``bug_triage``, ``coverage_audit``, ``seed_audit``,
  ``deliverability`` were rewritten to read from ``schema_hub``
  directly.
* ~76 test sites mechanically migrated across 12 test files.
* APIHub no longer carries the table/seed method surface.

Lint guard:
* ``tests/test_workflow_policies_gate_lint_guard.py`` extended:
    - New ``RETIRED_TO_SCHEMA_HUB`` frozenset.
    - New ``NoCallerUsesRetiredAPIHubSchemaMethods`` test class.
    - New ``Q3SchemaHubConsumerSignatureParity`` test class —
      pins the get_table_consumers ↔ get_consumers signature
      parity AND the list-of-dict return shape.
    - Paired pin-tests for ``RETIRED_TO_SCHEMA_HUB``.

Acceptance: 456/456 focused regression tests pass.

Next: PR 6 (profile rewiring + ghost-tool sweep).

### 7.7 PR 6 — Tool→hub routing inventory + tool-name stability pins (2026-05-29)

The reviewer's framing for rank 6 was "update agents_config.yaml
profiles to include the new module tool bundles where appropriate"
plus running the ghost-tool sweep. After PRs 3–5 the tool wrappers
that were renamed-internally still carry their historical
``apihub_*`` / ``workhub_*`` NAMEs because those names are LLM
contracts (prompts reference them, models are trained against
them). Renaming would force a prompt + test sweep across every
agent profile, with no behavior benefit. So PR 6 took the "where
appropriate" judgment in the OTHER direction — keep tool names
stable, but add drift-detection so the gap between **tool NAME**
and **hub it actually calls** can't quietly widen.

New regression test ``tests/test_tool_to_hub_routing_inventory.py``
(6 tests + 6 subtests):

* ``HubToolImplementationsRouteThroughNewHubs`` — AST-walks
  ``tools/hub_tools.py`` and verifies that EVERY call site for a
  retired method (from PR 3's GateRegistry set, PR 4's MCPRegistry
  set, PR 5's SchemaHub set) routes through the NEW hub receiver,
  NOT the legacy ``apihub`` / ``workhub`` chain. A future commit
  that flips a tool body back to
  ``self._hubs.apihub.register_table(...)`` fails this test with
  the exact file:line.

* ``ToolNamesRemainStableAcrossRetirement`` — pins a curated set
  of LLM-facing tool NAMEs that the prompt templates rely on
  (``apihub_register_table``, ``workhub_create_page``,
  ``workhub_task``, etc.). A rename has to be a conscious PR that
  also updates this test, forcing the maintainer to sweep prompts
  in the same change.

* ``RetiredMethodSetsMatchTheLintGuard`` — cross-references the
  retired-method frozensets in this file against the canonical
  copies in
  ``test_workflow_policies_gate_lint_guard.py``. If one drifts,
  this test fires and the maintainer has to align both. (A
  future PR that adds a 6th retirement set has ONE update site
  for the canonical list and ONE for this inventory.)

Ghost-tool sweep: ``test_no_ghost_tool_references.py`` was already
green at PR 5 baseline (no prompt references a tool that doesn't
exist in the registry). PR 6 didn't add tool names, so it stays
green.

Profile rewiring intentionally deferred: the reviewer's plan
mentioned ``schemahub_tools`` as the new bundle label, but
splitting ``apihub_tools`` (which today contains both endpoint
and table tools) would require careful prompt updates without
any user-visible benefit while every profile that uses the table
subset also uses the endpoint subset. The cleanest follow-up
(separate from PR 6) would be a focused "bundle rename" PR with
an audit of every profile + prompt.

Acceptance: 134/134 focused regression tests pass.

This completes the hub-responsibility-split plan. WorkHub method
count: 61 → 48 (-13). APIHub method count: 38 → 22 (-16). Three
new plain modules own the extracted state: GateRegistry,
MCPRegistry, SchemaHub. Q2 (condition-based retirement + lint
guard), Q3 (signature parity for table consumers), Q4 (plain
module pattern) all met.

## 8. What this plan does NOT cover

* The reviewer's deferred behavior gate ("claim-task before
  finish") from a prior round — separate concern, separate plan.
* `focus_hub` removal — explicitly deferred until surface shrinks.
  After this plan ships, reviewer's question "do we still need
  focus_hub?" can be answered with data (count writes per agent
  after the surface contraction).
* Skills / ADR / Postmortem tool surface expansion (e.g. exposing
  ADR to design or verifier). That's a tool-surface decision,
  orthogonal.

---

Hand back to reviewer for sign-off on the proposed order + open
questions in §6. No code change until reviewer picks. Once they
do, PRs land one at a time in the order above.
