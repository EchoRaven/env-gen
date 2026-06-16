# R2 Post-Fix Briefing — Cross-Stack Calibration Spike Results + (d) Host Upgrade Eval

> **Status**: R2 round-10 approved fix-set applied (Q2 + Fix A + drop arm 3) and spike re-run. **4/4 arms PASS**. (d) host upgrade research workflow ran in parallel and recommends `defer_upgrade_dockerkit0_works` for the pilot, with one adversarial counter-finding R2 should verdict.
>
> **Surfacing raw to R2 per Q6 standing process. No builder self-grading.**

---

## 1. Raw post-fix `##SPIKE_RESULT##` JSON (verbatim from pytest -s output)

```json
{
  "arm_1a_green_on_reference": {
    "failed_tests": [],
    "flows_failed": 0,
    "flows_passed": 10,
    "verdict": "PASS"
  },
  "arm_1b_green_on_target": {
    "failed_tests": [],
    "flows_failed": 0,
    "flows_passed": 10,
    "verdict": "PASS"
  },
  "arm_2_catches_broken": {
    "actual_failed_flows": ["test_unauthenticated_post_creation_is_rejected"],
    "caught_subtle_bug": true,
    "expected_failed_flows": ["test_unauthenticated_post_creation_is_rejected"],
    "unexpected_extra_failures": [],
    "verdict": "PASS"
  },
  "arm_4_fixture_reliability": {
    "attempts": 5,
    "failure_reasons": [],
    "successes": 5
  }
}
```

Pytest summary: **5 passed in 137.57s** (~2.3 min total wall-clock for all 4 arms + the aggregator).

## 2. Per-arm meaning (factual, no R2-verdict-grade language)

| Arm | Pre-fix | Post-fix | What this measures |
|---|---|---|---|
| 1a green-on-reference | RAW_DATA (pip exit 2) | **10/10 oracle flows passed** | Oracle's behavior assertions pass against FastAPI/cookie reference. Floor sanity. |
| 1b green-on-target | RAW_DATA (apt exit 100) | **10/10 oracle flows passed** | The cross-stack proof: Bearer/Express + /api prefix is judged with same fairness as FastAPI/cookie + bare routes. R2's named "real make-or-break". |
| 2 catches-broken | RAW_DATA (npm exit 134) | **PASS — exact target failure, zero extras** | Oracle catches the single-line auth mutation (`req.user = {email: 'anonymous'}; return next();` in the no-Bearer branch). Confirms oracle is not under-strict on negative assertions. |
| 4 fixture reliability | 0/5 | **5/5 deterministic** | A1 #2 closed for the spike's hand-written Dockerfiles. Classic builder (`DOCKER_BUILDKIT=0`) is stable. |

## 3. Fix correctness — what changed vs the pre-fix state

### 3.1 Q2: target_impl_broken rebuilt as target_impl + 1-line auth mutation

**Pre-fix** (committed `e284fa4b` as honest-signal): target_impl_broken was an independent app with `{"express": "^4.18.2"}` package.json — no JWT, no DB, no auth-to-bypass.

**Post-fix** (committed `f3c87659`): target_impl_broken's server.js is now a byte-for-byte mirror of target_impl/server.js EXCEPT line 57 (the no-Bearer-header branch of `authMiddleware`):

```diff
   if (!header || typeof header !== 'string' || !header.startsWith('Bearer ')) {
-    return res.status(401).json({ error: 'missing or invalid Authorization header' });
+    // BROKEN (R2 round-9 subtle): silently treat missing/invalid Bearer
+    // header as anonymous. Original target_impl returned 401 here.
+    req.user = { email: 'anonymous' }; return next();
   }
```

All other rejection branches (invalid token payload, user not found, jwt verify throws) STILL return 401. package.json + Dockerfile are exact copies of target_impl (better-sqlite3 + jsonwebtoken + express + apt-get python3/make/g++).

**Behavior check (verified post-run)**: arm_2 caught `test_unauthenticated_post_creation_is_rejected` (POST /api/posts with NO Authorization header returns 201 instead of 401) and NOTHING ELSE. That's the precise single-point failure mode the broken-variant was supposed to exhibit. No drift.

### 3.2 Fix A: DOCKER_BUILDKIT=0 on runner.py up -d --build subprocess

Applied at `runner.py:134-152` — added `up_env = os.environ.copy(); up_env["DOCKER_BUILDKIT"] = "0"; up_env["COMPOSE_DOCKER_CLI_BUILD"] = "0"` and passed `env=up_env` to the `subprocess.run(["docker", "compose", "up", "-d", "--build"], ...)` call.

**Scope confirmation**: env var is set ONLY on this subprocess. Host docker daemon settings unchanged. Other workflows (openenv image builds, etc.) on this host still get BuildKit. This addresses the adversarial counter-finding from (d) — see §6.

Zero Dockerfile / app content changed. The earlier-failing builds (pip rich progress bar, apt Post-Invoke hook, node uv_thread_create) all succeed under classic builder.

### 3.3 Drop arm 3

Removed `test_arm_3_airbnb_auth_helper`, `AIRBNB_COMPOSE_DIR` constant, and the now-unused `_conventions` + `requests` imports. Airbnb's date+bigint SQL bug filed separately (see §7).

## 4. Q4 threshold check — direct against R2's criteria

R2's Q4 stated (verbatim): *"arm 1a(reference) green ... arm 1b(target Bearer/Express)= 满绿 ← 真 make-or-break ... arm 2(受控 broken)= 恰好挂 auth flow、其余绿 → oracle 没瞎 ... 三条都满足 + 一个可信的'生成 app build 可靠性'方案((d) 或证据表明 pipeline 发 classic-兼容 Dockerfile)→ 才 green-light pilot"*

| Criterion | R2 ask | Actual | Status |
|---|---|---|---|
| arm 1a green | "green" | 10/10 PASS | ✓ |
| arm 1b 满绿 (full green) | "make-or-break ... if <满绿 → cross-stack circular, fix oracle convention tolerance first" | 10/10 PASS | ✓ |
| arm 2 恰好挂 auth flow、其余绿 | "exactly auth flow fails + rest green → oracle is not blind" | actual_failed=`["test_unauthenticated_post_creation_is_rejected"]`; unexpected_extras=`[]` | ✓ |
| 可信的生成 app build 可靠性方案 | "(d) host upgrade OR pipeline emits classic-compat Dockerfiles" | (d) workflow verified: pipeline emits 0 BuildKit-only constructs across templates + 31 demos. See §6. | **needs R2 verdict on adversarial counter-finding** |

**Builder note**: I'm NOT calling green-light on the pilot. R2 verdicts the oracle signal AND the (d) decision. Three of four Q4 criteria are unambiguously satisfied by the data; the fourth depends on R2's read of (d)'s pipeline-syntax audit + adversarial counter on openenv.

## 5. Adversarial verify of the post-fix oracle signal (builder side, surfaced for R2's verdict)

Per Q6 process: R2 owns the oracle-signal verdict. Builder surfaces these adversarial considerations transparently:

- **"arm 1b 10/10 — could this be tuned?"** The oracle test files were written BEFORE target_impl by independent workflow agents with no cross-context (per round-9 build agents 1 vs 4). The oracle's per-flow assertions (e.g., `items_of` envelope tolerance accepting `{posts: [...]}` OR `{items: [...]}` OR `[...]`) were calibrated to the spec, not to a specific app's response shape. Same test code judged both ref ({posts:[...]} envelope, cookie auth, bare routes) and target ({items:[...]} envelope, Bearer auth, /api prefix) green — the convention tolerance is doing real work, not tuned to one app.
- **"arm 2 caught exactly the expected flow — could the oracle just be coincidentally weak in the right place?"** The pre-fix broken variant (express-only, no JWT) would ALSO have failed `test_unauthenticated_post_creation_is_rejected` — because there was no auth at all. The post-fix broken variant adds JWT verification BACK (with valid Bearer tokens accepted) and ONLY drops auth on missing-Bearer. arm 2 must show: unauth POST fails (caught), authenticated POST passes (oracle isn't false-positive on success path). 9 of 10 flows passing = authenticated flows still work = the JWT path is genuinely exercised. The one failing flow is the precise negative the mutation introduced.
- **"could fixture timing mask a content failure?"** No — fixture failure paths in runner.py return `(None, None, reason)` and the calibration arms emit `verdict=RAW_DATA` on fixture failure (not PASS). The `verdict=PASS` requires both fixture-up AND oracle judgment. All 4 arms went through fixture-up successfully (arm 4 confirms 5/5).

## 6. (d) Host Docker upgrade evaluation — workflow `w2mx2w4xa` summary

Ran in parallel with the spike re-run. 5-agent workflow: 3 parallel inventory probes + 1 synthesizer + 1 adversarial verifier. Full output at `/tmp/claude-1052/.../w2mx2w4xa.output`.

### 6.1 Synthesizer recommendation: `defer_upgrade_dockerkit0_works`

**Load-bearing finding**: env-gen pipeline emits **zero** BuildKit-only Dockerfile syntax. Verified by:
- Full grep of `env_generator/*.py` and `env_generator/*.j2` for `RUN --mount=`, heredocs, `# syntax=`, `DOCKER_BUILDKIT` — **0 hits**
- 31/31 emitted demo Dockerfiles surveyed: only one cosmetic `# syntax=docker/dockerfile:1` (jira-web/app/database/Dockerfile), which the classic builder treats as a comment
- Templates use standard multi-stage (supported since Docker 17.05); knowledge seeds reinforce classic syntax

**Therefore**: `DOCKER_BUILDKIT=0` is technically a permanent workaround for env-gen output. Pilot can proceed without host upgrade.

### 6.2 Adversarial counter-finding (R2 should verdict)

**The synthesizer's "pipeline emits no BuildKit-only" claim was REFUTED in scope by the adversarial agent**:

> The openenv subtree at `/data/common/haibotong/env-gen/openenv/` DOES contain BuildKit-only Dockerfiles:
> - `openenv/envs/websearch_env/server/Dockerfile`
> - `openenv/envs/echo_env/server/Dockerfile`
> - `openenv/src/openenv/core/containers/images/Dockerfile`
> - `openenv/src/openenv/cli/templates/openenv_env/server/Dockerfile`
>
> All use `RUN --mount=type=cache,target=/root/.cache/uv`. **env-gen is OpenEnv-targeted** (per `llm_generator/__init__.py:2` and `project_structure.py:252`).
>
> **If the pilot or downstream verification builds any openenv image, DOCKER_BUILDKIT=0 will break those builds.**

**Mitigation already in place**: my Fix A sets `DOCKER_BUILDKIT=0` ONLY on the runner's `up -d --build` subprocess (`runner.py:134`), NOT as a host-wide or process-wide export. Other docker invocations on this host (including any openenv image builds) still get BuildKit. The adversarial agent's specific recommendation: "do NOT set DOCKER_BUILDKIT=0 as a global host env var. Set it only in the env-gen pipeline runner's invocation" — Fix A already satisfies this.

**Open question for R2**: does the env-gen pipeline (or pilot verifier) ever build an openenv image via `runner.run_app(<some_openenv_app>)` or equivalent? If yes, that one path needs BuildKit and a separate fixture strategy. If no, Fix A's narrow scope is sufficient.

### 6.3 Other host findings (informational; not pilot blockers)

- Disk: /dev/sda2 94% full (1.6T/1.8T, 109G free). Not pilot-blocking but next big image pull could ENOSPC.
- 17+ live containers on host (whatsapp eval pools job 1724244, red-teaming-sandbox, paypal[unhealthy×2], etc.). Host upgrade requires sysadmin + maintenance window.
- haibotong has no passwordless sudo, not in docker group; relies on `chmod 0666 /var/run/docker.sock` for daemon access.
- Custom seccomp-allow-all.json is in `daemon.json` — adversarial flagged this is likely load-bearing for red-team workloads (bpf/perf_event_open/ptrace/keyctl/mount syscalls). Restoring default seccomp = separate ticket with tenant sign-off.
- Apt path to Docker 28.1.1 + containerd.io 1.7.27 is straightforward but adversarial revised downtime estimate from 45min → **90-120min**.

### 6.4 Soft caveat from synthesizer (R2 should accept or push back)

Synthesizer + adversarial both recommend adding a **post-generation lint/normalization pass** in env_generator that:
- Strips `# syntax=docker/dockerfile:1` parser directives
- Regex-rejects emitted Dockerfiles containing `RUN[[:space:]]+--mount=` or heredoc `<<[-]?EOF`

This prevents agent drift toward BuildKit-only syntax. ~30 LOC change, low risk, would make the DOCKER_BUILDKIT=0 commitment durable.

## 7. Airbnb date+bigint bug — filed separately (NOT in spike scope)

Per R2 round-10: airbnb's `02_seed.sql:70` has `(DATE '2016-01-01' + ((row_number() OVER (ORDER BY u.email)) * 120))` which fails with `operator does not exist: date + bigint`.

**B2 (`::integer` cast) is R2's preferred fix** — preserves original date+integer-days arithmetic semantics:
```sql
(DATE '2016-01-01' + ((row_number() OVER (ORDER BY u.email)) * 120)::integer)
```

This is **NOT committed in the spike PR**. Will file as a separate demo-bug commit after R2 verdicts the spike. R2 said: *"B1 INTERVAL 多引入 interval 语义,不必要"*.

## 8. R2 decision asks

Per Q6 standing process, R2 owns the verdict on:

**Q-postfix-1** — Does R2 accept the oracle signal as honest? (4/4 PASS with the per-arm characteristics described in §2-§5.)

**Q-postfix-2** — Does R2 accept `defer_upgrade_dockerkit0_works` for the pilot, given:
  - Audit confirms env-gen pipeline itself emits 0 BuildKit-only Dockerfiles
  - Adversarial counter-finding: openenv subtree (which env-gen targets) DOES use `RUN --mount=type=cache`
  - Fix A's scope is narrow (per-subprocess env var, not host-wide)
  - Synthesizer + adversarial both recommend adding a post-generation lint to prevent agent drift

**Q-postfix-3** — Green-light the 6.5-day simple_blog pilot?

**Q-postfix-4** — Should the post-generation lint normalization pass be added before pilot launch, or as a parallel work item?

**Q-postfix-5** — Airbnb B2 SQL fix as a third commit (separate from spike), or defer to a future demo-bug PR?

---

## 9. Commits so far

- `d787be79` — A3 baseline pin (pre-spike)
- `e284fa4b` — spike honest-signal preservation (~1100 LOC pre-fix state + briefing v3 with §8 R2 verdict)
- `f3c87659` — R2-approved fix-set applied (Q2 target_impl_broken rebuild + Fix A DOCKER_BUILDKIT=0 in spike runner + drop arm 3)

**Post-R2-round-11 pre-pilot work (verdict round-11 ACCEPTED 4/4 oracle signal + 🟢 GO + 5 directives):**
- `006261ff` — feat(multi-agent): post-generation Dockerfile classic-compat lint (Q-postfix-4: pilot 前做的 durable structural pin; 11/11 unit tests green; integrated at shared.py:230 single chokepoint)
- `67ecb385` — fix(demos/airbnb): cast row_number() to integer for DATE arithmetic (Q-postfix-5: atomic separate from spike; B2 ::integer per R2 minimum-semantic-delta)
- `8a48cc26` — fix(pipeline): force DOCKER_BUILDKIT=0 on BuildKit-reaching subprocess sites (Q-postfix-3 condition: Fix A propagated to docker_tools._run_compose + runhub/compose._default_runner + database_tools._try_start_db_service + runtime_tools.ExecuteBashTool per pre-pilot workflow wdk87hg1c adversarial-flagged execute_bash bypass risk)
- `244656e4` — docs(sysadmin): Docker daemon + kernel HWE upgrade ticket (R2 round-11: 别无限期; docs/sysadmin_ticket_docker_upgrade.md with 10 sections + DoD + adversarial-flagged BuildKit-default-builder smoke gate)
- this commit — docs(spike): post-fix briefing for R2 round-11 spike close-out

## 10. R2 round-11 verdict received → executed (this section updated post-verdict)

R2 round-11 verdict in summary (full verdict transcript in commit `006261ff` follow-up convo):
- **Q-postfix-1 ✅** oracle signal accepted as honest (cross-stack make-or-break satisfied with real evidence)
- **Q-postfix-3 🟢** GO 6.5-day simple_blog pilot, conditioned on a pipeline end-to-end smoke confirming generation-side docker builds also work on this host (or Fix A applied there too)
- **Q-postfix-2** ACCEPT `defer_upgrade_dockerkit0_works` + file sysadmin ticket (don't let it rot)
- **Q-postfix-4** lint pilot 前做 (~30 LOC structural pin — Fix A's durable companion)
- **Q-postfix-5** airbnb B2 atomic separate commit NOW (don't rot, don't bundle into spike)

What changed since v1 of this briefing:

- **Spike commits stand** (e284fa4b honest-signal + f3c87659 fix-set). R2 accepted the spike as closed.
- **Pre-pilot work executed** via pre-pilot workflow `wdk87hg1c` (4 parallel investigations + synthesizer + adversarial verify):
  - smoke test on jira-web confirmed BuildKit is PARTIALLY functional on this host (db + backend built fine; jira-web frontend had a pre-existing vite content bug unrelated to our infrastructure). Adversarial maintained Fix A defense-in-depth is still warranted given spike's deterministic 0/5 failure on hand-written Dockerfiles
  - lint module shipped to disk + integrated at shared.py:230 chokepoint (11/11 unit tests green)
  - airbnb B2 ::integer applied as atomic commit (not in spike scope)
  - Fix A propagated to 4 BuildKit-reaching subprocess sites (3 from synthesizer plan + execute_bash from adversarial counter-finding)
  - sysadmin ticket drafted with 10 sections + DoD including adversarial-flagged BuildKit-default-builder smoke gate

- **(d) host upgrade evaluation** completed and filed as sysadmin ticket `docs/sysadmin_ticket_docker_upgrade.md`. Decision: `defer_upgrade_dockerkit0_works`. Workaround narrowly scoped (per-subprocess env var, not host-wide); openenv-subtree BuildKit-only usage NOT triggered by env-gen pipeline; post-gen lint prevents agent drift.

**Open after this briefing**: pilot launch is unblocked per R2 round-11 + the 5 commits above. R2 next sees: spec-level oracle signals as the simple_blog pilot progresses.
