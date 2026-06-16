# North-Star Pilot Report — 2026-06-01 (first written report)

**Branch:** `haibotong-0527-hub-focus-and-tooling-cleanup`
**Head at report write:** `9557e64f` (P0+P3 cleanup; 22 mechanisms / 12 thresholds + 24 METHOD_ALLOWLIST + 2310/0 dt-env suite)
**Operator:** haibotong@virtueai.com (Claude session)
**Trigger:** Audit `wg7qfhi2m` flagged that NO pilot report had ever been written and the R2 round-11 GO criterion calibration was 32+ hours stale.

---

## TL;DR

| What | Status |
|---|---|
| Oracle calibration spike (3 hand-built apps × 4 arms + result-emit) | ✅ **5/5 PASS** in 132s |
| `test_oracle_passes_against_a_real_generated_app` (R2 round-11 observation #1) | ❌ **NOT RUNNABLE** — `simple_blog_pilot_take2/` generation died at 13 min / 0 ticks with empty `app/{backend,frontend,database}/src/` |
| Programmatic env-vs-functional classifier wired into runner.py BEFORE data (R2 round-11 #2) | ⏸ **CLASSIFIER EXISTS, WIRING UNCHANGED** — `tests/north_star/classifier.py` is 47KB of judgment logic but `runner.py:574` still emits raw verdicts; no pre-data gate |
| Fixture reliability per generated app (R2 round-11 #3) | ⏸ **MEASURED ON HAND-BUILT TARGET, NOT ON GENERATED APP** — `arm_4_fixture_reliability` runs 5× against `target_impl/` with 100% success; no measurement against a real generated app exists |
| §9.1.5 anti-circularity A1 cross-stack proof against pipeline-generated app | ❌ **STILL ONLY IN HAND-WRITTEN SPIKE** `f3c87659` |
| v3 prompts (Knowledge `d89d8c49` / Backend `92d98837` / Frontend `2eadf0c6` / Design `911a6452`) validated by re-pilot | ❌ **NEVER RE-PILOTED** — all v3 commits landed AFTER take2 was abandoned |

**Bottom line:** the oracle infrastructure works (5/5 spike). The real question — *do the 3-bug runtime fixes + 4 v3 prompt rewrites actually move the Backend Lead 0-tool-calls bottleneck on a fresh generation?* — remains unanswered because no generation has run end-to-end since they landed.

---

## What ran (the calibration spike)

```
$ /home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
    tests/north_star/simple_blog/oracle_validation/test_calibration.py \
    --confcutdir=tests -v --tb=short
```

| Arm | Result | Meaning |
|---|---|---|
| `test_arm_1a_green_on_reference` | PASS | Oracle is **signal-positive** on reference_impl (Flask/cookie/`/api/` prefix). No false-negatives on the canonical stack. |
| `test_arm_1b_green_on_target` | PASS | Oracle is **signal-positive** on target_impl (Express/Bearer/`/_api/_` prefix). No cross-stack false-fails. This is the R2 round-10 make-or-break cross-stack test. |
| `test_arm_2_catches_broken` | PASS | Oracle is **signal-negative** on target_impl_broken (target + ONE auth-middleware line mutation). Unauthenticated-create flow correctly fails. No false-positives on a real bug. |
| `test_arm_4_fixture_reliability` | PASS | `runner.run_app(target_impl)` ran 5× successfully. Docker-compose-up flakiness is below threshold on the hand-built fixture. |
| `test_zzz_emit_spike_result` | PASS | `##SPIKE_RESULT## {json}` line emitted for machine consumption. |

Total wall-time: **132.20 seconds** (5 arms, includes 5 docker-compose lifecycles for arm_4).

**Interpretation:** the oracle + runner + classifier wiring is signal-tight on the controlled hand-built fixtures. There are NO false-negatives, NO false-positives, and NO fixture flakiness measurable on hand-built apps. The cross-stack convention pivot (target_impl) does not over-strict the oracle. This validates the §9.1.5 anti-circularity claim *for the spike inputs* — it does NOT validate it for a pipeline-generated app, which is the actual north-star metric.

---

## What did NOT run (and why)

### 1. `simple_blog_pilot_take2/` end-to-end runner

Inspection:

| Field | Value |
|---|---|
| `tmp/simple_blog_pilot_take2/simple_blog/project.json::created_at` | 1780203219 (2026-05-31 23:53) |
| `tmp/simple_blog_pilot_take2/simple_blog/project.json::last_active_at` | 1780204174 (~16 min after create) |
| `run_budget.json::usage.ticks` | **0** (no agent loop iteration completed) |
| `run_budget.json::usage.elapsed_sec` | 780.7 (~13 min) |
| `run_budget.json::usage.status` | `"running"` (stale; process is dead) |
| `app/{backend,frontend,database}/src/` | EMPTY (only `mkdir`'d subdirs, NO code files) |
| `app/{backend,frontend,database}/Dockerfile*` | MISSING |
| `design/spec.{api,database,ui}.json` | PRESENT (design phase produced specs) |
| `.memory/*.knowledge.jsonl` | Only `orchestrator` + `design` wrote entries (5 of 7 agents wrote nothing) |

**Diagnosis:** generation crashed/stalled ~13 minutes in, after design produced specs but before backend/frontend/database wrote any code. 0 ticks completed means the agent loop never advanced past initial setup. The `running` status is stale.

**Why this isn't an oracle test today:** `runner.run_app(take2)` would fail at `docker build` because there are no Dockerfiles. The runner classifies that as `env.compose_build` failure (P0 fixture failure, not a flow verdict) — so we wouldn't even reach oracle judgment.

### 2. The temporal gap that matters most

The take2 attempt **predates** every piece of work the recent 36 hours produced:

| Work | Landed | Take2 last active |
|---|---|---|
| Take2 generation died | 1780204174 (May 31 ~00:02) | — |
| `9a015dc7` memory-bank stash-pop fix | 1780352097 (Jun 1 ~16:54) | +41 hours **after** |
| `48a1471a` step-start merge_conflict → WorkHub task | 1780352200 (Jun 1 ~16:56) | +41 hours after |
| `2e518079` observer-loop exponential backoff | 1780352375 (Jun 1 ~17:00) | +41 hours after |
| Phase 4.5d / 4.7-slim / 3.5 / 3.9 / 4.1c gates | 1780300000–1780500000 (Jun 1) | hours-to-days after |
| v3 prompts (Knowledge `d89d8c49`, Backend `92d98837`, Frontend `2eadf0c6`, Design `911a6452`) | (Jun 1) | hours-to-days after |

**The R2 round-11 GO criterion was: validate v3 prompts on a fresh generation BEFORE adding more mechanism. Take2 happened BEFORE v3. So the criterion has never actually been tested — we don't know if v3 moves Backend Lead's 0-tool-calls bottleneck because no v3-driven generation has run end-to-end yet.**

---

## R2 round-11 observation points — actual status

### #1 — `test_oracle_passes_against_a_real_generated_app` against `PINNED_GENERATED_APP=take2`

**NOT runnable** in this session. Take2 has no app code → `docker build` would fail.

**To unblock:** launch a fresh generation against the current head (`9557e64f` post-P0+P3 cleanup, post-v3 prompts, post-3-bug fixes). Then re-attempt this test against the new `tmp/simple_blog_pilot_take3/`. Cost: a full LLM-driven generation run (hours; not free).

### #2 — Programmatic env-vs-functional classifier wired into `runner.py` BEFORE data

The classifier module exists at `tests/north_star/classifier.py` (47 KB, comprehensive — env signatures + functional verdict synthesis). However:

```
$ grep -c "import classifier\|from classifier" tests/north_star/simple_blog/runner.py
0
```

The runner does NOT consume the classifier today. `runner._classify_and_emit` (line 461) writes a verdict directly to the sink without classifier consultation. The "BEFORE data" requirement was that classifier gates would prevent ambiguous verdicts from polluting the sink — that gating doesn't exist.

**To unblock:** wire `classifier.classify(verdict, ctx)` into `runner._classify_and_emit` and `runner._emit_pass_verdict`. The classifier already returns the right shape. Likely ~20 LOC + tests.

### #3 — Fixture reliability per generated app

`arm_4_fixture_reliability` measures fixture-up reliability for `target_impl` (hand-built). We have 5/5 on that. We have ZERO measurements on a pipeline-generated app because no generated app has built successfully.

**To unblock:** same as #1 — needs a fresh generation that actually produces working Dockerfiles.

---

## §9.1.5 anti-circularity status

The hand-written spike commit `f3c87659` shipped A1 cross-stack proof against the 3 hand-built apps (reference + target + broken). The calibration spike I just ran is essentially the same shape — it confirms the oracle is convention-agnostic on those 3 inputs.

**What's still pending:** A1 against a pipeline-generated app. Until a generation produces something the runner can `docker build`, this is blocked by the same precondition as observation #1.

---

## Recommendation

Three options for the next session (in increasing cost):

**A. Land observation #2 wiring (cheap).** Wire `classifier.classify` into `runner._classify_and_emit` + `runner._emit_pass_verdict` and write the classifier-gate test. ~20 LOC. No LLM cost. Unblocks the "classifier BEFORE data" R2 invariant *before* the next generation runs, so the sink it populates is already gated.

**B. Launch a fresh generation against current head (expensive — hours of LLM cost, but is THE answer to the R2 round-11 GO criterion).** With v3 prompts + 3-bug fixes both in place, launch `simple_blog_pilot_take3/` and let it run to completion (or fail). If it succeeds, run the oracle against it (observation #1). If it fails, the agent_logs will pinpoint whether the Backend Lead bottleneck is moved.

**C. Both A then B.** A first, so B's run produces classifier-gated sink data from the start. This is the principled order.

**Author judgment:** Option **C** matches R2's "classifier BEFORE data" discipline. Option B alone risks producing an ungated sink that we then have to retroactively classify (the exact ambiguity R2 round-11 warned against).

---

## Things this report deliberately does NOT claim

- This report does NOT claim the v3 prompts work. They are untested on a real generation.
- This report does NOT claim the 3-bug runtime fixes prevent the next stall. They are designed to but have not run against a real generation cycle.
- This report does NOT claim the 22-mechanism phase ladder makes a generation more likely to succeed. The mechanisms are correctness gates, not progress gates; they fire when generation paths violate authorship, not when generation produces working code.

These claims will be testable only after Option B above runs to completion.

---

## Sink files written this session

- This file: `docs/north_star/pilot_report_2026_06_01.md` (first written pilot report ever per audit `wg7qfhi2m`)
- Spike test artifact: pytest-cached at `tests/north_star/.pytest_cache/` (132s runtime; 5/5 PASS)
- No `PILOT_VERDICT_SINK` was set during the spike run — that env var is for `pilot_driver.py` A/B runs, not the calibration spike. A future Option B run should set it.
