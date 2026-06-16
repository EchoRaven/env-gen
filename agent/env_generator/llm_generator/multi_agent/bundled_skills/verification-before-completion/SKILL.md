---
name: verification-before-completion
description: Use when about to claim a task is done, a check passes, a build succeeds, or a bug is fixed — before calling finish, recording a build:/validation: check as success, submit_review, deliver_project, or report_completion. Triggers when you're about to set status='implemented'/'completed' or tell the orchestrator work is done. For the verifier, backend, frontend, and orchestrator lanes.
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command (or read the check output) in THIS step, you cannot claim it passes. A green check you recorded must be backed by output you actually read in this run.

## The Gate Function

```
BEFORE recording a check, marking status, calling finish/deliver_project, or saying "done":

1. IDENTIFY: what command / probe / check proves this claim?
2. RUN: execute it fresh and in full (docker compose up, the env's test command,
        the endpoint probe, the build)
3. READ: full output — exit code, failure count, the actual response body/status
4. VERIFY: does the output confirm the claim?
   - NO  → state the actual status WITH the evidence; do not record success
   - YES → record the check / make the claim WITH the evidence
5. ONLY THEN: codehub_record_check(... success), finish(), submit_review, deliver_project
```

Skipping any step = lying, not verifying.

## How this maps to the env-gen pipeline

| Claim you're about to make | Requires (fresh, this run) | NOT sufficient |
|----------------------------|----------------------------|----------------|
| `build:docker_build` success | `docker compose build` exit 0, read log | "the Dockerfile looks right" |
| `build:npm_install` success | `npm install` / `npm run build` exit 0, read log | "the linter passed so it builds" |
| `build:backend_start` success | container up + health endpoint 200 | "it started last run" |
| `validation:api_smoke` success | run the probe, read status + body | "the route exists in the code" |
| `validation:ui_flow:<flow>` success | run the flow, see it complete | "the page renders" |
| task `status='implemented'` | the lane's checks are green, files exist | "I wrote the files" |
| `deliver_project` ready | `_validate_delivery_gate` inputs all present + green | "all lanes said done" |
| a sub-agent/lane finished | inspect its actual hub state / diff | the lane's self-report |

The delivery gate aggregates RunHub + probes + build/validation checks. If you record a check as success without reading its output, you poison the gate with a false positive — exactly the failure this skill prevents.

## Red Flags — STOP

- Using "should", "probably", "seems to", "looks correct"
- Expressing satisfaction before verifying ("Great!", "Perfect!", "Done!")
- About to `codehub_record_check(... success)` / `finish` / `deliver_project` without fresh output
- Trusting another lane's or sub-agent's success report instead of its hub state / diff
- Relying on a partial or previous-run check
- "Just this once" / "I'm tired" / "the linter passed so it builds"

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification. |
| "I'm confident" | Confidence ≠ evidence. |
| "Just this once" | No exceptions. |
| "Linter passed" | Linter ≠ build ≠ runtime. |
| "It passed last run" | Stale. State changed. Re-run. |
| "The other lane said it's done" | Verify its hub state / diff independently. |
| "Different words, so the rule doesn't apply" | Spirit over letter. Any implication of success counts. |

## When to apply

ALWAYS before: any success/completion claim, any `codehub_record_check` with success, `finish`, `submit_review`, `deliver_project`, `report_completion`, moving to the next task, or trusting a delegated lane.

## The bottom line

Run the command (or read the check output). Read the result. THEN claim it. This is non-negotiable. Pairs with `systematic-debugging` (when a check fails) and `release-readiness` (the delivery checklist this discipline feeds).

---
*Adapted for env-gen from `obra/superpowers` `verification-before-completion` (MIT, © 2025 Jesse Vincent). Tuned red-flag/rationalization content preserved deliberately.*
