# Phase 4.6 expansion (6 CodeHub methods) — Design Notes (workflow `wvimglo1v` DEFER)

**Status:** DEFER. Workflow `wvimglo1v` (7 agents, 240k tokens) found
that the original audit's "MECHANICAL no-phantom-blockers"
pre-judgment was wrong — bundling gates onto the 6 remaining CodeHub
methods would BREAK existing production AND duplicate already-shipped
gates. The Phase 4.6 ship note in `runtime/elaboration_phase.py:411-412`
explicitly fences this:

> "open_pull_request / request_review / record_check stay open
> pending callsite cleanup (ui_user/unknown defaults)"

The real work is **callsite cleanup first** (the `ui_user` / `unknown`
phantom defaults), not gate fan-out. DEFER counter: 1.

## Per-method analysis (why bundle-A breaks)

| Method | Why the proposed gate is wrong |
|---|---|
| `record_commit` | **Tautology**. `hub_tools.py:184` already forwards `agent=self._agent_id`; `persisted commit.author == self._agent_id` always at tool layer. Proposed `{author, orchestrator}` gate would only deny if `author != self._agent_id` — which never happens. Net protection ≈ zero. |
| `open_pull_request` | **Phantom-denial**. Static 6-tuple `{backend, frontend, database, design, verifier, orchestrator}` OMITS 7 configured profiles in `agents_config.yaml`: architect_reviewer / visual_reviewer / knowledge / bug_triage_orchestrator / analysis_worker / review_worker / worker. Each could legitimately open a PR. |
| `record_check` | **Phantom + cleanup-pending**. `runhub` in the proposed `{verifier, runhub, orchestrator}` is a HUB-INTERNAL actor string (`hubs/runhub/service.py:89`), NOT an agent profile → adds a phantom. ALSO `hub_registry.py:413-419` passes `agent=publisher` (any agent that emitted validation_failed) into the record_check retry path — the static set would deny most real callers. |
| `resolve_conflict` | **Already gated** at `hubs/codehub/service.py:822-838` with `{orchestrator, pr.author, pr.assignee}`. The proposed `{author, orchestrator}` SILENTLY NARROWS by dropping `pr.assignee` — regression. |
| `create_release` | **Already orchestrator-gated** at `hubs/codehub/service.py:930-932`. Proposed `{orchestrator}` singleton is duplicate dead code. |
| `register_agent_repo` | **Production-breaker**. Called from `hub_tools.py:165` with `self._agent_id` for every resident's bootstrap. Singleton `{orchestrator}` bricks every non-orchestrator agent's onboarding. |

## What the audit got wrong

The audit synth's `next_session_recommended_order` #1 said Phase 4.6
expansion was "MECHANICAL, no phantom blockers, reuses just-shipped
PR-lifecycle inline dict-return idiom from a4cac71f, high".

This was based on a high-level reading of the roadmap row, NOT a
per-method check against shipped code. The workflow's discovery phase
caught the issue by greping agents_config.yaml + checking each
method's actual callers. The directive in the workflow prompt
("PHANTOM_IDENTITY: any name NOT in agents_config.yaml is a phantom")
forced the verify-before-ship discipline.

**Lesson**: even when an audit pre-judges work as mechanical, the
per-method phantom-identity check is non-optional.

## What needs to happen before Phase 4.6 expansion can ship

### Step A (callsite cleanup, prerequisite)

Per `elaboration_phase.py:411-412`: the methods need their default-actor
strings cleaned up (ui_user / unknown / hub-internal sentinels) BEFORE
gates can be added. Specifically:

1. **`record_check` retry path** (`hub_registry.py:413-419`): replace
   `agent=publisher` with a properly-bound caller identity. Threads
   into the existing O14 caller-kwarg pattern.
2. **HTTP-shim defaults** for codehub methods: confirm the
   `live_monitor_server.py` shim defaults pass `agent=""` (empty-actor
   fallthrough) not `agent="ui_user"`. Same pattern as the Phase 4.5
   HTTP shim flip.
3. **`hub_tools.py` tool wrappers**: each codehub tool wrapper should
   pass `agent=self._agent_id` (consistent with how I threaded
   EventHub tool wrappers in commit `dc3d972d`). Most likely already
   correct; audit the 3-4 codehub tool classes.

### Step B (gate fan-out, after Step A)

For methods where the cleanup is done AND there's a real
trust-bearing surface:

1. **`open_pull_request`**: data-driven allowed_set from a project
   `pr_authors` config OR `{all configured agent profiles in agents_config.yaml}`.
   Static literal is wrong.
2. **`record_check`**: data-driven from the PR's `checks_authorized`
   field OR honor the existing `publisher`-based retry path.
3. **`record_commit`**: NOT a tool-layer concern — only meaningful at
   the service layer for direct callers bypassing hub_tools. Probably
   skip.

### Step C (DON'T expand — already gated or producer-side)

- `resolve_conflict`: already gated; leave the existing `{orchestrator, pr.author, pr.assignee}` set.
- `create_release`: already gated; existing `{orchestrator}` is correct.
- `register_agent_repo`: bootstrap path; producer-side per agent. NOT a
  candidate for gating regardless. Treat as producer-only.

## Recommendation

1. Land **Step A** as 1-2 small reversible commits (callsite cleanup
   for `record_check` retry + audit codehub HTTP shims). These match
   the "callsite cleanup pending" comment in elaboration_phase.py
   exactly.
2. **DROP** the 6-method-bundle framing entirely. Replace with 1-2
   targeted Phase 4.6.1 commits, each gating ONE specific method with
   a data-driven allowed_set whose contents are verified against
   agents_config.yaml at gate-construction time (e.g., via a
   `get_configured_agent_profiles()` helper).
3. Re-attempt as Phase 4.6.1 (`record_check`) + Phase 4.6.2
   (`open_pull_request`) AFTER Step A lands.

## Workflow stats

- 7 agents, 240k tokens, ~6.5 min wall-time.
- 3 parallel discovery agents (methods / idiom-shape / phantom-audit).
- 3 candidates (A: bundle-6 / B: verdict-only-4 / C: DEFER).
- Judge picked C — the audit's "MECHANICAL" pre-judgment was
  contradicted by the phantom-identity check; DEFER is the correct
  move per the verify-then-narrow-or-DEFER directive.
- No adversarial review run (judge fast-pathed DEFER).
- Full output: `/tmp/claude-1052/.../tasks/wvimglo1v.output`.

## What this unblocks

Once Step A lands (callsite cleanup), Phase 4.6.1 + 4.6.2 become
mechanical ships in the data-driven allowed_set shape. Phase 4.6 ship
note in `elaboration_phase.py:411-412` can be updated to say
"open_pull_request / request_review / record_check NOW gated" instead
of "stay open pending callsite cleanup".

DEFER counter: 1 (the first DEFER after the 3-bug-fix + Phase 3
mechanism + persistence + deliverability + design-notes ship train).

---

## 2026-06-01 — Phase 4.6.1 re-attempt: DEFER (workflow `wnjpij4xw`)

After the 4-item Path A/B/C batch shipped (4.5d / 4.7-slim Path A /
3.5 Path B / 3.9 Path B → mechanisms 18→21), Phase 4.6.1 was
re-attempted as the velocity-batch B.2 item. Workflow `wnjpij4xw`
(6 agents, 116k tokens, ~74s) returned **DEFER** with two
independent blockers:

### Blocker 1 — `helpers.py:189` `"unknown"` literal fallback

`step_pipeline/helpers.py:188` (artifact-sync `record_check` caller)
fell back to `getattr(self, "agent_id", "unknown")` when the
step-pipeline instance had no bound `agent_id`. The literal
`"unknown"` is non-empty, non-allowlisted, and would be rejected by
any future Phase 4.6.1 allowlist gate — breaking artifact sync on
every step that runs unbound.

**Status: ✅ RESOLVED** as the Step A spin-off shipped in this
session (helpers.py flip + regression test
`tests/test_step_pipeline_artifact_sync_empty_actor.py`). The
evidence payload still records `agent_id or "unknown"` so the audit
trail stays readable; only the gate-facing `agent=` kwarg flips to
`""`.

### Blocker 2 — No `checks_authorized` field on PR record (UNSHIPPED)

`submit_review`'s precedent at `service.py:366` sources `allowed`
from `pr["reviewers"]`, populated by `open_pull_request(reviewers=...)`.
For `record_check` the analogous field — `pr["checks_authorized"]` —
**does not exist** on the PR record (`service.py:293-313`). The
check record itself (`L496-505`) persists no author field either.

A static allowed_set like `{verifier, tester, ci_runner}` would be a
**phantom set**: `ci_runner` has zero callsites; production traffic
comes from `publisher`-of-`validation_failed` (any agent) at
`hub_registry.py:280` and from step-pipeline agents (now empty-actor
fallthrough). This is the same failure mode that DEFER'd the original
`wvimglo1v` bundle-A attempt (runhub phantom).

**Unblock:** plumb `checks_authorized: list[str]` through
`open_pull_request` (mirror `reviewers` plumbing at `L184/193/301`),
backfill defaults for existing PRs, then
`allowed = {"orchestrator"} | set(pr.get("checks_authorized") or []) | set(pr.get("reviewers") or [])`
becomes a real data-driven gate.

### Recommended threshold disposition (when ready)

When both blockers clear, the gate ships as **an extension of the
existing Phase 4.6 _MECHANISMS row** — NOT a new 4.6.1/4.61 slot.
The repo uses single-decimal float thresholds; 4.61 would break
granularity and 4.7 is occupied. `record_check` is a near-identical
instance of the PR-LIFECYCLE-ALLOWLIST idiom (`a4cac71f`, anchor
**M**) applied to a sibling method — extend the M row from 1→2
entries. Mechanism count would go 21→22; anchor-letter inventory
unchanged.

DEFER counter: **2** (Blocker 2 unblocked-by-construction is a
data-model PR, not another gate attempt).
