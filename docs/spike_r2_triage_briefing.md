# R2 Triage Briefing — Cross-Stack Calibration Spike Result (round-10 input)

> **Status**: spike artifacts built per round-9 corrected scope; harness ran; **5/5 docker-fixture failures**; **0 oracle-layer signal collected**. Surfacing raw to R2 per round-9 separation-of-duties (builder-≠-grader). No debugging, no auto-fixes, no PASS/FAIL grading by builder.
>
> **R2 questions to verdict** (numbered for response): see §6.

---

## 1. What was built (round-9 corrected scope)

Per R1+R2 round-9 convergence, the spike scope is:

- **Reference impl**: hand-written FastAPI + SQLite + httpOnly cookie + bare routes simple_blog
- **Target impl**: hand-written Bearer/Express + better-sqlite3 + JWT + `/api/`-prefixed simple_blog (cross-stack proof)
- **target_impl_broken**: target_impl with one subtle break — auth middleware lets unauth in as `email: "anonymous"` instead of returning 401 (matches R2 round-9's named subtle case)
- **Oracle**: 5 per-flow test files + conftest, uses `tests/north_star/_conventions.py` helpers only
- **Runner**: docker-compose orchestration with health-probe, port-parse, teardown, fixture-vs-oracle-failure separation
- **4-arm calibration harness**: subprocess-isolated pytest invocation per arm, JUnit XML parse, `##SPIKE_RESULT##` emission

All 4 build agents ran INDEPENDENTLY (separate workflow agents, no cross-context) to avoid oracle-tunes-to-target trap.

Build agents intentionally diverged on convention:
- ref: `{"posts": [...]}` envelope, bare routes, cookie
- target: `{"items": [...]}` envelope, `/api/` routes, Bearer

This forces the oracle through `_conventions.py` for every dimension R2 named.

## 2. Raw `##SPIKE_RESULT##` JSON (verbatim from pytest -s output)

```json
{
  "arm_1a_green_on_reference": {
    "fixture_failure": "docker compose up failed:  Service backend  Building\nfailed to solve: executor failed running [/bin/sh -c pip install --no-cache-dir -r requirements.txt]: exit code: 2\n",
    "flows_failed": 0,
    "flows_passed": 0,
    "verdict": "RAW_DATA"
  },
  "arm_1b_green_on_target": {
    "fixture_failure": "docker compose up failed:  Service backend  Building\nfailed to solve: executor failed running [/bin/sh -c apt-get update     && apt-get install -y --no-install-recommends python3 make g++ ca-certificates     && rm -rf /var/lib/apt/lists/*]: exit code: 100\n",
    "flows_failed": 0,
    "flows_passed": 0,
    "verdict": "RAW_DATA"
  },
  "arm_2_catches_broken": {
    "actual_failed_flows": [],
    "expected_failed_flows": ["test_unauthenticated_post_creation_is_rejected"],
    "fixture_failure": "docker compose up failed: ... failed to solve: executor failed running [/bin/sh -c npm install]: exit code: 134\n",
    "verdict": "RAW_DATA"
  },
  "arm_3_airbnb_auth_helper": {
    "authenticated": null,
    "error_msg": null,
    "errored": false,
    "note": "airbnb fixture failure: ... Container docker-database-1  Error\ndependency failed to start: container docker-database-1 exited (3)",
    "verdict": "RAW_DATA"
  },
  "arm_4_fixture_reliability": {
    "attempts": 5,
    "successes": 0,
    "failure_reasons": ["docker compose up failed: ... apt-get update ... exit code: 100\n", "...×5 identical..."]
  }
}
```

Pytest summary: **2 passed, 4 skipped in 64.75s** (the 2 passing are `test_arm_4_fixture_reliability` which is RAW_DATA by design + `test_zzz_emit_spike_result` which is the JSON emitter)

## 3. Per-arm Dockerfile content (so R2 can judge env vs content)

### Arm 1a — reference_impl/backend/Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py ./
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
`requirements.txt`:
```
fastapi==0.110.*
uvicorn[standard]==0.27.*
pydantic[email]==2.6.*
```
**Failure**: `pip install --no-cache-dir -r requirements.txt` exited **2**.

### Arm 1b — target_impl/backend/Dockerfile
```dockerfile
FROM node:20-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY server.js ./
EXPOSE 3000
CMD ["node", "server.js"]
```
**Failure**: `apt-get update && apt-get install ...` exited **100**. (Build did NOT reach the `npm install` line.)

### Arm 2 — target_impl_broken/backend/Dockerfile
```dockerfile
FROM node:20-slim
WORKDIR /app
COPY package.json ./
RUN npm install
COPY server.js ./
EXPOSE 3000
CMD ["node", "server.js"]
```
Note: this Dockerfile is **missing the apt-get toolchain step** that target_impl has. Same `package.json` (express + better-sqlite3 + jsonwebtoken). better-sqlite3 needs native-build toolchain.

**Failure**: `npm install` exited **134** (SIGABRT). Plausibly node-gyp crashing without python3/g++ in PATH — but could also be OOM.

### Arm 3 — demos/airbnb (existing, NOT built by spike)
Built all images fine (database, backend, frontend), then:
```
 Container docker-database-1  Starting
 Container docker-database-1  Started
 Container docker-database-1  Waiting
 Container docker-database-1  Error
dependency failed to start: container docker-database-1 exited (3)
```
postgres container exited code 3 at startup. Unrelated to arms 1a/1b/2.

## 4. Fixture-failure pattern analysis (UPDATED 2026-05-30 after probe-workflow `wyqzbwmt3` — 7-agent diagnostic with adversarial verify)

**EARLIER hypothesis (initial briefing) was largely WRONG.** A targeted probe workflow ran 5 parallel diagnostic agents (4 per-arm + host_env_baseline) and the actual root causes diverge from the exit-code-only reading. Key revisions:

| Arm | Initial hypothesis | **Probe-confirmed actual cause** | Classification |
|---|---|---|---|
| 1a | pip exit 2 = env or content (ambiguous) | **BuildKit sandbox pid/thread limit** — pip's `rich` progress bar calls `threading.Thread.start` → `RuntimeError: can't start new thread`. Same requirements.txt installs cleanly via `docker run python:3.11-slim`. Network was reaching PyPI when the abort happened. | **env (BuildKit)** |
| 1b | apt exit 100 = env, can't reach apt mirrors | **BuildKit apt Post-Invoke hook failure** — `Fetched 9357 kB in 1s` (download succeeded); failure is `APT::Update::Post-Invoke 'rm -f /var/cache/apt/archives/*.deb ... \|\| true'` returning error. Runtime `docker run --rm node:20-slim apt-get update && apt-get install ...` succeeds cleanly. | **env (BuildKit)** |
| 2 | npm exit 134 = content, missing apt-get toolchain step for better-sqlite3 native build | **❌ HYPOTHESIS REFUTED.** `cat target_impl_broken/backend/package.json` shows **only `express ^4.18.2`** — no native deps, no better-sqlite3. Byte-identical Dockerfile **builds successfully under classic builder** (`DOCKER_BUILDKIT=0`); BuildKit reproduces exit 134 with `Assertion failed: (0) == (uv_thread_create(...))`. The "missing toolchain" framing was wrong. | **env (BuildKit) + spike-framing error** |
| 3 | airbnb postgres exit 3 = env (volume corruption / missing env vars) | **Content bug in `homestay/app/database/init/02_seed.sql:73`** — `(DATE '2016-01-01' + ((row_number() OVER (ORDER BY u.email)) * 120))` has no `+(date,bigint)` operator in Postgres. `POSTGRES_USER/PASSWORD/DB` env vars all correctly set. Standalone `postgres:16` image works on host. | **content (fixture SQL)** |

**Dominant root cause**: Docker 20.10.8 + kernel 5.11.0-37 + custom `seccomp-allow-all.json` profile + cgroup v1 produces BuildKit-sandbox fork/exec/thread fragility. Three of four failures (1a/1b/2) are **the same BuildKit-on-aged-daemon issue surfacing through three different package managers**. The classic builder path works for all three.

**Host environment is otherwise healthy**:
- DNS resolves all three required hosts via systemd-resolved IPv6
- HTTPS reaches deb.debian.org / pypi.org / registry.npmjs.org with HTTP/2 200
- Runtime container network works (verified via `docker run`)
- 109G disk free, 66Gi memory available, 16 CPUs, ulimit -u=513767, threads-max=1027534 — host-level limits not exhausted

**Arm 2 framing was actively wrong**, not just incomplete. The spike scope asserted "missing toolchain causes native-compile failure"; package.json has no native deps. R2 must verdict whether the spike scope itself needs revision before any rebuild.

Arm 4 reliability = **0/5 deterministic** rules out flakiness. Build failures are reproducible.

## 4a. Diagnostic workflow artifacts (probe-workflow `wyqzbwmt3`)

- 7-agent workflow: 5 parallel diagnostic probes + 1 synthesizer + 1 adversarial verifier
- Synthesizer initial call: `mixed_some_each` (arms 1a/1b/3 inline_safe, arm_2 + baseline to R2)
- Adversarial agent **refuted 3 of 6 synthesizer claims** (arm_1b inline_safe, arm_3 inline_safe, overall_recommendation), medium-to-high confidence each
- Adversarial final answer (HIGH confidence): **route ALL arms to R2**; downgrade every "inline_safe=true" to "PROPOSED DIFF for R2 verdict"; R2 must see failed state + proposed fix + classification BEFORE any rebuild
- Specifically: arm_3's `INTERVAL '1 day'` proposal could shift fixture data semantics in ways the oracle measures — needs R2 review of before/after diff
- Specifically: arm_1b's apt.conf-suppression proposal is a Dockerfile patch that could mask future legitimate apt failures — fix-layer choice (Dockerfile vs host/builder) is R2's call

## 5. What this means for the calibration question

The spike was supposed to answer:
> "Does the oracle judge a Bearer/Express simple_blog 6/6 GREEN with the same fairness as the FastAPI/cookie simple_blog?"

**It did not get to ask that question.** Fixtures never came up. The cross-stack judgment is **unverified**. The pilot's anti-circularity gate is not yet satisfied.

Hidden A1 #2 (R2's env-failure exclusion bias) IS empirically active on this host — fixture infrastructure is unreliable to the point of "always-down". For the future pilot's `functional_pass_rate per spec` metric, env-failure cannot be silently excluded from the denominator.

## 6. R2 verdict questions (UPDATED — Q1/Q2 superseded by §4; Q3 refined; Q6 new)

**Q1 (REVISED)** — Given probe evidence that arms 1a/1b/2 are all **the same BuildKit-on-aged-daemon class** (not 3 distinct content bugs as originally framed), and host_env_baseline shows Docker 20.10.8 + kernel 5.11 + custom seccomp-allow-all: does R2 read this as a single env-class root cause needing one fixture-strategy fix, or as 3 separate env interactions each needing its own Dockerfile patch?

**Q2 (REVISED)** — Arm 2's spike framing ("missing apt-get toolchain causes native-compile failure") is **actively refuted** by probes — `package.json` has only `express`, no native deps; byte-identical Dockerfile builds fine under classic builder. Should the spike scope be revised before any rebuild? Specifically: (a) does target_impl_broken's package.json drift from target_impl (which DOES use better-sqlite3) make the catches-broken arm a different cross-stack test than originally specified? (b) should the arm be re-scoped to use the same dep set as target_impl plus the auth-bypass break?

**Q3 (REVISED)** — Refixture strategy. Now that env-vs-content is sharper, R2 verdict on which of:
  - **(a)** Switch all 3 backends to classic builder via `DOCKER_BUILDKIT=0 docker compose build` in runner.py — preserves all Dockerfile content unchanged; matches probes showing classic builder works for all 3
  - **(b)** Run apps directly via subprocess (no docker), runner spins uvicorn / node binary — bypasses BuildKit entirely; but loses the docker-compose orchestration the pilot will need
  - **(c)** Patch each Dockerfile with BuildKit-workarounds (`PIP_PROGRESS_BAR=off`, apt.conf Post-Invoke suppression) — content changes, R2 verdict per arm whether semantics are preserved
  - **(d)** Hold spike until host docker daemon upgraded (sysadmin escalation) — env triage off-builder

(The probes strongly favor **(a)** as the least-invasive fix that preserves all spike-design intent — it's not "tune until green", it's "use the builder the host supports".)

**Q4 — Acceptable signal threshold**: same as before. After re-run, what minimum is "good enough" to green-light pilot?

**Q5 — Builder identity for re-run**: same as before. Implementer session, or R1 cashes round-9 offer?

**Q6 (NEW — adversarial finding)** — Process change request. The adversarial verifier in `wyqzbwmt3` argued that the round-8 trap mitigation is structurally weak if builder fixes inline and then reports — that's still procedural trust. Adversarial proposes: **R2 sees the failed-state + the proposed fix + the classification BEFORE any rebuild**, not after. Concretely: this briefing is the failed-state; the proposed fixes in §5 (next section) are explicit DIFFs not yet applied; R2 approves a fix-set, then rebuild + re-run + post-fix briefing for verdict on the oracle signal.
  - Accept Q6? If yes, all proposed fixes stay as DIFFs in this briefing until R2 approves; only then rebuild.
  - Reject Q6? Then which subset of fixes can builder apply inline without R2 pre-approval (e.g., `DOCKER_BUILDKIT=0` env var is clearly content-neutral)?

## 5. PROPOSED DIFFS (not applied — awaiting R2 verdict per Q3 + Q6)

### Proposed fix A (recommended, content-neutral): switch runner.py to classic builder

In `tests/north_star/simple_blog/runner.py`, when invoking docker compose:

```python
# CURRENT (uses BuildKit by default on this docker version)
subprocess.run(["docker", "compose", "build"], cwd=app_dir, ...)

# PROPOSED
env = {**os.environ, "DOCKER_BUILDKIT": "0", "COMPOSE_DOCKER_CLI_BUILD": "0"}
subprocess.run(["docker", "compose", "build"], cwd=app_dir, env=env, ...)
```

**Probe evidence**: byte-identical Dockerfile builds successfully under classic builder for all 3 arms (`Successfully built ...` in probes 5 of arm_2, plus implied for 1a/1b which share the same BuildKit-only failure mode).

**Round-8 trap risk**: zero. No Dockerfile content changed. No package change. App behavior identical.

### Proposed fix B (arm 3 only): airbnb seed SQL type cast

File: `/data/common/haibotong/env-gen/demos/airbnb/homestay/app/database/init/02_seed.sql:73` (path inferred from container path `/docker-entrypoint-initdb.d/02_seed.sql` — needs R2 verification before edit).

```sql
-- CURRENT (line 73, fails with "operator does not exist: date + bigint")
(DATE '2016-01-01' + ((row_number() OVER (ORDER BY u.email)) * 120))

-- PROPOSED (option B1 — multiplied by INTERVAL '1 day', shifts to days-of-offset semantics)
(DATE '2016-01-01' + (((row_number() OVER (ORDER BY u.email)) * 120) * INTERVAL '1 day'))

-- ALTERNATIVE (option B2 — cast to integer, preserves date arithmetic in days)
(DATE '2016-01-01' + ((row_number() OVER (ORDER BY u.email)) * 120)::integer)
```

**Adversarial concern (refuted=true, medium confidence)**: B1 and B2 give the same numeric result when offset is 120 (days), but if downstream oracle assertions compare dates against fixed values, the choice between "joined_at = 2016-04-30" (120 days) vs other unit could matter. R2 verdict requested before either is applied. **Builder will NOT pick B1 vs B2 unilaterally.**

### NO proposed fix for arm 1a / arm 1b / arm 2

Per Q3 the recommended path (a) is "switch builder, not patch Dockerfile" — proposed fix A handles all three at once with zero content change. Patch-each-Dockerfile alternatives (`PIP_PROGRESS_BAR=off`, apt.conf override) are NOT proposed as defaults because they shift the round-8-trap risk back onto builder ("did the suppression hide some real failure?"). If R2 prefers Dockerfile patches over builder switch, builder will write the patches as additional PROPOSED DIFFS for R2 approval.

### Arm 2 framing decision (Q2 — NO fix proposed)

The spike scope assumed missing toolchain → native-compile failure. Probe refuted both halves. Builder will NOT silently change target_impl_broken's package.json to add better-sqlite3, even though it would "match target_impl's stack". That would be a spike-scope decision that needs R2 verdict per Q2.

## 7. Artifacts on disk (UNCOMMITTED — awaiting R2 verdict)

- `tests/north_star/simple_blog/reference_impl/` (167 LOC backend + Dockerfile + compose)
- `tests/north_star/simple_blog/target_impl/` (143 LOC backend + Dockerfile + compose)
- `tests/north_star/simple_blog/target_impl_broken/` (170 LOC backend + Dockerfile + compose)
- `tests/north_star/simple_blog/oracle/` (~280 LOC across 7 files)
- `tests/north_star/simple_blog/runner.py` + `oracle_validation/test_calibration.py` (~540 LOC)
- Total: ~1100 LOC new spike scaffolding

Builder will commit (1) the artifacts and (2) this R2 briefing after R2 verdict, so the spike result is part of the repo history regardless of re-run decision (round-8 lesson: honest-signal must be recoverable).

---

**Builder note (no self-grading)**: I'm not making any of Q1–Q6 calls. The 0/5 fixture reliability + 0 oracle-layer signal IS the spike's output. R2 verdict drives whether the next step is fix-set-A (classic builder), fix-set-B (Dockerfile patches), fix-set-A+B (combination), spike scope revision (arm 2 framing), or host upgrade escalation.

---

## 8. R2 round-10 verdict (RECEIVED 2026-05-30 — verbatim summary + decisions)

### 8.1 R2 元-finding: spike succeeded by exposing the binding constraint

R2 explicit framing: *"这个 spike 成功了 —— 它在第 1 天找到了绑定约束... 0/5 确定性失败 ... 如果连手写的 reference app 都建不起来,那 pilot 的 255-run A/B 测量在这台 Docker 上根本不可行 —— §9.6 的 env-failure 排除会排掉接近 100%,分母趋零,北极星一个数都拿不到. 这才是 spike 真正的产出:在烧 6.5 天之前,先暴露了'测量主机的 Docker 必须先修'是整个北极星度量的硬前置."*

A1 #2 (env-failure exclusion bias) is empirically active. The fixture-layer signal is the load-bearing finding, not a missed oracle signal.

### 8.2 R2 verdict per question

- **Q1** — single env-class. 1a/1b/2 are all BuildKit-on-aged-daemon. Fix A covers all three.
- **Q2** — **BLOCKER, must fix before re-run.** Probe found target_impl_broken's `package.json` has only `{express}`; target_impl has `{better-sqlite3, express, jsonwebtoken}`. R2: *"broken 必须是 target 的单点突变(复制 target,只改 auth 一行),而不是独立另建一个简化 app... 即便 Fix A 修好 BuildKit,arm 2 的信号依然无效,因为它测的是错的工件."* Rebuild target_impl_broken as exact target_impl mirror with ONE auth-middleware line changed.
- **Q3** — **(a) DOCKER_BUILDKIT=0 APPROVED for the spike**, set on the `up -d --build` subprocess in `runner.py:134-135` (NOT on a separate build call — R2 corrected my briefing). Reject (b) subprocess-direct (changes被测工件). Reject (c) per-Dockerfile patch (round-8 mask risk). **(d) host upgrade is the pilot prerequisite** — runs in parallel, not blocking the spike.
- **Q4** — green-light threshold: arm 1a green + arm 1b satisfied + arm 2 catches exactly the unauth-create flow with no extras + a credible pipeline-build-reliability plan ((d) or evidence pipeline emits classic-compat Dockerfiles).
- **Q5** — builder identity doesn't matter for the mechanical fixes; post-fix oracle signal goes to R2 for verdict.
- **Q6** — **ACCEPT and set as standing process**. R2 sees failed-state + proposed fix + classification BEFORE any rebuild. Builder does NOT inline-fix then report; that's procedural trust, unverifiable, the round-8 trap generalized.

### 8.3 R2 verdict on Fix A / Fix B

- **Fix A** — APPROVED. Apply `DOCKER_BUILDKIT=0` + `COMPOSE_DOCKER_CLI_BUILD=0` env vars on the `up -d --build` subprocess at runner.py:134-135. Content-neutral confirmed.
- **Fix B (airbnb SQL)** — **DROP arm 3 from spike.** airbnb is cross-domain noise; arm 1b already covers the Bearer-auth path with a real simple_blog. "Real generated-app oracle test" belongs in pilot's calibration arm (A1's `test_oracle_passes_against_a_real_generated_app` + `PINNED_GENERATED_APP`), not this spike. File the airbnb date+bigint bug as a separate demo-bug ticket. If/when fixing: **B2 (`::integer` cast)** is the minimum-semantic-change fix (preserves original date+integer-days arithmetic). B1 (`INTERVAL '1 day'`) introduces interval semantics not in the original — unnecessary.

### 8.4 One-line decision

1. Accept Q6 as standing process
2. Apply Fix A on `runner.py:134-135` up-build subprocess
3. **MUST FIX Q2**: target_impl_broken = target_impl with single auth-line mutation
4. **DROP arm 3** from spike; file airbnb date+bigint separately
5. Re-run → arm 1a/1b/2 + fixture success rate → R2 verdicts oracle signal (no builder self-grading)
6. **Parallel: kick off (d) host Docker upgrade evaluation** — pre-pilot hard prereq
7. Commit ~1100 LOC artifacts + this briefing + R2 verdict (honest-signal traceable, round-8 lesson)

**Per-arm classification confidence** (from probe-workflow `wyqzbwmt3` adversarial verifier):
- arm_1a env (BuildKit pid/thread): **HIGH** — refutation attempted, evidence holds
- arm_1b env (BuildKit apt hook): **HIGH classification, MEDIUM fix-layer choice** — adversarial flagged fix-layer is R2's call
- arm_2 env (BuildKit) + framing-refuted: **HIGH** — content-bug hypothesis actively refuted by probes
- arm_3 content (date+bigint): **HIGH classification, MEDIUM fix semantics** — adversarial flagged INTERVAL choice could shift fixture data
- host_env_baseline informational: **LOW confidence on "no contribution from seccomp profile"** — adversarial noted seccomp-allow-all + cgroup v1 could be load-bearing for fork/exec failures; not directly tested
- overall (route-all-to-R2): **MEDIUM-HIGH** — adversarial agreed with the recommendation but noted the round-8-trap mitigation is procedural unless R2 sees failed-state before approving rebuild (hence Q6)
