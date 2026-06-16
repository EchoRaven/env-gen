---
name: test-driven-development
description: Use when implementing any feature or bugfix in a generated env, before writing production code — about to write a route/handler, model, migration, UI component, or fix a failing build:/validation: check. Triggers on tasks like "implement endpoint X", "add the posts table", "build the feed page", "make the failing check pass". For the backend, frontend, and debugger lanes.
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Wrote code before the test? Delete it. Start over.

**No exceptions:**
- Don't keep it as "reference"
- Don't "adapt" it while writing the test
- Don't look at it
- Delete means delete

Thinking "skip TDD just this once"? Stop. That's rationalization.

## How this maps to the env-gen pipeline

You are a lane (backend / frontend / debugger) building or fixing a generated app. "The test" is whatever proves the behavior in THIS env's stack, and it must FAIL before you implement:

| Lane | RED (write + watch fail) | GREEN (minimal impl) | Evidence |
|------|--------------------------|----------------------|----------|
| backend | a request test / api_smoke probe asserting the endpoint's status + response shape | implement the route just enough to pass | verifier records `validation:api_smoke` via `codehub_record_check` |
| frontend | a UI test / ui_smoke or ui_flow assertion for the page or flow | build the component to pass | `validation:ui_smoke` / `validation:ui_flow:<flow>` |
| db/backend | a query/migration test asserting the table/columns exist | write the schema/migration | `build:sql_syntax` |
| debugger | a failing test reproducing the bug (see `systematic-debugging`) | fix root cause | the repro test goes green |

Use the generated env's own test command (`npm test` / `jest`, `pytest`, etc.) — NOT the framework's test runner. Run it inside the workspace before and after.

## Red-Green-Refactor

1. **RED** — write one minimal test for the next behavior. One thing, clear name, real code (no mocks unless unavoidable).
2. **Verify RED** — run it. Confirm it FAILS, and fails because the feature is missing (not a typo). Test passes already? You're testing existing behavior — fix the test.
3. **GREEN** — write the simplest code that passes. No extra features, no "while I'm here" refactors. YAGNI.
4. **Verify GREEN** — run it. Test passes, other tests still pass, output pristine (no errors/warnings). Test fails? Fix the code, not the test.
5. **REFACTOR** — only after green: remove duplication, improve names, extract helpers. Keep tests green; don't add behavior.
6. **Repeat** for the next behavior.

## Why order matters

- **"I'll write tests after to verify it works"** — tests written after pass immediately, which proves nothing: they may test the wrong thing, test the implementation not the behavior, or miss edge cases. You never saw them catch the bug.
- **"I already manually tested it"** — ad-hoc, no record, can't re-run, easy to forget cases under pressure.
- **"Deleting X minutes of work is wasteful"** — sunk cost. The time is gone. Keeping code you can't trust is technical debt.
- **"Tests-after achieve the same goal — it's spirit not ritual"** — no. Tests-after answer "what does this do?"; tests-first answer "what should this do?" Tests-after are biased by what you built.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Tests after achieve same goals" | Tests-after = "what does this do?"; tests-first = "what should this do?" |
| "Already manually tested" | Ad-hoc ≠ systematic. No record, can't re-run. |
| "Deleting work is wasteful" | Sunk cost. Keeping unverified code is technical debt. |
| "Keep as reference, write tests first" | You'll adapt it. That's testing after. Delete means delete. |
| "Need to explore first" | Fine. Throw away the exploration, start with TDD. |
| "Test hard = design unclear" | Listen to the test. Hard to test = hard to use. |
| "TDD will slow me down" | TDD is faster than debugging a wedged delivery gate later. |
| "The check is what counts, not a unit test" | The verifier's check IS your test — make it fail first, then pass. |

## Red Flags — STOP and Start Over

- Code before test
- Test passes immediately
- Can't explain why the test failed
- "Tests added later"
- "I already manually tested it"
- "It's about spirit not ritual"
- "Keep as reference" / "adapt existing code"
- "This is different because…"

**All of these mean: delete the code, start over with TDD.**

## When stuck

| Problem | Solution |
|---------|----------|
| Don't know how to test | Write the wished-for API / the assertion first. If still stuck, `send_message` the orchestrator. |
| Test too complicated | Design too complicated. Simplify the interface (and the contract — see `api-contract-guard`). |
| Must mock everything | Code too coupled. Use dependency injection. |

## Verification

Before marking a task `implemented`/`completed`, confirm with `verification-before-completion`: every behavior has a test you watched fail then pass, all tests green, output pristine. Can't check those boxes? You skipped TDD — start over.

**Exceptions (escalate to the orchestrator via `send_message` before skipping):** throwaway spikes, generated boilerplate, pure config.

---
*Adapted for env-gen from `obra/superpowers` `test-driven-development` (MIT, © 2025 Jesse Vincent). Tuned rationalization/red-flag content preserved deliberately.*
