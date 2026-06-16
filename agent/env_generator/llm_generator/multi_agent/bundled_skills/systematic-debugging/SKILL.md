---
name: systematic-debugging
description: Use when a build:/validation: check fails, a bug_create event fires, docker compose up errors, an endpoint probe returns the wrong status, a UI flow breaks, or any behavior is unexpected — before proposing or applying a fix. Triggers on test failures, npm install/build errors, 500s, broken flows, and repeated failed fixes. For the debugger and verifier lanes especially.
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find the root cause before attempting a fix. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose a fix.

**Boundary:** this is for *investigating a failure before a fix* (debugger/verifier lanes). About to *claim* a fix/check/build is done? That's `verification-before-completion`. Writing the repro/feature test itself? That's `test-driven-development`.

## When to use

ANY technical issue: failed `build:*`/`validation:*` check, `bug_create` event, docker compose / npm install / build failure, wrong HTTP status from a probe, broken UI flow, unexpected behavior.

**Especially when:** under time pressure, "just one quick fix" seems obvious, you've already tried multiple fixes, or you don't fully understand the issue. Don't skip because it "seems simple" — simple bugs have root causes too.

## The Four Phases (complete each before the next)

### Phase 1 — Root cause investigation (BEFORE any fix)
1. **Read the error completely** — stack trace, line numbers, file paths, the failing check's recorded output. The message often contains the solution.
2. **Reproduce consistently** — exact steps; does it happen every time? Not reproducible → gather more data, don't guess.
3. **Check recent changes** — git diff / recent commits / new deps / config. What changed in this env?
4. **Gather evidence across component boundaries** — env-gen apps are multi-layer (gateway → backend → db; compose → container → process). Before fixing, instrument each boundary: log what enters/exits, check env/config propagation, run ONCE to see WHERE it breaks (e.g. probe OK → backend ✓, backend → db ✗), THEN investigate that component.
5. **Trace data flow** — where does the bad value originate? Trace up to the source. Fix at the source, not the symptom.

### Phase 2 — Pattern analysis
Find a working example in the same codebase or the reference impl; read it COMPLETELY (don't skim). List EVERY difference between working and broken — don't assume "that can't matter." Check dependencies, config, assumptions.

### Phase 3 — Hypothesis and testing
State ONE hypothesis: "I think X is the root cause because Y." Test it with the SMALLEST possible change, one variable at a time. Worked → Phase 4. Didn't → form a NEW hypothesis; do NOT pile fixes on top. Don't understand something? Say so; investigate, or `send_message` for help. Don't pretend.

### Phase 4 — Implementation
1. **Create a failing test** reproducing the bug first (use `test-driven-development`). Must exist before fixing.
2. **Implement ONE fix** at the root cause. No "while I'm here" changes, no bundled refactors.
3. **Verify** with `verification-before-completion` — repro test passes, no other checks break, issue actually resolved.
4. **If the fix doesn't work:** STOP. Count attempts. < 3 → back to Phase 1 with new info. **≥ 3 → question the architecture** (below). Do NOT attempt fix #4 blindly.
5. **If 3+ fixes failed — question the architecture.** Pattern: each fix reveals new coupling elsewhere, fixes need "massive refactoring", each fix spawns new symptoms. This is a WRONG architecture, not a failed hypothesis. `send_message` the orchestrator / fire `bug_create` with the architectural finding rather than thrashing.

## Red Flags — STOP and return to Phase 1

- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run the checks"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- Proposing fixes before tracing data flow
- **"One more fix attempt" (already tried 2+)**
- **Each fix reveals a new problem in a different place**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, skip the process" | Simple issues have root causes too; process is fast for them. |
| "Emergency, no time" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "Just try this first, then investigate" | The first fix sets the pattern. Do it right from the start. |
| "I'll write the test after confirming the fix" | Untested fixes don't stick. The repro test proves it. |
| "Multiple fixes at once saves time" | Can't isolate what worked; spawns new bugs. |
| "Reference too long, I'll adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "One more fix attempt" (after 2+) | 3+ failures = architectural problem. Question the pattern. |

## Quick Reference

| Phase | Activities | Done when |
|-------|-----------|-----------|
| 1 Root cause | read errors, reproduce, check changes, instrument boundaries | you understand WHAT and WHY |
| 2 Pattern | find working example, compare | differences identified |
| 3 Hypothesis | one theory, smallest test | confirmed or new hypothesis |
| 4 Implementation | failing test, one fix, verify | bug resolved, checks green |

95% of "no root cause" cases are incomplete investigation. Pairs with `test-driven-development` (Phase 4 repro) and `verification-before-completion` (confirm the fix).

---
*Adapted for env-gen from `obra/superpowers` `systematic-debugging` (MIT, © 2025 Jesse Vincent). Tuned red-flag/rationalization content preserved deliberately.*
