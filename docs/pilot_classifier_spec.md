# Pilot Failure Classifier — Pre-Registration Spec

**Status:** 📝 DRAFT (commit pin) → 🔒 FROZEN-after-R1-gate.
DRAFT commit lands first as the pre-registration anchor; the SHA-pin freeze happens
ONLY after the R1 adversarial gate passes. The integrity-critical invariant is **no
A/B pilot datum before freeze-confirm**, not "frozen before impl" (R1 round-12).
**Author:** R2 (pre-registration) · **Adversarial gate:** R1 · **Date:** 2026-05-30
**Builds on:** §9.1.5 (validation arms), §9.6 (stats / B1), B2 (selection-bias risk),
the round-11 smoke nuance (BuildKit not uniformly broken; jira-web vite = functional).
**Signature provenance:** §3 tightened from the loose first draft via adversarial
workflow `wid8c0ydk` (24 agents; every ENV signature challenged "could this exclude a
broken app?") and re-scanned by R2 by hand. The first draft's bare-substring
signatures (`address already in use`, `137 + Killed`, `no space left on device`) were
**laundering holes** — each also occurs on the app's own fault; §3 now carries a
mandatory negative guard per signature.

---

## 0.1 R1 round-12 remediation (this commit, still DRAFT)

The R1 adversarial pass on the first DRAFT surfaced eight blocker classes
(B-1…B-8) — over-exclude vectors that would have inflated the new arm
pre-freeze. This commit lands the structured fixes; the spec text below
incorporates the §3 amendments (negative-guard extensions, channel-provenance
restriction, daemon-window probe, env.daemon_5xx deletion, OOMKilled
authority, df corroboration, RUN-step precedence-stealer, node SIGABRT/RUN-step
anchor, B-8 §2 schema + ITT recompute apparatus).

Ordering remains unchanged: SHA-pin freeze happens ONLY after R1 re-confirms
the patched gate is green. `classifier_spec_sha` stays at `a048316b-draft`
until the post-re-gate freeze commit.

---

## 0.1.1 R1/R2 round-13 env.oom remediation (this commit, still DRAFT)

Three independent vectors were found in the round-13 sweep against the
round-12 env.oom signature; this commit lands all three by-construction
closures (still DRAFT — `classifier_spec_sha` stays `a048316b-draft` until
the post-re-gate freeze):

  - **D1 (R1) — OOMKilled=False veto.** The round-12 form honored
    `OOMKilled=True` (own-cgroup carve-out → FUNCTIONAL) but never honored
    `OOMKilled=False`. A host CONSTRAINT_NONE OOM of an unrelated neighbor
    laundered into env.oom even when the docker daemon explicitly said
    this container was not the kernel's OOM victim. Closed: the daemon's
    `OOMKilled` bit is authoritative in BOTH directions.

  - **D2 (R1) — channel-provenance restriction for env.oom.** Round-12
    documented an exception that let env.oom positive-match in
    `raw_evidence` (compose-logs / app stdout). An app printing
    `child process 137 Killed` in its own output combined with a noisy
    neighbor's host CONSTRAINT_NONE laundered into env. Closed: env.oom
    positive matching restricted to the CONTAINER-EXIT channel
    (`docker_inspect_state.ExitCode == 137` OR `up_stderr`/`build_stderr`).
    No special case for env.oom anymore; the "documented exception"
    framing is removed everywhere in the spec.

  - **D3 (R2) — symmetric mem_limit injection precondition.** Without
    an injected mem_limit, dmesg CONSTRAINT_NONE collapses two
    structurally different worlds (app self-leak vs. co-tenant host
    pressure) into one ambiguous signal. Closed by construction: the
    runner now injects a symmetric 2 GiB `mem_limit` on every app
    container via `RUNNER_MEM_LIMIT` and records it on
    `FailureContext.runner_injected_mem_limit`. Evaluation of env.oom
    requires this field to be set; when None, env.oom defaults to
    FUNCTIONAL. With injection, an app self-leak hits the injected
    cgroup ceiling first → CONSTRAINT_MEMCG / OOMKilled=True → step-1
    own-cgroup carve-out → FUNCTIONAL; CONSTRAINT_NONE thereafter is
    genuinely host-level pressure.

Also closed in this commit (gate-infra, not signature): the north_star
`conftest.py` collect-ignore that silently skipped the gate tests under
`pytest tests/` (D4). Whitelist landed for the three gate files
(`test_classifier_acceptance.py`, `test_itt_recompute.py`,
`test_conventions_self.py`); the oracle runner and per-spec oracles
remain collection-isolated.

---

## 0. Why this document exists (the integrity argument)

The north-star metric is `functional_pass_rate` over pipeline-generated apps. When a
run fails, we must decide whether the failure is the **generated app's fault**
(FUNCTIONAL — counts against the rate) or the **host/infrastructure's fault**
(ENV — excluded). If that decision is made *after seeing the data*, or *by judgment
per-run*, it is **selection bias** (R2's B2): inconvenient failures get quietly
relabelled "env" and the pass rate inflates — especially for the new arm, which runs
longer and hits more infra hiccups.

The defence is **pre-registration**: the rules are written, frozen, and adversarially
gated **before any pilot datum exists**. This is the measurement analogue of the
round-8 honest-signal lesson — a gate authored after the thing it judges is not a gate.

**Ordering invariant (Q6, non-negotiable — R1 round-12 correction applied; re-gated post-remediation):**
```
spec committed as DRAFT (this doc, on-disk + commit SHA known)  ← unblocks impl
  → classifier impl in runner.py + runner instrumentation prerequisites (§3 stderr
    widening, build_stderr split, ephemeral ports in spike compose, dmesg/df/version
    probes) + 25 V-fixtures + [POPULATE] real smoke failures (§7)
  → R1 adversarial pass (expected to find signature gaps — that IS its job;
    amend the DRAFT until ★ rows pass + default-functional path holds for unmatched)
  → FREEZE — SHA-pin (the gate-passed commit SHA recorded into the pilot run manifest)
  → THEN pipeline-generate the first app
```
The hard line is **no pilot datum before freeze-confirm**. Committing-as-DRAFT is what
lets impl start; the SHA-pin freeze is the gate clearing into. Don't pin until the
adversarial pass is green — pinning before it is the premature-SHIPPED mistake one
domain over (Phase 0.2 attempt-1).

---

## 1. The core invariant: default-functional, exclude-only-on-proof

> A failed run is classified **FUNCTIONAL unless it matches an explicit, frozen ENV
> signature in §3 *and clears that signature's negative guard*.** Exclusion requires
> *proof of host fault*, never absence of proof, and never a bare substring that the
> app could also emit.

Same fail-closed shape as the Phase 0.2 write-gate (deny-by-default, allow-on-explicit
-match), one domain over. Consequences:

- You cannot drop an inconvenient failure — exclusion demands a guarded signature match.
- Bias direction is conservative: the rule protects against the **dangerous** error
  (inflating "the pipeline works"). The opposite error (counting host noise as a
  functional failure, which *deflates* the rate) is suppressed structurally by the
  `DOCKER_BUILDKIT=0`-by-construction build path (dockerfile_lint.py;
  runhub/compose.py:42; docker_tools.py:76; database_tools.py:264;
  runtime_tools.py:1041/1053) — host BuildKit variance is removed, so most remaining
  build failures are genuinely attributable to the app.

**Evaluation order (first match wins — load-bearing):**
0. Oracle JUnit `<failure>` → FUNCTIONAL **unconditionally** (the flow-assertion result
   IS the signal; no env signature may ever swallow it). Round-12 B-7: implemented as
   `junit_failure_text is not None` (element-presence sentinel) — an empty `<failure/>`
   body (xUnit emits self-closing tags) is still the oracle reporting a flow assertion.
1. Own-cgroup OOM carve-out (§3 `env.oom` negative guard) → FUNCTIONAL. Round-12 B-3:
   consults `docker_inspect_state.OOMKilled` FIRST (authoritative own-cgroup signal),
   then `app_has_mem_limit`, then `dmesg CONSTRAINT_MEMCG`.
2. The §3 ENV signatures, in id order.
3. Terminal default → FUNCTIONAL.

---

## 2. Verdict schema (emitted per run, BEFORE any aggregation)

```json
{
  "run_id": "str",
  "spec_id": "simple_blog | twitter_clone | simple_ecommerce",
  "arm": "known_good | known_broken | cross_stack_calibration | ab_old | ab_new",
  "phase_reached": "infra_setup | app_build | app_runtime | oracle",
  "outcome": "pass | fail",
  "verdict": "functional | env | uncertain",
  "matched_signature": "str | null",   // the §3 id that fired, or null
  "raw_evidence": "str",               // the log span that decided it (auditable)
  "negative_guard_evidence": "str | null", // what was checked to clear the guard
  "retry_count": 0,                    // reassign-retries consumed (port predicate)
  "classifier_spec_sha": "str"         // the frozen SHA of THIS doc used to judge
}
```

- `verdict` is computed **only** from §3 + §4; no per-run human judgment enters the metric.
- `raw_evidence` + `negative_guard_evidence` make every exclusion auditable. "We
  excluded N runs as env" is trustworthy only if each carries the span that fired the
  signature AND the guard check that cleared it.
- `classifier_spec_sha` pins which frozen ruleset judged the run — a post-freeze
  amendment (§6) is detectable in the data.

`functional` and `uncertain` both **count against** the rate. `env` is **excluded**
from the denominator (and logged separately, per-arm — §5.1).

---

## 3. ENV signatures (the FROZEN exclusion set) — guarded against laundering

A run is ENV iff its evidence matches a signature below **in the matching phase** AND
clears that signature's **negative guard**. Match ENV signatures ONLY against the
relevant subprocess's OWN stderr (`up`/`build`/`down`), NEVER `compose logs` (runtime
app output is never env-eligible). **Runner prerequisite:** widen the stderr capture
from `[-800:]` to full (`[-4000:]` floor) and split `docker compose build` into its own
`build_stderr` buffer — the negative guards cannot fire if they can't see RUN context.

### §3 prereq clarifications (cross-cutting — R1 round-12)

1. **Stderr is stderr.** `build_stderr` / `up_stderr` MUST contain ONLY the
   corresponding subprocess's stderr stream. The runner now routes
   `build.stdout` and `up.stdout` (runtime app output that a tool happened to
   echo through the build context) into `raw_evidence` — never into
   `*_stderr`. Folding stdout into stderr breaks every row's positive
   admissibility (an app's RUN-step print of `Cannot connect to the Docker
   daemon ...` would otherwise satisfy env.daemon_down).
2. **Channel-provenance restriction.** Docker-CLI-transport signatures
   (`env.daemon_down`, `env.image_pull`, `env.disk_full` storage-driver arm,
   `env.port_conflict`, `env.buildkit_recurrence`, **and `env.oom` — R1
   round-13**) search ONLY the CONTAINER-EXIT / TRANSPORT channel
   (`build_stderr ∪ up_stderr`, plus `docker_inspect_state.ExitCode` for
   `env.oom`). `raw_evidence` (compose-logs / app output channel) is
   excluded from in-band signature matching to defeat star-launder
   vectors where the app itself prints discriminator tokens.
   **No exception for `env.oom`.** The earlier "documented exception"
   letting `env.oom` positive-match in `raw_evidence` (exit 137 /
   `Killed` in compose logs) was a self-adversarial rationalization —
   an app self-printing the token is content, not host fault, and the
   daemon's ExitCode/OOMKilled bit is the authoritative infra-channel
   signal (R1 round-13 PoC + R2 round-13 PoC both showed it as an
   over-exclude vector; closed by construction).
3. **Foreign-holder / reassign-retry are RUNNER responsibilities.** The
   classifier's port-conflict guard chain
   (`foreign_holder_found`, `reassign_retry_success`,
   `second_collision_on_free_port`, `retry_count`) requires the runner to
   populate them at port-conflict failure time. Default None remains the
   conservative FUNCTIONAL path — there is NO implicit "absence means True".
4. **Positive port admissibility names P literally.** The env.port_conflict
   positive regex MUST anchor every alternative on the injected port P;
   bare-substring alternatives (`port is already allocated`, `bind: address
   already in use`) are forbidden as standalone positives even when other
   admissibility gates are open.
5. **Daemon-window probe.** `env.daemon_down` consumes
   `daemon_up_at_failure_time` (Optional[bool]) captured by the runner at
   T+0 via `systemctl is-active docker` (fallback `service docker status`),
   SYNCHRONOUSLY on subprocess.run failure with no intervening sleeps.
   Post-hoc `docker version` retries are corroborating evidence only, never
   gating.

| id | phase | match (all required) | NEGATIVE GUARD — MUST NOT match (→ FUNCTIONAL) | why the bare form laundered |
|----|-------|----------------------|-----------------------------------------------|------------------------------|
| `env.daemon_down` | infra_setup, app_build | `Cannot connect to the Docker daemon at unix://` / `dial unix /var/run/docker\.sock: connect: (permission denied\|no such file or directory\|connection refused)` (`Is the docker daemon running\?` only co-occurring) **AND** `daemon_up_at_failure_time == False` (synchronous T+0 probe) | any of `executor failed running` / `failed to solve` / `returned a non-zero code` / `The command '/bin/sh -c` / `Cannot find module` / `context deadline exceeded` / `i/o timeout` / `client timeout exceeded` / **`Error response from daemon:`** (daemon answered → daemon is up) | a truncated tail showing a daemon string could mask a build failure for another service; a healed transient blip; a mid-build connect-timeout (pathological RUN); a daemon that returns an error response is by definition reachable |
| `env.port_conflict` | infra_setup, app_runtime | **ADMISSIBILITY:** runner injected a run-unique ephemeral port P (static 8001/8002/8003 → INADMISSIBLE → FUNCTIONAL). Positive regex MUST name P literally on every alternative; bare substrings are forbidden. Match `port is already allocated` / `bind: address already in use` naming **P** **AND** `docker ps --filter publish=P` shows a holder whose compose-project ≠ OURPROJ **AND** a single reassign-and-retry on a fresh verified-free port SUCCEEDS (health passes) | holder is a service in OUR OWN compose project; a SECOND collision on a verified-free port; no foreign holder found (TOCTOU/ambiguous); injected port absent from transport stderr | a free port can't be pre-owned, so a second collision is provably the app's own bug; self-inflicted compose port misconfig is the app's fault; a positive substring naming a *different* port is self-inflicted |
| `env.image_pull` | infra_setup, app_build | a SINGLE line with a base-image-registry host (`registry-1\.docker\.io\|index\.docker\.io\|ghcr\.io\|quay\.io\|gcr\.io\|.*\.dkr\.ecr\..*\.amazonaws\.com\|.*-docker\.pkg\.dev\|mcr\.microsoft\.com\|public\.ecr\.aws`) **AND** a transient token (`TLS handshake timeout` / `dial tcp .*(i/o timeout\|connection refused\|no route to host)` / `failed to (resolve\|fetch) .*registry` / `temporary failure in name resolution` / `received unexpected HTTP status: (429\|5\d\d)`) | package-index hosts (`pypi\.org\|files\.pythonhosted\.org\|registry\.npmjs\.org\|deb\.debian\.org\|archive\.ubuntu\.com`) — these default FUNCTIONAL; **AND** globally none of `manifest unknown` / `pull access denied` / `repository .* not found` / `401 Unauthorized` / `404 Not Found.*(manifest\|blob)` / **`: not found`** / **`insufficient_scope`** / **`denied: requested access to the resource is denied`** / **bare `403 Forbidden`/`403 denied`** / **`error pulling image configuration`** (round-12 B-2 negative-guard extension) | a `:vfake: not found` after a manifest reference is the registry telling us the tag doesn't exist; `denied`/`insufficient_scope`/`403` are auth content (the image name / token is the app's responsibility) |
| `env.oom` | any | `exit 137` / `Killed` / `signal 9` / `OOMKilled` / `cannot allocate memory` / `fork: retry: Resource temporarily unavailable` matched **ONLY in the CONTAINER-EXIT CHANNEL** (`docker_inspect_state.ExitCode == 137` OR `up_stderr`/`build_stderr`) — **NEVER `raw_evidence` (compose-logs / app-print channel)** **AND** out-of-band `dmesg -T` shows `oom-kill:constraint=CONSTRAINT_NONE` (HOST-wide) **AND** no `mem_limit`/`deploy.resources.limits.memory` in the app compose **AND** `runner_injected_mem_limit` IS SET (symmetric mem_limit injection MUST be active for env.oom to be admissible) **AND** `docker_inspect_state.OOMKilled` is not True (round-12 B-3 — daemon's authoritative cgroup verdict wins over a host-wide CONSTRAINT_NONE window) **AND** `docker_inspect_state.OOMKilled` is not False (R1 round-13 D1 — daemon's bit is authoritative both ways; OOMKilled==False vetoes env.oom) | `constraint=CONSTRAINT_MEMCG` / `oom_memcg=/docker/<app-cid>` / app declares a memory limit (own-cgroup OOM = the app's own memory bug — evaluated FIRST, step 1) / **`docker_inspect_state.OOMKilled is True` → FUNCTIONAL (step-1 own-cgroup carve-out re-affirmed; daemon's bit is authoritative both ways — R1 round-13)** / **`docker_inspect_state.OOMKilled is False` → FUNCTIONAL (R1 round-13 D1 veto; daemon affirms this container was NOT the kernel's OOM victim, host CONSTRAINT_NONE is co-tenant noise)** / **`raw_evidence` (compose-logs) is the ONLY source of `137`/`Killed`/`OOMKilled` → FUNCTIONAL (channel-provenance restriction; an app self-printing the token is content, not infra — R1 round-13 close of the "documented exception")** / **`runner_injected_mem_limit is None` → FUNCTIONAL (without symmetric injection, host CONSTRAINT_NONE is ambiguous between co-tenant pressure and app-self-leak — R2 round-13)** | `137 + Killed` alone is also how an app's own-cgroup OOM and a SIGKILL of a hung app surface; OOMKilled==True is the docker-layer authority on which cgroup OOMed; **R1 round-13 PoC**: OOMKilled=False + neighbor-tenant host OOM was over-excluded by the bare form — closed by routing through the CONTAINER-EXIT channel + daemon bit; **R2 round-13 PoC**: an app with no `mem_limit` self-leaks → host OOM-killer fires with CONSTRAINT_NONE (no cgroup attribution because no cgroup limit), bare form excluded it as "host pressure" — closed by requiring `runner_injected_mem_limit` so CONSTRAINT_NONE means "host-wide despite the app being capped" |
| `env.disk_full` | any | ENOSPC in docker's **storage-driver** path, tightened: `failed to register layer:[^\n]*/var/lib/docker/(overlay2\|aufs\|btrfs\|devicemapper\|zfs)/[^\n]*no space left on device` / `Error processing tar file[^\n]*/var/lib/docker/[^\n]*no space left on device` / `write /var/lib/docker/(overlay2\|aufs\|btrfs\|devicemapper\|zfs)/[^\n]*no space left on device` **AND** `df -P /var/lib/docker` corroborates **≥90% used** (round-12 B-4 — storage-driver phrases without df pressure are unverified → FUNCTIONAL) | bare `no space left on device`; **`Errno 28` / `ENOSPC: no space left on device, (write\|mkdir\|open)` inside a `RUN` step → explicit FUNCTIONAL** (runaway/bloated deps = content) — RUN-step is a *precedence-stealer* evaluated BEFORE the storage-driver match; `System limit for number of file watchers` (app inotify config); df shows <90% usage | a runaway app `pip/npm install` filling disk is content; an app printing the phrase can't self-classify; the df guard catches storage-driver phrases that come from overlayfs quirks rather than a truly full disk |
| `env.buildkit_recurrence` | app_build | post-Fix-A these should be EXTINCT; if they recur (a Fix-A path leaked): pip `pip[/\\]_vendor[/\\]rich[/\\]` frame **+** `RuntimeError: can'?t start new thread`; OR apt `APT::Update::Post-Invoke` **+** download-proof `Fetched\b.*\b(B\|kB\|MB\|GB)\b` **+** none of `Could not resolve`/`Failed to fetch`/`404`; OR **node variant tightened (round-12 B-5): `Assertion failed:\s*\(0\)\s*==\s*\(uv_thread_create` AND a SIGABRT marker (`Aborted \(core dumped\)` \| `signal: aborted` \| exit code 134) AND a BuildKit RUN-step prefix `^[#\s]*\d+\s+\d+\.\d+[^\n]*\b(npm\|node\|yarn\|pnpm)\b`** on the same evidence | the bare mechanism token WITHOUT its frame/assertion anchor (`can't start new thread` with no rich frame; `Could not resolve` apt DNS; `MODULE_NOT_FOUND`/`ETARGET`/`gyp ERR!`); node variant missing SIGABRT / exit 134 / RUN-step prefix | the bare thread/assertion message is also CPython/libuv generic resource-pressure or app-content failure; uv_thread_create on its own can appear in dependency stack traces without an abort |
| ~~`env.daemon_5xx`~~ | **DELETED in R1 round-12 (B-6)** | dockerd 500s on the docker.sock transport are not separable from app-printed 500-strings in-band; genuine dockerd panics manifest as `env.daemon_down` (socket dial failure) corroborated by the runner's `systemctl is-active docker` + `journalctl -u docker` out-of-band probes | n/a | n/a |
| `env.oracle_infra` | oracle | a `<error>` (NOT `<failure>`) with a traceback frame in `tests/north_star/` (oracle code crash), OR Playwright `Executable doesn't exist`/`Failed to launch`/`No usable sandbox` at browser-launch BEFORE any navigation — **AND** the identical fingerprint reproduces against a same-run `reference_impl` control | reproduces only against the app-under-test, not the control; any `<failure>` (that is step-0 FUNCTIONAL) | an app-triggered oracle crash is the app's fault; **separate bucket, target count 0 — if non-trivial, the oracle itself is buggy → fix before trusting data** |

> **Frozen.** After this doc is SHA-pinned, adding/altering a row is a §6 amendment
> (logged methodology change + re-classification of all prior runs), never an in-flight edit.

---

## 4. NON-signatures (explicitly FUNCTIONAL — the round-11 lesson, codified)

Never env, regardless of how they surface. These are the tempting false-exclusions:

- **`build exited non-zero` is NOT an env signature.** A build can fail because the
  *generated app* is broken. The canonical proof: jira-web frontend `vite`/`cli.js`
  failure under `BUILDKIT=0` is FUNCTIONAL (the generated app does not build), not host
  noise. Only the specific §3 patterns (each guarded) exclude.
- App dependency / content failures: `npm ERR` / `ModuleNotFoundError` /
  `Cannot find module` / `vite: command not found` / `cli.js` / `ETARGET` / `ERESOLVE` /
  `gyp ERR!` / `No matching distribution found` / `error TS\d+` / version-peer conflicts
  from the app's own `package.json`/`requirements.txt` / missing referenced files /
  `COPY failed: .*not found in build context` → FUNCTIONAL.
- **App boot crash:** `docker inspect` `State.Status` in {exited,dead} with
  `ExitCode!=0` AND `OOMKilled==false` (exit 137 with `OOMKilled==false` = SIGKILL of a
  hung app → FUNCTIONAL).
- **Own-cgroup OOM** (`CONSTRAINT_MEMCG` / app `mem_limit`) → FUNCTIONAL (step 1).
- **Self-inflicted port/compose misconfig** (holder is our own project; `is not a valid
  port`; `depends_on.*undefined service`; `variable is not set`) → FUNCTIONAL.
- **Broken seed/init SQL** (`psql:.*ERROR:` / `syntax error at or near` / `relation .*
  does not exist` / `/docker-entrypoint-initdb.d/.*error`) → FUNCTIONAL.
- **In-budget health timeout:** `_wait_for_ready` None within the frozen symmetric
  budget (≥180s, identical both arms) with the service `running` and no §3 signal →
  FUNCTIONAL. (A slow-but-correct app that eventually returns 2xx/3xx is a PASS.)
- **Endpoint reachable but never green** (last code in {404,500,502,503,504}) → FUNCTIONAL.
- **Oracle assertion failure** (auth flow, post-appears-in-listing, created-without-id,
  200-HTML-instead-of-4xx-JSON, …) → FUNCTIONAL, unconditionally (step 0).
- **`failed to solve` / `buildkit …` under forced `BUILDKIT=0`** — anomalous; do NOT
  auto-exclude → **UNCERTAIN** (§5), flagged: it signals the determinism guard was
  bypassed and must be investigated, not silently dropped.

---

## 5. The `uncertain` bucket + per-arm exclusion audit

### 5.0 Uncertain
A failure matching no §3 signature and no §4 non-signature, genuinely ambiguous:
**counts as FUNCTIONAL** for the metric (conservative — never inflates), is flagged for
human review, and its evidence becomes a candidate for a §6 amendment in a *later* round
(logged), never a silent re-label of the current run.

### 5.1 Per-arm exclusion audit (mandatory artifact, every comparison)
- Report `excluded_env_runs / total_runs` **per arm, broken down by signature id**, with
  the per-run manifest (§2 schema). A null `matched_signature` on every FUNCTIONAL run
  proves no silent exclusion. `retry_count` logged so the heavier arm can't accrue silent
  reassign-retries.
- **Large-asymmetry gate (blocks the run):** if the env-exclusion rate differs across
  arms by **>2× relative OR >5pp absolute (frozen now)**, the comparison is BLOCKED
  pending manual audit — the asymmetry must trace to a genuine §3 infra predicate, not a
  signature quietly absorbing content failures.
- **Intent-to-treat sensitivity (report ALWAYS, not only on asymmetry):** for every
  comparison report BOTH the as-classified delta AND the ITT-worst-case delta (recompute
  the rate counting ALL excluded NEW-arm runs as FUNCTIONAL FAILURES). If the new-arm
  advantage does NOT survive ITT, it is NOT reported as a win. Even a flawed signature
  cannot manufacture a win ITT does not show. *(This is the decisive B2 backstop; the
  aggregation lives in B1/§9.6, but the constraint is fixed here.)*

---

## 6. Freeze + amendment protocol

- **DRAFT** = this doc committed (commit SHA exists) but pre-R1-gate. Amendments
  during this phase are free and expected (R1's job is to find gaps).
- **FREEZE** = the gate-passed commit SHA is recorded into the pilot run manifest;
  every run records `classifier_spec_sha`. Only frozen SHAs may judge pilot data.
- **Pre-freeze amendments** are free (still a draft).
- **Post-freeze amendments** (adding/altering a §3 signature) are permitted only as a
  **logged methodology change**: new commit + CHANGELOG entry with rationale and the
  host-fault evidence that motivated it, AND **re-classification of all already-collected
  runs under the new SHA** (the metric is never a mix of rulesets).
- An amendment motivated by a *specific failed run's outcome* (rather than a host-fault
  pattern) is **forbidden** — that is the exact selection bias this doc prevents.

### 6.1 Freeze criterion (R1 + R2 round-13 layer-2 framing)

The trigger for the FREEZE SHA-pin bump is **NOT** "classifier perfection" or "signature
set is complete." env-signature is a denylist; adversarial generators structurally find
edge cases in clean code forever. Chasing zero-residual is the layer-1 grind that
Phase 0.2 attempts 1-7 fell into; layer-2 closed-by-construction is the discipline that
broke it (one structural fail-closed default, not 50 enumerated patches). The same
mechanism applies here.

**FREEZE requires all four:**

1. **V-fixtures all green** — including the launder-trap stars (★) and the
   by-construction pre-condition fixtures (e.g. `runner_injected_mem_limit=None` →
   FUNCTIONAL; static port → INADMISSIBLE → FUNCTIONAL).
2. **Residual gaps are immaterial / hygiene only** — any new adversarial finding either
   (a) cannot change a real verdict on any in-distribution input, or (b) is
   vocabulary/dead-code/comment cleanup that does not weaken any env-positive
   determination. **New semantic class** (a host/app confusion mode never modeled,
   like R2 round-13's no-`mem_limit` self-leak/co-tenant ambiguity) → BLOCKS freeze
   until fixed. **Vocabulary variant** of a known class (`back-compat`/`legacy`/
   `transitional`/`documented exception`/`design-accepted`/`acceptable trade-off`/
   `in practice` framing on an env-positive code path) → ACTIVE rationalization →
   BLOCKS freeze. **Dead-code or already-CLOSED reference** (a comment describing a
   past hole that the current code has structurally closed; verified by reading the
   current code and confirming the comment matches reality) → does NOT block.
3. **§5.1 backstop is in position and decisive-tested**:
   - `compute_itt_delta` reports both as-classified rate AND ITT-worst-case rate
     (every excluded run counted as functional-fail in the ITT recount).
   - Asymmetry gate (`ASYMMETRY_REL_X=2.0` rel OR `ASYMMETRY_ABS_PP=5.0` absolute pp)
     hard-blocks any comparison where new-arm env-exclusion outpaces old-arm.
   - Pinned tests: `test_itt_advantage_does_not_survive_blocked_by_asymmetry`,
     `test_itt_asymmetry_trigger_blocks_on_small_gap` — both green.
4. **Every reported comparison gates wins on both rates** — a "win" requires the
   advantage to survive BOTH the as-classified rate AND the ITT-worst-case rate.
   Survives one but not the other = NOT a reported win. This is the structural fail-
   closed that bounds any residual layer-1 signature leak: a hole in §3 cannot
   manufacture a win that ITT does not show.

### 6.2 Triage rule for any adversarial finding (substance, not novelty)

- **Vocabulary variant / dead-code hygiene of a known class** → floor reached → fix
  inline + amend DRAFT or note as already-CLOSED reference; does not block freeze.
- **New semantic class** (host/app confusion mode never modeled) → BLOCKS freeze.
  Fix the one, then freeze.
- **Active rationalization** (any of the forbidden vocabulary on an env-positive
  determination) → BLOCKS freeze. Remove the rationalization (either delete the path
  or convert to a documented closure with reality-matching comment).

### 6.3 Cleanup discipline (R2 round-13, attempt-7 over-correction analogue)

vocabulary/legacy rewrites must be **behavior-preserving**. A "rationalization" rewrite
that flips any fixture's verdict is not a cleanup — it is a fix and needs its own
bidirectional fixture (launder-trap + legitimate-env positive control). After any
cleanup pass, the FULL acceptance suite must be re-run and pass; any unexpected verdict
flip = the cleanup was actually load-bearing, treat as a fix.

### 6.4 Why this freeze criterion, not zero-residual

env-signature enumeration is a denylist. Layer-1 grind (find-and-patch each new leak)
does not converge — adversarial-style generation structurally always finds an edge
case in clean code. The structural answer is **layer-2 bound**: ITT-worst-case
recount + asymmetry gate. The §5.1 apparatus already proves it bounds the residual
(decisive tests pinned). Demanding zero-residual before freeze underuses the backstop
and never converges; demanding (V green + residual immaterial + ITT in position)
freezes when the substance is exhausted, with the layer-2 bound carrying any
residual layer-1 risk.

**Current status: 🔒 FROZEN 2026-05-30 (R1 round-14 CLEAR + R2 round-14 CLEAR):**
`CLASSIFIER_SPEC_SHA = "4c1c3370"`. The SHA-pin bump landed alongside the CI
import fix at commit `4c1c3370` per R1's round-14 ask ("land the CI-import fix
together with the FREEZE commit so that the moment CLASSIFIER_SPEC_SHA comes
off `-draft`, the thing actually defending it is running in CI").

R1 round-14 substance verdict: §6.1 (1)-(4) CLEAR. R1 independently verified the
§5.1 layer-2 backstop: planted +25.7pp spurious as-classified win → ITT recount
zeros the delta + asymmetry gate blocks (the structural guarantee that bounds
residual layer-1 leaks). R1 round-14 explicit: "I co-sign the SHA-pin — no
round-15 on signatures; the treadmill ends here, on the backstop, exactly as
designed."

R2 round-14 verdict: FREEZE-READY from spec-author angle. All 4 R2 findings
landed faithfully; env.oom now closed from two angles (channel provenance +
OOMKilled=False veto + by-construction mem_limit injection); spec §6 freeze
criterion is the round-13 meta-review encoded.

Pre-registration paper trail (every Verdict-bearing commit in the freeze ledger):
  d787be79  A3 baseline pin
  a048316b  DRAFT spec (pre-registration anchor)
  de5aa82e  EXT register seed
  00ce5a12  classifier impl + 27 V-fixtures
  102ce90b  runner instrumentation + ephemeral ports + [POPULATE]
  de05b9a9  R1-gate remediation rounds 1-3
  e50fe23f  round-4/5 env.oom + daemon_down + §6 layer-2 criterion
  7ec7fee6  R1 round-14 routing brief
  4c1c3370  CI import fix (R1 round-14 close)
  <this>    FREEZE: CLASSIFIER_SPEC_SHA bump to 4c1c3370

Post-freeze amendments per §6: a future signature change is a new commit + a
CHANGELOG entry + re-classification of all already-collected pilot runs under
the new SHA. Per §6.2, outcome-motivated amendments are forbidden.

---

## 7. Acceptance test (the R1 gate target)

`agent/tests/north_star/test_classifier_acceptance.py` pins the fixture table; the
classifier is frozen-confirmed only after ALL pass. Each is `(evidence) → expected`.
The launder-trap rows (★) are the load-bearing ones — they prove the §3 guards reject
app-faults that the loose first draft would have excluded.

| # | fixture (log span) | phase | expected | signature |
|---|--------------------|-------|----------|-----------|
| V1 | `pip/_vendor/rich/live.py … RuntimeError: can't start new thread` | app_build | env | `env.buildkit_recurrence` |
| V2 ★ | generated `RUN python build_index.py` → `can't start new thread`, NO rich frame | app_build | functional | null (anchor absent) |
| V4 ★ | `[4/9] RUN npm ci … Cannot find module '/app/node_modules/dist/node/cli.js' … executor failed: exit code 1` | app_build | functional | null (jira-web vite) |
| V5 | exit 137; dmesg `CONSTRAINT_NONE … Out of memory: Killed`; no mem_limit | app_build | env | `env.oom` |
| V6 ★ | exit 137; dmesg `CONSTRAINT_MEMCG oom_memcg=/docker/<app>` OR compose mem_limit | app_runtime | functional | null (own-cgroup) |
| V7 | injected P=49231; `Bind for 0.0.0.0:49231 failed: port is already allocated`; `--filter publish=49231` → foreign project; reassign-retry on fresh port → PASS | infra_setup | env | `env.port_conflict` |
| V8 ★ | as V7 but reassign-retry on a NEW verified-free port ALSO fails | infra_setup | functional | null (free port can't be pre-owned) |
| V9 ★ | run used static `8003`; `port is already allocated` | infra_setup | functional | null (INADMISSIBLE) |
| V10 | `Cannot connect to the Docker daemon at unix://…`; live `docker version` ×3 all rc≠0 | infra_setup | env | `env.daemon_down` |
| V11 ★ | `error during connect: … context deadline exceeded` during a long RUN | app_build | functional | null (deadline guard) |
| V12 ★ | `Cannot connect to the Docker daemon` but live `docker version` rc=0 (healed) | infra_setup | functional | null (live-probe guard) |
| V13 ★ | `OSError: [Errno 28] No space left on device` inside `RUN pip install` | app_build | functional | null (runaway content) |
| V14 | `failed to register layer: write /var/lib/docker/overlay2/…: no space left on device`; df 99% | app_build | env | `env.disk_full` |
| V15 ★ | runtime `ENOSPC: System limit for number of file watchers reached` (vite/chokidar) | app_runtime | functional | null (app inotify) |
| V16 | JUnit `<failure>AssertionError: expected 401 got 201` | oracle | functional | null (step-0 invariant) |
| V19 | `apt-get update … Fetched 24.3 MB … APT::Update::Post-Invoke … fork: Cannot allocate memory`, no DNS tokens | app_build | env | `env.buildkit_recurrence` |
| V20 ★ | `apt-get update … Could not resolve 'archive.ubuntu.com'` | app_build | functional | null (DNS ≠ this class) |
| V21 | `failed to do request … registry-1.docker.io … net/http: TLS handshake timeout` | app_build | env | `env.image_pull` |
| V22 ★ | `404 Not Found - GET https://registry.npmjs.org/leftpad-typo` | app_build | functional | null (package-index = content) |
| V23 ★ | `manifest unknown` / `pull access denied for ghcr.io/...` | app_build | functional | null (naming nonexistent image) |
| V24 | `<error>` traceback in `tests/north_star/_conventions.py`, reproduces against reference_impl control | oracle | env (oracle bucket) | `env.oracle_infra` |
| V25 ★ | Playwright `Failed to launch … No usable sandbox`, launches fine on control, crashes only on app page | oracle | functional | null (app-triggered) |
| jira-db | jira-web db + backend came up under default builder | app_runtime | pass | null |
| **[POPULATE — LANDED]** every real round-11 smoke failure mechanically labelled by §3/§4. All landed cleanly; no spec gaps surfaced before freeze: | | | |
| V26 | node `uv_thread_create` assertion + npm RUN context (round-11 spike arm_2 actual stderr) | app_build | env | `env.buildkit_recurrence` (variant 3) |
| V27 ★ | airbnb `02_seed.sql:73 ERROR: operator does not exist: date + bigint` + postgres `exited (3)` (round-11 spike arm_3 actual stderr; demo-bug content failure) | app_runtime | functional | null (seed-SQL content bug, fixed in 67ecb385) |
| V28 | real spike arm_1a pip rich-frame + RuntimeError can't-start-new-thread (round-11 honest-signal log) | app_build | env | `env.buildkit_recurrence` (variant 1) |

**Gate criteria (R1):** (a) every fixture's verdict reproduces; (b) the adversarial pass
**cannot construct an app-fault (functional) failure that a §3 signature excludes as env**
(over-exclusion = inflation, the dangerous direction) — the ★ rows are the minimum bar;
(c) the default-functional path holds for an unmatched failure.

---

## 8. Out of scope (this doc)

- The §9.6 statistics rewrite (B1) — parallel, quality-phase-blocking, NOT pilot-blocking.
  The classifier only *labels* runs; aggregation/comparison is B1's domain. **Constraints
  passed downstream:** the §2 verdict schema is the data shape B1 must consume; the §5.1
  ITT-always + large-asymmetry-gate rules are fixed here and B1 must honor them.
- Real-generated-app calibration (obs #1): the classifier must be exercised on a
  *pipeline-emitted* simple_blog before the metric is trusted, not only the hand-written
  spike target. Gated separately.
- Fixture reliability per generated app (obs #3): `docker compose up` success-rate N/N is
  recorded but is a *reliability* signal, distinct from the functional/env verdict here.
