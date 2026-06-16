# Phase 4.5a/b/c WorkHub Authorship Gates — Design Notes (RETIRED via 4.5d Path A SHIPPED)

**Status:** ✅ RETIRED via **Phase 4.5d Path A** SHIPPED at `3a768740`
(2026-06-01). The 4.5a/b/c bundle stays DEFERRED for the architectural
reason below (WorkHub is producer-side), but the actual
verdict-authoring surface that motivated the items —
`gate_registry.mark_path_intentionally_dead` — was identified and
gated at Anchor L.1 (`allowed_set={orchestrator}` via
`require_allowed_actor` at phase>=4.5). Path A retire-to-gate_registry
discharges the original 4.5a/b/c intent without trying to gate
producer-side WorkHub methods.

**Original DEFER rationale (preserved for context):** Bundled DEFER
for all three WorkHub roadmap items (4.5a planning + 4.5b state +
4.5c collaboration). Workflow `wzzr5iyx7` (8 agents, 254k tokens,
22 min) discovered that WorkHub is **architecturally non-gatable
for authorship** — the trust-bearing surface was deliberately
migrated OFF WorkHub by PR 3 of the hub-responsibility-split plan.

## Why WorkHub is non-gatable (architectural finding)

From the workflow's discovery against
`runtime/hubs/workhub/service.py` header comment (L21-26 and L61-79):

> **PR 3 of the hub-responsibility-split plan deliberately moved every
> VERDICT-AUTHORING surface (design review, visual review, retro,
> coverage allowlist) OFF this hub and into
> multi_agent/runtime/gate_registry.py, with
> tests/test_workflow_policies_gate_lint_guard.py failing the build
> if a new `workhub.<retired_name>(...)` call is added.**

The 11 write methods that remain on WorkHub
(`create_page` / `create_plan` / `create_task` / `archive_page` /
`update_plan_metadata` / `add_task_to_plan` /
`upsert_plan_snapshot` / `_upsert_snapshot_task` / `claim_task` /
`set_task_priority` / `link_task_to_pr` / `link_task_to_apis` /
`update_block` / `record_decision` / `comment` / `react`) are all
**PRODUCER-AUTHORING** or **ADMIN**, not VERDICT-AUTHORING:

| Method | Category | Trust signal? |
|---|---|---|
| `create_page` | PRODUCER | No — owner creates own draft/active page |
| `create_plan` | PRODUCER | No — plans start `status='active'` unconditionally, no producer/reviewer split |
| `create_task` | PRODUCER | No — caller authors task in pending state, claim_task elsewhere |
| `archive_page` | ADMIN | No — janitorial; sets `status='archived'` without ownership check |
| `update_plan_metadata` | PRODUCER/ADMIN hybrid | No — partial LWW patch with no ownership check |
| `add_task_to_plan` | PRODUCER | No — adds child task to plan; no plan-ownership check |
| `upsert_plan_snapshot` | PRODUCER | No — per-tick step-pipeline plan re-sync |
| `claim_task` (Phase 4.5b) | PRODUCER | No — agent claims task assigned to itself |
| `set_task_priority` (4.5b) | ADMIN | No — anyone can re-prioritize any task |
| `link_task_to_pr` / `_apis` (4.5b) | LWW link | No — bidirectional metadata join |
| `comment` / `react` / `update_block` (4.5c) | PRODUCER | No — collaboration metadata |

The `agent=` kwarg on every method is **string author bookkeeping**
(stamped into `created_by` / `_updated_by` and the LWW author slot
on `JsonStore.update`), **NOT a trust principal**. Verified:

> agent= kwarg semantics across all six: it is a string author tag fed
> into `actor = agent or 'workhub'`, stamped into created_by/_updated_by
> on the row, and passed as the LWW author to
> `self.stores.<store>.update(... change_info={'agent': actor})`. There
> is no agent-identity check, no allowlist of writers, no ACL — any
> caller can pass any agent string. A downstream consumer cannot use
> these rows as trust-bearing evidence about who actually performed
> the write.

## Implications for Phase 4.5a/b/c roadmap entries

The roadmap entries Phase 4.5a (planning), 4.5b (state), 4.5c
(collaboration) were drafted ASSUMING WorkHub has VERDICT-AUTHORING
methods to gate. The workflow discovery proves that assumption wrong:

- **Phase 4.5a planning surface**: PRODUCER-AUTHORING. No VERDICT
  semantics. Gating would just lock down "who can author their own
  plan", which has no security value.
- **Phase 4.5b state surface**: `claim_task` is producer-side
  (assignee claims own task). `set_task_priority` is admin. Same
  conclusion as 4.5a.
- **Phase 4.5c collaboration surface**: comment/react/update_block —
  collaboration metadata, no trust-bearing.

Gating any of these would **violate the PR 3 architectural decision**
that VERDICT-AUTHORING belongs on `gate_registry`, not WorkHub.

## What COULD ship from this track (if scope expands later)

**Option 1 — Re-target to gate_registry methods**: the methods PR 3
*moved* to gate_registry are the trust-bearing surface. Phase 4.5
shipped gates for `submit_design_review` + `submit_visual_review`
(both on gate_registry). The remaining trust-bearing methods on
gate_registry are:
- `submit_retro_finding` (if present)
- `add_critical_route` (if present)
- `submit_review_request_state_change` (if present)

A "Phase 4.5d gate_registry verdict-extension" PR could lock these
down. But that's a new roadmap entry, not 4.5a/b/c.

**Option 2 — WorkHub assignee/ownership gates**: even though WorkHub
is producer-side, certain methods admit cross-agent mutation that
COULD be tightened:
- `claim_task`: should only the assignee or orchestrator be able to
  claim a task? Currently anyone can pass `agent=<x>` and claim on
  behalf of `<x>`.
- `archive_page`: should only the page author or orchestrator be able
  to archive? Currently anyone.

These are ownership invariants, not VERDICT-AUTHORING. They'd be a
NEW design (compare `created_by == agent` rather than allowlist).
But the PR 3 lint guard would NOT block this — it only blocks the
specific retired VERDICT-AUTHORING method names, not new ownership
invariants on producer-side methods.

This is operator-judgment territory: is "claim_task spoofing" a real
risk that justifies adding a new ownership-check idiom? The Phase 4+
roadmap doesn't claim so. Defer until a real pilot incident shows
spoofing.

## Recommendation for next implementer

1. **DROP roadmap entries 4.5a/b/c as currently described.** They
   target a non-existent VERDICT-AUTHORING surface on WorkHub.
2. **EITHER** add Phase 4.5d (or 4.7+) targeting remaining gate_registry
   VERDICT-AUTHORING methods that weren't covered by Phase 4.5
   (submit_design_review + submit_visual_review).
3. **OR** introduce a new "ownership-equals" gate idiom for WorkHub
   producer-side methods (claim_task / archive_page). This was
   considered in O1 (`require_owner_actor`) but DROPPED as premature
   abstraction. The reason it was dropped (no canonical call site) is
   no longer true if WorkHub adopts the pattern.

## Why this wasn't shipped autonomously

Three architectural reasons:

1. **PR 3 lint guard would fail the build** if I add a `workhub.<retired
   method>(...)` gate call. The guard is intentional and load-bearing.
2. **All WorkHub write methods are producer-side**. Gating them with
   an allowlist is gate-for-gates-sake — no security benefit, just
   prevents agents from authoring their own producer state.
3. **The "ownership-equals" alternative** is a new gate idiom not yet
   designed. Phase 4+ roadmap O1 explicitly dropped it as premature.
   Designing + applying it autonomously exceeds safe scope.

## Workflow stats

- 8 agents, 254k tokens, 22 min wall-time.
- 3 parallel discovery agents (methods + prod callers + test callers).
- 4 candidates: orchestrator-owned / lane-parity / minimal / DEFER.
- Judge picked Candidate D (DEFER fast-path).
- Verdict: DEFER (no adversarial review run since judge picked defer).
- Full output: `/tmp/claude-1052/.../tasks/wzzr5iyx7.output`.

## Out of scope

- Re-running the workflow for Phase 4.5b + 4.5c — same architectural
  conclusion applies (WorkHub state + collaboration surfaces are also
  producer-side per PR 3). Skipping the workflow runs saves ~500k
  tokens that would arrive at the same DEFER verdict.
- O1 `require_owner_actor` idiom — re-add when first real consumer
  exists.
