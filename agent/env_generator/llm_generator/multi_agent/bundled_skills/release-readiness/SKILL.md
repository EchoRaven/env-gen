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

## What actually blocks delivery

The `build:*` / `validation:*` families above are what you RUN. These four are what the
delivery gate REPORTS when it refuses, measured across 40 run logs — none of them was named
anywhere in these skills before, so lanes met them for the first time in a remediation task:

| blocker | times | what it means |
|---|---|---|
| `validation_ui_evidence_failed` | 46 | no passing UI capture for a page. Twice as common as anything else. A capture also fails when the STACK is down — `net::ERR_CONNECTION_REFUSED` is not a page bug and no edit to your page will fix it (#1202ba). |
| `business_chain_failing` | 19 | a chain step returned a status its `expect` does not list. netflix-r30 spent 148min and $930 here on `GET /api/genres/11/titles -> 404`, where the id had been correctly captured from the list endpoint and the detail handler could not resolve it. |
| `deliverability_ui_flow_failed` | 13 | a declared UI flow could not be walked end to end. |
| `database_sql_missing` | 4 | the DDL the app needs is not staged. |

Two of these have causes that live outside the failing lane, so check before rewriting your
own code: a refused capture means the stack is down, and a chain 404 on a valid id often
means the CONTRACT is thin — netflix-r30 registered `titles` with one column while 60 rows
of 12 fields were staged for it, and every symptom appeared four layers away (#1202az).

## Output expectations

- Separate three buckets explicitly: **verified pass** (green check + read output), **known fail** (red check or open `bug_create` with owning lane), **not yet checked** (no record). Never collapse the third into the first.
- Each reported bug: reproduction steps + owning lane (backend / frontend / etc.) so the orchestrator can route it.
- Do **not** clear delivery / call `deliver_project` unless the critical path is green and the release gate is clear. If any required check is absent or red, the answer is "not ready" with the specific check named — never "probably fine".
