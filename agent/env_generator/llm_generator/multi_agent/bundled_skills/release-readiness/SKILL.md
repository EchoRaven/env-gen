---
name: release-readiness
description: Use when coordinating or running final validation before delivery — about to call deliver_project / report_completion, or deciding whether a milestone is delivery-ready. Triggers on "is this ready to ship", "run final checks", "validate before delivery", pre-deliver gate review, aggregating the build:/validation: checks the _validate_delivery_gate reads, and deciding fixed-vs-blocking on known bugs. For the orchestrator and verifier lanes; this is the milestone-level gate, not the per-claim evidence rule (that's verification-before-completion, the discipline this checklist consumes).
---

# Release Readiness

The milestone gate for the **orchestrator** and **verifier** lanes: run this right before `deliver_project` / `report_completion` to decide whether the env (or milestone) is delivery-ready. It **aggregates** the evidence — it does not produce it. `_validate_delivery_gate` folds the recorded `build:*` and `validation:*` checks plus RunHub probes into the hard gate; your job here is to confirm that picture is coherent and complete before you trip it.

**Boundary:** this is the *milestone* gate. Verifying one claim before you record it (fresh output for a single `build:`/`validation:` check) is `verification-before-completion` — release-readiness consumes those green checks, it doesn't re-derive them. A failing check is `systematic-debugging`, not a blocker you wave through here. For a brand-new env, `new-env-bootstrap` Step 12 produces the smoke evidence; this skill is the lane-agnostic gate that consumes it.

## Readiness checklist

1. **Environment health (build:* family)** — `build:sql_syntax`, `build:docker_build`, `build:npm_install`, `build:backend_start` are all recorded green via `codehub_record_check`; `docker compose up` brings services up and RunHub's api/ui probes return 200 (not just "the container is up").
2. **Product-critical paths (validation:* family)** — `validation:api_smoke` and `validation:ui_smoke` pass; the primary user journey is covered by a `validation:ui_flow:<flow>` record per critical flow. Auth (OAuth/JWT), tenant-scoping (`X-Tenant-ID`), and core CRUD are exercised where relevant — not asserted from code reading.
3. **Edge cases** — empty states, invalid-input / validation errors, and dependency/network-failure behavior where applicable.
4. **Delivery gate (`_validate_delivery_gate`)** — every required `build:*` / `validation:*` check is present and green (a missing check fails the gate as hard as a red one); known critical bugs are either fixed or filed via `bug_create` on eventhub and explicitly accepted as blocking; workhub tasks, registryhub spec, implementation, and validation evidence all tell the same story.

## Output expectations

- Separate three buckets explicitly: **verified pass** (green check + read output), **known fail** (red check or open `bug_create` with owning lane), **not yet checked** (no record). Never collapse the third into the first.
- Each reported bug: reproduction steps + owning lane (backend / frontend / etc.) so the orchestrator can route it.
- Do **not** clear delivery / call `deliver_project` unless the critical path is green and the release gate is clear. If any required check is absent or red, the answer is "not ready" with the specific check named — never "probably fine".
