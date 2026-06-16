# Parallel-Tracks Proposal — Adversarial-Corrected Brief for R2

**Audience:** R2 (round 14+ follow-up).
**Author:** Implementer, 2026-05-30, after running an internal adversarial workflow against R2's mechanism-phase parallelization proposal, then a hedge spike on the lightweight gate.
**Status:** Action requested. R2 already offered to spell §9.4 / §9.5 softening into a concrete diff against `docs/progressive_elaboration_refactor.md`; this brief gives R2 the adversarial-corrected version of that diff plus two holes the synthesizer's first pass missed, plus the spike result that validates the lightweight gate as a no-regression instrument.

**Spike verdict (preview):** `gate_works_with_caveats` — G2/G3/G4/G6 verified with sharp green-pass/red-fail discrimination on a planted-regression copy of `simple_blog/reference_impl`. Real-bug test on `demos/jira-web` fired the predicted gate (G4 during `RUN npm run build`) with the exact round-11 `ERR_MODULE_NOT_FOUND` error. G5 is honestly inapplicable on the current reference_impl (no app-bundled tests to break). G1 was skipped per the LLM-cost directive. See §8 for full evidence.

---

## 1. TL;DR

The implementer ran an internal adversarial workflow on R2's parallel-tracks proposal, then ran a 1-day hedge spike on the lightweight no-regression gate. **The structural argument holds** — Phase 1 / Phase 2 / Phase 2.5 dependencies on the oracle are ASSUMED-not-HARD; the load-bearing sentences in §9.4 / §9.5 / §9.1.5 / §6 are reporting/process gates, not technical prerequisites. **AND the lightweight gate works on the gates that were tested** (G2/G3/G4/G6 all sharp; G3 even names the offending Dockerfile line as the contract advertises; G4 caught the jira-web round-11 build bug at exactly the predicted step). **BUT the adversarial caught 2 real holes** in the proposal that R2's prose edit must address before merging, and the spike has 2 honestly-disclosed caveats that should be flagged in §8:

- **Hole 1 — §10 flag-fork does not exist in code.** R2's proposal cites the §10 `ELABORATION_REFACTOR_PHASE` flag-fork coexistence guarantee 4× as the safety net that lets parallel branches not cross-contaminate. `grep -rn ELABORATION_REFACTOR_PHASE /data/common/haibotong/env-gen/agent/env_generator/` returns **zero** matches; the flag lives only in docs §10.1–10.4. Without code, Phase 1's lint guard on `schema_hub.register_table` is a HARD REPLACEMENT, not a fork — it breaks the baseline (A) checkout the moment anyone re-runs it.
- **Hole 2 — back-fill grading is operationally lossy for perf-shaped metrics.** `classifier.py` Verdict has `run_id / spec_id / arm / phase_reached / outcome / classifier_spec_sha` but no source-tree SHA and no captured perf data. Back-fill against the validated oracle is deterministic for `functional_pass_rate` but inherently lossy for `tokens_used / wallclock_seconds / agent_steps_total` (capture-at-generation-time: Anthropic temperature, sandbox CPU contention, npm-registry drift). The proposal's "§9 numbers are back-filled retroactively" line must be sharpened.
- **Spike caveat 1 — G5 has zero discriminative power on reference_impl** (no app-bundled tests to break). Mechanism phases get a *de facto* 4-gate (not 5-gate) no-regression check on the current target. Flagged in §8; does not invalidate parallel-tracks because the other four gates carry the load, but it weakens the SHIPPED-eligibility prose by ~20% and is worth disclosing to R2.
- **Spike caveat 2 — G1 (LLM-call-based gate) was skipped per cost directive.** ~1/6 of the lightweight-gate surface is untested. If G1 turns out to depend on the validated oracle, the parallelization argument weakens. Mitigation: hold G1's status open in §8 and re-spike G1 alone before any mechanism phase ships under the lightweight gate.

**Honest savings re-estimate:** ~10–12 days net, not the proposal's original 3–4 weeks. The sub-estimates (~2d §10 inert plumbing + ~3–5d back-fill cost + ~1–2d 3-4-parallel-branch integration overhead) are order-of-magnitude correct but eyeballed, not rigorously timed — R2 may revise after scoping the §10 inert plumbing PR.

**§10.5 numbering collision (R2 housekeeping):** the plan doc already uses §10.5 for "The exit criterion" (line 1853). The brief proposes a §10.5 "inert flag scaffolding" subsection — R2 will need to renumber to **§10.6** or carve it as **Phase 0.3** instead. The implementer prefers Phase 0.3 (makes the dependency-order commitment explicit in the phase list, not buried in §10).

The recommendation is **accept the parallel-tracks proposal with both holes patched** as additional prose edits, **with the spike result (§8 below) attached as evidence that the lightweight gate is operational** and the two caveats (G5 dormant on this target, G1 untested) explicitly carried into R2's PR text.

---

## 2. Adversarial-Confirmed Dependency Classes

These findings are quoted from M1 / M2 of the prior workflow (`/tmp/claude-1052/-data-common-haibotong/a5ccb289-a8c1-4e67-ab1b-1b0dfec42e5f/tasks/wa61a26lv.output`, sections `result.maps[0].findings` and `result.maps[1].findings`).

### Phase 1 — ASSUMED-not-HARD on the oracle

- Phase 1 is a lint guard on `schema_hub.register_table` rejecting writes from `agent != \"backend\"` (M1, §5:1136–1145). Acceptance gate is AST/lint + 1-sample end-to-end smoke + concurrent `claim_task` test + hub-tool drift consistency (M1, §5:1153–1158). **None of these require oracle, baseline (A), or classifier.**
- Plan's own honest framing explicitly predicts FLAT north-star delta (M1, §5:1162–1169: "Phase 1's value = 'the database-drift class of bug becomes structurally impossible' … North-star metrics (§9) for Phase 1 are expected to be flat").

### Phase 2 — ASSUMED-not-HARD on the oracle

- Phase 2 mechanism = EventHub handshake + circuit breaker (`MAX_NEGOTIATION_STEPS = 5`) + fallback path + trust-boundary wrapper (M1, §5:1183–1200). Four of five acceptance gates are deterministic mock-driven unit tests (M1, §5:1217–1234); only the 15-run N-run E2E uses real generation, and the metric is plain pass/fail of the contract flow.
- Plan's own honest framing: "delta is expected flat or slightly negative (more coordination overhead). Quality payoff lands in Phase 3." (M1, §5:1237–1240).

### Phase 2.5 — ASSUMED-not-HARD on the oracle

- Phase 2.5 = audit doc + RunHub probe field schema extension + SSIM module (M1, §5:1257–1281). Verifiable by reading probe records + an SSIM unit test. **The oracle is a CONSUMER of probe evidence in Phase 3, not a prerequisite for building probes.**
- Plan's own honest framing: "plumbing, no user-visible quality change. §9 north-star delta expected flat" (M1, §5:1300–1302).

### The HARD-looking sentences are reporting/process gates, not technical prerequisites

- **§9.4:1745–1746** "Mandatory deliverable BEFORE Phase 0.1 starts: (A) — the 90-cell absolute baseline. Without it, the refactor cannot CLAIM improvement." → wording is "cannot CLAIM improvement", a reporting gate.
- **§9.5:1762** "No phase reports 'complete' until both (A) and (B) numbers are in the doc." → "complete" is a documentation state, not a code state.
- **§9.1.5:1674–1676** "an oracle that has not passed both validation runs CANNOT be used for north-star metrics" → genuinely HARD for §9 metric CLAIMS, but the scope is the reporting step, not the implementation step.
- **§6:1547–1554** 12-cell north-star template REQUIRED for SHIPPED on every phase → enforces process-level oracle dependency; splittable by phase class.

The plan ALREADY uses this scoping pattern once: §5:1049–1053 scopes the §9.6 statistics rewrite to "before any quality phase ships" — direct precedent for scoping (A), (B), and §9.1.5 the same way.

---

## 3. Six Prose-Edit Candidates (the R2 ask, pre-drafted)

These are verbatim from `result.proposal.dependency_softening_diffs` in the workflow output, with Edit 3 carrying the adversarial Hole-2 carve-out language. R2 should land these as a single PR against `docs/progressive_elaboration_refactor.md`.

### Edit 1 — §9.5 closing rule (`docs/progressive_elaboration_refactor.md:1762`)

**Current text:**
> **No phase reports "complete" until both (A) and (B) numbers are in the doc**.

**Proposed text:**
> **No QUALITY phase (Phase 3, Phase 4) reports "complete" until both (A) and (B) numbers are in the doc.** Mechanism phases (Phase 1, 2, 2.5, 3.5) report complete on their mechanism gates (AST/lint, handshake circuit breaker, probe-field schema) plus the lightweight no-regression gate defined under §9.5 below; their §9 numbers are back-filled retroactively once the validated independent oracle (§9.1.5) ships.

**Rationale:** This is the single most-blocking sentence in the doc. As written it gates every phase — including the already-SHIPPED Phase 0.2 — on a validated oracle that does not yet exist. The plan's own §5:1162–1169 (Phase 1 flat-expected), §5:1239 (Phase 2 flat-or-negative), §5:1300–1302 (Phase 2.5 plumbing) already concede mechanism phases have no quality story to report.

### Edit 2 — §9.4 Mandatory deliverable (`docs/progressive_elaboration_refactor.md:1745-1746`)

**Current text:**
> **Mandatory deliverable BEFORE Phase 0.1 starts**: (A) — the 90-cell absolute baseline. Without it, the refactor cannot claim improvement.

**Proposed text:**
> **Mandatory deliverable BEFORE any quality-phase SHIPPED claim**: (A) — the 90-cell absolute baseline. Without it, the refactor cannot CLAIM improvement (mechanism phases that ship on mechanism gates do not make improvement claims and are not blocked). Full 3-spec oracle build is estimated at ~15 days (6.5d simple_blog pilot per §5:1045–1048, then ~4d simple_ecommerce + ~4.5d twitter_clone). Baseline (A) is one-shot, frozen, runnable in an isolated worktree at SHA `9ba65c35` (§9.4:1707–1721) and therefore parallelizable with mechanism-phase development.

**Rationale:** Phase 0.1 has already SHIPPED without (A), so the literal text is self-contradictory. Rewriting to "BEFORE any quality-phase SHIPPED claim" aligns the gate with what the baseline is actually FOR. The explicit ~15-day total-effort estimate makes the parallelization argument concrete — that figure does NOT appear verbatim in the doc today, only the ~6.5d pilot estimate.

### Edit 3 — §9.5 mechanism acceptance criterion (`docs/progressive_elaboration_refactor.md:1756`)

**Current text:**
> Mechanism phases (Phase 1, 2, 2.5, 3.5): delta on `functional_pass_rate` ≥ −5pp (no significant regression). Phase value = mechanism shipped, not quality.

**Proposed text:**
> Mechanism phases (Phase 1, 2, 2.5, 3.5): delta on `functional_pass_rate` ≥ −5pp (no significant regression). Phase value = mechanism shipped, not quality. **When the validated independent oracle (§9.1.5) is not yet available, the ≥−5pp criterion is measured by the lightweight no-regression gate**: against a pinned simple_blog fixture, generated app (a) builds with `docker compose up --build --wait`, (b) `/health` returns 2xx within 10s of healthy, (c) any agent-shipped test suite passes (skip-if-absent), (d) no Dockerfile classic-builder lint violation, (e) PROJECT_STRUCTURE-required files all present. Full `functional_pass_rate` numbers are back-filled in the phase's SHIPPED note once the oracle validates per §9.1.5. Wall-clock budget: ~10 min per gate run. **Perf-shaped metrics (`tokens_used`, `wallclock_seconds`, `agent_steps_total`) are marked N/A-RETRO in back-filled phase tables — they are capture-at-generation-time and cannot be reconstructed weeks later (see Hole 2 below).**

**Rationale:** The criterion the doc already sets is non-regression, not improvement — but never defines how to measure non-regression without the oracle. Adding the lightweight gate definition (G2–G6 from M3) makes the deferral operational. The trailing perf-N/A-RETRO clause patches the adversarial-identified Hole 2.

**Spike-grounded caveat (NEW, after spike):** clauses (a) (G4), (b) (G6), (d) (G3), (e) (G2) are spike-validated with sharp green/red discrimination. Clause (c) (G5 own-tests pass-if-present) is dormant on the current reference_impl because reference_impl ships no app tests — mechanism phases that change only generation logic without adding agent-shipped tests get no G5 signal. R2 should decide whether to (i) keep clause (c) and accept the de-facto 4-gate floor, or (ii) add a "must include at least one agent-emitted test" requirement to the mechanism-phase template so G5 becomes a live gate. Implementer recommends (i) — own-tests are a defense-in-depth signal, not the primary gate.

### Edit 4 — §6 submission template (`docs/progressive_elaboration_refactor.md:1547-1554`)

**Current text:**
> ### North-star delta (per §9, REQUIRED for SHIPPED status)
> | Spec | Metric | Baseline (mean ± sd) | This phase (mean ± sd) | Δ | Sig (p<0.1)? |
> ... (12 cells: 3 specs × 4 quantitative metrics)
> For mechanism phases (1, 2, 2.5, 3.5): Δ must be ≥ −5pp on functional_pass_rate. For quality phases (3, 4): Δ must be ≥ +5pp on ≥2 of 3 specs with p<0.1.

**Proposed text:**
> ### North-star delta (per §9)
> **For QUALITY phases (3, 4) — REQUIRED for SHIPPED status:** 12-cell table (3 specs × 4 quantitative metrics), Δ must be ≥ +5pp on ≥2 of 3 specs with p<0.1, using a §9.1.5-validated oracle.
> **For MECHANISM phases (1, 2, 2.5, 3.5) — REQUIRED for SHIPPED status:** lightweight no-regression gate (see §9.5): pinned-fixture build + health + own-tests + Dockerfile-lint + file-tree pass; full 12-cell table is OPTIONAL at SHIPPED time and back-filled within 1 sprint of oracle validation (perf-shaped cells marked N/A-RETRO per Hole 2).

**Rationale:** Splitting the template by phase class removes the strongest process-level enforcement of the oracle-as-blocker pattern. Mechanism phases get a SHIPPED-eligible gate they can run today (~10 min); quality phases keep the full statistical rigor.

### Edit 5 — §7 Strictly sequential (`docs/progressive_elaboration_refactor.md:1593`)

**Current text:**
> **Numeric**. Phases are strictly sequential (each subsumes lower; story gate requires backend-owns-DB). Per-feature multiplies test/A-B matrix to 2^N for zero benefit. Rollback = "lower the number".

**Proposed text:**
> **Numeric**. Phases are strictly sequential AT RUNTIME (each `ELABORATION_REFACTOR_PHASE` value subsumes all lower behaviors; story gate requires backend-owns-DB to be active). Per-feature multiplies test/A-B matrix to 2^N for zero benefit. Rollback = "lower the number". **Sequential runtime does NOT imply sequential development**: Phase 1 mechanism work, Phase 2 mechanism work, Phase 2.5 plumbing, and oracle/§9.1.5 validation can proceed in parallel branches, merged in numeric order once each independent acceptance gate passes. The §10.2 flag-fork coexistence guarantee ensures parallel branches do not cross-contaminate baseline runs — **PROVIDED the §10 flag scaffolding has actually landed in code (see new Phase 0.3 below); today the flag exists only in docs**.

**Rationale:** "Strictly sequential" is the strongest justification any reader would cite for serial development. Clarifying it as a runtime feature-flag invariant unblocks parallel work at the conceptual level. The trailing clause patches Hole 1 by making the §10 prerequisite explicit at the moment the reader is being told parallel is safe.

### Edit 6 — §5 next-steps precedent citation (`docs/progressive_elaboration_refactor.md:1049-1053`)

**Current text:**
> 3. **Phase 3/4 prerequisite (R2 35-finding §B1)**: rewrite §9.6 statistics — the three incompatible ship-gates (paired bootstrap with no pairing structure / IID assumption violation / stale §6 p<0.1 template) are the load-bearing wall for "did the refactor make apps better". Must close before any quality phase ships.

**Proposed text:**
> 3. **Phase 3/4 prerequisite (R2 35-finding §B1)**: rewrite §9.6 statistics — the three incompatible ship-gates (paired bootstrap with no pairing structure / IID assumption violation / stale §6 p<0.1 template) are the load-bearing wall for "did the refactor make apps better". Must close before any quality phase ships. **Pattern note**: the §9.6 rewrite is scoped to quality phases only — mechanism phases (Phase 1, 2, 2.5, 3.5) do not depend on it. The same scoping pattern applies to the §9.1.5 oracle-validation rule, the §9.4 (A)-baseline rule, and the §9.5 (A)+(B) reporting rule: HARD gates for quality phases, lightweight gates for mechanism phases.

**Rationale:** The doc ALREADY scopes one major prerequisite (§9.6 statistics rewrite) to quality-phases-only. Citing this as the pattern justifies generalizing the same scoping to (A), (B), and §9.1.5 — uses the doc's own consistency as the softening argument rather than introducing a new principle.

---

## 4. Hole 1 — §10 Flag Must Land FIRST

### Adversarial PoC

```
$ grep -rn ELABORATION_REFACTOR_PHASE /data/common/haibotong/env-gen/agent/env_generator/
(zero matches)

$ grep -rn ELABORATION_REFACTOR_PHASE /data/common/haibotong/env-gen/docs/
docs/progressive_elaboration_refactor.md:<§10.1-10.4 only>
```

The flag is **vapor in code**. It exists exclusively as design prose in §10.1–10.4 of the plan doc.

### Why this breaks the parallel-tracks safety argument

R2's proposal cites the §10 flag-fork coexistence guarantee 4× as the reason parallel branches don't cross-contaminate baseline runs. The argument is structurally: "Phase 1's lint lands behind `if phase >= 1`, so when baseline (A) re-runs with no flag set it still works."

That argument **only holds if `if phase >= 1` actually exists as a dispatch point in the code path**. Today it doesn't. The moment Phase 1's lint guard on `schema_hub.register_table` lands, it is a **HARD REPLACEMENT** — every pre-refactor design-agent write is rejected. Re-running baseline (A) at SHA `9ba65c35` from the new tree breaks immediately because the baseline source itself emits design-agent writes that the new lint forbids.

### Required prerequisite

Add a **new §10 subsection** that names this as a HARD prerequisite. **NUMBERING NOTE:** §10.5 in the plan doc is already "The exit criterion" (line 1853). The brief originally proposed §10.5; R2 must either renumber to **§10.6** or — preferred — carve it as **Phase 0.3** so the dependency-order commitment is explicit in the phase list, not buried as a §10 subsection.

> **Phase 0.3 (NEW) — Inert flag scaffolding (carved out of §10)**
>
> Before any phase-flag-gated mechanism code lands, the dispatch points must exist as inert plumbing. Concretely: introduce `get_phase()` returning the integer value of `ELABORATION_REFACTOR_PHASE` (default `0`), and at every location §10.2 names as a "behavior fork point" insert an `if get_phase() >= N: <new path> else: <old path>` gate where the new branch does NOTHING (raises NotImplementedError or routes to the old path). Acceptance: all existing tests pass with the flag unset; setting the flag to any value still routes to the old path; baseline (A) checkout still runs cleanly because nothing in `9ba65c35`'s ancestor tree calls `get_phase()`. **This is the FIRST gate that must land — without it Edit 5's "parallel branches don't cross-contaminate" claim is false.**

R2's PR should add this subsection alongside Edits 1–6, **and add a one-line Phase 0.3 entry to the phase list in §1/§2 of the plan doc** so the ordering is visible to any reader.

---

## 5. Hole 2 — Perf-Shaped Metrics N/A-RETRO Carve-out

### Adversarial finding

Inspecting `classifier.py:172-209` (Verdict dataclass) and `test_itt_recompute.py:36-48`:

- The `Verdict` schema captures `run_id, spec_id, arm, phase_reached, outcome, classifier_spec_sha` (plus a few non-perf signal fields).
- It does **NOT** capture a source-tree SHA. `arm` is a free string (`ab_old | ab_new | …`), so identifying which historical phase commit produced a verdict requires out-of-band bookkeeping.
- It does **NOT** capture perf telemetry. `tokens_used`, `wallclock_seconds`, `agent_steps_total` from §9.3 are inherently capture-at-generation-time.

### Why back-fill is lossy

The §10.2 / §10.3 A-B harness was designed to run **at-phase-time** against a live flag toggle, not weeks later against a snapshotted phase commit. Re-running generation against a frozen historical phase tree gives a **non-deterministic** result because:

- LLM temperature non-determinism (Anthropic sampling).
- Sandbox CPU contention and network RTT shift `wallclock_seconds`.
- npm-registry drift since the snapshot can change `agent_steps_total`.
- §9.1.5:1670–1672 explicitly says reference_impl dirs are pinned and "any change shifts the calibration of every later A-B number" — implying calibration is meant to be locked once and applied forward, not retro-applied to a series of frozen historic phase commits.

`functional_pass_rate` back-fills cleanly (deterministic given the same generated tree applied to a validated oracle). The perf-shaped cells do not.

### Required prose change

Edit 3 above already carries the required carve-out language. Specifically the trailing sentence:

> Perf-shaped metrics (`tokens_used`, `wallclock_seconds`, `agent_steps_total`) are marked N/A-RETRO in back-filled phase tables — they are capture-at-generation-time and cannot be reconstructed weeks later.

R2 should confirm that wording lands inside the Edit 3 patch.

---

## 6. Honest Savings Re-estimate

| Estimate | Source | Net wall-clock savings |
|---|---|---|
| Synthesizer original | `result.proposal.distance_to_phase_1_serial_vs_parallel` | ~3–4 weeks calendar before Phase 1 begins |
| **Adversarial-corrected** | This brief | **~10–12 days net** |

Why the gap:

- **§10 flag scaffolding** adds ~2 days of inert-plumbing work **before** any parallel branch can safely start.
- **Back-fill cost** (re-running phase generation against the validated oracle and reconciling Verdicts) consumes ~3–5 days that the original proposal counted as savings.
- **Operational complexity** of running 3–4 parallel branches with merge ordering, flag-state hygiene, and cross-branch lint discipline adds ~1–2 days of integration work.

**Caveat (adversarial-disclosed):** these sub-estimates are eyeballed, not derived from timing data. R2 may legitimately revise: (i) §10 inert plumbing could be smaller than 2d if scoped to just `get_phase()` + a few call sites, (ii) back-fill cost depends on whether the team accepts N/A-RETRO for perf cells (this brief recommends accepting it; see §5), (iii) the integration overhead figure is order-of-magnitude only. The 10–12d figure is the implementer's honest read; the right move is to scope the §10 inert-plumbing PR first and replace the 2d estimate with an actual ticket size.

Still meaningful. But the user should hear the real number before approving the pivot — the saved ~2 weeks of calendar must be weighed against the operational complexity of 3–4 parallel branches with a still-unbuilt §10 flag.

---

## 7. R2 Next-Step Ask

R2 already offered (round 14 close):

> 要不要我把这个解法,对着 §9.4/§9.5 的依赖具体化成一个改动建议

**The implementer's answer is YES.** Specifically the ask is:

1. **Land Edits 1–6 (§3 above) as one PR** against `docs/progressive_elaboration_refactor.md`. Each edit has verbatim current_text and proposed_text — they are ready to apply.
2. **Patch Hole 1** by carving out a new **Phase 0.3 — Inert flag scaffolding** (§4 above) as part of the same PR, explicitly naming it as a HARD prerequisite that must ship before any phase-flag-gated mechanism code. (Note: do NOT use §10.5 — that slot is already taken by "The exit criterion" at plan doc line 1853. Use §10.6 if you'd rather keep it inside §10, but Phase 0.3 is preferred.)
3. **Patch Hole 2** by ensuring Edit 3 carries the perf-shaped-metrics N/A-RETRO carve-out language verbatim.
4. **Attach the §8 spike result** (below) as evidence in the PR description that the lightweight gate is operational on G2/G3/G4/G6 with the two disclosed caveats (G5 dormant on reference_impl; G1 untested per cost directive).
5. **Optional but recommended:** before merging Edit 3, re-spike G1 alone (the LLM-call-based gate) to close the untested-1/6 gap. If G1 turns out to depend on the validated oracle, narrow Edit 3 clause (c)→(e) and drop G1 from the mechanism-phase gate definition.

If R2 ships this PR, the parallel-tracks pivot is unblocked. If any reviewer finds a HARD dependency we missed (a specific mechanism file that imports oracle output — adversarial Attack A's failed-but-instructive angle), revert that specific phase to the serial path; the other two can still parallelize.

---

## 8. Spike Result — Lightweight Gate Ground-Truthing

**Spike verdict:** `gate_works_with_caveats`. Total wall-clock 275 seconds (well under the 25-minute budget). G2/G3/G4/G6 all green-pass and red-fail with sharp discrimination. G5 honestly inapplicable on this target (no app-bundled tests in reference_impl). G1 skipped per LLM-cost directive. Real-bug test on `demos/jira-web` fired the predicted gate (G4 during `RUN npm run build`) with the exact round-11 `ERR_MODULE_NOT_FOUND` error.

### 8.1 Per-gate results

#### G2 — PROJECT_STRUCTURE file-tree assertion

- **Green target:** `/tmp/spike_green` (copy of `reference_impl`)
- **Green command:** `python3 /tmp/spike_g2.py /tmp/spike_green`
- **Green outcome:** **PASS** — `G2 PASS: all 4 required files present under /tmp/spike_green` (exit=0)
- **Planted red:** `/tmp/spike_r_g2` (deleted `backend/main.py` from /tmp copy)
- **Red command:** `python3 /tmp/spike_g2.py /tmp/spike_r_g2`
- **Red outcome:** **FAIL** — `G2 FAIL: PROJECT_STRUCTURE-required files missing: /tmp/spike_r_g2/backend/main.py` (exit=1)

#### G3 — Dockerfile classic-builder lint (`enforce_dockerfile_classic_compat`)

- **Green target:** `/tmp/spike_green/backend/Dockerfile`
- **Green command:** `python3 /tmp/spike_g3.py /tmp/spike_green/backend/Dockerfile`
- **Green outcome:** **PASS** — `G3 PASS: /tmp/spike_green/backend/Dockerfile is classic-builder compatible` (exit=0)
- **Planted red:** `/tmp/spike_r_g3/backend/Dockerfile` — replaced `RUN pip install --no-cache-dir -r requirements.txt` with `RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt` on line 6
- **Red command:** `python3 /tmp/spike_g3.py /tmp/spike_r_g3/backend/Dockerfile`
- **Red outcome:** **FAIL** — `G3 FAIL: Dockerfile rejected by classic-builder compatibility lint: /tmp/spike_r_g3/backend/Dockerfile:6: BuildKit-only --mount=type=... on RUN/COPY (rejected: classic builder cannot execute this).` (exit=1) — **gate names the offending line (line 6) as the contract advertises.**

#### G4 — `docker compose up --build` with `--wait`

- **Green target:** `/tmp/spike_green` (RUNNER_HOST_PORT=40767, `-p spike_green`)
- **Green command:** `cd /tmp/spike_green && RUNNER_HOST_PORT=40767 DOCKER_BUILDKIT=0 docker compose -p spike_green up --build --wait --wait-timeout 180 -d`
- **Green outcome:** **PASS** — `Container spike_green-backend-1  Healthy` (exit=0)
- **Planted red:** `/tmp/spike_r_g6` (`/health` raises `HTTPException(500)`), RUNNER_HOST_PORT=58185, `-p spike_r_g6` — also exercises G4 because broken `/health` causes container to never become healthy under `--wait`
- **Red command:** `cd /tmp/spike_r_g6 && RUNNER_HOST_PORT=58185 DOCKER_BUILDKIT=0 docker compose -p spike_r_g6 up --build --wait --wait-timeout 30 -d`
- **Red outcome:** **FAIL** — `container spike_r_g6-backend-1 is unhealthy` (real exit code: 1)
- **Caveat (adversarial-noted):** G4 is a broad-band signal that fires on any build/healthcheck failure including environment causes (registry hiccups, daemon flakes). The spike shows G4 *catches* the planted /health regression with sharp discrimination, but does not demonstrate G4 *isolates* the regression from environmental confounds. For a no-regression gate, favoring recall over precision is the correct trade-off; flag this in the mechanism-phase ship checklist so reviewers know to retry G4 on transient red before declaring regression.

#### G5 — app's own tests (pass-if-present)

- **Green target:** `/tmp/spike_green/backend` (no `test_*.py`, no `pytest.ini`, no `tests/` dir)
- **Green command:** `if [ -d backend/tests ] || [ -f backend/pytest.ini ] || find backend -name 'test_*.py' -print -quit | grep -q .; then echo present; else echo absent; fi`
- **Green outcome:** **INAPPLICABLE** — `G5 PASS-IF-PRESENT: no app tests in reference_impl, skipping — gate trivially passes by construction, providing no discrimination on this target`
- **Planted red:** n/a (no app-tests to break)
- **Red outcome:** **INAPPLICABLE** — `Could not plant a meaningful R-G5: reference_impl has no app-bundled tests to break. The pass-if-present semantics means G5 has zero discriminative power on this target.`
- **Adversarial-noted impact:** Mechanism phases get a *de facto* 4-gate (not 5-gate) no-regression check on the current reference_impl, weakening the SHIPPED-eligibility prose by ~20%. Not a gate failure per se — but worth flagging for R2's PR text. See §3 Edit 3 spike-grounded caveat.

#### G6 — `/health` smoke probe (40 × 0.25s retry)

- **Green target:** `http://localhost:40767/health` (spike_green backend, healthy)
- **Green command:** `/tmp/spike_g6.sh http://localhost:40767/health`
- **Green outcome:** **PASS** — `G6 PASS: http://localhost:40767/health responded 2xx on attempt 1; body: {"status":"ok"}` (exit=0)
- **Planted red:** `http://localhost:58185/health` (spike_r_g6 backend with `/health -> HTTPException 500`) — patched `main.py` `/health` route from `return {"status":"ok"}` to `raise HTTPException(status_code=500, detail="intentionally broken")`
- **Red command:** `/tmp/spike_g6.sh http://localhost:58185/health`
- **Red outcome:** **FAIL** — `G6 FAIL: http://localhost:58185/health did not return 2xx after 40 attempts; last stderr: curl: (22) The requested URL returned error: 500 Internal Server Error` (exit=1) — **discrimination is sharp: green hits 2xx on attempt 1, red exhausts all 40 retries on 500.**

#### G1 — SKIPPED

- **Status:** Skipped per LLM-cost-avoidance directive.
- **Risk:** ~1/6 of the lightweight-gate surface is untested. If G1 turns out to require LLM calls with the validated oracle as a sub-dependency, the parallelization argument weakens.
- **Mitigation:** §7 step 5 — re-spike G1 alone before any mechanism phase ships under the lightweight gate. If G1 depends on the oracle, drop it from Edit 3's mechanism-phase gate definition and accept the 4-gate floor.

### 8.2 Real-bug test on `demos/jira-web`

- **Target:** `/data/common/haibotong/env-gen/demos/jira-web` (copied to `/tmp/spike_jira` with ports remapped to ephemeral 49099/43259/35261 and container names prefixed `spike-jira-*`)
- **Which gates fired:** **G4**
- **Gate caught real bug:** **YES**
- **Observed behavior:** G4 (`docker compose -p spike_jira up --build --wait --wait-timeout 180 -d`) exited 1 during the frontend image build at Step 15/21 `RUN npm run build`. Vite CLI shim failed with:
  ```
  Error [ERR_MODULE_NOT_FOUND]: Cannot find module '/app/node_modules/dist/node/cli.js'
  imported from /app/node_modules/.bin/vite
  ```
  — exactly the round-11 reported failure. The build never produced a frontend image, so no service ever started; G6 was not reached. **This is the correct gate**: G4 covers `up --build` end-to-end including image construction, and the bug lives in the build step. The earliest-fault short-circuit means G6 would only have been needed if the build had succeeded but the running app then refused `/health`.

### 8.3 Spike hygiene

- No state leakage. All spike containers/networks/images namespaced under `spike_*` projects. All torn down with `down -v`. `docker ps -a` shows no leftover `spike_*` containers after spike completion.
- Green tracked tree under `/data/common/haibotong/env-gen/agent/tests/north_star/simple_blog/reference_impl/` was **never modified** — only `/tmp` copies were planted with regressions.
- Spike scripts retained at `/tmp/spike_g2.py`, `/tmp/spike_g3.py`, `/tmp/spike_g6.sh` for reproducibility.
- Total wall-clock: **275 seconds** (well under the 25-min budget).

### 8.4 Spike conclusion

**Pass with caveats.** The lightweight gate is operational on G2/G3/G4/G6 with sharp green/red discrimination on planted regressions and one real demo bug. R2 may merge Edits 1–6 + Phase 0.3 with two caveats disclosed in the PR text:

1. G5 (app's own tests) is dormant on reference_impl — mechanism phases get a 4-gate floor today.
2. G1 (LLM-call-based gate) is untested — re-spike before any mechanism phase ships under Edit 3.

If R2 disagrees with accepting either caveat, the fallback is to drop G5 and/or G1 from the Edit 3 mechanism-phase gate definition. The remaining gates carry the load.

---

## Appendix — Source pointers

- Prior workflow output (full JSON, 416 lines): `/tmp/claude-1052/-data-common-haibotong/a5ccb289-a8c1-4e67-ab1b-1b0dfec42e5f/tasks/wa61a26lv.output`
  - `result.proposal.dependency_softening_diffs` — the 6 prose edits (verbatim source for §3).
  - `result.proposal.parallelization_safety` — ASSUMED-not-HARD classification for Phases 1/2/2.5.
  - `result.proposal.lightweight_gate_proposal.criterion_list` — G1–G6 definitions used in Edit 3 and §8.
  - `result.adversarial.challenges` — five attacks (A–E), of which A and C identified the two holes addressed in §4 and §5.
  - `result.adversarial.user_question_revised` — the adversarial-corrected recommendation summary.
- Plan doc under edit: `/data/common/haibotong/env-gen/docs/progressive_elaboration_refactor.md`.
- Classifier evidence for Hole 2: `/data/common/haibotong/env-gen/agent/.../classifier.py:172-209` (Verdict dataclass), `test_itt_recompute.py:36-48`.
- §10 flag-vapor evidence for Hole 1: `grep -rn ELABORATION_REFACTOR_PHASE /data/common/haibotong/env-gen/agent/env_generator/` → 0 matches.
- §10.5 collision: `docs/progressive_elaboration_refactor.md:1853` already titled "The exit criterion" — Phase 0.3 carve-out preferred over §10.6.
- Spike scripts: `/tmp/spike_g2.py`, `/tmp/spike_g3.py`, `/tmp/spike_g6.sh`.
- Spike targets: `/tmp/spike_green` (G2/G3/G4/G6 green), `/tmp/spike_r_g2` (G2 red), `/tmp/spike_r_g3` (G3 red), `/tmp/spike_r_g6` (G4+G6 red), `/tmp/spike_jira` (real-bug test).
