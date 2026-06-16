---
name: api-contract-guard
description: Use when creating or changing an API endpoint's contract, or when a check/bug points at API drift — about to write or edit a route/handler, define request/response shapes, pick status codes or auth, or when frontend↔backend payloads disagree, a probe returns an unexpected field/status, or validation:api_smoke fails on shape. Triggers on "add endpoint X", "change the response of Y", "frontend gets 500 / undefined field", "spec vs impl mismatch", renaming a resource/field. For the backend and verifier lanes; pairs with frontend api.js work.
---

# API Contract Guard

The API contract lives in **registryhub**, not in prose — it is the source of truth that the backend implements, the frontend consumes, and the verifier probes. Register every endpoint with `registryhub_register_endpoint` (method, path, request/response schema, status codes, auth) and every table with `registryhub_register_table`; have the frontend declare what it reads via `registryhub_register_consumer` so coupling is tracked. Use this skill before you write or edit a route/handler, and whenever a check or `bug_create` points at drift.

## Contract checklist

1. For every endpoint, verify:
   - method and path
   - request params/body shape
   - response shape with stable field names
   - status codes for success and failure
   - auth requirements
2. Keep spec and implementation aligned:
   - do not invent response fields that are absent from the spec
   - do not silently change casing or resource naming
   - if the implementation requires a new field, update the spec and dependent consumers
3. Error handling:
   - define deterministic error payloads
   - avoid generic 500s for expected validation/auth failures
4. Integration handoff:
   - frontend should know exact payload shapes
   - verifier should know expected status codes and error scenarios

## Detecting + recording drift

Drift is detected mechanically, not by eyeballing. Before changing a registered endpoint's shape, call `registryhub_check_endpoint_drift` / `registryhub_get_breaking_changes` to see which consumers break; if you change the contract, call `registryhub_update_schema` and re-notify consumers rather than letting the frontend find out via a 500. The contract is enforced by the **validation:api_smoke** check (and contract tests recorded via `registryhub_record_contract_test`) — a passing api_smoke is the evidence that spec and impl agree on shape/status, recorded through `codehub_record_check`. When you find a mismatch, cite the exact endpoint/field/status in a `bug_create` event (verifier) or in `codehub_review_pr` (reviewer) — do not patch it client-side.

## Output expectations

- In design artifacts, write endpoint contracts in a way frontend and verifier can consume directly.
- In code reviews or bug reports, cite the exact field/path/status mismatch.
- Prefer fixing the contract once at the source over adding scattered client-side workarounds.

## Boundaries

Contract *shape* (fields, status codes, casing, the registryhub registry) is this skill. Not the auth *design* behind an endpoint — that's `env-oauth-blueprint`. Not the X-Tenant-ID / tenant_id scoping rules — that's `multi-tenancy-pattern`. Not whether the rendered UI uses the payload well — that's `ui-ux-review`. Not the evidence discipline for claiming a check passed — that's `verification-before-completion`. When api_smoke fails and the cause is unclear, root-cause via `systematic-debugging` before editing the contract.
